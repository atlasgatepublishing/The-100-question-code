#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — PEAD (Bernard & Thomas SUE, long leg).
Frozen mapping (written before runs): PEAD is an event system; its only
holdings count is MAX CONCURRENT POSITIONS. Native: slice=10% of equity,
max 10 concurrent (v11 NATIVE-SPEC). Sweep: count N -> slice=1/N of equity,
max N concurrent. ALL-ELIGIBLE -> no concurrency cap, native 10% slice
(cash is the only limit). Entry/exit/signal identical to v11 engine:
SUE top-decile vs previous-quarter breakpoints, entry adjclose first
trading day after EDGAR filing, exit +60 trading days.
Forms: native = no floor. house = v9: plain -15% floor from episode start;
halt -> liquidate next trading day, sit out 90 calendar days, restart at
next signal entry; ep2 floor -15% from restart balance; 2nd halt ends run.
Costs: small habitat 0.35%/side, lite 0.10%/side (v11, unchanged both forms).
Placebos: same n signals, random ticker+day, seeds 1..20, FULL window.
"""
import json, os, sys, glob, random, statistics
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V11S = "/home/hatch/workspace/stock-app/backtests/v11-native-rules/pead-small"
V11L = "/home/hatch/workspace/stock-app/backtests/v11-native-rules/pead-lite"
V3 = "/home/hatch/workspace/stock-app/backtests/v3/pead-cache"
V4 = "/home/hatch/workspace/stock-app/backtests/v4/pead-small-cache"
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, None]  # None = ALL-ELIGIBLE

def load_px(t):
    for c in (V3, V4):
        p = os.path.join(c, f"px_{t}.json")
        if os.path.exists(p):
            d = json.load(open(p))["chart"]["result"][0]
            out = {}
            for i, x in enumerate(d["timestamp"]):
                a = d["indicators"]["adjclose"][0]["adjclose"][i]
                if a: out[date.fromtimestamp(x).isoformat()] = a
            return out
    return {}

def build_signals(tickers, eps_dir):
    anns = []
    for t in tickers:
        fp = os.path.join(eps_dir, f"eps_{t}.json")
        if not os.path.exists(fp): continue
        facts = json.load(open(fp))["facts"]
        ues = []
        for f in facts:
            e = date.fromisoformat(f["end"]); prior = None
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
        y, m = int(filed[:4]), int(filed[5:7]); q = (m - 1) // 3
        return (y - 1, 4) if q == 0 else (y, q)
    signals = []
    for filed, t, sue in anns:
        py, pq = prev_q(filed)
        pool = sorted(s for (fd, _, s) in anns
                      if int(fd[:4]) == py and (int(fd[5:7]) - 1) // 3 + 1 == pq)
        if len(pool) < 20: continue
        thr = pool[min(len(pool) - 1, int(0.90 * len(pool)))]
        if sue >= thr and sue > 0:
            signals.append({"filed": filed, "ticker": t, "sue": round(sue, 3)})
    return signals

class Sim:
    def __init__(self, px, spy, cal, cost):
        self.px, self.spy, self.cal, self.cost = px, spy, cal, cost
        self.cal_idx = {d: i for i, d in enumerate(cal)}
    def trades_for(self, sig_list, start, end):
        trades = []
        for s in sig_list:
            cand = [d for d in self.cal if d > s["filed"]]
            if not cand: continue
            ed = cand[0]
            if not (start <= ed <= end): continue
            i = self.cal_idx[ed]
            if i + 60 >= len(self.cal): continue
            xd = self.cal[i + 60]
            p0 = self.px[s["ticker"]].get(ed); p1 = self.px[s["ticker"]].get(xd)
            if not p0 or not p1: continue
            trades.append({**s, "entry": ed, "exit": xd, "p0": p0, "p1": p1})
        trades.sort(key=lambda x: x["entry"])
        return trades
    def run(self, trades, start, end, n_count, house=False):
        slice_frac = 0.10 if n_count is None else 1.0 / n_count
        cap = 10**9 if n_count is None else n_count
        days = [d for d in self.cal if start <= d <= end]
        cash, pos, curve, total_cost, ti = 100.0, [], [], 0.0, 0
        ep_start_eq, ep = 100.0, 1
        halted_dates, resume_after = [], None
        pending_liq = False
        for d in days:
            if pending_liq:  # liquidate at today's prices, start sit-out
                for p in pos:
                    pr = self.px[p["ticker"]].get(d, p["p1"])
                    cash += p["shares"] * pr * (1 - self.cost); total_cost += p["shares"] * pr * self.cost
                pos = []; pending_liq = False
                halted_dates.append(d)
                if ep == 2:
                    curve.append([d, round(cash, 2)]); break
                resume_after = (date.fromisoformat(d) + timedelta(days=90)).isoformat()
                ep_start_eq = cash; ep = 2
                while ti < len(trades) and trades[ti]["entry"] < resume_after: ti += 1
            still = []
            for p in pos:
                if d >= p["exit"]:
                    pr = self.px[p["ticker"]].get(d, p["p1"])
                    cash += p["shares"] * pr * (1 - self.cost); total_cost += p["shares"] * pr * self.cost
                else: still.append(p)
            pos = still
            while ti < len(trades) and trades[ti]["entry"] == d:
                tr = trades[ti]; ti += 1
                equity = cash + sum(p["shares"] * self.px[p["ticker"]].get(d, p["p0"]) for p in pos)
                amt = slice_frac * equity
                if len(pos) < cap and cash >= amt > 0:
                    sh = amt * (1 - self.cost) / tr["p0"]; total_cost += amt * self.cost
                    cash -= amt; pos.append({**tr, "shares": sh})
            equity = cash + sum(p["shares"] * self.px[p["ticker"]].get(d, p["p0"]) for p in pos)
            curve.append([d, round(equity, 2)])
            if house and equity <= 0.85 * ep_start_eq and d != days[-1]:
                pending_liq = True
        final = curve[-1][1] if curve else 100.0
        peak, mdd = 100.0, 0.0
        for _, v in curve:
            peak = max(peak, v); mdd = min(mdd, v / peak - 1)
        s0 = self.spy.get(curve[0][0]) if curve else None
        s1 = self.spy.get(curve[-1][0]) if curve else None
        return {"final": final, "max_dd_pct": round(mdd * 100, 2),
                "costs": round(total_cost, 2), "n_signals": len(trades),
                "halts": len(halted_dates), "halt_dates": halted_dates,
                "spy_final": round(100 * s1 / s0, 2) if s0 and s1 else None,
                "curve": curve}

def period_stats(curve, months=True):
    # monthly period returns from daily curve
    bym = {}
    for d, v in curve: bym[d[:7]] = v
    keys = sorted(bym); rets = []
    prev = 100.0
    for k in keys:
        rets.append(bym[k] / prev - 1); prev = bym[k]
    if not rets: return None
    prof = sum(1 for r in rets if r > 0)
    worst_run = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; worst_run = max(worst_run, cur)
    # longest stretch between new highs (months)
    peak, since, longest = 100.0, 0, 0
    for k in keys:
        if bym[k] >= peak: peak = bym[k]; longest = max(longest, since); since = 0
        else: since += 1
    longest = max(longest, since)
    return {"period": "calendar month", "n_periods": len(rets),
            "pct_profitable": round(100 * prof / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "mean_pct_secondary_average": round(statistics.mean(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_run_periods": worst_run,
            "longest_stretch_between_new_highs_periods": longest}

WINDOWS = {"FULL_2019_2026": ("2019-01-01", "2026-11-20"),
           "DESIGN_2019_2022": ("2019-01-01", "2022-12-31"),
           "VAL_2023_2026": ("2023-01-01", "2026-11-20")}
CONFIRM = {"CONF_A_2020_2023": ("2020-01-01", "2023-12-31"),
           "CONF_B_2024_2026": ("2024-01-01", "2026-11-20")}

def main():
    out = {"family": "pead", "native_count": 10, "counts_grid": ["ALL" if c is None else c for c in COUNTS],
           "habitats": {}}
    for mode, eps_dir, cost in (("small", os.path.join(V11S, "eps_cache"), 0.0035),
                                ("lite", os.path.join(V11L, "eps_cache"), 0.0010)):
        if mode == "lite":
            tickers = sorted({os.path.basename(f)[3:-5] for c in (V3, V4)
                              for f in glob.glob(os.path.join(c, "px_*.json"))} - {"SPY"})
        else:
            tickers = sorted({os.path.basename(f)[3:-5] for f in glob.glob(os.path.join(V4, "px_*.json"))} - {"SPY"})
        px = {t: load_px(t) for t in tickers}; spy = load_px("SPY")
        cal = sorted(spy.keys())
        sim = Sim(px, spy, cal, cost)
        signals = build_signals(tickers, eps_dir)
        hab = {"universe_n": len(tickers), "cost_per_side": cost, "forms": {}}
        for form, house in (("native", False), ("house", True)):
            cells = {}
            for n in COUNTS:
                key = "ALL" if n is None else str(n)
                cell = {}
                for w, (a, b) in {**WINDOWS, **CONFIRM}.items():
                    tr = sim.trades_for(signals, a, b)
                    r = sim.run(tr, a, b, n, house=house)
                    cell[w] = {k: v for k, v in r.items() if k != "curve"}
                    if w in ("FULL_2019_2026",) and ((form == "native" and n == 10) or False):
                        pass
                    cell[w]["_curve"] = r["curve"]
                # placebos FULL only
                a, b = WINDOWS["FULL_2019_2026"]
                real_tr = sim.trades_for(signals, a, b)
                days = [d for d in cal if a <= d <= b]
                pls = []
                for seed in range(1, 21):
                    rng = random.Random(seed)
                    fake = [{"filed": cal[max(0, sim.cal_idx[rng.choice(days)] - 1)],
                             "ticker": rng.choice(tickers), "sue": 0} for _ in range(len(real_tr))]
                    ftr = sim.trades_for(fake, a, b)
                    pls.append(sim.run(ftr, a, b, n, house=house)["final"])
                real_final = cell["FULL_2019_2026"]["final"]
                cell["placebos_full"] = {"finals": [round(x, 2) for x in pls],
                    "beaten": sum(1 for x in pls if real_final > x),
                    "median": round(statistics.median(pls), 2)}
                cells[key] = cell
            hab["forms"][form] = cells
        out["habitats"][mode] = hab
        print(mode, "signals done", flush=True)
    # curves + period stats for native count & best count per habitat/form (FULL)
    for mode, hab in out["habitats"].items():
        for form, cells in hab["forms"].items():
            finals = {k: c["FULL_2019_2026"]["final"] for k, c in cells.items()}
            best = max(finals, key=finals.get)
            keep = {"10", best}
            for k in list(cells):
                for w in list(cells[k]):
                    if isinstance(cells[k][w], dict) and "_curve" in cells[k][w]:
                        curve = cells[k][w].pop("_curve")
                        if k in keep and w == "FULL_2019_2026":
                            cells[k][w]["curve"] = curve
                            cells[k][w]["period_stats_monthly"] = period_stats(curve)
            hab["forms"][form]["_best_full"] = best
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"))
    for mode, hab in out["habitats"].items():
        for form in ("native", "house"):
            cells = hab["forms"][form]
            print(mode, form, {k: cells[k]["FULL_2019_2026"]["final"] for k in cells if not k.startswith("_")},
                  "placebo native10 beaten", cells["10"]["placebos_full"]["beaten"])

if __name__ == "__main__":
    main()
