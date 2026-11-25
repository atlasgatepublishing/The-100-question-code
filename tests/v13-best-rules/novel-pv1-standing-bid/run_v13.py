#!/usr/bin/env python3
"""
V13 BEST-RULES — N-PV1 "THE STANDING BID". Simulation only.

Implements BEST-RULES-SPEC.md in this folder, frozen before this run:
  - Universe: honest top-30 pond as of Nov 2016 (champion engine UNIVERSE).
  - Score: share of trailing 63 trading days with LS > US (lower-shadow
    share > upper-shadow share), tiebreak = median daily (LS - US).
    >= 50 valid (R > 0) days required.
  - Gate: signal-day close above the name's trailing 200-day SMA.
  - Top 10, equal-weight targets (1/10 of signal-day close pot value),
    quarterly signals (last trading day of Mar/Jun/Sep/Dec), execution at
    next open, NETTING (only entries bought / exits sold; continuing
    names untouched, weights drift).
  - NO pot floor. Costs 0.10%/side + $0.01 per sell order. $100 pots.
  - If fewer than 10 names pass the gate, unfilled slots stay in cash.
  - Placebos: 20 seeds/road, random draws of the ranked run's pick count
    from the same quarter's gate-passing eligible set, same mechanics.
Roads: LONG 2010-01-04, DECADE 2016-11-21, CONT 2019-01-02,
VAL 2023-01-03, all -> 2026-11-20 (v10 confirmation windows).
Data: PIT pxfull caches (v7 long-hold; GOOGL from the v10 folder's
documented payload). Signals use only bars <= signal day.
"""
import bisect
import importlib.util
import json
import os
import random
import statistics
import time

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
V10 = os.path.join(BT, "v10-retest", "novel-pv1-standing-bid")

