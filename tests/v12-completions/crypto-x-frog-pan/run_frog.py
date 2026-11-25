#!/usr/bin/env python3
"""
CRYPTO-X FROG-IN-THE-PAN — coin cross-section run (Wing 1).
Frozen spec: CONSTRUCTION-SPEC.md in this folder (written before runs).
Reuses the shared crypto plumbing of v12 crypto-basket-pit (weekly CMC
Sunday snapshots + v4 cmc-id price registry + HYPE), READ-ONLY.
Signal: 12-1 calendar formation (365/30), ID from daily-return signs
inside the span; monthly; hold 5 lowest-ID positive-momentum PIT
top-20 coins at 20% each; dead coins (bars silent >7d) to ZERO.
Rule sets: native no-floor + v9 protections. Cost headline 0.60%/side.
"""
import json, math, os, random, time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SIB = os.path.join(HERE, "..", "crypto-basket-pit")
V4 = os.path.join(HERE, "..", "..", "v4")
V4CACHE = os.path.join(V4, "crypto-basket-pit-data")
POT = 100.0
MOM_FAR, MOM_NEAR, SILENCE_DAYS = 365, 30, 7
WINDOWS = {"full": ("2017-01-01", "2026-11-20"),
           "design": ("2017-01-01", "2022-12-31"),
           "validation": ("2023-01-01", "2026-11-20")}
PLACEBO_SEEDS = list(range(1, 21))
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}

# ---------------------------------------------------------------- data ----
def load_registry():
    with open(os.path.join(V4, "crypto-basket-pit-results.json")) as f:
        v4res = json.load(f)
    reg = {}
    for cid_s, info in v4res["registry"].items():
        cid = int(cid_s)
        if info["source"] == "excluded":
            reg[cid] = {**info, "rows": []}; continue
        kind, name = info["source"].split(":", 1)
        fn = {"yahoo": f"y_{name}.json", "binance": f"b_{name}.json",
              "kraken": f"k_{name}.json"}[kind]
        with open(os.path.join(V4CACHE, fn)) as f: rows = json.load(f)
        if cid in CREDIBLE_START:
            rows = [r for r in rows if r["d"] >= CREDIBLE_START[cid]]
        reg[cid] = {**info, "rows": rows}
    with open(os.path.join(SIB, "data", "hype.json")) as f: rows = json.load(f)
    reg[32196] = {"symbol": "HYPE", "slug": "hyperliquid", "source": "hyperliquid:HYPE",
                  "reason": None, "rows": rows}
    return reg

def load_weekly():
    with open(os.path.join(SIB, "data", "weekly_snapshots.json")) as f:
        return json.load(f)

# ------------------------------------------------------------- market -----
class Market:
    def __init__(self, reg, weekly):
        self.reg = reg
        btc = reg[1]["rows"]
        self.cal = [r["d"] for r in btc]
        self.bars, self.ff, self.lb, self.bc = {}, {}, {}, {}
        for cid, info in reg.items():
            if info["source"] == "excluded" or not info["rows"]: continue
            bars = {r["d"]: (r["o"], r["c"]) for r in info["rows"]}
            self.bars[cid] = bars
            ff, lb, bc = [], [], []
            last, li, n = None, -1, 0
            for i, d in enumerate(self.cal):
                if d in bars: last, li, n = bars[d][1], i, n + 1
                ff.append(last); lb.append(li); bc.append(n)
            self.ff[cid], self.lb[cid], self.bc[cid] = ff, lb, bc
        self._elig = {}
        self.snap_keys = sorted(weekly.keys())
        self.snap_top = {k: [c["cmc_id"] for c in weekly[k]["top20"]] for k in self.snap_keys}
    def universe(self, d):
        import bisect
        k = bisect.bisect_right(self.snap_keys, d) - 1
        return self.snap_top[self.snap_keys[k]] if k >= 0 else []
    def trade_open(self, cid, i):
        d = self.cal[i]
        if d in self.bars[cid]: return self.bars[cid][d][0]
        if i - self.lb[cid][i] <= SILENCE_DAYS and self.ff[cid][i] is not None:
            return self.ff[cid][i]
        return None
    def value_close(self, cid, i):
        lb = self.lb[cid][i]
        if lb < 0: return None
        return self.ff[cid][i] if i - lb <= SILENCE_DAYS else 0.0
    def eligible(self, cid, j):
        key = (cid, j)
        if key not in self._elig: self._elig[key] = self._eligible(cid, j)
        return self._elig[key]
    def _eligible(self, cid, j):
        """Return (formation_mom, ID) or None. Frozen spec section (b)."""
        if cid not in self.bars or j < 0: return None
        lb = self.lb[cid]
        if lb[j] < 0 or j - lb[j] > 7: return None
        if self.bc[cid][j] < 300: return None
        ai, bi = lb[j-MOM_FAR], lb[j-MOM_NEAR]
        if ai < 0 or bi < 0: return None
        if (j-MOM_FAR)-ai > 7 or (j-MOM_NEAR)-bi > 7: return None
        a, b = self.ff[cid][ai], self.ff[cid][bi]
        if a is None or b is None or a <= 0: return None
        mom = b/a - 1.0
        if mom <= 0: return None
        up = down = 0
        ff = self.ff[cid]
        for k in range(ai+1, bi+1):
            if ff[k] is None or ff[k-1] is None or ff[k-1] <= 0: continue
            r = ff[k]/ff[k-1] - 1.0
            if r > 0: up += 1
            elif r < 0: down += 1
        n = bi - ai
        if n <= 0: return None
        idv = (down - up) / n  # sign(mom)=+1 for all eligible (winners only)
        return (mom, idv)

