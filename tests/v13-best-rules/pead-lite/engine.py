"""V13 pead-lite engine — implements BEST-RULES-SPEC.md exactly (frozen before runs).

SUE (seasonal random walk, Bernard & Thomas) from the v11 EDGAR EPS cache (read-only).
Announcement date = earliest 8-K/8-K-A Item 2.02 filing date in [period_end, 10-Q filed];
fallback = 10-Q/10-K filed date. Entry = first trading day AFTER announcement, at
adjusted open (raw open * adjclose/close). Exit = entry + 60 trading days at adj close.
Gate: SUE >= 90th pct of SUEs ANNOUNCED in the previous calendar quarter (min 20 obs), SUE > 0.
Sizing: 10% of equity per signal, max 10 concurrent, fractional. Costs 0.10%/side.
No floor, no stop, no regime exit. $100 pots. Roads per spec. 20-seed placebos per road.
Per-year distribution + drawdown + stretch-between-highs computed from equity curves.
"""
import json, os, statistics
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data_cache")
EPS = "/home/hatch/workspace/stock-app/backtests/v11-native-rules/pead-lite/eps_cache"
COST = 0.0010
START_CASH = 100.0

def load_px(t):
    d = json.load(open(os.path.join(CACHE, f"pxe_{t}.json")))
    out = {}
    for i, x in enumerate(d["timestamp"]):
        adj, cl, op = d["adjclose"][i], d["close"][i], d["open"][i]
        if adj and cl and op:
            ds = date.fromtimestamp(x).isoformat()
            out[ds] = {"close": adj, "open": op * adj / cl}
    return out

tickers = sorted(f[4:-5] for f in os.listdir(CACHE) if f.startswith("pxe_") and f != "pxe_SPY.json")
px = {t: load_px(t) for t in tickers}
spy = load_px("SPY")
cal = sorted(spy.keys())
cal_idx = {d: i for i, d in enumerate(cal)}

# --- announcements with SUE ---
anns = []  # (ann_date, ticker, sue, period_end, src)
n_fallback = 0
for t in tickers:
    ep = os.path.join(EPS, f"eps_{t}.json")
    if not os.path.exists(ep): continue
    facts = json.load(open(ep))["facts"]
    evf = os.path.join(CACHE, f"ev8k_{t}.json")
    ev = json.load(open(evf)) if os.path.exists(evf) else []
    ues = []
    for f in facts:
        e = date.fromisoformat(f["end"]); prior = None
        for g in facts:
            ge = date.fromisoformat(g["end"])
            if 330 <= (e - ge).days <= 400: prior = g["val"]
        ues.append(None if prior is None else f["val"] - prior)
    for i, f in enumerate(facts):
        ue = ues[i]
        hist = [u for u in ues[max(0, i - 8):i] if u is not None]
        if ue is None or len(hist) < 4: continue
        sd = statistics.pstdev(hist)
        if sd <= 0: continue
        cand = [d for d in ev if f["end"] <= d <= f["filed"]]
        if cand:
            ann, src = cand[0], "8K-2.02"
        else:
            ann, src = f["filed"], "10Q-filed"; n_fallback += 1
        anns.append((ann, t, ue / sd, f["end"], src))
anns.sort()

def prev_q(ds):
    y, m = int(ds[:4]), int(ds[5:7]); q = (m - 1) // 3
    return (y - 1, 4) if q == 0 else (y, q)