spec = importlib.util.spec_from_file_location(
    "pv1v8", os.path.join(BT, "v8", "novel-pv1-standing-bid",
                          "novel-pv1-standing-bid.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)
UNIVERSE = list(M.UNIVERSE)

START_CASH = 100.0
TOP_N = 10
TRAIL = 63
MIN_VALID = 50
SMA_N = 200
ROADS = (("LONG", "2010-01-04", "2026-11-20"),
         ("DECADE", "2016-11-21", "2026-11-20"),
         ("CONT", "2019-01-02", "2026-11-20"),
         ("VAL", "2023-01-03", "2026-11-20"))
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
PUBLISHED = {"LONG": 730.61, "DECADE": 276.41, "CONT": 160.35, "VAL": 135.91}
SEEDS = list(range(1, 21))


def pxfull(ticker):
    if ticker == "GOOGL":
        path = os.path.join(V10, "pxfull_GOOGL.json")
    else:
        path = os.path.join(LH, f"pxfull_{ticker}.json")
    j = json.load(open(path))
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if c is None or o is None or h is None or l is None:
            continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": o * r, "h": h * r, "l": l * r, "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


BARS = {t: pxfull(t) for t in UNIVERSE + ["SPY"]}
CAL = sorted({b["d"] for bl in BARS.values() for b in bl})
IDX = {t: {b["d"]: i for i, b in enumerate(bl)} for t, bl in BARS.items()}
BAR = {t: {b["d"]: b for b in bl} for t, bl in BARS.items()}
DATES = {t: [b["d"] for b in bl] for t, bl in BARS.items()}


def close_on(t, d):
    i = IDX[t].get(d)
    if i is not None:
        return BARS[t][i]["c"]
    j = bisect.bisect_right(DATES[t], d) - 1
    return BARS[t][j]["c"] if j >= 0 else 0.0


def score_and_gate(t, d):
    """(score, tiebreak_median) or None if ineligible on signal day d."""
    i = IDX[t].get(d)
    if i is None or i < SMA_N - 1:
        return None
    bl = BARS[t]
    sma = sum(b["c"] for b in bl[i - SMA_N + 1:i + 1]) / SMA_N
    if bl[i]["c"] <= sma:
        return None
    diffs = []
    lo = max(0, i - TRAIL + 1)
    for b in bl[lo:i + 1]:
        r = b["h"] - b["l"]
        if r <= 0:
            continue
        ls = (min(b["o"], b["c"]) - b["l"]) / r
        us = (b["h"] - max(b["o"], b["c"])) / r
        diffs.append(ls - us)
    if len(diffs) < MIN_VALID:
        return None
    share = sum(1 for x in diffs if x > 0) / len(diffs)
    return share, statistics.median(diffs)


def run_pot(start, end, picker):
    """picker(signal_date, eligible) -> picks list; eligible =
    {ticker: (share, median)}. Returns run record with daily curve."""
    days = [d for d in CAL if start <= d <= end]
    day_set = set(days)
    # signal days: last in-road trading day of Mar/Jun/Sep/Dec with a
    # next in-road day to execute on
    signal_days = set()
    for k, d in enumerate(days[:-1]):
        if d[5:7] in ("03", "06", "09", "12") and days[k + 1][5:7] != d[5:7]:
            signal_days.add(d)
    cash = START_CASH
    positions = {}
    pending = None
    trades = []
    costs = 0.0
    curve = []
    signals = []

    def pot_close(d):
        return cash + sum(sh * close_on(t, d) for t, sh in positions.items())

    for d in days:
        if pending is not None:
            picks, target = pending
            pending = None
            for t in list(positions):
                if t in picks:
                    continue
                b = BAR[t].get(d)
                if not b:
                    continue
                val = positions[t] * b["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                costs += c
                trades.append((d, t, "SELL", round(b["o"], 4),
                               round(val, 2), round(c, 2)))
                del positions[t]
            for t in picks:
                if t in positions:
                    continue
                b = BAR[t].get(d)
                if not b:
                    continue
                buy_val = min(target, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / b["o"]
                c = buy_val * 0.001
                cash -= buy_val + c
                costs += c
                positions[t] = sh
                trades.append((d, t, "BUY", round(b["o"], 4),
                               round(buy_val, 2), round(c, 2)))
        v = pot_close(d)
        curve.append((d, round(v, 4)))
        if d in signal_days:
            elig = {}
            for t in UNIVERSE:
                s = score_and_gate(t, d)
                if s is not None:
                    elig[t] = s
            picks = picker(d, elig)
            signals.append({"signal_date": d, "eligible": len(elig),
                            "picks": list(picks),
                            "scores": {t: [round(s[0], 4), round(s[1], 4)]
                                       for t, s in sorted(
                                           elig.items(),
                                           key=lambda kv: (-kv[1][0],
                                                           -kv[1][1]))}})
            pending = (list(picks), v / TOP_N)
    last = days[-1]
    for t in list(positions):
        val = positions[t] * close_on(t, last)
        c = val * 0.001 + 0.01
        cash += val - c
        costs += c
        trades.append((last, t, "SELL-END", round(close_on(t, last), 4),
                       round(val, 2), round(c, 2)))
    return {"final": cash, "costs": costs, "trades": trades,
            "curve": curve, "signals": signals}


def ranked_picker(d, elig):
    return sorted(elig, key=lambda t: (-elig[t][0], -elig[t][1],
                                       UNIVERSE.index(t)))[:TOP_N]


def spy_net(start, end):
    days = [d for d in CAL if start <= d <= end]
    b0 = BAR["SPY"][days[0]]
    sh = (START_CASH / 1.001) / b0["o"]
    buy_cost = START_CASH - sh * b0["o"]  # approx: recompute exactly below
    # exact: spend x where x + 0.001x = 100 -> x = 100/1.001
    x = START_CASH / 1.001
    sh = x / b0["o"]
    c_buy = x * 0.001
    val = sh * close_on("SPY", days[-1])
    c_sell = val * 0.001 + 0.01
    return val - c_sell, c_buy + c_sell


def curve_stats(curve):
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    peak_d = curve[0][0]
    longest_no_high = 0
    for d, v in curve:
        if v > peak:
            peak, peak_d = v, d
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    # longest stretch between new highs (calendar days)
    from datetime import date
    prev_high_d = curve[0][0]
    runmax = curve[0][1]
    for d, v in curve:
        if v > runmax:
            runmax = v
            gap = (date.fromisoformat(d) - date.fromisoformat(prev_high_d)).days
            longest_no_high = max(longest_no_high, gap)
            prev_high_d = d
    gap = (date.fromisoformat(curve[-1][0]) -
           date.fromisoformat(prev_high_d)).days
    longest_no_high = max(longest_no_high, gap)
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = round(v, 2)
    # quarterly period returns from curve (calendar quarters)
    q_end = {}
    for d, v in curve:
        q_end[(d[:4], (int(d[5:7]) - 1) // 3)] = v
    keys = sorted(q_end)
    rets = []
    prev = START_CASH
    for k in keys:
        rets.append(q_end[k] / prev - 1.0)
        prev = q_end[k]
    pos = sum(1 for r in rets if r > 0)
    streak = longest = 0
    for r in rets:
        streak = streak + 1 if r <= 0 else 0
        longest = max(longest, streak)
    return {"max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "year_end_closes": year_end,
            "quarters": {"n": len(rets),
                         "median_pct": round(statistics.median(rets) * 100, 2)
                         if rets else None,
                         "share_positive_pct": round(100.0 * pos / len(rets), 1)
                         if rets else None,
                         "best_pct": round(max(rets) * 100, 2) if rets else None,
                         "worst_pct": round(min(rets) * 100, 2) if rets else None,
                         "longest_losing_streak_q": longest,
                         "returns_pct": [round(r * 100, 2) for r in rets]},
            "longest_stretch_between_new_highs_days": longest_no_high}


def main():
    out = {"family": "novel-pv1-standing-bid",
           "spec": "BEST-RULES-SPEC.md (v13, frozen before run)",
           "pot": START_CASH, "floor": None,
           "rules": "63d shadow-persistence share (LS>US), median tiebreak; "
                    "200d SMA gate; top 10; quarterly; netting; no floor; "
                    "costs 0.10%/side + $0.01/sell",
           "roads": {}}
    for tag, ws, we in ROADS:
        spy, spy_c = spy_net(ws, we)
        ok = abs(spy - SPY_REF[tag]) < 1.00
        print(f"SPY CHECK {tag}: ${spy:,.2f} vs ref ${SPY_REF[tag]:,.2f} "
              f"(within $1: {ok})", flush=True)
        r = run_pot(ws, we, ranked_picker)
        st = curve_stats(r["curve"])
        pick_counts = {s["signal_date"]: len(s["picks"])
                       for s in r["signals"]}
        finals = []
        rows = []
        for seed in SEEDS:
            rng = random.Random(seed)

            def placebo_picker(d, elig, rng=rng):
                n = min(pick_counts.get(d, TOP_N), len(elig))
                return rng.sample(sorted(elig), n) if n else []

            pr = run_pot(ws, we, placebo_picker)
            finals.append(pr["final"])
            rows.append({"seed": seed, "final": round(pr["final"], 2),
                         "costs": round(pr["costs"], 2)})
        srt = sorted(finals)
        beaten = sum(1 for f in finals if f < r["final"])
        pl = {"median": round(statistics.median(finals), 2),
              "q1": round(srt[len(srt) // 4], 2),
              "q3": round(srt[3 * len(srt) // 4], 2),
              "best": round(srt[-1], 2), "worst": round(srt[0], 2),
              "seeds_beaten": beaten, "rows": rows}
        rec = {"window": [ws, we], "final": round(r["final"], 2),
               "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
               "costs": round(r["costs"], 2),
               "n_trades": len(r["trades"]),
               "n_signals": len(r["signals"]),
               "spy_final": round(spy, 2),
               "champion_final": CHAMPION[tag],
               "published_form_final": PUBLISHED[tag],
               "placebo": pl,
               "signals": r["signals"], "trades": r["trades"],
               "curve": r["curve"]}
        rec.update(st)
        out["roads"][tag] = rec
        print(f"{tag}: final=${r['final']:,.2f} ({rec['return_pct']:+.2f}%) "
              f"maxDD={st['max_drawdown_pct']}% costs=${r['costs']:,.2f} "
              f"trades={len(r['trades'])} signals={len(r['signals'])} | "
              f"SPY=${spy:,.2f} CHAMP=${CHAMPION[tag]:,.2f} "
              f"PUB=${PUBLISHED[tag]:,.2f} | placebo median=${pl['median']:,.2f} "
              f"beat {beaten}/20", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
