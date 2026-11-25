#!/usr/bin/env python3
"""crypto-x-carry — cross-sectional funding-rate carry, PIT panel.
Spec: ../CONSTRUCTION-SPEC.md (frozen before this run).
Form X: published long-short perp tercile form, PAPER RECORD.
Form L: CONSTRUCTED long-only spot tilt (bottom tercile only).
Both under native (no floor) and v9 (permanent halt at -$15% daily close).
Costs 0.60%/side on turnover. Funding charged/credited in full in Form X only.
Windows: FULL 2020-02-03->2026-10-31, EARLY ->2022-12-31, VAL 2023-01-02->2026-10-31.
Placebos: 20 seeds, random terciles from same eligible set, native rules."""
import json, os, math, random
import pandas as pd, numpy as np

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
POT = 100.0
COST = 0.006
SNAP = "/home/hatch/workspace/stock-app/backtests/v12-completions/crypto-basket-pit/data/weekly_snapshots.json"
EXCLUDE = {"USDT","USDC","DAI","BUSD","TUSD","UST","USD1","USDE","WBTC"}
MAP = {"SHIB": "1000SHIBUSDT", "PEPE": "1000PEPEUSDT", "MIOTA": "IOTAUSDT"}
MATIC_MASK = pd.Timestamp("2024-09-10", tz="UTC")

# ---------- load panel ----------
spans = json.load(open(os.path.join(DATA, "spans.json")))
perp2cmc = {p: s["cmc"] for p, s in spans.items() if s["funding_months"] > 0}
fund_daily = {}   # cmc -> Series of daily accrued funding (sum of settlements that UTC day)
price_daily = {}  # cmc -> Series of daily close
for perp, cmc in perp2cmc.items():
    f = pd.read_csv(os.path.join(DATA, f"{perp}_funding.csv"))
    if len(f) == 0: continue
    f["t"] = pd.to_datetime(f["calc_time"], unit="ms", utc=True)
    f["day"] = f["t"].dt.floor("D")
    daily = f.groupby("day")["last_funding_rate"].sum()
    cnt = f.groupby("day")["last_funding_rate"].count()
    fund_daily[cmc] = daily
    fund_daily[cmc + "__cnt"] = cnt
    k = pd.read_csv(os.path.join(DATA, f"{perp}_klines1d.csv"))
    k["day"] = pd.to_datetime(k["open_time"], unit="ms", utc=True)
    price_daily[cmc] = k.set_index("day")["close"].sort_index()
coins = sorted({c for c in fund_daily if not c.endswith("__cnt")})
print("panel coins with funding files:", len(coins), coins)

# PIT snapshots: sorted list of (date, set of cmc symbols)
snaps = json.load(open(SNAP))
snap_dates = sorted(snaps.keys())
snap_sets = []
for d in snap_dates:
    s = {c["symbol"] for c in snaps[d]["top20"]} - EXCLUDE
    # MIOTA snapshot symbol -> perp-era symbol IOTA data is under IOTAUSDT cmc key 'IOTA'
    snap_sets.append((pd.Timestamp(d, tz="UTC"), s))

def pit_set(date):
    cur = set()
    for d, s in snap_sets:
        if d <= date: cur = s
        else: break
    return cur

def trailing_funding(cmc, t):
    """mean daily funding over (t-7d, t]; coverage = settlements in window / expected.
    Returns (mean_daily_rate, n_settlements) or None."""
    s = fund_daily.get(cmc)
    if s is None: return None
    lo = t - pd.Timedelta(days=7)
    w = s[(s.index > lo) & (s.index <= t)]
    c = fund_daily[cmc + "__cnt"][(fund_daily[cmc + "__cnt"].index > lo) &
                                  (fund_daily[cmc + "__cnt"].index <= t)]
    n = int(c.sum()) if len(c) else 0
    if len(w) < 6 or n < 18: return None
    return float(w.sum()) / 7.0, n

def price_on(cmc, t):
    s = price_daily.get(cmc)
    if s is None: return None
    idx = s.index[s.index <= t]
    if len(idx) == 0: return None
    if (t - idx[-1]).days > 3: return None  # stale/dead series
    return float(s.loc[idx[-1]])

