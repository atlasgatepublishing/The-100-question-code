#!/usr/bin/env python3
"""crypto-funding-basis — V13 BEST RULES run.
Spec: ./BEST-RULES-SPEC.md (frozen 2026-11-22 19:32 UTC, before this run).

My rules vs the v12 published construction, ONE change: always-on
fully-collateralized 1x carry (long spot / short perp, $50 notional of a $100
pot at entry), no gate, no floor, no leverage — plus a MONTHLY hedge rebalance
(first settlement of each new calendar month: resize to notional = 50% of
current equity, both legs, fees on the traded delta). Everything else reuses
the v12 machine: funding settled per 8h event as qty x mark x published rate,
mark = 8h bar open at the settlement instant, spot fee 0.50%/side, perp fee
0.20%/side, final liquidation charged.

Placebos (20 seeds): the coin's funding-rate series permuted across time
(payments from the shuffled series, real price path, same machine/costs).
Roads: FULL 2020-01-01->2026-10-31 (SOL from first event), VAL 2023-01-01->
2026-10-31. PAPER RECORD — not a tradable pot.
"""
import json, os, random, sys
import pandas as pd, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "v12-completions", "crypto-funding-basis", "data")
POT = 100.0
SPOT_FEE, PERP_FEE = 0.005, 0.002
END = pd.Timestamp("2026-10-31 23:59:59", tz="UTC")

def load(coin):
    f = pd.read_csv(os.path.join(DATA, f"{coin}_funding.csv"))
    f["t"] = pd.to_datetime(f["calc_time"], unit="ms", utc=True)
    k = pd.read_csv(os.path.join(DATA, f"{coin}_klines8h.csv"))
    k["t"] = pd.to_datetime(k["open_time"], unit="ms", utc=True)
    k = k.set_index("t")["open"]
    f = f[f["t"] <= END].sort_values("t")
    f["bar_t"] = f["t"].dt.floor("8h")
    f["mark"] = f["bar_t"].map(k)
    n0 = len(f)
    f = f.dropna(subset=["mark"]).reset_index(drop=True)
    print(f"load {coin}: events kept {len(f)} of {n0}", flush=True)
    return f

def run_book(f, start, rates=None):
    """Always-on carry with monthly rebalance to notional = equity/2.
    rates: optional array aligned to f's rows replacing last_funding_rate
    (placebo runs). Returns dict with 8h equity Series + stats."""
    rate = f["last_funding_rate"].values if rates is None else rates
    idx = list(f.index[f["t"] >= start])
    if not idx:
        return None
    eq = POT
    qty = 0.0
    total_fees = 0.0
    funding_net = 0.0
    n_rebal = 0
    curve = []
    # entry at first event
    i = idx[0]
    p = float(f.at[i, "mark"])
    notional = eq / 2.0
    qty = notional / p
    fees = notional * SPOT_FEE + notional * PERP_FEE
    eq -= fees; total_fees += fees
    last_rb_month = (f.at[i, "t"].year, f.at[i, "t"].month)
    for pos, i in enumerate(idx):
        t = f.at[i, "t"]; p = float(f.at[i, "mark"])
        pay = qty * p * float(rate[i])
        eq += pay; funding_net += pay
        # monthly rebalance: first settlement seen in a new calendar month,
        # after that settlement's funding is collected
        mkey = (t.year, t.month)
        if pos > 0 and mkey != last_rb_month:
            target = eq / 2.0
            cur_notional = qty * p
            delta = target - cur_notional
            if abs(delta) > 1e-9:
                fees = abs(delta) * (SPOT_FEE + PERP_FEE)
                eq -= fees; total_fees += fees
                qty = target / p
                n_rebal += 1
            last_rb_month = mkey
        curve.append((t, eq))
    # final liquidation
    i = idx[-1]
    notional = qty * float(f.at[i, "mark"])
    fees = notional * SPOT_FEE + notional * PERP_FEE
    eq -= fees; total_fees += fees
    curve[-1] = (curve[-1][0], eq)
    s = pd.Series(dict(curve)); s.index = pd.DatetimeIndex(s.index)
    return {"equity": s, "final": float(eq), "fees": total_fees,
            "funding_net": funding_net, "rebalances": n_rebal}

def max_dd(s):
    return float((s / s.cummax() - 1).min()) if len(s) else 0.0

def period_stats_from_rets(rets):
    rets = np.asarray(rets, dtype=float)
    if len(rets) == 0:
        return {}
    win = rets > 0
    longest_loss = cur = 0
    for w in win:
        cur = 0 if w else cur + 1
        longest_loss = max(longest_loss, cur)
    return {"periods": int(len(rets)),
            "pct_periods_profitable": round(100 * float(win.mean()), 1),
            "median_period_pct": round(100 * float(np.median(rets)), 3),
            "best_period_pct": round(100 * float(rets.max()), 2),
            "worst_period_pct": round(100 * float(rets.min()), 2),
            "longest_losing_streak_periods": int(longest_loss),
            "mean_period_pct_secondary_average": round(100 * float(rets.mean()), 3)}

def monthly_stats(s):
    m = s.resample("M").last().dropna()
    vals = np.concatenate([[POT], m.values])
    st = period_stats_from_rets(np.diff(vals) / vals[:-1])
    # longest stretch between new highs, in months
    peak = vals[0]; since = 0; gap = 0
    for v in vals[1:]:
        if v >= peak: peak = v; since = 0
        else: since += 1; gap = max(gap, since)
    st["longest_stretch_between_new_highs_periods"] = int(gap)
    return st