def is_rebalance(d, first):
    if first: return True
    return datetime.strptime(d, "%Y-%m-%d").day == 1

# ----------------------------------------------------------- simulate -----
def simulate(mkt, start_d, end_d, ruleset, cost, mode="ranked", seed=42):
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    cash, pos, entry = float(POT), {}, {}
    wo = {}
    orders, costs = 0, 0.0
    curve, events, halts = [], [], []
    picks_log, elig_sum, elig_n, inv_sum = [], 0, 0, 0.0
    episode, floor_abs = 1, 85.0
    pending_liq, sit_until, ended = False, None, False

    def equity_at(i):
        return cash + sum(sh * (mkt.value_close(cid, i) or 0.0) for cid, sh in pos.items())
    def note_exit(cid, px, when):
        if cid in entry and entry[cid] > 0 and px <= 0.10 * entry[cid]:
            events.append({"type": "collapse_exit", "coin": mkt.reg[cid]["symbol"],
                           "cmc_id": cid, "date": when, "entry_px": entry[cid],
                           "exit_px": px, "loss_pct": round((px/entry[cid]-1)*100, 2)})

    for i in range(i0, i1+1):
        d = cal[i]
        for cid in list(pos):
            lb = mkt.lb[cid][i]
            if lb >= 0 and i - lb == SILENCE_DAYS + 1 and not wo.get(cid):
                events.append({"type": "write_off", "coin": mkt.reg[cid]["symbol"],
                               "cmc_id": cid, "date": d, "last_bar_date": cal[lb],
                               "last_px": mkt.ff[cid][lb],
                               "written_off_value": round(pos[cid]*mkt.ff[cid][lb], 2)})
                wo[cid] = True
            if lb >= 0 and i - lb <= SILENCE_DAYS and wo.get(cid): wo[cid] = False
        if pending_liq:
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    note_exit(cid, 0.0, d); del pos[cid]; entry.pop(cid, None); continue
                val = pos[cid]*px; fee = val*cost; cash += val - fee
                costs += fee; orders += 1; note_exit(cid, px, d)
                del pos[cid]; entry.pop(cid, None)
            pending_liq = False
            halts.append({"episode": episode, "halt_date": d, "liquidated_at": round(cash, 2)})
            if episode == 1:
                episode = 2
                sit_until = (datetime.strptime(d, "%Y-%m-%d") + timedelta(days=90)).strftime("%Y-%m-%d")
            else:
                ended = True
            curve.append((d, cash))
            if ended:
                for k in range(i+1, i1+1): curve.append((cal[k], cash))
                break
            continue
        sitting = sit_until is not None and d < sit_until
        if not sitting and is_rebalance(d, i == i0):
            if sit_until is not None and d >= sit_until:
                floor_abs = 0.85 * cash; sit_until = None
                halts[-1]["restart_date"] = d; halts[-1]["restart_balance"] = round(cash, 2)
            universe = mkt.universe(d)
            j = i - 1
            elig = [(cid, mkt.eligible(cid, j)) for cid in universe]
            elig = [(c, v) for c, v in elig if v is not None]
            elig_sum += len(elig); elig_n += 1
            if mode == "ranked":
                elig.sort(key=lambda x: (x[1][1], -x[1][0], mkt.reg[x[0]]["symbol"]))
                picks = [c for c, _ in elig[:5]]
                picks_log.append({"date": d,
                                  "picks": [{"symbol": mkt.reg[c]["symbol"],
                                             "mom_pct": round(v[0]*100, 2),
                                             "ID": round(v[1], 4)} for c, v in elig[:5]],
                                  "n_eligible": len(elig)})
            else:
                names = sorted(c for c, _ in elig)
                picks = rng.sample(names, min(5, len(names))) if names else []
            inv_sum += 0.20 * len(picks)
            eq = equity_at(i)
            target = {cid: 0.20*eq for cid in picks}
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:  # silent >7d: exit at ZERO per death rule
                    note_exit(cid, 0.0, d); del pos[cid]; entry.pop(cid, None); continue
                cur = pos[cid]*px; want = target.get(cid, 0.0)
                if want <= 0.0 and cur <= 0.01:
                    note_exit(cid, px, d); del pos[cid]; entry.pop(cid, None); continue
                if cur > want + 0.01:
                    sv = cur - want; fee = sv*cost; cash += sv - fee
                    costs += fee; orders += 1; pos[cid] -= sv/px
                    if want <= 0.0 or pos[cid]*px < 0.01:
                        note_exit(cid, px, d); del pos[cid]; entry.pop(cid, None)
            for cid in picks:
                px = mkt.trade_open(cid, i)
                if px is None: continue
                deficit = target[cid] - pos.get(cid, 0.0)*px
                if deficit <= 0.01: continue
                bv = min(deficit, cash/(1.0+cost))
                if bv <= 0.01: continue
                fee = bv*cost; cash -= bv + fee; costs += fee; orders += 1
                sh = bv/px; old = pos.get(cid, 0.0)
                entry[cid] = (entry[cid]*old + px*sh)/(old+sh) if old > 0 and cid in entry else px
                pos[cid] = old + sh
        eq_close = equity_at(i)
        curve.append((d, eq_close))
        if ruleset == "v9" and not sitting and sit_until is None and eq_close <= floor_abs:
            if i == i1:
                tot = cash
                for cid, sh in list(pos.items()):
                    v = mkt.value_close(cid, i)
                    if v: tot += sh*v - sh*v*cost; costs += sh*v*cost; orders += 1
                halts.append({"episode": episode, "halt_date": d, "liquidated_at": round(tot, 2)})
                curve[-1] = (d, tot); cash = tot; pos.clear(); ended = True
            else:
                pending_liq = True
    final = curve[-1][1]
    peak, dd = -1.0, 0.0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0: dd = min(dd, e/peak - 1.0)
    yrs = (datetime.strptime(end_d, "%Y-%m-%d") - datetime.strptime(start_d, "%Y-%m-%d")).days/365.25
    return {"final": round(final, 2), "ret_pct": round((final/POT-1)*100, 2),
            "cagr_pct": round(((final/POT)**(1/yrs)-1)*100, 2) if final > 0 else None,
            "max_dd_pct": round(dd*100, 2), "orders": orders, "costs": round(costs, 2),
            "avg_eligible": round(elig_sum/elig_n, 2) if elig_n else None,
            "avg_invested_pct": round(100*inv_sum/elig_n, 1) if elig_n else None,
            "events": events, "halts": halts, "ended_by_second_halt": ended,
            "curve": [[d, round(e, 4)] for d, e in curve], "picks_log": picks_log}

