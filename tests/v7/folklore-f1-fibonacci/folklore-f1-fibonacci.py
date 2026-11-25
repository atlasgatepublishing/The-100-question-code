#!/usr/bin/env python3
"""
FOLKLORE TEST F-1 — FIBONACCI 61.8% RETRACEMENT ENTRIES (pond form).
Terry's AI stock app. Simulation only. Run once as specified, no tuning.

THE SPEC IS FROZEN — Spec F-1 of
~/workspace/stock-app/research/v7-completeness/folklore-audit.md,
implemented verbatim:

  - Universe: the honest top-30 pond (point-in-time membership as in the
    champion engine), daily closes, free Yahoo/EDGAR data as per the
    engine (the champion's cached split/dividend-adjusted bars).
  - Swing definition (frozen): ZigZag on daily closes with a 10%
    reversal threshold produces alternating swing highs and lows. A
    swing is COMPLETE when the ZigZag confirms its endpoint (a
    subsequent 10% reversal) — entries may only use completed swings,
    never the forming leg.
  - Signal: after a completed up-swing (swing low L -> swing high H,
    with H >= 1.20 x L), compute R = H - 0.618 x (H - L). If a daily
    close crosses down to or through R while price remains above L,
    buy at the next open.
  - Positions: one open position per name; max 5 concurrent; each entry
    commits 1/5 of the pot's current value. Signals while full are
    skipped and logged.
  - Exit (first of): close >= H; close < L; 252 trading days held.
    Exit at next open.
  - Chassis (audit-wide): $100 pot, execution at next session's open
    after a signal computed on closes, costs 0.10%/side + $0.01 per
    sell order, plain -15% floor at the pot level (close <= $85
    liquidates everything at next open and ends the run), windows
    continuous 2019-01-02 -> 2026-11-20 and validation
    2023-01-03 -> 2026-11-20, benchmarks SPY buy-hold net (champion
    engine's spy_net) and the 20-seed random placebo on the same
    universe and cadence. Promotion bar (program standard): beat SPY
    AND the placebo median on validation.

READINGS OF THE SPEC (stated here, before any result — the spec is
frozen, so where its prose admits two mechanical readings these are the
ones implemented; none was chosen after seeing an outcome):
  R1. ZigZag mechanics: from a candidate high, a close at or below
      0.90 x high confirms that high; from a candidate low, a close at
      or above 1.10 x low confirms that low (the standard percentage
      ZigZag). A pivot is usable only from its confirmation date.
  R2. The live setup for a name is its MOST RECENT completed up-swing.
      If that swing fails the H >= 1.20 x L test there is no live
      setup (an older qualifying swing is superseded, not revived).
  R3. Signal day = the FIRST day, on or after the swing high's
      confirmation date, whose close is <= R while the close is > L.
      (Reaching R from H always implies the 10% reversal has occurred
      when H >= 1.20 L, so the trigger can fall on the confirmation
      day itself; the first day the setup is knowable and the level is
      touched is the signal.) Each completed swing produces at most
      one signal, whether taken or skipped.
  R4. Signals are detected for every name every day (a swing is
      consumed when its signal fires). A signal is TAKEN only if the
      name is not already held or pending and fewer than 5 positions
      are open or pending; otherwise it is logged as skipped with the
      reason. Same-day takes are processed in alphabetical ticker
      order. Positions with a pending exit still count as open (they
      are held until the exit executes at the next open).
  R5. "1/5 of the pot's current value" = the pot's close value on the
      signal day (cash + positions at that day's closes), converted
      to shares at the execution open under the champion's buy
      mechanics (spend capped at cash/1.001, 0.10% buy cost).
  R6. "252 trading days held" is counted in the entered ticker's own
      bars from the entry bar; the exit is evaluated on the close of
      the first day the count reaches 252 and executes at the next
      open, like every exit.
  R7. ZigZag state is computed on the full cached price history
      (from 2017-06) for both windows: a swing confirmed before a
      window opens whose R-cross falls inside the window is a valid
      in-window signal, because every input was knowable in real
      time. Each window is a fresh $100 pot starting in cash.
  R8. Placebo construction (the audit's "same universe and cadence"
      for an event-driven rule): each placebo pot takes one entry on
      every day the ranked pot actually entered, buying a random pond
      name (seeded RNG) not held in that placebo pot, sized at 1/5 of
      the placebo pot's own prior-day close value, with exits
      referenced to that name's own most recent completed up-swing as
      of the prior close (the 1.20 qualification is part of the
      ranked SIGNAL, so it is not applied to the placebo's exit
      yardstick). Identical exit rules, costs, and floor. This
      randomizes WHICH name each entry buys while preserving the
      ranked strategy's entry days, sizing, and mechanics exactly.

ENGINE: price handling, cost schedule, floor/halt liquidation,
end-of-window liquidation, SPY benchmark, diagnostics and the placebo
percentile method are the champion engine's
(~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py),
imported. A replication check runs FIRST: the imported champion
engine must reproduce $544.47 (continuous) and $288.05 (validation)
to the cent before any F-1 number is trusted.
"""
import bisect
import importlib.util
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
V4_ENGINE = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/value-momentum-plainfloor.py")

