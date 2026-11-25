"""V13 BEST-RULES — pead-small. Frozen spec: BEST-RULES-SPEC.md (2026-11-22T19:26:53Z).

Signal construction copied from the v11 native engine (Bernard & Thomas seasonal
random-walk SUE, long leg, small habitat) — identical SUE, identical point-in-time
prev-quarter decile threshold, identical EDGAR filed-date entry discipline.
MY changes (frozen in spec): hold 40 trading days (was 60); max 3 concurrent
(was 10); slice = equity/3 at entry (was 10% of equity). Costs 0.35%/side.
No floor, no stop. $100 pots. Roads: CONT 2019-01-02->2026-11-20,
VAL 2023-01-03->2026-11-20 (LONG/DECADE not buildable — data begins 2018).
Placebos: 20 seeds per road, same chassis, random ticker + random day.
Also computes the v11 native form on the same roads for the published-form bar,
and (for the frozen confirmation protocol) native + mine on CONF_A/CONF_B and
yearly folds — confirmation numbers are only *used* if a road beats the champion.
"""
import json, os, sys, glob, random, statistics
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V11 = "/home/hatch/workspace/stock-app/backtests/v11-native-rules/pead-small"
V3 = "/home/hatch/workspace/stock-app/backtests/v3/pead-cache"
V4 = "/home/hatch/workspace/stock-app/backtests/v4/pead-small-cache"
EPS = os.path.join(V11, "eps_cache")
COST = 0.0035

def load_px(t):
    for c in (V3, V4):
        p = os.path.join(c, f"px_{t}.json")
        if os.path.exists(p):
            d = json.load(open(p))["chart"]["result"][0]
            ts = d["timestamp"]; adj = d["indicators"]["adjclose"][0]["adjclose"]
            out = {}
            for i, x in enumerate(ts):
                if adj[i]:
                    out[date.fromtimestamp(x).isoformat()] = adj[i]
            return out
    return {}

tickers = sorted({os.path.basename(f)[3:-5] for f in glob.glob(os.path.join(V4, "px_*.json"))} - {"SPY"})
px = {t: load_px(t) for t in tickers}
spy = load_px("SPY")
cal = sorted(spy.keys())
cal_idx = {d: i for i, d in enumerate(cal)}

# --- SUE per announcement (identical to v11) ---
anns = []
for t in tickers:
    fp = os.path.join(EPS, f"eps_{t}.json")
    if not os.path.exists(fp): continue
    facts = json.load(open(fp))["facts"]
    ues = []
    for f in facts:
        e = date.fromisoformat(f["end"])
        prior = None
        for g in facts:
            ge = date.fromisoformat(g["end"])
            if 330 <= (e - ge).days <= 400: prior = g["val"]
        ues.append(None if prior is None else f["val"] - prior)
    for i, f in enumerate(facts):
        ue = ues[i]
        hist = [u for u in ues[max(0, i-8):i] if u is not None]
        if ue is None or len(hist) < 4: continue
        sd = statistics.pstdev(hist)
        if sd <= 0: continue
        anns.append((f["filed"], t, ue / sd))
anns.sort()

def prev_q(filed):
    y, m = int(filed[:4]), int(filed[5:7])
    q = (m - 1) // 3
    return (y - 1, 4) if q == 0 else (y, q)

