#!/usr/bin/env python3
"""V13 best-rules: crypto-vol-breakout-trend.
Spec: BEST-RULES-SPEC.md (FROZEN before this run).
MY form: Donchian 20-in / 20-out, daily, binary 100%/0%, no floor, 0.60%/side.
Published forms S1 20/10, S2 55/20 (0.40%/side) are recomputed ONLY on the
spec's frozen confirmation folds; full/conf published best is read from the
v12 record (read-only). Shared v4 data cache READ-ONLY.
"""
import json, os, sys
import numpy as np
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/crypto-vol-breakout-trend")
CACHE = os.path.join(V4, "crypto-basket-pit-data")
COST_BEST = 0.006
COST_PUB = 0.004
POT = 100.0
STABLES = {"USDT", "USDC", "DAI", "BUSD", "UST", "USD1", "USDe"}
CREDIBLE_START = {"FIL": "2020-10-15", "ARB": "2023-03-23", "TIA": "2023-10-31"}
BEST = (20, 20)
PUB_FORMS = {"S1_20_10": (20, 10), "S2_55_20": (55, 20)}

def load_coin(info):
    src = info["source"]
    kind, _, tag = src.partition(":")
    fn = {"yahoo": f"y_{tag}.json", "binance": f"b_{tag}.json",
          "kraken": f"k_{tag}.json"}.get(kind)
    if fn is None:
        return None
    with open(os.path.join(CACHE, fn)) as f:
        rows = json.load(f)
    sym = info["symbol"]
    cs = CREDIBLE_START.get(sym)
    out = []
    for r in rows:
        if cs and r["d"] < cs:
            continue
        if r["o"] <= 0 or r["c"] <= 0:
            continue
        out.append(r)
    return out

def roll_extreme(c, n, fn):
    out = np.full(len(c), np.nan)
    if len(c) > n:
        from numpy.lib.stride_tricks import sliding_window_view
        vals = fn(sliding_window_view(c, n), axis=1)
        idx = np.arange(n, len(c))
        out[idx] = vals[idx - n]
    return out

def simulate(dates, o, c, entry_n, exit_n, cost, start_i):
    """Long-only channel system, daily, no floor. Decisions at close i,
    executed at open i+1. Arrays are pre-truncated at the road's end bar."""
    n = len(c)
    hi = roll_extreme(c, entry_n, np.max)
    lo = roll_extreme(c, exit_n, np.min)
    cash, shares, inpos = POT, 0.0, False
    trades = 0
    equity = np.full(n, POT)
    invested_days = 0
    for i in range(start_i, n):
        if inpos:
            equity[i] = shares * c[i]
            invested_days += 1
        else:
            equity[i] = cash
        if i + 1 >= n:
            continue
        if not inpos and not np.isnan(hi[i]) and c[i] > hi[i]:
            shares = cash * (1 - cost) / o[i + 1]
            cash, inpos = 0.0, True
            trades += 1
        elif inpos and not np.isnan(lo[i]) and c[i] < lo[i]:
            cash = shares * o[i + 1] * (1 - cost)
            shares, inpos = 0.0, False
    if inpos:
        final = shares * c[-1] * (1 - cost)
    else:
        final = cash
    eq = equity[start_i:]
    peak = np.maximum.accumulate(eq)
    max_dd = float(np.min(eq / peak - 1)) if len(eq) else 0.0
    exposure = invested_days / max(len(eq), 1)
    return {"final": float(final), "max_dd_pct": round(max_dd * 100, 2),
            "trades": trades, "exposure": round(exposure, 3),
            "curve": equity}

def period_stats(equity, start_i):
    """Daily periods from the equity curve. No averages as headline."""
    eq = equity[start_i:]
    if len(eq) < 2:
        return None
    rets = eq[1:] / eq[:-1] - 1
    pos = int(np.sum(rets > 0))
    longest_loss, cur = 0, 0
    for x in rets:
        cur = cur + 1 if x < 0 else 0
        longest_loss = max(longest_loss, cur)
    peak = -np.inf
    last_high = 0
    longest_gap = 0
    for i, v in enumerate(eq):
        if v >= peak:
            peak = v
            longest_gap = max(longest_gap, i - last_high)
            last_high = i
    longest_gap = max(longest_gap, len(eq) - 1 - last_high)
    return {"periods": int(len(rets)),
            "pct_positive": round(100.0 * pos / len(rets), 1),
            "median_pct": round(float(np.median(rets)) * 100, 3),
            "best_pct": round(float(np.max(rets)) * 100, 2),
            "worst_pct": round(float(np.min(rets)) * 100, 2),
            "longest_losing_run": int(longest_loss),
            "longest_between_highs_days": int(longest_gap),
            "mean_pct_secondary": round(float(np.mean(rets)) * 100, 3)}