spec = importlib.util.spec_from_file_location("vm_plainfloor", V4_ENGINE)
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
START_CASH = 100.0
FLOOR0 = 85.0            # plain -15% floor on $100, no ladder, ever
PLACEBO_SEEDS = list(range(1, 21))
FULL = ("2019-01-02", "2026-11-20")
VALIDATION = ("2023-01-03", "2026-11-20")
ZZ_THR = 0.10            # frozen ZigZag reversal threshold
RETR = 0.618             # frozen retracement fraction
MIN_SWING = 1.20         # frozen H >= 1.20 x L qualification
MAX_POS = 5              # frozen max concurrent positions
MAX_HOLD_BARS = 252      # frozen time exit


# ------------------------------------------------------------------ inputs
def build_inputs():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return E.PriceBook(bars), equity_rows, shares_rows


# ------------------------------------------------------------------ zigzag
def zigzag_pivots(closes, thr=ZZ_THR):
    """Standard percentage ZigZag on closes.
    Returns [(bar_idx, price, 'H'|'L', confirm_bar_idx), ...]."""
    pivots = []
    if len(closes) < 2:
        return pivots
    state = "none"
    hi_i = lo_i = 0
    hi = lo = closes[0]
    cand_i, cand = 0, closes[0]
    for i in range(1, len(closes)):
        c = closes[i]
        if state == "none":
            if c > hi:
                hi, hi_i = c, i
            if c < lo:
                lo, lo_i = c, i
            up_trig = c >= lo * (1 + thr) and lo_i < i
            dn_trig = c <= hi * (1 - thr) and hi_i < i
            if up_trig and (not dn_trig or lo_i <= hi_i):
                pivots.append((lo_i, lo, "L", i))
                state = "up"
                cand_i, cand = hi_i, hi
            elif dn_trig:
                pivots.append((hi_i, hi, "H", i))
                state = "down"
                cand_i, cand = lo_i, lo
        elif state == "up":
            if c > cand:
                cand, cand_i = c, i
            elif c <= cand * (1 - thr):
                pivots.append((cand_i, cand, "H", i))
                state = "down"
                cand_i, cand = i, c
        else:  # down
            if c < cand:
                cand, cand_i = c, i
            elif c >= cand * (1 + thr):
                pivots.append((cand_i, cand, "L", i))
                state = "up"
                cand_i, cand = i, c
    return pivots


def build_ticker_data(pb):
    """Per ticker: bars, date->bar index, completed up-swings with
    confirmation dates (full cache history; R7)."""
    tdata = {}
    for t in UNIVERSE:
        bars = pb.bars.get(t, [])
        closes = [b["c"] for b in bars]
        pivots = zigzag_pivots(closes)
        swings = []
        for a, b in zip(pivots, pivots[1:]):
            if a[2] == "L" and b[2] == "H":
                L, H = a[1], b[1]
                swings.append({
                    "id": len(swings),
                    "L": L, "H": H,
                    "L_date": bars[a[0]]["d"], "H_date": bars[b[0]]["d"],
                    "confirm_date": bars[b[3]]["d"],
                    "qualifies": H >= MIN_SWING * L,
                    "R": H - RETR * (H - L),
                })
        tdata[t] = {
            "bars": bars,
            "idx": {b["d"]: i for i, b in enumerate(bars)},
            "swings": swings,
            "confirms": [s["confirm_date"] for s in swings],
        }
    return tdata


