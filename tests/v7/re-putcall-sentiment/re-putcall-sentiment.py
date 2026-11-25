#!/usr/bin/env python3
"""
PUBLIC PUT/CALL SENTIMENT TIMING — reverse-engineering audit spec 4.5
(the public shadow of options-flow information; Pan & Poteshman 2006).

FROZEN SPEC (research/v7-completeness/firm-reverse-engineering.md, SS4.5):
  - Data: CBOE daily EQUITY put/call ratio, free historical file.
    Total and index ratios are NOT run -- one series, one shot.
  - Rule: 5-trading-day mean of the equity P/C ratio. Threshold = the
    90th percentile of that 5-day mean over 2006-2015 (pre-design data
    ONLY), computed once, reported, frozen. Each Friday close: if the
    current 5-day mean >= threshold, hold SPY for the following week;
    otherwise hold cash. (Contrarian form.)
  - Costs/floor: program standard on every state flip (buy 0.10%;
    sell 0.10% + $0.01); plain -15% floor ($85). 2x-cost stress reported
    alongside (program SS4 preamble convention).
  - Judging: continuous 2019-01-01 -> 2026-11-20 and validation
    2023-01-01 -> 2026-11-20 vs SPY buy-hold. Placebo: 20 seeds with the
    threshold drawn at random percentiles (70th-99th) of the same
    2006-2015 distribution. Gate: beat SPY net on validation AND
    >=18/20 threshold placebos.

DATA REALITY (found before any strategy number was taken; see the .md):
  CBOE's free equitypc.csv ends 2019-10-04. The 2006-2015 threshold
  freeze is fully supported; the judging windows are not (validation
  coverage = 0 days). This script therefore (a) freezes the threshold
  exactly as specified, (b) runs the strategy over the covered stub of
  the continuous window (2019-01-01 -> 2019-10-04) with full mechanics
  as a PARTIAL-COVERAGE descriptive run, and (c) does NOT apply the
  pre-registered gate, which is defined on the validation window.

FORCED READINGS (stated in the report before results):
  1. Friday's P/C ratio is published after Friday's close, so a Friday-
     close decision using Friday's own ratio fills at the NEXT trading
     day's open (the champion engine's decide-at-close / fill-at-next-
     open convention).
  2. Decision day = the last SPY trading day of each calendar week
     (Friday, or the week's final trading day when Friday is a holiday).
  3. Always-on window entry (the CAPE test's convention): a pot enters
     its window in the state dictated by the most recent decision day
     on or before the window start; if IN, it buys at the window's
     first open at program costs.
  4. The 5-day mean at a decision day uses the 5 most recent CBOE
     prints on or before that day.
  5. 2x stress doubles both cost components (buy 0.20%; sell 0.20%
     + $0.02).
  6. Placebo seeds 1..20: percentile = random.Random(seed).uniform(70,
     99); threshold = that percentile of the identical freeze
     distribution via the champion engine's _pct (linear interpolation).

Simulation only. Run once; no tuning.
"""
import csv
import datetime
import json
import math
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SPY_CACHE = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/data/px_SPY.json")

START_CASH = 100.0
FLOOR0 = 85.0
BUY_RATE = 0.001          # 0.10%
SELL_RATE = 0.001         # 0.10%
SELL_FEE = 0.01

FREEZE_START = "2006-11-01"   # first day of the CBOE equity series
FREEZE_END = "2015-12-31"
THRESH_Q = 0.90

FULL = ("2019-01-01", "2026-11-20")        # continuous judging window
VALIDATION = ("2023-01-01", "2026-11-20")  # validation judging window


