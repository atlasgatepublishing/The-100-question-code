#!/usr/bin/env python3
"""
NOVEL TEST N-3 — "QUARTER-END WINDOW-DRESSING REBOUND" — Terry's AI stock
app, v8 novel ("never been done") track. Simulation only.

Implements Rule N-3 from research/v8-novel/novel-cross-calendar.md
VERBATIM. The spec is frozen: no parameter was improved, re-cut, or
reinterpreted. Forced readings are declared in the report BEFORE results
and summarized in the header notes of the results JSON.

Spec N-3 as written:
  - Dates (SPY trading calendar): L = last trading day of each calendar
    quarter (Mar/Jun/Sep/Dec). Event window = L plus the first 5 trading
    days of the new quarter.
  - Ranking: at the close of L, each pond name's quarter-to-date return
    = close(L) / close(last trading day of prior quarter) - 1.
  - Entry: at the close of L, sell SPY and buy the 5 pond names with the
    lowest quarter-to-date returns, equal weight (20% of pot each).
  - Exit: at the close of the 5th trading day of the new quarter, sell
    the basket in full and buy SPY.
  - Outside the window the pot holds SPY.
  - Placebo: same window dates, 5 pond names drawn at random instead of
    the quarter's losers, same entry/exit mechanics, 20 seeds.
  - The spec explicitly FORBIDS a non-quarter-end control run ("the same
    loser basket bought on the same dates in non-quarter-end months is
    not run"). None was run.

House chassis (program-wide): $100 pot, long-only; costs 0.10% of trade
value per side + $0.01 per sell order; plain -15% floor at pot level
(close at/below $85 -> liquidate at next open, run ends — champion
engine semantics); windows continuous 2019-01-02->2026-11-20 and
validation 2023-01-03->2026-11-20; benchmarks SPY buy-hold net of the
same costs (the champion engine's spy_net, imported) and the champion's
published finals ($544.47 / $288.05).

INVENTED-RULE BAR (harsher than for published families; this rule was
invented in 2026 by an inventor who had seen the 2019-2026 tape, and is
reported as "1 of 12 invented rules"): the best possible verdict is
CANDIDATE — only a forward paper trial can promote an invented rule.
CANDIDATE requires ALL of: (1) validation final > SPY $187.77,
(2) validation placebo >= 19/20 beaten, (3) continuous final > SPY
$313.62, (4) no floor halt on either main window. Anything less is
NOT A CANDIDATE.

Prices: the champion engine's own cached adjusted bars (Yahoo
adjclose/close ratio method), loaded through the champion engine's
get_prices, read-only. Integrity: the engine's spy_net on this data
must reproduce the published $313.62 / $187.77 to the cent before any
variant number is taken.
"""
import bisect
import importlib.util
import json
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")

START_CASH = 100.0
FLOOR0 = 85.0
WINDOWS = (("FULL", "2019-01-02", "2026-11-20"),
           ("VALIDATION", "2023-01-03", "2026-11-20"))
PLACEBO_SEEDS = list(range(1, 21))
CHAMPION = {"FULL": 544.47, "VALIDATION": 288.05}
SPY_PUBLISHED = {"FULL": 313.62, "VALIDATION": 187.77}
TOP_N = 5

# ------------------------------------------------------------ champion engine
spec = importlib.util.spec_from_file_location(
    "champion", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)
UNIVERSE = list(E.UNIVERSE)


# ------------------------------------------------------------------- prices
class Bars:
    """Close/open lookup over the champion engine's adjusted bars."""

    def __init__(self, bars_by_t):
        self.bars = bars_by_t
        self.dates = {t: [b["d"] for b in bl] for t, bl in bars_by_t.items()}
        self.by_date = {t: {b["d"]: b for b in bl}
                        for t, bl in bars_by_t.items()}

    def close_on_or_before(self, t, d):
        ds = self.dates[t]
        j = bisect.bisect_right(ds, d) - 1
        if j < 0:
            return None
        return self.bars[t][j]["c"]

    def open_on(self, t, d):
        b = self.by_date[t].get(d)
        return b["o"] if b else None


