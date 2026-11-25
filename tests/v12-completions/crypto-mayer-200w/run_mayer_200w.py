#!/usr/bin/env python3
"""
CRYPTO MAYER / 200W — v12 crypto wing, family crypto-mayer-200w. SIMULATION ONLY.

Frozen construction (see CONSTRUCTION-SPEC.md):
  Form W: hold coin when close <= mean(last 1400 daily closes), else cash.  [CONSTRUCTED]
  Form M: hold coin while Mayer Multiple (close / mean(last 200 closes)) < 2.4, else cash. [CONSTRUCTED around Mayer's published 2.4 gate]
  Rule sets: native (no floor) and v9 house (floor+ladder: 85 -> 100 @125 -> 125 @150,
  checked on daily close, liquidate next open, halt permanently).
  Signals on close, execute next bar open. Cost 0.40%/side. Cash 0%. Pot $100.
Data (READ-ONLY): v4 crypto-basket-pit registry + cached daily bars.
Eligibility: honest history span >= 1400 days, else INSUFFICIENT-HISTORY closure.
"""
import json, os, random, statistics, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
CACHE = os.path.join(V4, "crypto-basket-pit-data")
COST = 0.004
START = 100.0
MIN_SPAN_DAYS = 1400
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}

# ---------------------------------------------------------------- data ----
def load_registry():
    with open(os.path.join(V4, "crypto-basket-pit-results.json")) as f:
        reg = json.load(f)["registry"]
    out = {}
    for cid_s, v in reg.items():
        cid = int(cid_s)
        rows = []
        if v["bars"] > 0:
            src = v["source"]
            if src.startswith("yahoo:"):
                path = os.path.join(CACHE, f"y_{src[6:]}.json")
            elif src.startswith("binance:"):
                path = os.path.join(CACHE, f"b_{src[8:]}.json")
            elif src.startswith("kraken:"):
                path = os.path.join(CACHE, f"k_{src[7:]}.json")
            else:
                path = None
            if path and os.path.exists(path):
                with open(path) as f:
                    rows = json.load(f)
            if cid in CREDIBLE_START:
                rows = [r for r in rows if r["d"] >= CREDIBLE_START[cid]]
        out[cid] = {**v, "rows": rows}
    return out

def sma_series(closes, w):
    out = [None] * len(closes)
    s = 0.0
    for i, c in enumerate(closes):
        s += c
        if i >= w:
            s -= closes[i - w]
        if i >= w - 1:
            out[i] = s / w
    return out

# ---------------------------------------------------------------- engine ----
def run_strategy(rows, signal, house):
    """signal[i] = desired holding (bool) decided on close of day i.
    Trades execute at open of day i+1. Returns dict with final, curve, maxdd, trades, exposure."""
    n = len(rows)
    cash, units = START, 0.0
    floor = 85.0
    halted = False
    trades = 0
    curve = []
    held_days = 0
    for i in range(n):
        o, c = rows[i]["o"], rows[i]["c"]
        # execute yesterday's signal at today's open
        if i > 0 and not halted:
            want = signal[i - 1]
            holding = units > 0
            if want and not holding and cash > 0:
                units = cash * (1 - COST) / o
                cash = 0.0
                trades += 1
            elif not want and holding:
                cash = units * o * (1 - COST)
                units = 0.0
                trades += 1
        eq = cash + units * c
        if units > 0:
            held_days += 1
        curve.append(eq)
        if house and not halted:
            if eq >= 150.0 and floor < 125.0:
                floor = 125.0
            elif eq >= 125.0 and floor < 100.0:
                floor = 100.0
            if eq <= floor:
                # liquidate at next open
                if i + 1 < n and units > 0:
                    cash = units * rows[i + 1]["o"] * (1 - COST)
                    units = 0.0
                    trades += 1
                halted = True
    final = cash + units * rows[-1]["c"]
    peak, maxdd = START, 0.0
    for eq in curve:
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1.0)
    if halted:
        final = cash
    return {"final": round(final, 2), "maxdd_pct": round(maxdd * 100, 1),
            "trades": trades, "exposure_pct": round(100.0 * held_days / max(n, 1), 1),
            "halted": halted, "curve": [round(x, 4) for x in curve]}

def buy_hold(rows):
    units = START * (1 - COST) / rows[0]["o"]
    curve = [units * r["c"] for r in rows]
    peak, maxdd = START, 0.0
    for eq in curve:
        peak = max(peak, eq)
        maxdd = min(maxdd, eq / peak - 1.0)
    return {"final": round(units * rows[-1]["c"], 2), "maxdd_pct": round(maxdd * 100, 1),
            "curve": [round(x, 4) for x in curve]}

def window_rows(rows, start_idx):
    return rows[start_idx:]

