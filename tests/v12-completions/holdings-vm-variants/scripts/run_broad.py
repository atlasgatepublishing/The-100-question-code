#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — broad-stack families: vm-broad and
vm-twosleeve (constructed form). Spec: ../SPEC.md (frozen before runs).

vm-broad: the v12 vm-broad constructed engine (W04 EDGAR stack, annual
June formation, tiered costs, vanished->ZERO, percentile-averaged B/M +
12-1 rank) generalized from fixed top-30 to the count grid, under
native rules (no floor — AMP publishes none) and house rules (v9 -15%
floor checked on monthly marks, restart at next June formation on/after
liquidation+90d, second halt ends the run — SPEC named convention).
Native count = 30. ALL-ELIGIBLE placebos degenerate (draw = whole pool),
marked, not run.

vm-twosleeve constructed: the v12 vm-twosleeve engine (W04 stack,
monthly, two single-signal sleeves, 50/50 re-equalized monthly, tiered
costs, vanished->ZERO, no floor) generalized from top-tercile to a
per-sleeve count grid; TERCILE kept as the native cell. The documented
corrupt series AMCCF (CIK 1748790) is excluded in-process only, exactly
as the family's own diagnostic did (shared cache untouched).
Simulation only. Writes only ../results_broad.json.
"""
import json, os, sys, random, statistics, time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "results_broad.json")
W04 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data")
sys.path.insert(0, W04)
import engine_w04 as EW
EW.D = EW.Data()
D4 = EW.D
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
SEEDS = list(range(1, 21))
BAD_CIK = 1748790  # AMCCF — documented corrupt series (twosleeve family only)

def ym(y, m): return f"{y:04d}-{m:02d}"
def ym_add(s, k):
    y, m = int(s[:4]), int(s[5:7]) - 1 + k
    return ym(y + m // 12, m % 12 + 1)

# ================================================================ vm-broad
def pct_ranks(vals):
    items = sorted(vals.items(), key=lambda kv: kv[1]); n = len(items)
    if n == 1: return {items[0][0]: 0.5}
    return {c: i / (n - 1) for i, (c, _) in enumerate(items)}

def broad_eligible(F):
    s = EW.snapshot(F); pool = {}
    for c, v in s.items():
        if not v["cap"] or v["cap"] < 50e6: continue
        if not v["equity"] or v["equity"] <= 0: continue
        if not v["shares"] or not v["px_adj"]: continue
        if not D4.has_price_month(c, ym(F, 6)): continue
        if not D4.has_price_month(c, ym(F, 5)): continue
        if not D4.has_price_month(c, ym(F - 1, 6)): continue
        p_may = D4.price(c, ym(F, 5)); p_jun = D4.price(c, ym(F - 1, 6))
        if not p_may or not p_jun: continue
        pool[c] = dict(bm=v["equity"] / v["cap"], mom=p_may / p_jun - 1.0,
                       cap=v["cap"], ticker=v["ticker"], px=v["px_adj"])
    vr = pct_ranks({c: v["bm"] for c, v in pool.items()})
    mr = pct_ranks({c: v["mom"] for c, v in pool.items()})
    ranked = sorted(pool, key=lambda c: -(vr[c] + mr[c]) / 2.0)
    return ranked, pool

POOLS = {}
def broad_run(formations, n, rules, seed=None):
    cash = 100.0; curve = []; costs = 0.0; orders = 0; zeroed = 0; yearly = []
    ep_start = 100.0; halts = 0; restart_after = None  # ym string: formations before this are skipped
    rng = random.Random(seed) if seed is not None else None
    for F in formations:
        ranked, pool = POOLS[F]
        if len(pool) < 30:
            yearly.append({"formation": F, "pool": len(pool), "ret": 0.0}); continue
        if restart_after is not None and ym(F, 6) < restart_after:
            for mm in [ym(F, m) for m in range(7, 13)] + [ym(F + 1, m) for m in range(1, 7)]:
                curve.append([mm, round(cash, 2)])
            yearly.append({"formation": F, "pool": len(pool), "ret": 0.0, "halted_out": True}); continue
        if halts >= 2:
            for mm in [ym(F, m) for m in range(7, 13)] + [ym(F + 1, m) for m in range(1, 7)]:
                curve.append([mm, round(cash, 2)])
            yearly.append({"formation": F, "pool": len(pool), "ret": 0.0, "run_ended": True}); continue
        k = len(ranked) if n == "ALL" else min(n, len(ranked))
        if rng is not None:
            keys = list(pool.keys()); rng.shuffle(keys); picks = keys[:k]
        else:
            picks = ranked[:k]
        start = cash; ep_start = cash if (halts == 0 or restart_after is not None) else ep_start
        if halts == 0 and restart_after is None: ep_start = start
        w = cash / len(picks); pos = {}
        for c in picks:
            r = EW.cost_rate(pool[c]["cap"]); costs += w * r; orders += 1
            pos[c] = (w - w * r) / pool[c]["px"]
        months = [ym(F, m) for m in range(7, 13)] + [ym(F + 1, m) for m in range(1, 7)]
        liquidated = False
        for mm in months:
            val = 0.0
            for c, sh in pos.items():
                if D4.has_price_month(c, mm): val += sh * D4.price(c, mm)
                else: zeroed += 1
            if rules == "house" and halts < 2 and val <= 0.85 * ep_start and mm != months[-1]:
                # liquidate at this month's prices
                end = 0.0
                for c, sh in pos.items():
                    if D4.has_price_month(c, mm):
                        gross = sh * D4.price(c, mm); r = EW.cost_rate(pool[c]["cap"])
                        costs += gross * r; orders += 1; end += gross - gross * r
                    else: zeroed += 1
                cash = end; halts += 1; liquidated = True
                restart_after = ym_add(mm, 3)
                curve.append([mm, round(cash, 2)])
                # remaining months of this holding year: cash
                for mm2 in months[months.index(mm) + 1:]:
                    curve.append([mm2, round(cash, 2)])
                break
            curve.append([mm, round(val, 2)])
        if liquidated:
            yearly.append({"formation": F, "pool": len(pool), "picks": [pool[c]["ticker"] for c in picks],
                           "ret": round(cash / start - 1, 4) if start else 0.0, "halt": True})
            continue
        end = 0.0
        for c, sh in pos.items():
            if D4.has_price_month(c, ym(F + 1, 6)):
                gross = sh * D4.price(c, ym(F + 1, 6)); r = EW.cost_rate(pool[c]["cap"])
                costs += gross * r; orders += 1; end += gross - gross * r
            else: zeroed += 1
        cash = end
        yearly.append({"formation": F, "pool": len(pool), "picks": [pool[c]["ticker"] for c in picks],
                       "ret": round(cash / start - 1, 4) if start else 0.0})
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak) if peak else 0
    spy = None
    if formations and D4.spy:
        a = D4.spy.get(ym(formations[0], 6)); b = D4.spy.get(ym(formations[-1] + 1, 6))
        if a and b: spy = round(100 * b / a, 2)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "halts": halts,
            "zeroed_name_months": zeroed, "curve": curve, "yearly": yearly,
            "spy_final_same_window": spy}

# ============================================================ twosleeve
def load_frame(name):
    p = os.path.join(W04, "frames", name)
    if not os.path.exists(p): return {}
    return {int(k): v for k, v in json.load(open(p)).items()}

class TSData:
    def __init__(self):
        self.cand = {int(k): v for k, v in json.load(open(os.path.join(W04, "candidates.json"))).items()}
        self.px = {}
        for cik, info in self.cand.items():
            if cik == BAD_CIK: continue
            t = info["ticker"].replace("/", "-")
            p = os.path.join(W04, f"px_{t}.json")
            if os.path.exists(p):
                self.px[cik] = {r[0]: (r[1], r[2]) for r in json.load(open(p))}
        self.eq = {y: load_frame(f"StockholdersEquity_{y}I.json") for y in range(2014, 2026)}
        self.sh = {y: load_frame(f"Shares_{y}I.json") for y in range(2014, 2026)}
        self.sf = {}
        for B in range(2014, 2026):
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
        s = self.px.get(cik); v = s[m][0] if s and m in s else None
        return v if (v is not None and v > 0) else None
    def raw(self, cik, m):
        s = self.px.get(cik); v = s[m][1] if s and m in s else None
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
        B = self.book_year(m); sh, shy = self.shares_for(cik, B); raw = self.raw(cik, m)
        if not sh or not raw: return None
        return sh * raw * self.sf.get(shy, {}).get(cik, 1.0)
    def equity(self, cik, m):
        return self.eq[self.book_year(m)].get(cik)

def ts_cost_rate(cap):
    if cap is None: return 0.0075
    if cap >= 5e9: return 0.0010
    if cap >= 1e9: return 0.0025
    return 0.0075

TD = None
def ts_pools(m):
    m1, m12 = ym_add(m, -1), ym_add(m, -12); out = {}
    for cik in TD.px:
        pm, pm1 = TD.adj(cik, m), TD.adj(cik, m1)
        if pm is None or pm1 is None: continue
        cap = TD.cap(cik, m); eq = TD.equity(cik, m)
        bm = (eq / cap) if (eq is not None and eq > 0 and cap and cap > 0) else None
        pm12 = TD.adj(cik, m12)
        mom = (pm1 / pm12 - 1.0) if pm12 else None
        out[cik] = (bm, mom, cap)
    val_pool = {c: v[0] for c, v in out.items() if v[0] is not None}
    mom_pool = {c: v[1] for c, v in out.items() if v[1] is not None}
    caps = {c: v[2] for c, v in out.items()}
    return val_pool, mom_pool, caps

class TSSleeve:
    def __init__(self, cash): self.cash = cash; self.pos = {}; self.costs = 0.0; self.orders = 0
    def value(self, m):
        v = self.cash
        for c, sh in self.pos.items():
            p = TD.adj(c, m)
            if p: v += sh * p
        return v

def ts_run(start_m, end_form_m, final_m, k, seed=None):
    """k: int per-sleeve count, 'ALL', or 'TERCILE' (native)."""
    forms = []; m = start_m
    while m <= end_form_m:
        forms.append(m); m = ym_add(m, 1)
    sV, sM = TSSleeve(50.0), TSSleeve(50.0)
    rng = random.Random(seed) if seed is not None else None
    curve = []; pool_log = []
    def picks_for(pool):
        n_pool = len(pool)
        if k == "TERCILE": kk = max(1, n_pool // 3)
        elif k == "ALL": kk = n_pool
        else: kk = min(k, n_pool)
        if rng is not None:
            return rng.sample(sorted(pool), kk)
        return sorted(pool, key=lambda c: -pool[c])[:kk]
    for m in forms:
        val_pool, mom_pool, caps = ts_pools(m)
        picksV = picks_for(val_pool); picksM = picks_for(mom_pool)
        pool_log.append([m, len(val_pool), len(mom_pool), len(picksV), len(picksM)])
        total = sV.value(m) + sM.value(m); budget = total / 2.0
        for sl, picks in ((sV, picksV), (sM, picksM)):
            tgt = {c: budget / len(picks) for c in picks} if picks else {}
            for c in list(sl.pos):
                p = TD.adj(c, m)
                if p is None:
                    del sl.pos[c]; continue
                cur = sl.pos[c] * p; t = tgt.get(c, 0.0)
                if cur > t + 1e-9:
                    sell = cur - t; cost = sell * ts_cost_rate(caps.get(c))
                    sl.cash += sell - cost; sl.costs += cost; sl.orders += 1
                    sl.pos[c] = t / p
                    if sl.pos[c] < 1e-12: del sl.pos[c]
        holdV = sum(sh * (TD.adj(c, m) or 0.0) for c, sh in sV.pos.items())
        holdM = sum(sh * (TD.adj(c, m) or 0.0) for c, sh in sM.pos.items())
        sV.cash = max(0.0, budget - holdV); sM.cash = max(0.0, budget - holdM)
        for sl, picks in ((sV, picksV), (sM, picksM)):
            if not picks: continue
            t_each = budget / len(picks)
            for c in picks:
                p = TD.adj(c, m)
                if p is None: continue
                cur = sl.pos.get(c, 0.0) * p; buy = t_each - cur
                if buy > 1e-9:
                    buy = min(buy, sl.cash / (1 + ts_cost_rate(caps.get(c))))
                    if buy <= 1e-9: continue
                    cost = buy * ts_cost_rate(caps.get(c))
                    sl.cash -= buy + cost; sl.costs += cost; sl.orders += 1
                    sl.pos[c] = sl.pos.get(c, 0.0) + buy / p
        curve.append([m, round(sV.value(m) + sM.value(m), 4)])
    final = 0.0
    for sl in (sV, sM):
        v = sl.cash
        for c, sh in sl.pos.items():
            p = TD.adj(c, final_m)
            if p:
                gross = sh * p; rate = ts_cost_rate(TD.cap(c, final_m))
                v += gross - gross * rate; sl.costs += gross * rate; sl.orders += 1
        final += v
    curve.append([final_m, round(final, 4)])
    peak, maxdd = 100.0, 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    spy_final = None
    a, b = TD.spy.get(start_m), TD.spy.get(final_m)
    if a and b: spy_final = round(100.0 * b / a, 2)
    sizes = [p[3] + p[4] for p in pool_log]
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(sV.costs + sM.costs, 2), "orders": sV.orders + sM.orders,
            "curve": curve, "pool_log": pool_log, "spy_final_same_window": spy_final,
            "holdings_mean": round(sum(sizes) / len(sizes), 1) if sizes else None}

def main():
    global TD
    t0 = time.time()
    out = {"program": "v12 holdings-count sweep — broad-stack families"}
    # ---------------- vm-broad
    roads = {"FULL_2017_2025": list(range(2017, 2026)),
             "CONT_era_2019_2025": list(range(2019, 2026)),
             "VAL_era_2023_2025": list(range(2023, 2026)),
             "fold_2017_2020": list(range(2017, 2021)),
             "fold_2021_2025": list(range(2021, 2026))}
    for F in range(2017, 2026):
        POOLS[F] = broad_eligible(F)
        print(f"pool {F}: {len(POOLS[F][1])} eligible ({time.time()-t0:.0f}s)", flush=True)
    broad = {}
    for rname, forms in roads.items():
        cells = {}
        for n in COUNTS:
            for rules in ("native", "house"):
                r = broad_run(forms, n, rules)
                cell = {kk: r[kk] for kk in ("final", "max_dd_pct", "costs", "orders", "halts", "zeroed_name_months", "spy_final_same_window", "curve", "yearly")}
                if n == "ALL":
                    cell["placebo_finals"] = []; cell["placebos_beaten"] = 0
                    cell["placebo_note"] = "degenerate: random draw of ALL = whole pool"
                else:
                    twins = []
                    for seed in SEEDS:
                        twins.append(broad_run(forms, n, rules, seed=seed * 7919 + forms[0])["final"])
                    cell["placebo_finals"] = twins
                    cell["placebos_beaten"] = sum(1 for x in twins if r["final"] > x)
                    cell["placebo_median"] = round(statistics.median(twins), 2)
                cells[f"{n}|{rules}"] = cell
                print(f"broad {rname} n={n} {rules}: ${r['final']} beat {cell['placebos_beaten']}/20 ({time.time()-t0:.0f}s)", flush=True)
        broad[rname] = cells
    out["vm-broad"] = broad
    with open(OUT, "w") as f: json.dump(out, f, indent=1)
    print("broad saved", flush=True)
    # ---------------- twosleeve constructed
    TD = TSData()
    print(f"twosleeve data: {len(TD.px)} price series ({time.time()-t0:.0f}s)", flush=True)
    windows = {"FULL": ("2017-01", "2026-09", "2026-10"),
               "CONTs": ("2019-01", "2026-09", "2026-10"),
               "VALs": ("2023-01", "2026-09", "2026-10"),
               "H1_2017_2021": ("2017-01", "2021-11", "2021-12"),
               "H2_2022_2026": ("2022-01", "2026-09", "2026-10")}
    ts = {}
    for wname, (s, e, f_) in windows.items():
        cells = {}
        for k in COUNTS + ["TERCILE"]:
            r = ts_run(s, e, f_, k)
            cell = {kk: r[kk] for kk in ("final", "max_dd_pct", "costs", "orders", "spy_final_same_window", "curve", "holdings_mean")}
            if k == "ALL":
                cell["placebo_finals"] = []; cell["placebos_beaten"] = 0
                cell["placebo_note"] = "degenerate: random draw of ALL = whole pool per sleeve"
            elif wname.startswith("H"):
                cell["placebo_finals"] = []; cell["placebos_beaten"] = None
                cell["placebo_note"] = "confirmation window: ranked only, head-to-head vs native"
            else:
                twins = []
                for seed in SEEDS:
                    twins.append(ts_run(s, e, f_, k, seed=seed)["final"])
                cell["placebo_finals"] = twins
                cell["placebos_beaten"] = sum(1 for x in twins if r["final"] > x)
                cell["placebo_median"] = round(statistics.median(twins), 2)
            cells[str(k)] = cell
            print(f"twosleeve-broad {wname} k={k}: ${r['final']} beat {cell['placebos_beaten']} ({time.time()-t0:.0f}s)", flush=True)
        ts[wname] = cells
    out["vm-twosleeve-constructed"] = ts
    out["runtime_s"] = round(time.time() - t0, 1)
    with open(OUT, "w") as f: json.dump(out, f, indent=1)
    print("DONE", OUT, flush=True)

if __name__ == "__main__":
    main()