# ------------------------------------------------------------------- events
def build_events(calendar):
    """All quarter-end events on the SPY calendar: L = last trading day
    of a Mar/Jun/Sep/Dec month; exit = 5th trading day after L (the 5th
    trading day of the new quarter); prev_L = prior quarter-end."""
    cal_idx = {d: i for i, d in enumerate(calendar)}
    qends = []
    for i, d in enumerate(calendar):
        if d[5:7] in ("03", "06", "09", "12"):
            if i == len(calendar) - 1 or calendar[i + 1][5:7] != d[5:7]:
                qends.append(d)
    events = []
    for j, L in enumerate(qends):
        i = cal_idx[L]
        if i + 5 >= len(calendar) or j == 0:
            continue
        events.append({"L": L, "exit": calendar[i + 5],
                       "prev_L": qends[j - 1]})
    return events


def qtd_table(bx, ev):
    """{ticker: quarter-to-date return} for names computable at L."""
    out = {}
    for t in UNIVERSE:
        c0 = bx.close_on_or_before(t, ev["prev_L"])
        c1 = bx.close_on_or_before(t, ev["L"])
        if c0 and c1 and c0 > 0:
            out[t] = c1 / c0 - 1.0
    return out


# ------------------------------------------------------------------- engine
def simulate(bx, calendar, start, end, events, picker, label=""):
    """One $100 pot under the N-3 mechanics. `events` = the events whose
    exit day falls inside [start, end] (the first may have L < start —
    the boundary event; its entry is executed at the close of L with the
    starting $100, so the pot opens the window holding that basket).
    picker(ev, qtd) -> list of 5 tickers."""
    days = [d for d in calendar if start <= d <= end]
    ev_by_L = {e["L"]: e for e in events}
    ev_by_exit = {e["exit"]: e for e in events}

    cash = START_CASH
    positions = {}            # ticker -> shares
    trades = []
    total_costs = 0.0
    curve = []
    halted = None
    halt_info = None
    event_log = []

    def value(d):
        v = cash
        for t, sh in positions.items():
            c = bx.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def sell_all_at_close(d, tag="SELL"):
        nonlocal cash, total_costs
        for t in list(positions):
            c = bx.close_on_or_before(t, d)
            if c is None:
                continue
            val = positions[t] * c
            cost = val * 0.001 + 0.01
            cash += val - cost
            total_costs += cost
            trades.append((d, t, tag, positions[t], c, val, cost))
            del positions[t]

    def buy_value(t, d, price, target):
        nonlocal cash, total_costs
        if price is None or price <= 0:
            return 0.0
        buy_val = min(target, cash / 1.001)
        if buy_val <= 0.005:
            return 0.0
        sh = buy_val / price
        cost = buy_val * 0.001
        cash -= buy_val + cost
        total_costs += cost
        positions[t] = positions.get(t, 0.0) + sh
        trades.append((d, t, "BUY", sh, price, buy_val, cost))
        return buy_val

    def do_entry(ev, d, boundary=False):
        qtd = qtd_table(bx, ev)
        picks = picker(ev, qtd)
        v_pre = value(d) if not boundary else START_CASH
        if not boundary:
            sell_all_at_close(d)
        for t in picks:
            buy_value(t, d, bx.close_on_or_before(t, d), 0.20 * v_pre)
        spy_c0 = bx.close_on_or_before("SPY", ev["L"])
        spy_c1 = bx.close_on_or_before("SPY", ev["exit"])
        basket_rel = None
        if picks:
            rels = []
            for t in picks:
                a = bx.close_on_or_before(t, ev["L"])
                b = bx.close_on_or_before(t, ev["exit"])
                if a and b:
                    rels.append(b / a)
            if rels:
                basket_rel = sum(rels) / len(rels)
        event_log.append({
            "L": ev["L"], "exit": ev["exit"], "boundary": boundary,
            "picks": list(picks),
            "picks_qtd_pct": {t: round(qtd[t] * 100, 2) for t in picks
                              if t in qtd},
            "basket_gross_pct": (round((basket_rel - 1) * 100, 2)
                                 if basket_rel else None),
            "spy_gross_pct": (round((spy_c1 / spy_c0 - 1) * 100, 2)
                              if spy_c0 and spy_c1 else None),
            "pot_after_entry": round(value(d), 2) if not boundary else None,
        })
        return picks

    def do_exit(ev, d):
        sell_all_at_close(d)
        buy_value("SPY", d, bx.close_on_or_before("SPY", d), cash)

    # ---- pre-window positioning
    first_ev = events[0] if events else None
    if first_ev is not None and first_ev["L"] < start:
        do_entry(first_ev, first_ev["L"], boundary=True)
    else:
        # no boundary event: open the window in SPY at the first open
        d0 = days[0]
        buy_value("SPY", d0, bx.open_on("SPY", d0), cash)

    end_date = days[-1]
    for k, d in enumerate(days):
        v = value(d)
        curve.append((d, v))
        # ---- floor check on the close (precedes any rotation at the
        # same close; champion semantics: halt -> liquidate next open)
        if v <= FLOOR0 and k < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": FLOOR0}
            nd = days[k + 1]
            for t in list(positions):
                opx = bx.open_on(t, nd)
                if opx is None:
                    opx = bx.close_on_or_before(t, nd)
                val = positions[t] * opx
                cost = val * 0.001 + 0.01
                cash += val - cost
                total_costs += cost
                trades.append((nd, t, "SELL-HALT", positions[t], opx,
                               val, cost))
            positions = {}
            end_date = nd
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": end_date,
                    "halt_info": halt_info, "curve": curve,
                    "events": event_log}
        # ---- entry rotation at the close of L
        if d in ev_by_L:
            do_entry(ev_by_L[d], d)
        # ---- exit rotation at the close of the 5th new-quarter day
        if d in ev_by_exit:
            do_exit(ev_by_exit[d], d)

    # ---- end of window: liquidate at the final close
    sell_all_at_close(days[-1], tag="SELL-END")
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": end_date,
            "halt_info": None, "curve": curve, "events": event_log}