# ---------------------------------------------------------------- main ----
def main():
    reg = load_registry()
    btc_rows = reg[1]["rows"]
    results = {"family": "crypto-mayer-200w", "cost_per_side": COST,
               "bar_convention": "daily bars, UTC dates as cached by v4 PIT work; signals on close, execute next bar open; 200WMA = mean of last 1400 daily closes",
               "coins": {}, "closures": []}
    btc_cache = {}

    def btc_hold_for(first_d, last_d):
        key = (first_d, last_d)
        if key not in btc_cache:
            sub = [r for r in btc_rows if first_d <= r["d"] <= last_d]
            btc_cache[key] = buy_hold(sub) if len(sub) >= 2 else None
        return btc_cache[key]

    for cid in sorted(reg):
        v = reg[cid]
        sym = v["symbol"]
        rows = v["rows"]
        if not rows:
            results["closures"].append({"cmc_id": cid, "symbol": sym,
                "closure": "NO-FREE-SERIES", "reason": v["reason"]})
            continue
        span_days = (date.fromisoformat(rows[-1]["d"]) - date.fromisoformat(rows[0]["d"])).days + 1
        weeks = round(span_days / 7.0, 1)
        if span_days < MIN_SPAN_DAYS:
            results["closures"].append({"cmc_id": cid, "symbol": sym,
                "closure": "INSUFFICIENT-HISTORY",
                "reason": f"history spans {span_days} days = {weeks} weeks (< 200 weeks required for the 200WMA)",
                "weeks_available": weeks, "first": rows[0]["d"], "last": rows[-1]["d"]})
            continue

        closes = [r["c"] for r in rows]
        sma200 = sma_series(closes, 200)
        sma1400 = sma_series(closes, 1400)
        coin = {"cmc_id": cid, "symbol": sym, "source": v["source"],
                "first": rows[0]["d"], "last": rows[-1]["d"], "bars": len(rows),
                "weeks_history": weeks, "forms": {}}
        for form, sig_full, start_idx in (
            ("W_200wma", [ (sma1400[i] is not None and closes[i] <= sma1400[i]) for i in range(len(rows))], 1399),
            ("M_mayer24", [ (sma200[i] is not None and closes[i] / sma200[i] < 2.4) for i in range(len(rows))], 199),
        ):
            wrows = window_rows(rows, start_idx)
            sig = sig_full[start_idx:]
            nat = run_strategy(wrows, sig, house=False)
            hou = run_strategy(wrows, sig, house=True)
            hold = buy_hold(wrows)
            bh = btc_hold_for(wrows[0]["d"], wrows[-1]["d"])
            # ---- placebos on native (20 seeds each) ----
            n = len(wrows)
            exposure = sum(sig) / max(n, 1)
            rng = random.Random(12345 + cid)
            rand_finals, shift_finals = [], []
            for s in range(20):
                rsig = [rng.random() < exposure for _ in range(n)]
                rand_finals.append(run_strategy(wrows, rsig, house=False)["final"])
                off = rng.randint(30, max(31, n - 30))
                ssig = sig[off:] + sig[:off]
                shift_finals.append(run_strategy(wrows, ssig, house=False)["final"])
            def pct_rank(vals, x):
                return round(100.0 * sum(1 for y in vals if y < x) / len(vals), 0)
            # ---- split-half confirmation if native beats own hold ----
            confirm = None
            if nat["final"] > hold["final"]:
                mid = n // 2
                h1 = run_strategy(wrows[:mid], sig[:mid], house=False)
                h2 = run_strategy(wrows[mid:], sig[mid:], house=False)
                h1h = buy_hold(wrows[:mid]); h2h = buy_hold(wrows[mid:])
                confirm = {"half1_strategy": h1["final"], "half1_hold": h1h["final"],
                           "half2_strategy": h2["final"], "half2_hold": h2h["final"],
                           "both_halves_beat_hold": bool(h1["final"] > h1h["final"] and h2["final"] > h2h["final"])}
            coin["forms"][form] = {
                "window": [wrows[0]["d"], wrows[-1]["d"]],
                "native": {k: nat[k] for k in ("final", "maxdd_pct", "trades", "exposure_pct", "halted")},
                "v9_house": {k: hou[k] for k in ("final", "maxdd_pct", "trades", "exposure_pct", "halted")},
                "coin_hold": {"final": hold["final"], "maxdd_pct": hold["maxdd_pct"]},
                "btc_hold_same_window": {"final": bh["final"], "maxdd_pct": bh["maxdd_pct"]} if bh else None,
                "placebo_random_pct_rank": pct_rank(rand_finals, nat["final"]),
                "placebo_shifted_pct_rank": pct_rank(shift_finals, nat["final"]),
                "placebo_random_median": round(statistics.median(rand_finals), 2),
                "placebo_shifted_median": round(statistics.median(shift_finals), 2),
                "confirmation_split_half": confirm,
                "curves": {"native": nat["curve"], "v9_house": hou["curve"], "coin_hold": hold["curve"]},
                "curve_dates": [r["d"] for r in wrows],
            }
        results["coins"][sym] = coin
        print(f"{sym}: done", flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f)
    print("coins run:", len(results["coins"]), "closures:", len(results["closures"]))

if __name__ == "__main__":
    main()