def buyhold(o, c, start_i, cost):
    sh = POT * (1 - cost) / o[start_i]
    eq = sh * c[start_i:]
    peak = np.maximum.accumulate(eq)
    dd = float(np.min(eq / peak - 1))
    return float(sh * c[-1] * (1 - cost)), round(dd * 100, 2)

def placebo_finals(dates, o, c, start_i, exposure, cost, seeds=range(1, 21)):
    """v12 chassis convention: weekly-step random timing, same average
    exposure, same costs, no floor."""
    n = len(c)
    wk = np.array([date.fromisoformat(d).isocalendar()[:2] for d in dates])
    step = np.zeros(n, dtype=bool)
    step[start_i] = True
    step[start_i + 1:] = (wk[start_i + 1:] != wk[start_i:-1]).any(axis=1)
    step_idx = np.where(step & (np.arange(n) >= start_i))[0]
    rets = np.zeros(n)
    rets[1:] = c[1:] / c[:-1] - 1
    finals = []
    for s in seeds:
        rng = np.random.default_rng(1000 + s)
        inweek = rng.random(len(step_idx)) < exposure
        pos = np.zeros(n, dtype=bool)
        for k, ix in enumerate(step_idx):
            j = step_idx[k + 1] if k + 1 < len(step_idx) else n
            pos[ix:j] = inweek[k]
        held = pos.copy()
        held[:-1] = pos[1:]
        chg = np.zeros(n, dtype=bool)
        chg[1:] = held[1:] != held[:-1]
        chg[start_i] = held[start_i]
        growth = np.where(held, 1 + rets, 1.0)
        growth = np.where(chg, growth * (1 - cost), growth)
        eq = POT * np.cumprod(growth)
        finals.append(float(eq[-1] * (1 - cost) if held[-1] else eq[-1]))
    return finals

