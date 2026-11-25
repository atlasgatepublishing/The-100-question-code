#!/usr/bin/env python3
"""V13 Best Rules — hunt-rhodl-ratio (RHODL dial).
Spec: BEST-RULES-SPEC.md in this folder (frozen before this run).
Dial: w(R) = clip((ln 7800 - ln R)/(ln 7800 - ln 350), 0, 1), weekly checks
(every 7th row, signal at close t effective t->t+1), BTC only, 0.60%/side
on traded delta, no floor. Roads: FULL 2022-11-22->end, VAL 2023-01-01->end.
Also: BTC buy-and-hold per road, published switch form re-run per road,
20 placebo dials (random anchors) on FULL.
Data: RHODL live keyless from BGeometrics (saved to data/rhodl.json);
BTC PriceUSD from the shared CoinMetrics cache (read-only).
"""
import json, math, urllib.request, pathlib, statistics, random

HERE = pathlib.Path(__file__).resolve().parent
HOME = pathlib.Path.home()
COST = 0.006
BOT, TOP = 350.0, 7800.0

# ---------- data ----------
req = urllib.request.Request("https://api.bitcoin-data.com/v1/rhodl-ratio",
                             headers={"User-Agent": "Mozilla/5.0"})
raw = urllib.request.urlopen(req, timeout=60).read()
(HERE / "data" / "rhodl.json").write_bytes(raw)
rhodl_rows = json.loads(raw)
rhodl = {r["d"]: float(r["rhodlRatio"]) for r in rhodl_rows}
print(f"RHODL rows fetched: {len(rhodl_rows)} {rhodl_rows[0]['d']} -> {rhodl_rows[-1]['d']}")

cm = json.loads((HOME / "workspace/stock-app/backtests/v12-completions/crypto-onchain/data/cm_btc.json").read_text())
px = {r["time"][:10]: float(r["PriceUSD"]) for r in cm}

dates = sorted(d for d in rhodl if d in px)
P = [px[d] for d in dates]
R = [rhodl[d] for d in dates]
print(f"Aligned days: {len(dates)} {dates[0]} -> {dates[-1]}")

# ---------- helpers ----------
def max_dd(curve):
    peak, mdd = -1.0, 0.0
    for v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1.0)
    return mdd * 100.0

def monthly_stats(dates_, curve):
    """Month-end equity series -> monthly returns distribution."""
    ends = []  # (yyyymm, last equity of month)
    for d, v in zip(dates_, curve):
        ym = d[:7]
        if ends and ends[-1][0] == ym:
            ends[-1] = (ym, v)
        else:
            ends.append((ym, v))
    vals = [100.0] + [v for _, v in ends]
    rets = [vals[i + 1] / vals[i] - 1.0 for i in range(len(vals) - 1)]
    # longest losing streak
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (in months, on month-end equity)
    high, since, longest = -1.0, 0, 0
    for v in vals[1:]:
        if v > high:
            high, since = v, 0
        else:
            since += 1
            longest = max(longest, since)
    return {
        "periods": len(rets),
        "share_positive": round(sum(1 for r in rets if r > 0) / len(rets), 4),
        "median": round(statistics.median(rets), 5),
        "best": round(max(rets), 5),
        "worst": round(min(rets), 5),
        "longest_losing_streak": streak,
        "longest_between_highs_periods": longest,
        "average_secondary": round(statistics.mean(rets), 5),
    }

def run_dial(idx, bot, top):
    """idx: list of row indices for the road. Weekly checks at local rows 0,7,14...
    Signal at close t (global row idx[k]) sets weight effective t->t+1."""
    n = len(idx)
    cash, units = 100.0, 0.0
    curve, weights = [], []
    trades, costs_paid = 0, 0.0
    lb, lt = math.log(bot), math.log(top)
    for k in range(n):
        g = idx[k]
        p = P[g]
        if k % 7 == 0:
            w = min(1.0, max(0.0, (lt - math.log(R[g])) / (lt - lb)))
            eq = cash + units * p
            target_val = w * eq
            delta = target_val - units * p
            if abs(delta) > 1e-9:
                c = COST * abs(delta)
                costs_paid += c
                if delta > 0:
                    spend = min(cash, delta + c)
                    buy_val = max(0.0, spend - c * (spend / (delta + c))) if delta + c > 0 else 0.0
                    # simpler exact: buy delta worth, pay cost from cash if available
                    if cash >= delta + c:
                        cash -= delta + c
                        units += delta / p
                    else:
                        # scale buy so delta+cost exactly exhausts cash
                        buy_val = cash / (1.0 + COST)
                        c = COST * buy_val
                        costs_paid -= (COST * abs(delta) - c)
                        cash = 0.0
                        units += buy_val / p
                    trades += 1
                else:
                    sell_val = -delta
                    units -= sell_val / p
                    cash += sell_val - c
                    trades += 1
        eq = cash + units * p
        curve.append(round(eq, 4))
        weights.append(units * p / eq if eq > 0 else 0.0)
    final_mtm = curve[-1]
    liq = cash + units * P[idx[-1]] * (1 - COST)
    return {"final_mtm": round(final_mtm, 2), "final_liquidated": round(liq, 2),
            "curve": curve, "max_dd_pct": round(max_dd(curve), 2),
            "trades": trades, "costs_paid": round(costs_paid, 2),
            "avg_exposure": round(statistics.mean(weights), 4),
            "end_weight": round(weights[-1], 4)}

