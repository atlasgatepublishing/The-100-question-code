#!/usr/bin/env python3
"""v12 CONSTRUCTED AMP two-sleeve (vm-twosleeve). Simulation only.
Implements CONSTRUCTION-SPEC.md frozen 2026-11-22, exactly:
broad W04 universe (read-only), monthly formation, value = book/market
(Jun-lag frames), momentum = 12-1, top-tercile long-only sleeves,
equal weight, 50/50 re-equalized monthly, tiered broad-habitat costs,
vanished price = ZERO, no floor. 20-seed placebos per window.
Writes only results.json in this folder.
"""
import json, os, sys, math, random

HERE = os.path.dirname(os.path.abspath(__file__))
W04 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
FR = os.path.join(W04, "frames")

def load_frame(name):
    p = os.path.join(FR, name)
    if not os.path.exists(p): return {}
    return {int(k): v for k, v in json.load(open(p)).items()}

def ym(y, m): return f"{y:04d}-{m:02d}"
def ym_next(s):
    y, m = int(s[:4]), int(s[5:7])
    return ym(y + (m // 12), m % 12 + 1)
def ym_add(s, k):
    y, m = int(s[:4]), int(s[5:7]) - 1 + k
    return ym(y + m // 12, m % 12 + 1)

MONTHS = [ym(2016 + i // 12, i % 12 + 1) for i in range(0, 131)]  # 2016-01..2026-11

class Data:
    def __init__(self):
        self.cand = {int(k): v for k, v in json.load(open(os.path.join(W04, "candidates.json"))).items()}
        self.px = {}
        for cik, info in self.cand.items():
            t = info["ticker"].replace("/", "-")
            p = os.path.join(W04, f"px_{t}.json")
            if os.path.exists(p):
                self.px[cik] = {r[0]: (r[1], r[2]) for r in json.load(open(p))}
        self.eq = {y: load_frame(f"StockholdersEquity_{y}I.json") for y in range(2014, 2026)}
        self.sh = {y: load_frame(f"Shares_{y}I.json") for y in range(2014, 2026)}
        # split factors per book year B: product of split-like YoY share
        # ratios for frame years >= B+1 (W04 convention, shifted to book yr)
        self.sf = {}
        for B in range(2014, 2026):
            f = 1.0
            avail = [(y, self.sh[y]) for y in range(2014, 2026)]
            ciks = set()
            for _, d in avail: ciks |= set(d)
            self.sf[B] = {}
            for cik in ciks:
                f = 1.0
                seq = [(y, d.get(cik)) for y, d in avail if d.get(cik)]
                for (y0, a), (y1, b) in zip(seq, seq[1:]):
                    if y1 >= B + 1 and a:
                        r = b / a
                        if r >= 1.6 or r <= 0.625: f *= r
                self.sf[B][cik] = f
        sp = json.load(open(os.path.join(W04, "px_SPY.json")))
        self.spy = {r[0]: r[1] for r in sp}
    def adj(self, cik, m):
        s = self.px.get(cik)
        v = s[m][0] if s and m in s else None
        return v if (v is not None and v > 0) else None
    def raw(self, cik, m):
        s = self.px.get(cik)
        v = s[m][1] if s and m in s else None
        return v if (v is not None and v > 0) else None
    def book_year(self, m):
        y, mo = int(m[:4]), int(m[5:7])
        return y - 2 if mo <= 6 else y - 1
    def shares_for(self, cik, B):
        for yy in range(B, 2013, -1):
            v = self.sh[yy].get(cik)
            if v: return v, yy
        return None, None
    def cap(self, cik, m):
        B = self.book_year(m)
        sh, shy = self.shares_for(cik, B)
        raw = self.raw(cik, m)
        if not sh or not raw: return None
        sf = self.sf.get(shy, {}).get(cik, 1.0)
        return sh * raw * sf
    def equity(self, cik, m):
        return self.eq[self.book_year(m)].get(cik)

def cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

D = None

def pools(m):
    """Eligible pools at formation month m: dict cik -> (bm, mom, cap)."""
    m1, m12 = ym_add(m, -1), ym_add(m, -12)
    out = {}
    for cik in D.px:
        pm, pm1 = D.adj(cik, m), D.adj(cik, m1)
        if pm is None or pm1 is None: continue
        cap = D.cap(cik, m)
        eq = D.equity(cik, m)
        bm = (eq / cap) if (eq is not None and eq > 0 and cap and cap > 0) else None
        pm12 = D.adj(cik, m12)
        mom = (pm1 / pm12 - 1.0) if pm12 else None
        out[cik] = (bm, mom, cap)
    val_pool = {c: v[0] for c, v in out.items() if v[0] is not None}
    mom_pool = {c: v[1] for c, v in out.items() if v[1] is not None}
    caps = {c: v[2] for c, v in out.items()}
    return val_pool, mom_pool, caps

def tercile_top(pool):
    n = max(1, len(pool) // 3)
    return sorted(pool, key=lambda c: -pool[c])[:n], n

class Sleeve:
    def __init__(self, cash):
        self.cash = cash; self.pos = {}; self.costs = 0.0; self.orders = 0
    def value(self, m):
        v = self.cash
        for c, sh in self.pos.items():
            p = D.adj(c, m)
            if p: v += sh * p
        return v

def run_window(start_m, end_form_m, final_m, seed=None, collect_corr=False):
    """Formations start_m..end_form_m monthly; final mark/liquidation at final_m."""
    forms = []
    m = start_m
    while m <= end_form_m:
        forms.append(m); m = ym_next(m)
    sV, sM = Sleeve(50.0), Sleeve(50.0)
    rng = random.Random(seed) if seed is not None else None
    curve = []            # [ym, total, val_sleeve, mom_sleeve] post-formation marks
    sleeve_rets = []      # (val_ret, mom_ret) per holding month
    prev_post = None      # (vV, vM) post-formation values at previous formation
    pool_log = []
    total_orders = 0
    for m in forms:
        # holding return since previous formation (pre-trade values at m)
        if prev_post is not None:
            pv_v, pv_m = prev_post
            cv_v, cv_m = sV.value(m), sM.value(m)
            if pv_v > 0 and pv_m > 0:
                sleeve_rets.append((cv_v / pv_v - 1.0, cv_m / pv_m - 1.0))
        val_pool, mom_pool, caps = pools(m)
        if rng is None:
            picksV, nV = tercile_top(val_pool)
            picksM, nM = tercile_top(mom_pool)
        else:
            nV = max(1, len(val_pool) // 3); nM = max(1, len(mom_pool) // 3)
            picksV = rng.sample(sorted(val_pool), min(nV, len(val_pool)))
            picksM = rng.sample(sorted(mom_pool), min(nM, len(mom_pool)))
        pool_log.append([m, len(val_pool), len(mom_pool), len(picksV), len(picksM)])
        total = sV.value(m) + sM.value(m)
        budget = total / 2.0
        # sells toward targets (both sleeves first)
        for sl, picks in ((sV, picksV), (sM, picksM)):
            tgt = {c: budget / len(picks) for c in picks} if picks else {}
            for c in list(sl.pos):
                p = D.adj(c, m)
                if p is None:
                    del sl.pos[c]  # vanished: sold for ZERO, no cost
                    continue
                cur = sl.pos[c] * p
                t = tgt.get(c, 0.0)
                if cur > t + 1e-9:
                    sell = cur - t
                    cost = sell * cost_rate(caps.get(c))
                    sl.cash += sell - cost; sl.costs += cost; sl.orders += 1
                    sl.pos[c] = t / p
                    if sl.pos[c] < 1e-12: del sl.pos[c]
        # re-equalize cash so each sleeve holds budget minus its holdings
        holdV = sum(sh * (D.adj(c, m) or 0.0) for c, sh in sV.pos.items())
        holdM = sum(sh * (D.adj(c, m) or 0.0) for c, sh in sM.pos.items())
        sV.cash = max(0.0, budget - holdV)
        sM.cash = max(0.0, budget - holdM)
        # buys
        for sl, picks in ((sV, picksV), (sM, picksM)):
            if not picks: continue
            t_each = budget / len(picks)
            for c in picks:
                p = D.adj(c, m)
                if p is None: continue
                cur = sl.pos.get(c, 0.0) * p
                buy = t_each - cur
                if buy > 1e-9:
                    buy = min(buy, sl.cash / (1 + cost_rate(caps.get(c))))
                    if buy <= 1e-9: continue
                    cost = buy * cost_rate(caps.get(c))
                    sl.cash -= buy + cost; sl.costs += cost; sl.orders += 1
                    sl.pos[c] = sl.pos.get(c, 0.0) + buy / p
        prev_post = (sV.value(m), sM.value(m))
        curve.append([m, round(sV.value(m) + sM.value(m), 4),
                      round(sV.value(m), 4), round(sM.value(m), 4)])
    # final liquidation at final_m (sell costs; vanished = 0)
    final = 0.0
    for sl in (sV, sM):
        v = sl.cash
        for c, sh in sl.pos.items():
            p = D.adj(c, final_m)
            if p:
                gross = sh * p
                rate = cost_rate(D.cap(c, final_m))
                v += gross - gross * rate
                sl.costs += gross * rate; sl.orders += 1
        final += v
    curve.append([final_m, round(final, 4), None, None])
    peak, maxdd = 100.0, 0.0
    for row in curve:
        peak = max(peak, row[1]); maxdd = max(maxdd, 1 - row[1] / peak)
    spy_final = None
    a, b = D.spy.get(start_m), D.spy.get(final_m)
    if a and b: spy_final = round(100.0 * b / a, 2)
    res = {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
           "costs": round(sV.costs + sM.costs, 2),
           "orders": sV.orders + sM.orders,
           "curve": curve, "pool_log": pool_log,
           "spy_final_same_window": spy_final}
    if collect_corr:
        res["sleeve_monthly_returns"] = [[round(a, 6), round(b, 6)] for a, b in sleeve_rets]
    return res

def pearson(xs, ys):
    n = len(xs)
    if n < 3: return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs); syy = sum((y - my) ** 2 for y in ys)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else None

def stdev(xs):
    n = len(xs)
    if n < 2: return None
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))

def main():
    global D
    D = Data()
    print(f"candidates {len(D.cand)} with prices {len(D.px)}", flush=True)
    windows = {
        "FULL": ("2017-01", "2026-09", "2026-10"),
        "CONTs": ("2019-01", "2026-09", "2026-10"),
        "VALs": ("2023-01", "2026-09", "2026-10"),
    }
    out = {"family": "vm-twosleeve", "constructed": True,
           "note": "CONSTRUCTED long-only AMP two-sleeve; see CONSTRUCTION-SPEC.md",
           "windows": {}}
    for name, (s, e, f) in windows.items():
        r = run_window(s, e, f, collect_corr=(name == "FULL"))
        twins = []
        for seed in range(1, 21):
            tr = run_window(s, e, f, seed=seed)
            twins.append(tr["final"])
            print(name, "twin", seed, tr["final"], flush=True)
        r["placebo_finals"] = twins
        r["placebos_beaten"] = sum(1 for t in twins if r["final"] > t)
        out["windows"][name] = r
        print(name, "final", r["final"], "spy", r["spy_final_same_window"],
              "dd", r["max_dd_pct"], "beaten", r["placebos_beaten"], flush=True)
    rets = out["windows"]["FULL"]["sleeve_monthly_returns"]
    xs = [a for a, _ in rets]; ys = [b for _, b in rets]
    corr = pearson(xs, ys)
    comb = [(a + b) / 2.0 for a, b in rets]
    out["sleeve_correlation"] = {
        "monthly_net_return_corr_FULL": round(corr, 3) if corr is not None else None,
        "n_months": len(rets),
        "value_sleeve_monthly_vol_pct": round(stdev(xs) * 100, 2) if stdev(xs) else None,
        "momentum_sleeve_monthly_vol_pct": round(stdev(ys) * 100, 2) if stdev(ys) else None,
        "combined_50_50_monthly_vol_pct": round(stdev(comb) * 100, 2) if stdev(comb) else None,
        "amp_published_long_short_corr": -0.60,
        "v5_house_pond_realized_corr": 0.47}
    print("corr", out["sleeve_correlation"], flush=True)
    # per-formation-year folds (confirmation apparatus; always printed)
    folds = {}
    for y in range(2017, 2026):
        s, e, f = ym(y, 1), ym(y, 11), ym(y, 12)
        fr = run_window(s, e, f)
        folds[str(y)] = {"final": fr["final"], "spy": fr["spy_final_same_window"]}
        print("fold", y, fr["final"], "spy", fr["spy_final_same_window"], flush=True)
    out["year_folds_fresh_100"] = folds
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved results.json", flush=True)

if __name__ == "__main__":
    main()