signals = []
for filed, t, sue in anns:
    py, pq = prev_q(filed)
    pool = [s for (fd, _, s) in anns if int(fd[:4]) == py and (int(fd[5:7]) - 1) // 3 + 1 == pq]
    if len(pool) < 20: continue
    pool.sort()
    thr = pool[min(len(pool) - 1, int(0.90 * len(pool)))]
    if sue >= thr and sue > 0:
        signals.append({"filed": filed, "ticker": t, "sue": round(sue, 3)})

def run(sig_list, start, end, hold, maxpos):
    trades = []
    for s in sig_list:
        cand = [d for d in cal if d > s["filed"]]
        if not cand: continue
        ed = cand[0]
        if not (start <= ed <= end): continue
        i = cal_idx[ed]
        if i + hold >= len(cal): continue
        xd = cal[i + hold]
        p0 = px[s["ticker"]].get(ed); p1 = px[s["ticker"]].get(xd)
        if not p0 or not p1: continue
        trades.append({**s, "entry": ed, "exit": xd, "p0": p0, "p1": p1})
    trades.sort(key=lambda x: x["entry"])
    cash, pos, curve, total_cost, taken = 100.0, [], [], 0.0, []
    ti = 0
    for d in cal:
        if not (start <= d <= end): continue
        still = []
        for p in pos:
            if d >= p["exit"]:
                v = p["shares"] * px[p["ticker"]].get(d, p["p1"])
                total_cost += v * COST
                cash += v * (1 - COST)
            else: still.append(p)
        pos = still
        while ti < len(trades) and trades[ti]["entry"] == d:
            tr = trades[ti]; ti += 1
            equity = cash + sum(p["shares"] * px[p["ticker"]].get(d, p["p0"]) for p in pos)
            slice_amt = equity / maxpos
            if len(pos) < maxpos and cash >= slice_amt > 0:
                shares = slice_amt * (1 - COST) / tr["p0"]
                total_cost += slice_amt * COST
                cash -= slice_amt
                pos.append({**tr, "shares": shares})
                taken.append(tr)
        equity = cash + sum(p["shares"] * px[p["ticker"]].get(d, p["p0"]) for p in pos)
        curve.append([d, round(equity, 2)])
    final = curve[-1][1] if curve else 100.0
    peak, mdd = 100.0, 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    s0 = spy.get(curve[0][0]) if curve else None; s1 = spy.get(curve[-1][0]) if curve else None
    spy_r = round(100 * s1 / s0, 2) if s0 and s1 else None
    return {"final": final, "max_dd_pct": round(mdd * 100, 2), "costs": round(total_cost, 2),
            "n_signals_eligible": len(trades), "n_trades_taken": len(taken),
            "spy_final_priceonly": spy_r, "curve": curve,
            "trades": [{k: tr[k] for k in ("filed", "ticker", "sue", "entry", "exit")} for tr in taken]}

def monthly_stats(curve):
    # month-end equity -> monthly returns distribution
    months = {}
    for d, v in curve: months[d[:7]] = v
    keys = sorted(months)
    rets, prev = [], 100.0
    for k in keys:
        rets.append(months[k] / prev - 1); prev = months[k]
    if not rets: return {}
    pos_share = sum(1 for r in rets if r > 0) / len(rets)
    # longest losing streak (consecutive months <= 0 with a loss, strictly negative)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (months)
    peak, since, worst = 100.0, 0, 0
    for k in keys:
        if months[k] >= peak: peak = months[k]; since = 0
        else: since += 1; worst = max(worst, since)
    return {"n_periods": len(rets), "median_period_pct": round(statistics.median(rets) * 100, 2),
            "share_positive_pct": round(pos_share * 100, 1),
            "best_period_pct": round(max(rets) * 100, 2), "worst_period_pct": round(min(rets) * 100, 2),
            "longest_losing_streak_months": streak, "longest_months_between_new_highs": worst,
            "avg_period_pct_secondary": round(statistics.mean(rets) * 100, 2)}

def placebos(start, end, n, hold=40, maxpos=3):
    days = [d for d in cal if start <= d <= end]
    finals = []
    for seed in range(1, 21):
        rng = random.Random(seed)
        fake = [{"filed": rng.choice(days), "ticker": rng.choice(tickers), "sue": 0} for _ in range(n)]
        fake = [{**f, "filed": cal[max(0, cal_idx[f["filed"]] - 1)]} for f in fake]
        finals.append(run(fake, start, end, hold, maxpos)["final"])
    return finals

ROADS = {"CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"CONT": 544.47, "VAL": 288.05}
NATIVE_FINAL = {"CONT": 177.74, "VAL": 148.48}

out = {"family": "pead-small", "spec": "hold40_max3_slice_eq/3_cost0.35%_nofloor",
       "universe_n": len(tickers), "n_announcements_with_sue": len(anns),
       "n_signals_total": len(signals), "roads": {}, "confirmation": None}

for road, (a, b) in ROADS.items():
    mine = run(signals, a, b, hold=40, maxpos=3)
    native = run(signals, a, b, hold=60, maxpos=10)
    pls = placebos(a, b, mine["n_signals_eligible"])
    out["roads"][road] = {
        "window": [a, b], "mine": mine, "native_same_chassis": native,
        "placebos": {"finals": pls, "beaten": sum(1 for x in pls if mine["final"] > x),
                     "median": round(statistics.median(pls), 2)},
        "monthly_distribution_mine": monthly_stats(mine["curve"]),
        "monthly_distribution_native": monthly_stats(native["curve"]),
        "champion_vm": CHAMP[road], "native_published_final": NATIVE_FINAL[road],
        "beats_champion": mine["final"] > CHAMP[road],
        "beats_native_published": mine["final"] > NATIVE_FINAL[road]}
    print(road, "mine", mine["final"], "dd", mine["max_dd_pct"], "native", native["final"],
          "placebo beaten", out["roads"][road]["placebos"]["beaten"], "/20 median",
          out["roads"][road]["placebos"]["median"], "spy_px", mine["spy_final_priceonly"], flush=True)

# Confirmation data (frozen protocol) — computed always, USED only if a road beat the champion.
beats = any(out["roads"][r]["beats_champion"] for r in ROADS)
conf = {"triggered": beats, "folds": {}, "half_windows": {}}
for y in range(2019, 2027):
    a, b = f"{y}-01-02", min(f"{y}-12-31", "2026-11-20")
    conf["folds"][str(y)] = run(signals, a, b, hold=40, maxpos=3)["final"]
for name, (a, b) in {"CONF_A": ("2020-01-02", "2023-12-29"), "CONF_B": ("2024-01-02", "2026-11-20")}.items():
    conf["half_windows"][name] = {"mine": run(signals, a, b, hold=40, maxpos=3)["final"],
                                  "native": run(signals, a, b, hold=60, maxpos=10)["final"]}
out["confirmation"] = conf
print("confirmation triggered:", beats, "folds:", conf["folds"], "halves:", conf["half_windows"], flush=True)

json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("WROTE results.json")