def run_switch(idx):
    """Published constructed form: enter <350, exit >=50000, start cash, daily."""
    cash, units = 100.0, 0.0
    in_pos = False
    curve, orders, costs_paid = [], 0, 0.0
    for g in idx:
        p = P[g]
        if not in_pos and R[g] < 350:
            c = COST * cash
            units = (cash - c) / p
            costs_paid += c
            cash, in_pos, orders = 0.0, True, orders + 1
        elif in_pos and R[g] >= 50000:
            proceeds = units * p
            c = COST * proceeds
            costs_paid += c
            cash, units, in_pos, orders = proceeds - c, 0.0, False, orders + 1
        curve.append(round(cash + units * p, 4))
    liq = cash + units * P[idx[-1]] * (1 - COST)
    return {"final_mtm": round(curve[-1], 2), "final_liquidated": round(liq, 2),
            "curve": curve, "max_dd_pct": round(max_dd(curve), 2),
            "orders": orders, "costs_paid": round(costs_paid, 2)}

def run_bh(idx):
    p0 = P[idx[0]]
    units = 100.0 * (1 - COST) / p0
    curve = [round(units * P[g], 4) for g in idx]
    return {"final_mtm": round(curve[-1], 2),
            "final_liquidated": round(curve[-1] * (1 - COST), 2),
            "curve": curve, "max_dd_pct": round(max_dd(curve), 2)}

# ---------- roads ----------
full_idx = list(range(len(dates)))
val_start = next(i for i, d in enumerate(dates) if d >= "2023-01-01")
val_idx = list(range(val_start, len(dates)))
val_dates = [dates[i] for i in val_idx]
print(f"FULL {dates[0]}->{dates[-1]} ({len(full_idx)}d) | VAL {val_dates[0]}->{val_dates[-1]} ({len(val_idx)}d)")
print(f"RHODL FULL: min {min(R):.1f} max {max(R):.1f} | days<350: {sum(1 for r in R if r<350)} | days>=7800: {sum(1 for r in R if r>=7800)} | days>=50000: {sum(1 for r in R if r>=50000)}")
print(f"RHODL VAL: min {min(R[i] for i in val_idx):.1f} max {max(R[i] for i in val_idx):.1f} | days<350: {sum(1 for i in val_idx if R[i]<350)}")

out = {"family": "hunt-rhodl-ratio", "program": "v13-best-rules",
       "spec_anchors": {"BOT": BOT, "TOP": TOP, "cadence_rows": 7, "cost_per_side": COST},
       "data": {"rhodl_rows": len(rhodl_rows), "aligned_days": len(dates),
                "first": dates[0], "last": dates[-1]},
       "roads": {}}
for name, idx, dts in [("FULL", full_idx, dates), ("VAL", val_idx, val_dates)]:
    dial = run_dial(idx, BOT, TOP)
    bh = run_bh(idx)
    sw = run_switch(idx)
    out["roads"][name] = {
        "window": [dts[0], dts[-1]], "days": len(idx),
        "dial": {**{k: v for k, v in dial.items() if k != "curve"},
                 "curve": [[d, v] for d, v in zip(dts, dial["curve"])]},
        "buy_hold": {**{k: v for k, v in bh.items() if k != "curve"},
                     "curve": [[d, v] for d, v in zip(dts, bh["curve"])]},
        "published_switch_rerun": {**{k: v for k, v in sw.items() if k != "curve"},
                                   "curve": [[d, v] for d, v in zip(dts, sw["curve"])]},
        "period_stats_monthly": {
            "dial": monthly_stats(dts, dial["curve"]),
            "buy_hold": monthly_stats(dts, bh["curve"]),
            "published_switch_rerun": monthly_stats(dts, sw["curve"]),
        },
    }
    print(f"{name}: dial liq ${dial['final_liquidated']} (mtm ${dial['final_mtm']}, DD {dial['max_dd_pct']}%, trades {dial['trades']}, costs ${dial['costs_paid']}, avgExp {dial['avg_exposure']})")
    print(f"{name}: BH   liq ${bh['final_liquidated']} (mtm ${bh['final_mtm']}, DD {bh['max_dd_pct']}%)")
    print(f"{name}: SW   liq ${sw['final_liquidated']} (mtm ${sw['final_mtm']}, DD {sw['max_dd_pct']}%, orders {sw['orders']})")

# ---------- placebos on FULL ----------
rng = random.Random(20261122)
placebos = []
for s in range(20):
    bot_s = rng.uniform(200, 600)
    top_s = math.exp(rng.uniform(math.log(3000), math.log(20000)))
    r = run_dial(full_idx, bot_s, top_s)
    placebos.append({"seed": s, "BOT": round(bot_s, 1), "TOP": round(top_s, 1),
                     "final_liquidated": r["final_liquidated"], "final_mtm": r["final_mtm"]})
    print(f"placebo {s}: BOT {bot_s:.0f} TOP {top_s:.0f} -> liq ${r['final_liquidated']}")
real = out["roads"]["FULL"]["dial"]["final_liquidated"]
beaten = sum(1 for p in placebos if real > p["final_liquidated"])
out["placebos_20_FULL"] = placebos
out["placebos_beaten_FULL"] = beaten
print(f"Placebos beaten on FULL (liquidated): {beaten}/20")

(HERE / "results.json").write_text(json.dumps(out, indent=1))
print("results.json written")
