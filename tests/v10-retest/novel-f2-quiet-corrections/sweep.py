#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — N-F2 "QUIET CORRECTIONS" — CADENCE SWEEP.
Simulation only. No broker orders were placed.

Strategy (frozen, verbatim from backtests/v8/novel-f2-quiet-corrections/):
  at each selection date, over the trailing 1,095 days,
      AMEND_RATE = (count of 10-K/A + 10-Q/A) / (count of 10-K + 10-Q)
  counting EDGAR submissions by acceptance date in [sel-1095d, sel).
  Rank ASCENDING (cleanest first). Frozen tie-breaks: lower absolute
  amendment count; then fewer denominator filings; then ticker A->Z.
  Eligibility: denominator >= 10, else unscorable/excluded (never
  patched). Hold top 5, equal weight. Pond: the honest top-30 as of
  Nov 2016 (champion engine UNIVERSE). $100 pot, fractional shares.
  Costs: 0.10% of trade value per side + $0.01 per sell order.
  Trade mechanics (sell dropouts in full, keep survivors, equal-weight
  the new top-5, execute at next open, end-of-window liquidation at
  final close) copied VERBATIM from the v8 engine's run_pot_nf2, which
  is itself the champion engine's mechanics.

THE ONLY VARIATION vs the original test is the selection calendar
(the v10 cadence sweep): daily / weekly / biweekly / monthly /
quarterly (NATIVE) / semi-annual / annual, per the SPEC's uniform
definition — first trading day of each week / second week / month /
quarter / half-year / year; daily = every trading day. Selection on
day d, execution at the next open, exactly as the original engine.

Protection: adopted v9 rules (SPEC): plain -15% floor from the
episode's starting balance, NO ladder; on first halt: liquidate at
next open (engine semantics), sit in cash 90 calendar days, restart
at the strategy's next regular cadence date under an episode-2 floor
of -15% from the restart balance; second halt ends the run. The
wrapper below is lr_common.run_v9 copied in (provenance: backtests/
long-run-2010/lr_common.py), adapted only to read this engine's
'selections' records.

Data (all read-only shared caches; nothing written outside this
folder):
  - Prices: Yahoo full-range payloads (2008 -> 2026-11-20) in
    backtests/v7/long-hold/data/pxfull_<T>.json (GOOGL: backtests/
    long-run-2010/data/pxfull_GOOGL.json). Bars built with the
    champion construction (open/close scaled by adjclose/close),
    copied from lr_common.bars_adj. PriceBook is lr_common's
    FastPriceBook (bisect; proven identical to the champion's
    PriceBook by the long-run phase-0 checks).
  - Signal: EDGAR submissions histories cached by the original v8
    run in backtests/v8/novel-f2-quiet-corrections/data/sub_*.json
    (compact merged rows: form, acceptance date, accession).