def last_swing_asof(td, date):
    """Most recent completed up-swing confirmed on or before `date`
    (None if none)."""
    i = bisect.bisect_right(td["confirms"], date) - 1
    if i < 0:
        return None
    return td["swings"][i]


# ------------------------------------------------------------------ engine
def run_fib(pb, tdata, start, end, mode="ranked", entry_day_counts=None,
            rng=None, label=""):
    """One pot under Spec F-1. mode='ranked' runs the frozen rule;
    mode='placebo' keys entries to the ranked run's entry days (R8)."""
    cash = START_CASH
    positions = {}        # t -> dict(shares, entry_date, entry_idx, H, L, ...)
    trades = []
    total_costs = 0.0
    curve = []
    halted = None
    halt_info = None
    pending_entries = []  # dicts: t, commit, H, L, swing_id, signal_date
    pending_exits = []    # tickers
    exit_info = {}        # ticker -> (reason, trigger_date) — instrumentation only
    signals = []          # ranked: every fired signal + taken/skipped
    entry_events = {}     # exec_date -> count (ranked run output)
    consumed = set()      # (ticker, swing_id) that already fired
    closed_positions = [] # per-position records for the report
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    day_pos = {d: i for i, d in enumerate(days)}

    def portfolio_close(d):
        v = cash
        for t, p in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += p["shares"] * c
        return v

    def do_buy(d, t, commit, H, L, swing_id, signal_date):
        nonlocal cash, total_costs
        bar = pb.bar(t, d)
        if not bar:
            return False
        o = bar["o"]
        buy_val = min(commit, cash / 1.001)
        if buy_val <= 0.005:
            return False
        sh = buy_val / o
        c = buy_val * 0.001
        cash -= buy_val + c
        total_costs += c
        positions[t] = {"shares": sh, "entry_date": d,
                        "entry_idx": tdata[t]["idx"][d],
                        "entry_price": o, "H": H, "L": L,
                        "swing_id": swing_id, "signal_date": signal_date,
                        "commit": buy_val}
        trades.append((d, t, "BUY", sh, o, buy_val, c))
        return True

    def do_sell(d, t, tag, price=None):
        nonlocal cash, total_costs
        p = positions.get(t)
        if p is None:
            return
        if price is None:
            bar = pb.bar(t, d)
            if not bar:
                return
            price = bar["o"]
        val = p["shares"] * price
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((d, t, tag, p["shares"], price, val, c))
        info = exit_info.pop(t, (None, None))
        if info[0] is None:
            info = ({"SELL-END": "window end",
                     "SELL-HALT": "floor halt liquidation"}.get(tag, tag), None)
        closed_positions.append({
            "ticker": t, "signal_date": p["signal_date"],
            "entry_date": p["entry_date"], "entry_price": round(p["entry_price"], 4),
            "exit_date": d, "exit_price": round(price, 4), "tag": tag,
            "exit_reason": info[0], "exit_trigger_date": info[1],
            "H": round(p["H"], 4), "L": round(p["L"], 4),
            "pnl": round(val - c - p["commit"] - p["commit"] * 0.001, 2)})
        del positions[t]

    for di, d in enumerate(days):
        # ---- execute pending exits at today's open (before entries)
        still_pending = []
        for t in pending_exits:
            if t in positions and pb.bar(t, d):
                do_sell(d, t, "SELL")
            elif t in positions:
                still_pending.append(t)
        pending_exits = still_pending
        # ---- execute pending entries at today's open
        still_pending = []
        for pe in pending_entries:
            t = pe["t"]
            if t in positions:
                continue  # cannot happen mechanically; drop defensively
            if pb.bar(t, d):
                if do_buy(d, t, pe["commit"], pe["H"], pe["L"],
                          pe["swing_id"], pe["signal_date"]):
                    entry_events[d] = entry_events.get(d, 0) + 1
            else:
                still_pending.append(pe)
        pending_entries = still_pending

        last_day = di == len(days) - 1

        # ---- exit evaluation on today's close
        if not last_day:
            for t, p in list(positions.items()):
                bar = pb.bar(t, d)
                if not bar:
                    continue
                c = bar["c"]
                held = tdata[t]["idx"][d] - p["entry_idx"]
                reason = None
                if c >= p["H"]:
                    reason = "target: close >= swing high H"
                elif c < p["L"]:
                    reason = "invalidated: close < swing low L"
                elif held >= MAX_HOLD_BARS:
                    reason = "time: 252 trading days held"
                if reason is not None and t not in pending_exits:
                    pending_exits.append(t)
                    exit_info[t] = (reason, d)

        # ---- entries: signal detection (ranked) or cadence (placebo)
        if not last_day:
            if mode == "ranked":
                pv = portfolio_close(d)
                for t in sorted(UNIVERSE):
                    bar = pb.bar(t, d)
                    if not bar:
                        continue
                    sw = last_swing_asof(tdata[t], d)
                    if sw is None or not sw["qualifies"]:
                        continue
                    key = (t, sw["id"])
                    if key in consumed:
                        continue
                    c = bar["c"]
                    if c <= sw["R"] and c > sw["L"]:
                        consumed.add(key)
                        taken = (t not in positions
                                 and all(pe["t"] != t for pe in pending_entries)
                                 and t not in pending_exits
                                 and len(positions) + len(pending_entries) < MAX_POS)
                        rec = {"ticker": t, "signal_date": d,
                               "swing_L": round(sw["L"], 4),
                               "swing_H": round(sw["H"], 4),
                               "R": round(sw["R"], 4),
                               "L_date": sw["L_date"], "H_date": sw["H_date"],
                               "confirm_date": sw["confirm_date"],
                               "close": round(c, 4),
                               "taken": taken}
                        if taken:
                            pending_entries.append(
                                {"t": t, "commit": pv / MAX_POS,
                                 "H": sw["H"], "L": sw["L"],
                                 "swing_id": sw["id"], "signal_date": d})
                        else:
                            if t in positions or t in pending_exits:
                                rec["skip_reason"] = "already held"
                            elif len(positions) + len(pending_entries) >= MAX_POS:
                                rec["skip_reason"] = "pot full (5 open)"
                            else:
                                rec["skip_reason"] = "pending entry exists"
                        signals.append(rec)
            else:  # placebo: one entry attempt per ranked entry today
                n_attempts = (entry_day_counts or {}).get(
                    days[di + 1], 0) if di + 1 < len(days) else 0
                # NOTE: entry_day_counts is keyed by EXECUTION date; the
                # attempts are generated on the day BEFORE execution to
                # mirror ranked mechanics (signal close -> next open).
                # Execution dates in the ranked run are >= start+1 day,
                # so generating on di (for execution on days[di+1]) is
                # the exact mirror.
                if n_attempts:
                    prev_close = curve[-1][1] if curve else START_CASH
                    for _ in range(n_attempts):
                        if len(positions) + len(pending_entries) >= MAX_POS:
                            break
                        cands = []
                        for t in sorted(UNIVERSE):
                            if t in positions or t in pending_exits:
                                continue
                            if any(pe["t"] == t for pe in pending_entries):
                                continue
                            if not pb.bar(t, days[di + 1]):
                                continue
                            sw = last_swing_asof(tdata[t], d)
                            if sw is None:
                                continue
                            cands.append((t, sw))
                        if not cands:
                            break
                        t, sw = rng.choice(cands)
                        pending_entries.append(
                            {"t": t, "commit": prev_close / MAX_POS,
                             "H": sw["H"], "L": sw["L"],
                             "swing_id": sw["id"], "signal_date": d})

        # ---- floor check on the close (champion mechanics)
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= FLOOR0 and not last_day:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": FLOOR0}
            nd = days[di + 1]
            for t in list(positions):
                if pb.bar(t, nd):
                    do_sell(nd, t, "SELL-HALT")
            positions = {}
            pending_entries = []
            pending_exits = []
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "curve": curve,
                    "signals": signals, "entry_events": entry_events,
                    "closed_positions": closed_positions}
    # ---- end of window: liquidate at final close (champion convention)
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            do_sell(last, t, "SELL-END", price=c_)
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "curve": curve, "signals": signals,
            "entry_events": entry_events, "closed_positions": closed_positions}