signals = []
for ann, t, sue, pend, src in anns:
    py, pq = prev_q(ann)
    pool = sorted(s for (a, _, s, _, _) in anns
                  if int(a[:4]) == py and (int(a[5:7]) - 1) // 3 + 1 == pq)
    if len(pool) < 20: continue
    thr = pool[min(len(pool) - 1, int(0.90 * len(pool)))]
    if sue >= thr and sue > 0:
        signals.append({"ann": ann, "ticker": t, "sue": round(sue, 3), "src": src})

def run(sig_list, start, end):
    trades = []
    for s in sig_list:
        cand = [d for d in cal if d > s["ann"]]
        if not cand: continue
        ed = cand[0]
        if not (start <= ed <= end): continue
        i = cal_idx[ed]
        if i + 60 >= len(cal): continue
        xd = cal[i + 60]
        p0 = px[s["ticker"]].get(ed, {}).get("open"); p1 = px[s["ticker"]].get(xd, {}).get("close")
        if not p0 or not p1: continue
        trades.append({**s, "entry": ed, "exit": xd, "p0": p0, "p1": p1})
    trades.sort(key=lambda x: x["entry"])
    cash, pos, curve, total_cost, taken = START_CASH, [], [], 0.0, 0
    ti = 0
    for d in cal:
        if not (start <= d <= end): continue
        still = []
        for p in pos:
            if d >= p["exit"]:
                v = p["shares"] * px[p["ticker"]].get(d, {}).get("close", p["p1"])
                total_cost += v * COST; cash += v * (1 - COST)
            else: still.append(p)
        pos = still
        while ti < len(trades) and trades[ti]["entry"] == d:
            tr = trades[ti]; ti += 1
            equity = cash + sum(p["shares"] * px[p["ticker"]].get(d, {}).get("close", p["p0"]) for p in pos)
            slice_amt = 0.10 * equity
            if len(pos) < 10 and cash >= slice_amt > 0:
                shares = slice_amt * (1 - COST) / tr["p0"]
                total_cost += slice_amt * COST; cash -= slice_amt
                pos.append({**tr, "shares": shares}); taken += 1
        equity = cash + sum(p["shares"] * px[p["ticker"]].get(d, {}).get("close", p["p0"]) for p in pos)
        curve.append([d, round(equity, 2)])
    final = curve[-1][1] if curve else START_CASH
    peak, mdd = START_CASH, 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    # longest stretch between new highs (trading days)
    peak_v, peak_i, longest = START_CASH, -1, 0
    for i, (_, v) in enumerate(curve):
        if v >= peak_v: peak_v, peak_i = v, i
        longest = max(longest, i - peak_i)
    # per-year distribution from curve
    years = {}
    prev = START_CASH
    for y in sorted({d[:4] for d, _ in curve}):
        yc = [v for d, v in curve if d[:4] == y]
        if not yc: continue
        years[y] = round(yc[-1] / prev - 1, 4); prev = yc[-1]
    ys = list(years.values())
    streak = cur = 0
    for r in ys:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    dist = {"years": years,
            "median_year_pct": round(statistics.median(ys) * 100, 2) if ys else None,
            "share_years_positive": round(sum(1 for r in ys if r > 0) / len(ys), 3) if ys else None,
            "best_year_pct": round(max(ys) * 100, 2) if ys else None,
            "worst_year_pct": round(min(ys) * 100, 2) if ys else None,
            "longest_losing_streak_years": streak,
            "longest_stretch_between_highs_days": longest}
    s0 = spy.get(curve[0][0], {}).get("close") if curve else None
    s1 = spy.get(curve[-1][0], {}).get("close") if curve else None
    spy_r = round(100 * s1 / s0, 2) if s0 and s1 else None
    return {"final": final, "max_dd_pct": round(mdd * 100, 2), "costs": round(total_cost, 2),
            "n_signals": len(trades), "n_taken": taken, "spy_final": spy_r,
            "distribution": dist, "curve": curve}

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
import random
out = {"family": "pead-lite", "spec": "v13-best-rules", "universe_n": len(tickers),
       "n_announcements_with_sue": len(anns), "n_ann_fallback_10q": n_fallback,
       "n_signals_total": len(signals), "roads": {}}
for road, (a, b) in ROADS.items():
    r = run(signals, a, b)
    days = [d for d in cal if a <= d <= b]
    pls = []
    for seed in range(1, 21):
        rng = random.Random(seed)
        fake = [{"ann": cal[max(0, cal_idx[rng.choice(days)] - 1)], "ticker": rng.choice(tickers), "sue": 0}
                for _ in range(r["n_signals"])]
        pls.append(run(fake, a, b)["final"])
    r["placebos"] = {"finals": pls, "beaten": sum(1 for x in pls if r["final"] > x),
                     "median": round(statistics.median(pls), 2)}
    out["roads"][road] = r
    print(road, "final", r["final"], "dd", r["max_dd_pct"], "spy", r["spy_final"],
          "signals", r["n_signals"], "taken", r["n_taken"],
          "placebo beaten", r["placebos"]["beaten"], "/20 median", r["placebos"]["median"], flush=True)
json.dump(out, open(os.path.join(HERE, "results.json"), "w"))
print("anns", len(anns), "fallback", n_fallback, "signals", len(signals))