Road: DECADE 2016-11-21 -> 2026-11-20 for every cell, $100 per cell.
Placebos: 20 seeds per cell — random 5 names drawn from the same
selection date's ELIGIBLE set, identical dates/mechanics/protection
(the original v8 placebo design). One clean shot: no tuning.
"""
import json
import math
import os
import random
import time
from bisect import bisect_left, bisect_right
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH_DATA = os.path.join(BT, "v7", "long-hold", "data")          # read-only
LR_DATA = os.path.join(BT, "long-run-2010", "data")             # read-only
V8_DATA = os.path.join(BT, "v8", "novel-f2-quiet-corrections", "data")
V8_RESULTS = os.path.join(BT, "v8", "novel-f2-quiet-corrections",
                          "novel-f2-quiet-corrections-results.json")

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
START_CASH = 100.0
ORIG_FORMS = ("10-K", "10-Q")
AMEND_FORMS = ("10-K/A", "10-Q/A")
TRAILING_DAYS = 1095
MIN_DENOM = 10
PLACEBO_SEEDS = list(range(1, 21))

START, END = "2016-11-21", "2026-11-20"   # DECADE road
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ------------------------------------------------------------- prices
def load_payload(ticker):
    for base in (LH_DATA, LR_DATA):
        p = os.path.join(base, f"pxfull_{ticker}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            with open(p, "rb") as f:
                return json.loads(f.read())
    raise RuntimeError(f"no pxfull payload for {ticker}")


def bars_adj(payload):
    """Champion bar construction (lr_common.bars_adj verbatim):
    open/close scaled by adjclose/close; close = adjclose."""
    res = payload["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


class FastPriceBook:
    """lr_common.FastPriceBook verbatim (bisect-accelerated champion
    PriceBook; proven identical by the long-hold phase-0 checks)."""

    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values()
                             for b in bl})
        self.idx = {t: {b["d"]: b for b in bl}
                    for t, bl in bars_by_ticker.items()}
        self._dl = {t: [b["d"] for b in bl]
                    for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return None
        i = bisect_right(dl, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None

    def next_open(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return None, None
        i = bisect_right(dl, d)
        if i < len(dl):
            b = self.bars[t][i]
            return b["d"], b["o"]
        return None, None


# ------------------------------------------------------------- signal
def load_signal():
    """Per ticker: sorted acceptance-date lists for originals and
    amendments, from the v8 run's cached EDGAR submissions rows.
    CIK map read from the v8 results' signal_coverage (the program's
    own mapping, XOM overridden to parent CIK 34088 there)."""
    with open(V8_RESULTS) as f:
        cov = json.load(f)["signal_coverage"]
    orig, amend = {}, {}
    for t in UNIVERSE:
        cik = cov[t]["cik"]
        with open(os.path.join(V8_DATA, f"sub_{cik:010d}.json")) as f:
            rows = json.load(f)["rows"]
        orig[t] = sorted(r["acc_date"] for r in rows
                         if r["form"] in ORIG_FORMS)
        amend[t] = sorted(r["acc_date"] for r in rows
                          if r["form"] in AMEND_FORMS)
    return orig, amend


def amend_counts(orig_dates, amend_dates, sel_date):
    """v8 verbatim: (n_amend, n_denom) with acceptance date in
    [sel_date - 1095 days, sel_date)."""
    y, m, dd = int(sel_date[:4]), int(sel_date[5:7]), int(sel_date[8:10])
    lo = (date(y, m, dd) - timedelta(days=TRAILING_DAYS)).isoformat()
    n_o = (bisect_left(orig_dates, sel_date) -
           bisect_left(orig_dates, lo))
    n_a = (bisect_left(amend_dates, sel_date) -
           bisect_left(amend_dates, lo))
    return n_a, n_o


# ------------------------------------------------------- cadence dates
def cadence_dates(pb, cadence, start, end):
    """SPEC uniform cadence definition over the window's trading days:
    daily = every trading day; weekly = first trading day of each ISO
    week; biweekly = first trading day of every second week (anchored
    on the first week of the window); monthly = first trading day of
    each month; quarterly = first trading day of Jan/Apr/Jul/Oct;
    semiannual = first trading day of Jan/Jul; annual = first trading
    day of each year."""
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    out, seen = [], set()
    for d in days:
        dt = date.fromisoformat(d)
        if cadence == "weekly":
            key = dt.isocalendar()[:2]
        elif cadence == "biweekly":
            key = dt.isocalendar()[:2]
        elif cadence == "monthly":
            key = (dt.year, dt.month)
        elif cadence == "quarterly":
            if dt.month not in (1, 4, 7, 10):
                continue
            key = (dt.year, dt.month)
        elif cadence == "semiannual":
            if dt.month not in (1, 7):
                continue
            key = (dt.year, dt.month)
        elif cadence == "annual":
            key = (dt.year,)
        else:
            raise ValueError(cadence)
        if key not in seen:
            seen.add(key)
            out.append(d)
    if cadence == "biweekly":
        out = out[::2]
    return out


# ------------------------------------------------------------- engine
# run_pot_nf2 copied from the v8 engine VERBATIM except: (1) the
# selection-date source is the cadence calendar above instead of
# E.quarter_selection_dates; (2) anatomy counters are accumulated;
# (3) ranked tables are recorded in full only when record_ranked=True.
def run_pot_cadence(pb, orig, amend, cadence, start, end, start_cash,
                    floor0, placebo_rng=None, label="",
                    record_ranked=False):
    cash = start_cash
    floor = floor0
    positions = {}  # ticker -> shares
    trades = []     # (date, ticker, side, shares, price, value, cost)
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []      # (date, close equity) — instrumentation only
    selections = []  # (date, eligible, ranked rows, picks)
    anatomy = {"ranked_rows": 0, "zero_rate_rows": 0, "pick_counts": {}}
    sel_dates = cadence_dates(pb, cadence, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None  # list of (ticker, target_value) to execute at next open

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        """Execute at open of day d toward target dollar values (dict t->value).
        Sells first, then buys. Returns total cost."""
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        # sells / trims
        for t in list(positions):
            if t not in opens:
                continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c
                cost += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9:
                    del positions[t]
        # buys
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c
                cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
        total_costs += cost
        return cost

    for di, d in enumerate(days):
        # execute pending rebalance at today's open
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        # selection day: compute targets from filings accepted before today
        if d in sel_set:
            scores = {}  # ticker -> (amend_rate, n_amend, n_denom)
            for t in UNIVERSE:
                n_a, n_o = amend_counts(orig[t], amend[t], d)
                if n_o >= MIN_DENOM:
                    scores[t] = (n_a / n_o, n_a, n_o)
            if len(scores) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    # frozen rank: AMEND_RATE asc; ties -> fewer
                    # amendments; then fewer denominator filings; then
                    # ticker A->Z.
                    ranked = sorted(
                        scores.items(),
                        key=lambda kv: (kv[1][0], kv[1][1], kv[1][2],
                                        kv[0]))
                    picks = [t for t, _ in ranked[:5]]
                    anatomy["ranked_rows"] += len(ranked)
                    anatomy["zero_rate_rows"] += sum(
                        1 for _, v in ranked if v[0] == 0.0)
                    for p in picks:
                        anatomy["pick_counts"][p] = \
                            anatomy["pick_counts"].get(p, 0) + 1
                    selections.append({
                        "date": d,
                        "eligible": len(scores),
                        "ranked": ([[t, round(v[0], 4), v[1], v[2]]
                                    for t, v in ranked]
                                   if record_ranked else None),
                        "picks": list(picks),
                    })
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
        # end of day: plain floor check (v9: no ladder)
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            # liquidate at next open
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t],
                                   b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "curve": curve,
                    "selections": selections, "anatomy": anatomy}
    # end of window: liquidate at final close
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "curve": curve, "selections": selections,
            "anatomy": anatomy}


# ------------------------------------------------------- v9 protection
# lr_common.run_v9 copied in (see header for provenance), adapted only
# to read this engine's 'selections' records for the restart date.
def run_v9(run_one, trading_days, start, end, start_cash=START_CASH):
    episodes = []
    ep1 = run_one(start, end, start_cash, 0.85 * start_cash)
    episodes.append(ep1)
    restart = None
    if ep1 is not None and ep1["halted"]:
        halt_d = date.fromisoformat(ep1["halted"])
        elig = (halt_d + timedelta(days=90)).isoformat()
        if elig <= end:
            ep2 = run_one(elig, end, ep1["final"], 0.85 * ep1["final"])
            if ep2 is not None:
                episodes.append(ep2)
                first_sel = None
                if ep2.get("selections"):
                    first_sel = ep2["selections"][0]["date"]
                restart = {"halt_date": ep1["halted"],
                           "halt_signal_close":
                               ep1["halt_info"]["signal_close"]
                               if ep1.get("halt_info") else None,
                           "liquidation_proceeds": round(ep1["final"], 2),
                           "eligibility_date": elig,
                           "episode2_first_selection": first_sel,
                           "episode2_floor": round(0.85 * ep1["final"], 2),
                           "second_halt": ep2["halted"]}
    last = episodes[-1]
    curve = list(episodes[0]["curve"])
    if len(episodes) > 1:
        gap_days = [d for d in trading_days
                    if episodes[0]["end"] < d < episodes[1]["curve"][0][0]]
        curve += [(d, episodes[0]["final"]) for d in gap_days]
        curve += list(episodes[1]["curve"])
    halts = []
    for i, ep in enumerate(episodes):
        if ep["halted"]:
            halts.append({"episode": i + 1, "signal_date": ep["halted"],
                          "signal_close":
                              ep["halt_info"]["signal_close"]
                              if ep.get("halt_info") else None,
                          "floor_in_effect":
                              ep["halt_info"]["floor_in_effect"]
                              if ep.get("halt_info") else None,
                          "liquidation_date": ep["end"],
                          "proceeds": round(ep["final"], 2)})
    return {"episodes": episodes, "final": last["final"],
            "costs": sum(ep["costs"] for ep in episodes),
            "orders": sum(len(ep["trades"]) for ep in episodes),
            "halts": halts, "restart": restart, "curve": curve}


def curve_diagnostics(curve, start_cash=START_CASH):
    """lr_common.curve_diagnostics verbatim."""
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = (d, round(v, 2))
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "year_end_closes": {y: v for y, (_, v) in
                                sorted(year_end.items())}}


def cagr(final, start_cash, start, end):
    """lr_common.cagr verbatim."""
    yrs = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    return round(((final / start_cash) ** (1.0 / yrs) - 1.0) * 100, 2)


def spy_net(pb, start, end, start_cash):
    """Champion engine spy_net verbatim."""
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost


# ------------------------------------------------------------------ main
def main():
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = bars_adj(load_payload(t))
        print(f"{t}: {len(bars[t])} bars {bars[t][0]['d']}.."
              f"{bars[t][-1]['d']}", flush=True)
    pb = FastPriceBook(bars)
    orig, amend = load_signal()
    trading_days = [d for d in pb.dates if START <= d <= END]

    spy_final, spy_costs = spy_net(pb, START, END, START_CASH)
    print(f"SPY DECADE net = ${spy_final:,.2f} (costs ${spy_costs:,.2f})",
          flush=True)

    cells = {}
    for cadence in CADENCES:
        t0 = time.time()
        record = (cadence == "quarterly")

        def run_ranked(s, e, cash, floor):
            return run_pot_cadence(pb, orig, amend, cadence, s, e, cash,
                                   floor, label=f"{cadence} ranked",
                                   record_ranked=record)

        res = run_v9(run_ranked, trading_days, START, END)
        diag = curve_diagnostics(res["curve"])
        anatomy = {"ranked_rows": 0, "zero_rate_rows": 0, "pick_counts": {}}
        n_sel = 0
        all_picks = []
        for ep in res["episodes"]:
            a = ep["anatomy"]
            anatomy["ranked_rows"] += a["ranked_rows"]
            anatomy["zero_rate_rows"] += a["zero_rate_rows"]
            for k, v in a["pick_counts"].items():
                anatomy["pick_counts"][k] = \
                    anatomy["pick_counts"].get(k, 0) + v
            n_sel += len(ep["selections"])
            all_picks += [(s["date"], s["picks"])
                          for s in ep["selections"]]

        twin_finals = []
        for seed in PLACEBO_SEEDS:
            def run_twin(s, e, cash, floor, seed=seed):
                rng = random.Random(seed)
                return run_pot_cadence(pb, orig, amend, cadence, s, e,
                                       cash, floor, placebo_rng=rng,
                                       label=f"{cadence} P{seed}")
            tw = run_v9(run_twin, trading_days, START, END)
            twin_finals.append(round(tw["final"], 2))
        beaten = sum(1 for x in twin_finals if res["final"] > x)

        cell = {
            "cadence": cadence,
            "window": {"start": START, "end": END},
            "final": round(res["final"], 2),
            "cagr_pct": cagr(res["final"], START_CASH, START, END),
            "max_dd_pct": diag["max_drawdown_pct"],
            "max_dd_date": diag["max_drawdown_date"],
            "worst_close": diag["worst_close"],
            "worst_close_date": diag["worst_close_date"],
            "costs": round(res["costs"], 2),
            "orders": res["orders"],
            "halts": res["halts"],
            "restart": res["restart"],
            "n_selections": n_sel,
            "anatomy": {
                "ranked_rows": anatomy["ranked_rows"],
                "zero_rate_rows": anatomy["zero_rate_rows"],
                "zero_rate_pct": (round(100.0 * anatomy["zero_rate_rows"]
                                        / anatomy["ranked_rows"], 1)
                                  if anatomy["ranked_rows"] else None),
                "pick_counts": dict(sorted(
                    anatomy["pick_counts"].items(),
                    key=lambda kv: -kv[1])),
            },
            "picks_by_selection": [[d, p] for d, p in all_picks],
            "equity_curve": [[d, round(v, 4)] for d, v in res["curve"]],
            "placebo_twin_finals": twin_finals,
            "placebo_beaten": beaten,
            "placebo_median": round((sorted(twin_finals)[9] +
                                     sorted(twin_finals)[10]) / 2.0, 2),
            "year_end_closes": diag["year_end_closes"],
        }
        if record:
            cell["selections_full"] = [
                s for ep in res["episodes"] for s in ep["selections"]]
        with open(os.path.join(HERE, "cells", f"{cadence}.json"),
                  "w") as f:
            json.dump(cell, f, indent=1)
        cells[cadence] = cell
        print(f"== {cadence}: final=${cell['final']:,.2f} "
              f"CAGR={cell['cagr_pct']}% maxDD={cell['max_dd_pct']}% "
              f"costs=${cell['costs']:,.2f} orders={cell['orders']} "
              f"halts={len(cell['halts'])} restart="
              f"{bool(cell['restart'])} placebo {beaten}/20 "
              f"zero-rate={cell['anatomy']['zero_rate_pct']}% "
              f"({time.time()-t0:.0f}s)", flush=True)

    out = {
        "slug": "novel-f2-quiet-corrections",
        "decade_spy_final": round(spy_final, 2),
        "decade_spy_costs": round(spy_costs, 2),
        "cells_summary": {c: {k: cells[c][k] for k in
                              ("final", "cagr_pct", "max_dd_pct", "costs",
                               "orders", "placebo_beaten")}
                          for c in CADENCES},
    }
    with open(os.path.join(HERE, "sweep_cells.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("SWEEP DONE", flush=True)


if __name__ == "__main__":
    main()