def curve_stats(r):
    diag = E.diagnostics(r, FLOOR0)
    return {"final": round(r["final"], 2),
            "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
            "orders": len(r["trades"]), "costs": round(r["costs"], 2),
            "halted": r["halted"], "halt_info": r["halt_info"],
            "max_drawdown_pct": diag["max_drawdown_pct"],
            "max_drawdown_date": diag["max_drawdown_date"],
            "worst_close": diag["worst_close"],
            "worst_close_date": diag["worst_close_date"],
            "worst_close_above_floor": diag["worst_close_above_floor"],
            "year_end_closes": diag["year_end_closes"]}


def placebo_block(pb, tdata, ws, we, ranked):
    counts = ranked["entry_events"]
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = run_fib(pb, tdata, ws, we, mode="placebo",
                     entry_day_counts=counts, rng=rng,
                     label=f"PLACEBO {seed}")
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"], "orders": len(pr["trades"]),
                     "costs": round(pr["costs"], 2)})
        print(f"  PLACEBO seed {seed:2d}: final=${pr['final']:,.2f} "
              f"halted={pr['halted']} orders={len(pr['trades'])}", flush=True)
    srt = sorted(finals)
    ranked_final = ranked["final"]
    below = sum(1 for f in finals if f < ranked_final)
    ties = sum(1 for f in finals if f == ranked_final)
    pctile = 100.0 * (below + 0.5 * ties) / len(finals)
    return {"median": round(E._pct(srt, 0.50), 2),
            "q1": round(E._pct(srt, 0.25), 2),
            "q3": round(E._pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for p in rows if p["halted"]),
            "ranked_final": round(ranked_final, 2),
            "ranked_percentile": round(pctile, 1),
            "seeds_beaten": below, "rows": rows}