def main():
    with open(os.path.join(V4, "crypto-basket-pit-results.json")) as f:
        reg = json.load(f)["registry"]
    with open(os.path.join(V12, "results.json")) as f:
        v12 = json.load(f)
    btc_rows = None
    coins = {}
    excluded, not_applicable = {}, {}
    for cid, info in reg.items():
        sym = info["symbol"]
        if info["source"] == "excluded" or not info["bars"]:
            excluded[sym] = info["reason"]
            continue
        if sym in STABLES:
            not_applicable[sym] = "pegged stablecoin — no trend to break out of"
            continue
        rows = load_coin(info)
        if rows is None or len(rows) < 260:
            excluded[sym] = f"series too short after cleaning ({0 if rows is None else len(rows)} bars)"
            continue
        coins[sym] = rows
        if sym == "BTC":
            btc_rows = rows
    btc_dates = [r["d"] for r in btc_rows]
    btc_o = np.array([r["o"] for r in btc_rows])
    btc_c = np.array([r["c"] for r in btc_rows])

    def btc_hold(d0, d1, cost):
        i0 = next(i for i, d in enumerate(btc_dates) if d >= d0)
        i1 = max(i for i, d in enumerate(btc_dates) if d <= d1)
        f, dd = buyhold(btc_o[i0:i1 + 1], btc_c[i0:i1 + 1], 0, cost)
        return round(f, 2), dd

    en, xn = BEST
    results = {"spec": "BEST-RULES-SPEC.md", "form": "Donchian 20-in/20-out daily binary no-floor",
               "cost_best": COST_BEST, "cost_published": COST_PUB,
               "coins": {}, "excluded": excluded,
               "not_applicable": not_applicable, "curves": {}}
    for sym, rows in sorted(coins.items()):
        dates = [r["d"] for r in rows]
        o = np.array([r["o"] for r in rows], dtype=float)
        c = np.array([r["c"] for r in rows], dtype=float)
        entry = {"symbol": sym, "bars": len(rows), "first": dates[0],
                 "last": dates[-1]}
        # --- FULL road (start after my channel warmup, as v12 did per form) ---
        r = simulate(dates, o, c, en, xn, COST_BEST, en)
        bh, bh_dd = buyhold(o, c, en, COST_BEST)
        btch = btc_hold(dates[en], dates[-1], COST_BEST)
        pf = placebo_finals(dates, o, c, en, r["exposure"], COST_BEST)
        pf_sorted = sorted(pf)
        entry["full"] = {
            "final": round(r["final"], 2), "max_dd_pct": r["max_dd_pct"],
            "trades": r["trades"], "exposure": r["exposure"],
            "buyhold": round(bh, 2), "buyhold_dd_pct": bh_dd,
            "btc_hold": btch[0], "btc_hold_dd_pct": btch[1],
            "beats_hold": r["final"] > bh, "beats_btc_hold": r["final"] > btch[0],
            "placebo_median": round(pf_sorted[len(pf) // 2], 2),
            "placebo_beats_n_of_20": sum(1 for v in pf if r["final"] > v),
            "period_stats": period_stats(r["curve"], en)}
        # --- CONFIRMATION road 2023-> (v12 definition) ---
        i23 = next((i for i, d in enumerate(dates) if d >= "2023-01-01"), None)
        if i23 is not None and len(rows) - i23 > 60:
            rv = simulate(dates, o, c, en, xn, COST_BEST, i23)
            bhv, bhv_dd = buyhold(o, c, i23, COST_BEST)
            btchv = btc_hold(dates[i23], dates[-1], COST_BEST)
            entry["conf"] = {
                "final": round(rv["final"], 2), "max_dd_pct": rv["max_dd_pct"],
                "trades": rv["trades"], "exposure": rv["exposure"],
                "buyhold": round(bhv, 2), "buyhold_dd_pct": bhv_dd,
                "btc_hold": btchv[0],
                "beats_hold": rv["final"] > bhv,
                "beats_btc_hold": rv["final"] > btchv[0],
                "period_stats": period_stats(rv["curve"], i23)}
        # --- Published/native best from the v12 record (read-only) ---
        v = v12["coins"].get(sym)
        if v:
            s1 = v["forms"]["S1_20_10|native"]; s2 = v["forms"]["S2_55_20|native"]
            entry["published_best_full"] = max(s1["final"], s2["final"])
            entry["published_best_full_form"] = "S1" if s1["final"] >= s2["final"] else "S2"
            entry["published_best_full_dd_pct"] = s1["max_dd_pct"] if s1["final"] >= s2["final"] else s2["max_dd_pct"]
            if "conf_final" in s1 and "conf_final" in s2:
                entry["published_best_conf"] = max(s1["conf_final"], s2["conf_final"])
            entry["v12_buyhold_full"] = v["buyhold_full"]
        # --- Frozen confirmation folds (spec section: Confirmation rule) ---
        folds = {}
        # Fold A: start -> 2019-12-31
        iA = max((i for i, d in enumerate(dates) if d <= "2019-12-31"), default=None)
        if iA is not None and iA + 1 >= 260:
            dA, oA, cA = dates[:iA + 1], o[:iA + 1], c[:iA + 1]
            ra = simulate(dA, oA, cA, en, xn, COST_BEST, en)
            bha, _ = buyhold(oA, cA, en, COST_BEST)
            rec = {"bars": iA + 1, "final": round(ra["final"], 2),
                   "max_dd_pct": ra["max_dd_pct"], "buyhold": round(bha, 2),
                   "beats_hold": ra["final"] > bha, "published": {}}
            for pn, (pen, pxn) in PUB_FORMS.items():
                rp = simulate(dA, oA, cA, pen, pxn, COST_PUB, pen)
                rec["published"][pn] = round(rp["final"], 2)
            rec["published_best"] = max(rec["published"].values())
            rec["beats_published_best"] = ra["final"] > rec["published_best"]
            folds["A_to_2019"] = rec
        # Fold B: 2020-01-01 -> 2022-12-31 (pre-2020 lookback allowed)
        iB0 = next((i for i, d in enumerate(dates) if d >= "2020-01-01"), None)
        iB1 = max((i for i, d in enumerate(dates) if d <= "2022-12-31"), default=None)
        if iB0 is not None and iB1 is not None and (iB1 - iB0 + 1) >= 260:
            dB, oB, cB = dates[:iB1 + 1], o[:iB1 + 1], c[:iB1 + 1]
            rb = simulate(dB, oB, cB, en, xn, COST_BEST, iB0)
            bhb, _ = buyhold(oB, cB, iB0, COST_BEST)
            rec = {"bars": iB1 - iB0 + 1, "final": round(rb["final"], 2),
                   "max_dd_pct": rb["max_dd_pct"], "buyhold": round(bhb, 2),
                   "beats_hold": rb["final"] > bhb, "published": {}}
            for pn, (pen, pxn) in PUB_FORMS.items():
                rp = simulate(dB, oB, cB, pen, pxn, COST_PUB, iB0)
                rec["published"][pn] = round(rp["final"], 2)
            rec["published_best"] = max(rec["published"].values())
            rec["beats_published_best"] = rb["final"] > rec["published_best"]
            folds["B_2020_2022"] = rec
        entry["folds"] = folds
        if sym in ("BTC", "ETH"):
            results["curves"][f"{sym}|BEST_20_20"] = [
                [dates[i], round(float(r["curve"][i]), 2)]
                for i in range(en, len(dates))]
        results["coins"][sym] = entry
        print(sym, "done", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f)
    print("coins run:", len(results["coins"]))

if __name__ == "__main__":
    main()