# ------------------------------------------------------------------ pickers
def ranked_picker(ev, qtd):
    ranked = sorted(qtd.items(), key=lambda kv: (kv[1], kv[0]))
    return [t for t, _ in ranked[:TOP_N]]


def make_placebo_picker(seed):
    rng = random.Random(seed)

    def pick(ev, qtd):
        pool = sorted(qtd)
        return rng.sample(pool, TOP_N)
    return pick


# --------------------------------------------------------------- diagnostics
def diagnostics(r, floor0):
    curve = r["curve"]
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
        year_end[d[:4]] = (d, v)
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "floor": floor0,
            "worst_close_above_floor": round(worst_v - floor0, 2),
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "year_end_closes": {y: {"date": d, "close": round(v, 2)}
                                for y, (d, v) in sorted(year_end.items())}}


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def placebo_stats(ranked_final, finals):
    s = sorted(finals)
    beat = sum(1 for f in finals if ranked_final > f)
    return {"n": len(finals), "median": round(_pct(s, 0.5), 2),
            "q1": round(_pct(s, 0.25), 2), "q3": round(_pct(s, 0.75), 2),
            "best": round(s[-1], 2), "worst": round(s[0], 2),
            "beat": beat,
            "percentile": round(100.0 * beat / len(finals), 1),
            "finals": [round(f, 2) for f in finals]}