def main():
    pb, equity_rows, shares_rows = build_inputs()
    tdata = build_ticker_data(pb)
    out = {"strategy": "FOLKLORE F-1: Fibonacci 61.8% retracement entries, "
                       "ZigZag 10% frozen, honest top-30 pond, $100, "
                       "plain -15% floor",
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0,
           "spec_readings": "R1-R8 in the script header (stated before results)"}

    # ---- (0) replication check: champion engine must reproduce published
    for tag, (ws, we), expect in (("FULL", FULL, 544.47),
                                  ("VALIDATION", VALIDATION, 288.05)):
        r = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                      FLOOR0, [], label=f"REPL {tag}", quiet=True)
        ok = abs(r["final"] - expect) < 0.005
        print(f"REPLICATION {tag}: champion=${r['final']:,.2f} "
              f"expected=${expect:,.2f} match={ok}", flush=True)
        out[f"replication_{tag.lower()}"] = {
            "champion_final": round(r["final"], 2), "expected": expect,
            "match": ok}
        if not ok:
            raise SystemExit("REPLICATION FAILED — variant numbers untrusted")

    # ---- (1) ranked runs + SPY + placebo, both windows
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VALIDATION)):
        spy, _ = E.spy_net(pb, ws, we, START_CASH)
        r = run_fib(pb, tdata, ws, we, mode="ranked", label=f"{tag} FIB-F1")
        st = curve_stats(r)
        st.update({"start": ws, "end": we, "spy_net_final": round(spy, 2),
                   "spy_return_pct": round(spy / START_CASH * 100 - 100, 2),
                   "signals": r["signals"],
                   "closed_positions": r["closed_positions"],
                   "entry_events": r["entry_events"]})
        taken = sum(1 for s in r["signals"] if s["taken"])
        print(f"{tag} FIB-F1: final=${r['final']:,.2f} ({st['return_pct']:+.2f}%) "
              f"maxDD={st['max_drawdown_pct']}% orders={st['orders']} "
              f"costs=${st['costs']} halted={r['halted']} | SPY=${spy:,.2f} | "
              f"signals={len(r['signals'])} taken={taken}", flush=True)
        st["placebo"] = placebo_block(pb, tdata, ws, we, r)
        pl = st["placebo"]
        print(f"{tag} PLACEBO: median=${pl['median']:,.2f} best=${pl['best']:,.2f} "
              f"worst=${pl['worst']:,.2f} halted={pl['halted_count']}/20 | "
              f"RANKED ${pl['ranked_final']:,.2f} = {pl['ranked_percentile']}th "
              f"pctile (beat {pl['seeds_beaten']}/20)", flush=True)
        out[tag.lower()] = st

    with open(os.path.join(HERE, "folklore-f1-fibonacci-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