def btc_hold(mkt, start_d, end_d, cost):
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    sh = (POT*(1-cost))/mkt.trade_open(1, i0)
    peak, dd, curve = -1.0, 0.0, []
    for i in range(i0, i1+1):
        v = sh*mkt.ff[1][i]; curve.append([cal[i], round(v, 4)])
        peak = max(peak, v)
        if peak > 0: dd = min(dd, v/peak-1.0)
    final = sh*mkt.ff[1][i1]*(1-cost)
    return {"final": round(final, 2), "ret_pct": round((final/POT-1)*100, 2),
            "max_dd_pct": round(dd*100, 2), "curve": curve}

def pct(vals, q):
    s = sorted(vals)
    if len(s) == 1: return s[0]
    p = q*(len(s)-1); lo, hi = int(math.floor(p)), int(math.ceil(p))
    return s[lo] if lo == hi else s[lo]*(1-(p-lo)) + s[hi]*(p-lo)

def main():
    t0 = time.time()
    reg = load_registry()
    weekly = load_weekly()
    mkt = Market(reg, weekly)
    print(f"registry coins={len(reg)} mapped={sum(1 for v in reg.values() if v['rows'])} "
          f"weekly snapshots={len(weekly)} cal {mkt.cal[0]}..{mkt.cal[-1]}", flush=True)
    out = {"family": "crypto-x-frog-pan", "label": "ADAPTED (coin cross-section of Da-Gurun-Warachka long leg)",
           "cost_headline": 0.006, "pot": POT, "runs": {}, "btc_hold": {}, "placebos": {}}
    for cost, tag in ((0.006, "c060"), (0.004, "c040"), (0.008, "c080")):
        out["btc_hold"][tag] = {w: btc_hold(mkt, sd, ed, cost) for w, (sd, ed) in WINDOWS.items()}
    for ruleset in ("nofloor", "v9"):
        for w, (sd, ed) in WINDOWS.items():
            r = simulate(mkt, sd, ed, ruleset, 0.006)
            key = f"monthly|{ruleset}|{w}"
            out["runs"][key] = r
            print(f"{key}: ${r['final']} DD {r['max_dd_pct']}% orders {r['orders']} "
                  f"halts {len(r['halts'])} avg_elig {r['avg_eligible']} "
                  f"BTC ${out['btc_hold']['c060'][w]['final']} ({time.time()-t0:.0f}s)", flush=True)
    for cost, tag in ((0.004, "c040"), (0.008, "c080")):
        for w in ("full", "validation"):
            sd, ed = WINDOWS[w]
            r = simulate(mkt, sd, ed, "nofloor", cost)
            key = f"monthly|nofloor|{w}|{tag}"
            out["runs"][key] = r
            print(f"{key}: ${r['final']} BTC ${out['btc_hold'][tag][w]['final']} ({time.time()-t0:.0f}s)", flush=True)
    for w in ("full", "validation"):
        sd, ed = WINDOWS[w]
        finals, rows = [], []
        for seed in PLACEBO_SEEDS:
            r = simulate(mkt, sd, ed, "nofloor", 0.006, mode="placebo", seed=seed)
            finals.append(r["final"])
            rows.append({"seed": seed, "final": r["final"], "max_dd_pct": r["max_dd_pct"],
                         "orders": r["orders"], "n_events": len(r["events"])})
        rk = out["runs"][f"monthly|nofloor|{w}"]["final"]
        nb = sum(1 for v in finals if rk > v)
        out["placebos"][f"monthly|{w}"] = {
            "n_seeds": 20, "median_final": round(pct(finals, .5), 2),
            "p25_final": round(pct(finals, .25), 2), "p75_final": round(pct(finals, .75), 2),
            "best_final": round(max(finals), 2), "worst_final": round(min(finals), 2),
            "ranked_final": rk, "ranked_beats_n_of_20": nb,
            "ranked_percentile": round(100*nb/20, 1), "rows": rows}
        print(f"placebo monthly|{w}: median ${pct(finals,.5):.2f} ranked ${rk} beats {nb}/20 "
              f"({time.time()-t0:.0f}s)", flush=True)
    out["registry_summary"] = {str(cid): {"symbol": v["symbol"], "source": v["source"],
        "bars": len(v["rows"]), "first": v["rows"][0]["d"] if v["rows"] else None,
        "last": v["rows"][-1]["d"] if v["rows"] else None} for cid, v in reg.items()}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"saved results.json in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