def settle_stats(s):
    """Native-tempo distribution: per-8h-settlement returns of the equity curve."""
    vals = np.concatenate([[POT], s.values])
    rets = np.diff(vals) / vals[:-1]
    st = period_stats_from_rets(rets)
    peak = vals[0]; since = 0; gap = 0
    for v in vals[1:]:
        if v >= peak: peak = v; since = 0
        else: since += 1; gap = max(gap, since)
    st["longest_stretch_between_new_highs_periods"] = int(gap)
    return st

def buyhold(f, start):
    sub = f[f["t"] >= start]
    p0, p1 = float(sub["mark"].iloc[0]), float(sub["mark"].iloc[-1])
    qty = (POT * (1 - SPOT_FEE)) / p0
    final = qty * p1 * (1 - SPOT_FEE)
    s = sub.set_index("t")["mark"] * qty
    return {"final": round(float(final), 2), "max_dd_pct": round(100 * max_dd(s), 2),
            "period_stats_monthly": monthly_stats(s)}

def year_end(s):
    m = s.resample("M").last().dropna()
    out = {}
    for t, v in m.items():
        out[str(t.year)] = round(float(v), 2)
    return out

def main():
    windows = [("FULL", None), ("VAL_2023", pd.Timestamp("2023-01-01", tz="UTC"))]
    results = {"family": "crypto-funding-basis", "program": "v13-best-rules",
               "label": "PAPER RECORD — not a tradable pot",
               "pot": POT, "costs": {"spot_per_side": SPOT_FEE, "perp_per_side": PERP_FEE},
               "spec": "BEST-RULES-SPEC.md frozen 2026-11-22 19:32 UTC",
               "coins": {}, "curves_monthly": {}, "curves_daily": {}}
    basket_curves = {}
    for coin in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
        f = load(coin)
        rates = f["last_funding_rate"].values.copy()
        results["coins"][coin] = {"data_start": str(f["t"].iloc[0]),
                                  "n_funding_events": int(len(f))}
        for wname, wstart in windows:
            start = f["t"].iloc[0] if wstart is None else max(wstart, f["t"].iloc[0])
            r = run_book(f, start)
            # 20-seed permutation placebos
            plac = []
            for seed in range(20):
                rng = random.Random(1000 + seed)
                sh = rates.copy(); rng.shuffle(sh)
                pr = run_book(f, start, rates=sh)
                plac.append(pr["final"])
            entry = {
                "my_rules": {"final": round(r["final"], 2),
                             "max_dd_pct": round(100 * max_dd(r["equity"]), 2),
                             "funding_net": round(r["funding_net"], 2),
                             "fees": round(r["fees"], 2),
                             "rebalances": r["rebalances"],
                             "period_stats_monthly": monthly_stats(r["equity"]),
                             "period_stats_8h_settlements": settle_stats(r["equity"]),
                             "year_end_equity": year_end(r["equity"])},
                "placebo_permuted_funding_20seeds": {
                    "median_final": round(float(np.median(plac)), 2),
                    "min_final": round(min(plac), 2), "max_final": round(max(plac), 2),
                    "real_beats_placebos": int(sum(1 for x in plac if r["final"] > x)),
                    "all_finals": [round(x, 2) for x in plac]},
                "coin_buyhold_bar": buyhold(f, start),
            }
            results["coins"][coin][wname] = entry
            key = f"{coin}_{wname}"
            m = r["equity"].resample("M").last()
            results["curves_monthly"][key] = {str(t.date()): round(float(v), 4) for t, v in m.items()}
            d = r["equity"].resample("D").last().ffill()
            results["curves_daily"][key] = {str(t.date()): round(float(v), 4) for t, v in d.items()}
            basket_curves.setdefault(wname, {})[coin] = r["equity"]
            print(coin, wname, "my-rules final", round(r["final"], 2),
                  "dd", round(100 * max_dd(r["equity"]), 2),
                  "placebo median", round(float(np.median(plac)), 2),
                  "beats", entry["placebo_permuted_funding_20seeds"]["real_beats_placebos"], "/20",
                  "buyhold", entry["coin_buyhold_bar"]["final"], flush=True)
    # baskets: mean of books present on the 8h grid (v12 method)
    results["basket"] = {}
    for wname, curves in basket_curves.items():
        df = pd.DataFrame(curves).ffill()
        basket = df.mean(axis=1)
        results["basket"][wname] = {"final_mean_of_books": round(float(basket.iloc[-1]), 2),
                                    "max_dd_pct": round(100 * max_dd(basket), 2),
                                    "period_stats_monthly": monthly_stats(basket),
                                    "period_stats_8h_settlements": settle_stats(basket)}
        m = basket.resample("M").last()
        results["curves_monthly"][f"BASKET_{wname}"] = {str(t.date()): round(float(v), 4) for t, v in m.items()}
        d = basket.resample("D").last().ffill()
        results["curves_daily"][f"BASKET_{wname}"] = {str(t.date()): round(float(v), 4) for t, v in d.items()}
        print("BASKET", wname, results["basket"][wname]["final_mean_of_books"],
              "dd", results["basket"][wname]["max_dd_pct"], flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(results, fh, indent=1, default=str)
    print("wrote results.json")

if __name__ == "__main__":
    main()