# ---------- engine ----------
def run_window(start, end, form, house=False, placebo_seed=None):
    """Weekly Monday rebalances. Returns dict with daily equity curve + stats."""
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    mondays = pd.date_range(start, end, freq="W-MON", tz="UTC")
    eq = POT
    curve = [(start, eq)]
    weights = {}  # cmc -> weight (signed for X, positive for L)
    entry_price = {}
    dead_since = {}
    total_costs = 0.0
    funding_net = 0.0
    n_reb = 0
    halted = False
    # build daily timeline
    days = pd.date_range(start, end, freq="D", tz="UTC")
    monday_set = set(mondays)
    prev_prices = {}
    for d in days:
        # daily PnL from yesterday's close to today's close for held weights
        if weights and d > start:
            pnl = 0.0
            for cmc, w in list(weights.items()):
                p_now = price_on(cmc, d)
                p_prev = prev_prices.get(cmc)
                if p_now is None:
                    # series ended: grace 7d at last price, then written to ZERO:
                    # long loses 100% of its weight, short gains 100% of its weight (once)
                    if cmc not in dead_since: dead_since[cmc] = d
                    if (d - dead_since[cmc]).days > 7:
                        pnl += -w * 1.0
                        weights[cmc] = 0.0
                    continue
                dead_since.pop(cmc, None)
                if p_prev and p_prev > 0:
                    r = p_now / p_prev - 1.0
                    pnl += w * r
                    if form == "X":
                        fd = fund_daily.get(cmc)
                        f_today = float(fd.loc[d]) if (fd is not None and d in fd.index) else 0.0
                        pnl += -w * f_today
                        funding_net += -w * f_today * eq
            eq *= (1.0 + pnl)
        # snapshot prev prices at today's close
        for cmc in list(set(weights) | set(price_daily)):
            p = price_on(cmc, d)
            if p is not None: prev_prices[cmc] = p
        # rebalance at Monday close (positions earn from tomorrow)
        if d in monday_set and not halted:
            pit = pit_set(d)
            ranked = []
            for cmc in pit:
                if cmc == "MATIC" and d >= MATIC_MASK: continue
                tf = trailing_funding(cmc, d)
                if tf is None: continue
                if price_on(cmc, d) is None: continue
                ranked.append((tf[0], cmc))
            ranked.sort()
            new_w = {}
            if len(ranked) >= 6:
                n = max(1, len(ranked) // 3)
                if rng is not None:
                    idx = list(range(len(ranked)))
                    rng.shuffle(idx)
                    low = [ranked[i][1] for i in idx[:n]]
                    high = [ranked[i][1] for i in idx[-n:]]
                else:
                    low = [c for _, c in ranked[:n]]
                    high = [c for _, c in ranked[-n:]]
                if form == "X":
                    for c in low: new_w[c] = 0.50 / len(low)
                    for c in high: new_w[c] = -0.50 / len(high)
                else:
                    for c in low: new_w[c] = 1.0 / len(low)
                n_reb += 1
            # turnover cost
            allc = set(weights) | set(new_w)
            turn = sum(abs(new_w.get(c, 0.0) - weights.get(c, 0.0)) for c in allc)
            c_cost = turn * COST * eq
            eq -= c_cost; total_costs += c_cost
            weights = {c: w for c, w in new_w.items() if w != 0.0}
        curve.append((d, eq))
        if house and eq <= 0.85 * POT:
            # liquidate: charge exit turnover
            turn = sum(abs(w) for w in weights.values())
            c_cost = turn * COST * eq
            eq -= c_cost; total_costs += c_cost
            weights = {}
            halted = True
            curve[-1] = (d, eq)
            # flat to end
            for d2 in days[days > d]:
                curve.append((d2, eq))
            break
    # final liquidation cost (if still holding)
    if weights:
        turn = sum(abs(w) for w in weights.values())
        c_cost = turn * COST * eq
        eq -= c_cost; total_costs += c_cost
        curve[-1] = (curve[-1][0], eq)
    s = pd.Series(dict(curve)).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    return {"equity": s, "final": float(eq), "costs": float(total_costs),
            "funding_net_frac": float(funding_net), "rebalances": n_reb, "halted": halted}

def btc_hold(start, end):
    s = price_daily["BTC"]
    s = s[(s.index >= start) & (s.index <= end)]
    eq = POT * (1 - COST)
    curve = eq * s / s.iloc[0]
    final = float(curve.iloc[-1] * (1 - COST))
    curve.iloc[-1] = final
    return {"equity": curve, "final": final}

def max_dd(s):
    return float((s / s.cummax() - 1).min()) if len(s) else 0.0

def period_stats(s, freq="W"):
    """Weekly period distribution per REPORTING STANDARD."""
    m = s.resample(freq).last().dropna()
    vals = np.concatenate([[POT], m.values])
    rets = np.diff(vals) / vals[:-1]
    if len(rets) == 0: return {}
    win = rets > 0
    longest_loss = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        longest_loss = max(longest_loss, cur)
    # longest stretch between new highs (in periods)
    run_max = np.maximum.accumulate(vals)
    underwater = vals < run_max
    longest_uw = cur = 0
    for u in underwater:
        cur = cur + 1 if u else 0
        longest_uw = max(longest_uw, cur)
    return {"n_periods": int(len(rets)), "pct_profitable": float(100 * win.mean()),
            "median_pct": float(100 * np.median(rets)), "best_pct": float(100 * rets.max()),
            "worst_pct": float(100 * rets.min()), "longest_losing_run": int(longest_loss),
            "longest_between_highs_periods": int(longest_uw),
            "mean_pct_secondary": float(100 * rets.mean())}

WINDOWS = {"FULL": (pd.Timestamp("2020-02-03", tz="UTC"), pd.Timestamp("2026-10-31", tz="UTC")),
           "EARLY": (pd.Timestamp("2020-02-03", tz="UTC"), pd.Timestamp("2022-12-31", tz="UTC")),
           "VAL": (pd.Timestamp("2023-01-02", tz="UTC"), pd.Timestamp("2026-10-31", tz="UTC"))}

out = {"panel_coins": coins, "windows": {}, "btc": {}, "placebos": {}}
for wname, (st, en) in WINDOWS.items():
    b = btc_hold(st, en)
    out["btc"][wname] = {"final": b["final"], "max_dd": max_dd(b["equity"]),
                         "curve": {str(k.date()): float(v) for k, v in b["equity"].items()},
                         "weekly_stats": period_stats(b["equity"])}
    out["windows"][wname] = {}
    for form in ("X", "L"):
        for house in (False, True):
            r = run_window(st, en, form, house=house)
            key = f"{form}_{'v9' if house else 'native'}"
            out["windows"][wname][key] = {
                "final": r["final"], "max_dd": max_dd(r["equity"]), "costs": r["costs"],
                "funding_net_dollars_approx": r["funding_net_frac"], "rebalances": r["rebalances"],
                "halted": r["halted"], "weekly_stats": period_stats(r["equity"]),
                "curve": {str(k.date()): float(v) for k, v in r["equity"].items()}}
            print(wname, key, "final", round(r["final"], 2), "dd", round(max_dd(r["equity"]), 3),
                  "reb", r["rebalances"], "halted", r["halted"], flush=True)
    # placebos FULL/VAL only, native
    if wname in ("FULL", "VAL"):
        out["placebos"][wname] = {}
        for form in ("X", "L"):
            finals = []
            for seed in range(20):
                r = run_window(st, en, form, house=False, placebo_seed=seed)
                finals.append(r["final"])
            finals.sort()
            out["placebos"][wname][form] = {"finals": finals, "median": float(np.median(finals))}
            print(wname, "placebo", form, "median", round(float(np.median(finals)), 2), flush=True)

json.dump(out, open(os.path.join(HERE, "..", "results.json"), "w"), indent=1)
print("BTC:", {k: round(v["final"], 2) for k, v in out["btc"].items()})
print("done")