# --------------------------------------------------------------------- main
def main():
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
        print(f"{t}: {len(bars[t])} bars "
              f"{bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    pb = E.PriceBook(bars)
    bx = Bars(bars)
    calendar = [b["d"] for b in bars["SPY"]]  # SPY trading calendar

    # ---- integrity gate: SPY buy-hold must reproduce the published
    # figures to the cent before any variant number is taken.
    integrity = {}
    for wname, ws, we in WINDOWS:
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        integrity[wname] = round(s, 2)
        print(f"INTEGRITY {wname}: spy_net=${s:,.2f} "
              f"(published ${SPY_PUBLISHED[wname]:,.2f})", flush=True)
        assert abs(round(s, 2) - SPY_PUBLISHED[wname]) < 0.005, \
            f"SPY integrity failed on {wname}: {s} vs {SPY_PUBLISHED[wname]}"

    all_events = build_events(calendar)

    out = {
        "test": "N-3 Quarter-End Window-Dressing Rebound (invented 2026)",
        "invented_track": "1 of 12 invented rules",
        "spec_source": "research/v8-novel/novel-cross-calendar.md, Rule N-3",
        "chassis": {"start_cash": START_CASH, "floor": FLOOR0,
                    "costs": "0.10% of trade value per side + $0.01 per "
                             "sell order"},
        "integrity_spy_net": integrity,
        "champion_reference": CHAMPION,
        "spy_published": SPY_PUBLISHED,
        "forced_readings": [
            "Event membership: an event belongs to a window if its EXIT "
            "day (5th trading day of the new quarter) falls inside the "
            "window. This includes the quarter-end immediately preceding "
            "each window's start (2018-12-31 continuous; 2022-12-30 "
            "validation), giving the census of 32 continuous / 16 "
            "validation events. For that boundary event the entry is "
            "executed at the close of L with the starting $100, so the "
            "pot opens the window already holding the basket, exactly "
            "as the rule prescribes; no SPY is bought before it.",
            "Trades execute at the close prices the spec names (entry at "
            "the close of L, exit at the close of the 5th trading day) — "
            "the mechanism is defined on those closes, overriding the "
            "chassis' next-open default.",
            "Ranking ties break by ticker, alphabetically. A name with "
            "no computable quarter-to-date return (no close on L or on "
            "the prior quarter-end) is excluded from that quarter's "
            "ranking and from the placebo draw pool.",
            "At entry each name's target is 20% of the pot's pre-trade "
            "close value; buys execute sequentially in pick order under "
            "the champion cash constraint (buy value = min(target, "
            "cash/1.001)).",
            "The floor check at each close precedes any rotation "
            "scheduled at that same close; a halt liquidates at the "
            "next open (champion semantics).",
            "End-of-window finals are post-liquidation cash at the "
            "final close (champion convention).",
            "Placebo draws: uniform without replacement from the same "
            "quarter's rankable set; one RNG per seed, advanced "
            "chronologically across the window's events.",
            "The non-quarter-end control run the spec forbids was NOT "
            "run.",
        ],
        "windows": {},
    }

    verdict_inputs = {}
    for wname, ws, we in WINDOWS:
        evs = [e for e in all_events if ws <= e["exit"] <= we]
        print(f"== {wname}: {len(evs)} events "
              f"({evs[0]['L']} .. {evs[-1]['L']})", flush=True)
        r = simulate(bx, calendar, ws, we, evs, ranked_picker,
                     label=f"{wname} N-3 RANKED")
        diag = diagnostics(r, FLOOR0)
        print(f"== {wname} N-3 RANKED final=${r['final']:,.2f} "
              f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
              f"halted={r['halted']} | SPY=${SPY_PUBLISHED[wname]:,.2f} "
              f"| champion=${CHAMPION[wname]:,.2f}", flush=True)

        finals = []
        phalted = 0
        for seed in PLACEBO_SEEDS:
            pr = simulate(bx, calendar, ws, we, evs,
                          make_placebo_picker(seed),
                          label=f"{wname} placebo s{seed}")
            finals.append(pr["final"])
            if pr["halted"]:
                phalted += 1
        ps = placebo_stats(r["final"], finals)
        ps["halted"] = phalted
        print(f"   placebo: median=${ps['median']:,.2f} "
              f"best=${ps['best']:,.2f} worst=${ps['worst']:,.2f} "
              f"beat={ps['beat']}/20 halted={phalted}/20", flush=True)

        out["windows"][wname] = {
            "start": ws, "end": we,
            "event_census_count": len(evs),
            "events": r["events"],
            "ranked": {"final": round(r["final"], 2),
                       "costs": round(r["costs"], 2),
                       "orders": len(r["trades"]),
                       "halted": r["halted"],
                       "halt_info": r["halt_info"],
                       "diag": diag,
                       "trades": r["trades"]},
            "spy_net": SPY_PUBLISHED[wname],
            "champion": CHAMPION[wname],
            "placebo": ps,
        }
        verdict_inputs[wname] = {
            "final": r["final"], "halted": r["halted"],
            "placebo_beat": ps["beat"]}

    # ---- CANDIDATE bar (all four required)
    crit = {
        "validation_final_gt_spy_187.77":
            verdict_inputs["VALIDATION"]["final"] > SPY_PUBLISHED["VALIDATION"],
        "validation_placebo_ge_19_of_20":
            verdict_inputs["VALIDATION"]["placebo_beat"] >= 19,
        "continuous_final_gt_spy_313.62":
            verdict_inputs["FULL"]["final"] > SPY_PUBLISHED["FULL"],
        "no_floor_halt_either_window":
            not verdict_inputs["FULL"]["halted"]
            and not verdict_inputs["VALIDATION"]["halted"],
    }
    out["candidate_criteria"] = crit
    out["verdict"] = ("CANDIDATE" if all(crit.values())
                      else "NOT A CANDIDATE")
    print(f"VERDICT: {out['verdict']}  criteria={crit}", flush=True)

    with open(os.path.join(HERE, "novel-x3-window-dressing-results.json"),
              "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