# --------------------------------------------------------------- SPY bars
# Bar construction copied verbatim from the champion engine
# (v4/value-momentum-plainfloor.py get_prices): open scaled by the
# adjclose/close ratio, close = adjclose.
def load_spy_bars():
    with open(SPY_CACHE, "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
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


def _pct(sorted_vals, q):
    """Percentile, linear interpolation -- the champion engine's _pct."""
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


def spy_net(bars_by_date, days, start_cash):
    """Champion engine spy_net arithmetic, verbatim in substance."""
    first, last = days[0], days[-1]
    o = bars_by_date[first]["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    val = sh * bars_by_date[last]["c"]
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost


# ------------------------------------------------------------ CBOE series
def load_equity_pc():
    """Parse CBOE equitypc.csv -> sorted [(date_str, ratio)]."""
    path = os.path.join(DATA, "equitypc_raw.csv")
    rows = []
    with open(path, newline="") as f:
        for line in f:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 5 and parts[0] and parts[0][0].isdigit():
                d = datetime.datetime.strptime(parts[0], "%m/%d/%Y")
                rows.append((d.strftime("%Y-%m-%d"), float(parts[4]),
                             int(parts[1]), int(parts[2])))
    rows.sort(key=lambda r: r[0])
    return rows


def mean5_series(pc_rows):
    """[(date, mean of the 5 prints ending on that date)] for every
    print date with a full 5-print window."""
    out = []
    vals = [r[1] for r in pc_rows]
    for i in range(4, len(pc_rows)):
        out.append((pc_rows[i][0], sum(vals[i - 4:i + 1]) / 5.0))
    return out


# ------------------------------------------------------------- the engine
def decision_days(bars, upto):
    """Last SPY trading day of each ISO calendar week, for all bars
    with date <= upto. Returns a set of date strings."""
    by_week = {}
    for b in bars:
        if b["d"] > upto:
            break
        iso = datetime.date.fromisoformat(b["d"]).isocalendar()
        by_week[(iso[0], iso[1])] = b["d"]  # later day overwrites
    return set(by_week.values())


def run_pot(bars, bars_by_date, mean5_by_date, start, end, threshold,
            cost_mult=1.0, label=""):
    """Weekly put/call timing on SPY. Fresh $100 pot, plain -15% floor.
    Returns the house result dict plus timing diagnostics."""
    buy_rate = BUY_RATE * cost_mult
    sell_rate = SELL_RATE * cost_mult
    sell_fee = SELL_FEE * cost_mult
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    if not days:
        return None
    dec = decision_days(bars, end)
    cash = START_CASH
    shares = 0.0
    total_costs = 0.0
    trades = []
    curve = []
    halted = None
    halt_info = None
    days_in = 0
    entries = 0

    def mean5_on_or_before(d):
        # 5 most recent prints on or before d: mean5_series is keyed by
        # print date; walk back over sorted print dates.
        best = None
        for pd_, m in mean5_by_date:
            if pd_ <= d:
                best = m
            else:
                break
        return best

    # Always-on entry: state from the most recent decision day <= start.
    pending = None
    prior_dec = [d for d in dec if d < days[0]]
    if prior_dec:
        m = mean5_on_or_before(max(prior_dec))
        if m is not None:
            pending = "IN" if m >= threshold else "CASH"

    def do_buy(d):
        nonlocal cash, shares, total_costs, entries
        o = bars_by_date[d]["o"]
        sh = (cash / (1.0 + buy_rate)) / o
        c = cash - sh * o
        total_costs += c
        trades.append((d, "SPY", "BUY", round(sh, 6), round(o, 4),
                       round(sh * o, 2), round(c, 2)))
        shares = sh
        cash = 0.0
        entries += 1

    def do_sell(d, at_open=True, tag="SELL"):
        nonlocal cash, shares, total_costs
        px = bars_by_date[d]["o"] if at_open else bars_by_date[d]["c"]
        val = shares * px
        c = val * sell_rate + sell_fee
        cash = val - c
        total_costs += c
        trades.append((d, "SPY", tag, round(shares, 6), round(px, 4),
                       round(val, 2), round(c, 2)))
        shares = 0.0
        return cash

    for di, d in enumerate(days):
        # fill yesterday's decision at today's open
        if pending is not None:
            if pending == "IN" and shares == 0.0 and cash > 0:
                do_buy(d)
            elif pending == "CASH" and shares > 0.0:
                do_sell(d)
            pending = None
        if shares > 0.0:
            days_in += 1
        # decision at today's close?
        if d in dec:
            m = mean5_on_or_before(d)
            if m is not None:
                pending = "IN" if m >= threshold else "CASH"
        v = cash + shares * bars_by_date[d]["c"]
        curve.append((d, v))
        if v <= FLOOR0 and di < len(days) - 1:
            halted = days[di + 1]
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": FLOOR0}
            if shares > 0.0:
                do_sell(halted, at_open=True, tag="SELL-HALT")
            else:
                cash = v
            return {"label": label, "final": round(cash, 2),
                    "costs": round(total_costs, 2), "trades": trades,
                    "halted": halted, "end": halted,
                    "halt_info": halt_info, "curve": curve,
                    "days_in_market": days_in, "entries": entries}
    last = days[-1]
    if shares > 0.0:
        do_sell(last, at_open=False, tag="SELL-END")
    else:
        cash = cash
    return {"label": label, "final": round(cash, 2),
            "costs": round(total_costs, 2), "trades": trades,
            "halted": None, "end": last, "halt_info": None,
            "curve": curve, "days_in_market": days_in,
            "entries": entries}


def curve_stats(r, start_cash=START_CASH):
    curve = r["curve"]
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    worst, worst_d = 1e18, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
        if v < worst:
            worst, worst_d = v, d
    return {"final": r["final"],
            "return_pct": round(r["final"] / start_cash * 100 - 100, 2),
            "orders": len(r["trades"]), "costs": r["costs"],
            "halted": r["halted"], "halt_info": r["halt_info"],
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "worst_close": round(worst, 2), "worst_close_date": worst_d,
            "days_in_market": r["days_in_market"],
            "days_total": len(curve),
            "pct_days_in": round(100.0 * r["days_in_market"] / len(curve), 1),
            "entries": r["entries"]}


# ------------------------------------------------------------------ main
def main():
    out = {"strategy": "PUBLIC PUT/CALL SENTIMENT TIMING (spec 4.5): "
                       "CBOE equity P/C 5-day mean >= its 2006-2015 "
                       "90th percentile -> hold SPY the following week, "
                       "else cash; Friday decisions, next-open fills",
           "pot": START_CASH, "floor": FLOOR0,
           "source": "CBOE equitypc.csv (cdn.cboe.com/resources/options/"
                     "volume_and_call_put_ratios/equitypc.csv), fetched "
                     "2026-11-21; SPY bars from the program v4 cache "
                     "(px_SPY.json, Yahoo chart payload, champion-engine "
                     "bar construction)"}

    bars = load_spy_bars()
    bars_by_date = {b["d"]: b for b in bars}
    pc_rows = load_equity_pc()
    out["pc_coverage"] = {"first": pc_rows[0][0], "last": pc_rows[-1][0],
                          "rows": len(pc_rows)}
    print(f"CBOE equity P/C: {len(pc_rows)} rows, "
          f"{pc_rows[0][0]} -> {pc_rows[-1][0]}", flush=True)
    # parse cross-check: published ratio vs PUT/CALL volumes
    bad = 0
    for d, ratio, calls, puts in pc_rows:
        if abs(puts / calls - ratio) > 0.011:
            bad += 1
    out["pc_parse_check"] = {"rows_off_by_more_than_rounding": bad}
    print(f"parse cross-check: {bad} rows differ from PUT/CALL by "
          f">0.011 (rounding tolerance)", flush=True)

    # ---- replication check: champion SPY nets from this cache
    for tag, (ws, we), expect in (("FULL", FULL, 313.62),
                                  ("VALIDATION", VALIDATION, 187.77)):
        days = [b["d"] for b in bars if ws <= b["d"] <= we]
        net, cst = spy_net(bars_by_date, days, START_CASH)
        ok = abs(net - expect) < 0.005
        print(f"REPLICATION {tag}: SPY net=${net:,.2f} "
              f"expected=${expect:,.2f} match={ok}", flush=True)
        out[f"replication_{tag.lower()}"] = {
            "spy_net": round(net, 2), "expected": expect, "match": ok}
        if not ok:
            raise SystemExit("REPLICATION FAILED - numbers untrusted")

    # ---- (1) the frozen threshold, 2006-2015 only
    m5 = mean5_series(pc_rows)
    mean5_by_date = [(d, m) for d, m in m5]
    freeze_vals = sorted(m for d, m in m5
                         if FREEZE_START <= d <= FREEZE_END)
    freeze_rows = [r for r in pc_rows
                   if FREEZE_START <= r[0] <= FREEZE_END]
    threshold = _pct(freeze_vals, THRESH_Q)
    out["freeze"] = {
        "window": [FREEZE_START, FREEZE_END],
        "trading_days": len(freeze_rows),
        "five_day_means": len(freeze_vals),
        "mean5_min": round(freeze_vals[0], 4),
        "mean5_median": round(_pct(freeze_vals, 0.50), 4),
        "mean5_max": round(freeze_vals[-1], 4),
        "threshold_q": THRESH_Q,
        "threshold": round(threshold, 4)}
    print(f"FREEZE 2006-2015: {len(freeze_rows)} trading days, "
          f"{len(freeze_vals)} 5-day means; 90th pct = {threshold:.4f}",
          flush=True)

    # ---- (2) coverage accounting for the judging windows
    cov = {}
    for tag, (ws, we) in (("full", FULL), ("validation", VALIDATION)):
        days = [b["d"] for b in bars if ws <= b["d"] <= we]
        covered = [d for d in days if d <= pc_rows[-1][0]]
        cov[tag] = {"window": [ws, we], "spy_trading_days": len(days),
                    "days_with_pc_data": len(covered),
                    "pct_covered": round(100.0 * len(covered)
                                         / max(len(days), 1), 1),
                    "last_covered_day": covered[-1] if covered else None}
        print(f"COVERAGE {tag}: {len(covered)}/{len(days)} trading days "
              f"({cov[tag]['pct_covered']}%)", flush=True)
    out["coverage"] = cov

    # ---- (3) PARTIAL-COVERAGE stub run of the continuous window
    stub_start, stub_end = FULL[0], pc_rows[-1][0]
    out["stub_note"] = ("PARTIAL COVERAGE ONLY: the continuous window "
                        "is run from its start to the last date with "
                        "CBOE data (2019-10-04). The validation window "
                        "has zero covered days and is NOT run; the "
                        "pre-registered gate is defined on validation "
                        "and therefore cannot be evaluated.")
    stub_days = [b["d"] for b in bars if stub_start <= b["d"] <= stub_end]
    spy_stub, spy_stub_costs = spy_net(bars_by_date, stub_days, START_CASH)
    print(f"STUB {stub_start}->{stub_end}: SPY buy-hold net="
          f"${spy_stub:,.2f}", flush=True)

    r = run_pot(bars, bars_by_date, mean5_by_date, stub_start, stub_end,
                threshold, cost_mult=1.0, label="STUB RANKED")
    st = curve_stats(r)
    st.update({"start": stub_start, "end": stub_end,
               "spy_net_final": round(spy_stub, 2),
               "spy_costs": round(spy_stub_costs, 2),
               "threshold": round(threshold, 4)})
    print(f"STUB RANKED: final=${r['final']:,.2f} "
          f"({st['return_pct']:+.2f}%) maxDD={st['max_drawdown_pct']}% "
          f"orders={st['orders']} costs=${st['costs']} "
          f"in-market {st['pct_days_in']}% entries={st['entries']} "
          f"halted={r['halted']}", flush=True)
    out["stub_ranked"] = st

    r2 = run_pot(bars, bars_by_date, mean5_by_date, stub_start, stub_end,
                 threshold, cost_mult=2.0, label="STUB RANKED 2X")
    st2 = curve_stats(r2)
    st2.update({"start": stub_start, "end": stub_end})
    print(f"STUB RANKED 2x COSTS: final=${r2['final']:,.2f} "
          f"({st2['return_pct']:+.2f}%) costs=${st2['costs']}", flush=True)
    out["stub_ranked_2x"] = st2

    # signal frequency on the stub (decision days with mean5 >= thr)
    dec_stub = sorted(d for d in decision_days(bars, stub_end)
                      if stub_start <= d <= stub_end)
    m5map = dict(mean5_by_date)
    # mean on or before each decision day, same walk as the engine
    sorted_m5_dates = [d for d, _ in mean5_by_date]

    def m_on(d):
        best = None
        for pd_, m in mean5_by_date:
            if pd_ <= d:
                best = m
            else:
                break
        return best
    fires = sum(1 for d in dec_stub
                if (m_on(d) is not None and m_on(d) >= threshold))
    out["stub_signal"] = {"decision_days": len(dec_stub),
                          "weeks_signaled_in": fires}
    print(f"STUB SIGNAL: {fires}/{len(dec_stub)} decision weeks "
          f"signaled IN", flush=True)

    # ---- (4) threshold placebos on the stub (descriptive only)
    rows = []
    finals = []
    for seed in range(1, 21):
        rng = random.Random(seed)
        q = rng.uniform(70.0, 99.0)
        thr_p = _pct(freeze_vals, q / 100.0)
        pr = run_pot(bars, bars_by_date, mean5_by_date, stub_start,
                     stub_end, thr_p, cost_mult=1.0,
                     label=f"STUB PLACEBO {seed}")
        finals.append(pr["final"])
        rows.append({"seed": seed, "drawn_percentile": round(q, 2),
                     "threshold": round(thr_p, 4),
                     "final": pr["final"], "halted": pr["halted"],
                     "orders": len(pr["trades"]),
                     "costs": pr["costs"]})
        print(f"  STUB PLACEBO seed {seed:2d}: q={q:5.2f} "
              f"thr={thr_p:.4f} final=${pr['final']:,.2f} "
              f"halted={pr['halted']}", flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < r["final"])
    out["stub_placebo"] = {
        "median": round(_pct(srt, 0.50), 2), "best": round(srt[-1], 2),
        "worst": round(srt[0], 2),
        "ranked_final": r["final"], "seeds_beaten": below,
        "note": "Descriptive only - the pre-registered gate applies "
                "to the validation window, which has no data.",
        "rows": rows}
    print(f"STUB PLACEBO: median=${out['stub_placebo']['median']:,.2f} "
          f"| ranked ${r['final']:,.2f} beat {below}/20 (descriptive "
          f"only; gate not applicable)", flush=True)

    out["gate_evaluation"] = {
        "gate_as_specified": "beat SPY net on validation AND >=18/20 "
                             "threshold placebos (on validation)",
        "evaluable": False,
        "reason": "Validation window (2023-01-01 -> 2026-11-20) has "
                  "zero days of CBOE equity put/call data: CBOE's "
                  "free historical files end 2019-10-04.",
        "verdict": "NOT PROMOTED - UNTESTABLE ON FREE DATA past "
                   "2019-10-04 (data wall, not a strategy failure "
                   "and not a pass)"}

    with open(os.path.join(HERE, "re-putcall-sentiment-results.json"),
              "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
