#!/usr/bin/env python3
"""
RESIDUAL MOMENTUM — COIN CROSS-SECTION (v12 Crypto Wing 1, CONSTRUCTED transplant).

Frozen construction: see CONSTRUCTION-SPEC.md in this folder.
Blitz-Huij-Martens timing/score (36-mo regression, residual mean/SD over the
past 12 months skipping the most recent month, monthly, top decile long-only),
with the FF3 factor set replaced by the single coin market factor: BTC.

Reads v4 caches + v12 crypto-basket-pit weekly snapshots READ-ONLY.
Writes only inside this folder.
"""
import json, math, os, random, time, bisect
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
V4CACHE = os.path.join(V4, "crypto-basket-pit-data")
BASKET12 = os.path.join(HERE, "..", "crypto-basket-pit")
POT = 100.0
COST = 0.006  # 0.60%/side, midpoint of v4-measured retail range 0.40-0.80%
STALE_ZERO_DAYS = 7
WINDOWS = {"full": ("2017-01-01", "2026-11-20"),
           "design": ("2017-01-01", "2022-12-31"),
           "validation": ("2023-01-01", "2026-11-20")}
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}

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
    with open(os.path.join(BASKET12, "data", "hype.json")) as f: rows = json.load(f)
    reg[32196] = {"symbol": "HYPE", "slug": "hyperliquid", "source": "hyperliquid:HYPE",
                  "reason": None, "rows": rows}
    return reg

def load_weekly():
    with open(os.path.join(BASKET12, "data", "weekly_snapshots.json")) as f:
        return json.load(f)

def midx(d):  # month index from 'YYYY-MM-DD'
    return int(d[:4]) * 12 + (int(d[5:7]) - 1)

class Market:
    def __init__(self, reg, weekly):
        self.reg = reg
        btc = reg[1]["rows"]
        self.cal = [r["d"] for r in btc]
        self.bars, self.ff, self.lb = {}, {}, {}
        for cid, info in reg.items():
            if info["source"] == "excluded" or not info["rows"]: continue
            bars = {r["d"]: (r["o"], r["c"]) for r in info["rows"]}
            self.bars[cid] = bars
            ff, lb, last, li = [], [], None, -1
            for i, d in enumerate(self.cal):
                if d in bars: last, li = bars[d][1], i
                ff.append(last); lb.append(li)
            self.ff[cid], self.lb[cid] = ff, lb
        # monthly closes: cid -> {month_idx: close at last bar in month}
        self.mclose = {}
        for cid, bars in self.bars.items():
            mc = {}
            for d in sorted(bars): mc[midx(d)] = bars[d][1]
            self.mclose[cid] = mc
        # monthly returns: cid -> {month_idx: return that month}
        self.mret = {}
        for cid, mc in self.mclose.items():
            mr = {}
            for m, c in mc.items():
                if (m - 1) in mc and mc[m - 1] > 0 and c > 0:
                    mr[m] = c / mc[m - 1] - 1.0
            self.mret[cid] = mr
        # formation date (last BTC calendar day) per month idx
        self.month_end_idx = {}
        for i, d in enumerate(self.cal): self.month_end_idx[midx(d)] = i
        self.snap_keys = sorted(weekly.keys())
        self.snap_top = {k: [c["cmc_id"] for c in weekly[k]["top20"]] for k in self.snap_keys}
        self._scores = {}
    def universe_on(self, date_str):
        k = bisect.bisect_right(self.snap_keys, date_str) - 1
        return self.snap_top[self.snap_keys[k]] if k >= 0 else []
    def trade_open(self, cid, i):
        d = self.cal[i]
        if d in self.bars[cid]: return self.bars[cid][d][0]
        if i > 0 and self.cal[i-1] in self.bars[cid]: return self.bars[cid][self.cal[i-1]][1]
        return None
    def value_close(self, cid, i):
        lb = self.lb[cid][i]
        if lb < 0: return None
        return self.ff[cid][i] if i - lb <= STALE_ZERO_DAYS else 0.0
    def scores(self, M):
        """Residual-momentum scores at formation month-end M (month idx)."""
        if M in self._scores: return self._scores[M]
        fi = self.month_end_idx.get(M)
        out = {}
        if fi is not None:
            fdate = self.cal[fi]
            btc_r = self.mret.get(1, {})
            months = list(range(M - 35, M + 1))
            if all(m in btc_r for m in months):
                xs = [btc_r[m] for m in months]
                for cid in self.universe_on(fdate):
                    if cid == 1 or cid not in self.mret: continue
                    if self.lb[cid][fi] < 0 or fi - self.lb[cid][fi] > STALE_ZERO_DAYS: continue
                    cr = self.mret[cid]
                    if not all(m in cr for m in months): continue
                    ys = [cr[m] for m in months]
                    n = 36
                    mx = sum(xs) / n; my = sum(ys) / n
                    sxx = sum((x - mx) ** 2 for x in xs)
                    if sxx <= 0: continue
                    beta = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
                    alpha = my - beta * mx
                    resid = [y - (alpha + beta * x) for x, y in zip(xs, ys)]
                    win = resid[23:35]  # months M-12..M-1: past 12, skip most recent
                    mu = sum(win) / len(win)
                    var = sum((r - mu) ** 2 for r in win) / (len(win) - 1)
                    sd = math.sqrt(var)
                    if sd <= 0: continue
                    out[cid] = mu / sd
        self._scores[M] = out
        return out

def simulate(mkt, start_d, end_d, ruleset, mode="ranked", seed=42):
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    cash, pos, entry = float(POT), {}, {}
    orders, costs = 0, 0.0
    curve, events, halts, picks_log = [], [], [], []
    episode, floor_abs = 1, 85.0
    pending_liq, sit_until, ended = False, None, False
    first_rebalance = None

    def equity_at(i):
        return cash + sum(sh * (mkt.value_close(cid, i) or 0.0) for cid, sh in pos.items())

    for i in range(i0, i1 + 1):
        d = cal[i]
        for cid in list(pos):
            lb = mkt.lb[cid][i]
            if lb >= 0 and i - lb == STALE_ZERO_DAYS + 1:
                events.append({"type": "write_off_zero", "coin": mkt.reg[cid]["symbol"],
                               "date": d, "last_bar_date": cal[lb]})
        if pending_liq:
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    del pos[cid]; entry.pop(cid, None); continue
                val = pos[cid] * px; fee = val * COST; cash += val - fee
                costs += fee; orders += 1
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
                for k in range(i + 1, i1 + 1): curve.append((cal[k], cash))
                break
            continue
        sitting = sit_until is not None and d < sit_until
        dt = datetime.strptime(d, "%Y-%m-%d")
        if not sitting and dt.day == 1:
            if sit_until is not None and d >= sit_until:
                floor_abs = 0.85 * cash; sit_until = None
                halts[-1]["restart_date"] = d; halts[-1]["restart_balance"] = round(cash, 2)
            M = midx(d) - 1  # latest completed month-end
            sc = mkt.scores(M)
            if mode == "ranked":
                ranked = sorted(sc.items(), key=lambda x: -x[1])
                n_pick = max(1, len(ranked) // 10) if ranked else 0
                picks = [c for c, _ in ranked[:n_pick]]
            else:
                names = sorted(sc)
                n_pick = max(1, len(names) // 10) if names else 0
                picks = rng.sample(names, min(n_pick, len(names))) if names else []
            if picks and first_rebalance is None: first_rebalance = d
            if mode == "ranked":
                picks_log.append({"date": d, "formation_month": f"{M//12}-{M%12+1:02d}",
                                  "n_eligible": len(sc), "n_pick": len(picks),
                                  "picks": [mkt.reg[c]["symbol"] for c in picks],
                                  "scores": {mkt.reg[c]["symbol"]: round(sc[c], 4) for c in picks}})
            eq = equity_at(i)
            w = 1.0 / len(picks) if picks else 0.0
            target = {cid: w * eq for cid in picks}
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    lb = mkt.lb[cid][i]
                    if lb >= 0 and i - lb > STALE_ZERO_DAYS:
                        del pos[cid]; entry.pop(cid, None)
                    continue
                cur = pos[cid] * px; want = target.get(cid, 0.0)
                if cur > want + 0.01:
                    sv = cur - want; fee = sv * COST; cash += sv - fee
                    costs += fee; orders += 1; pos[cid] -= sv / px
                    if want <= 0.0 or pos[cid] * px < 0.01:
                        del pos[cid]; entry.pop(cid, None)
            for cid in picks:
                px = mkt.trade_open(cid, i)
                if px is None: continue
                deficit = target[cid] - pos.get(cid, 0.0) * px
                if deficit <= 0.01: continue
                bv = min(deficit, cash / (1.0 + COST))
                if bv <= 0.01: continue
                fee = bv * COST; cash -= bv + fee; costs += fee; orders += 1
                sh = bv / px; old = pos.get(cid, 0.0)
                entry[cid] = (entry[cid] * old + px * sh) / (old + sh) if old > 0 and cid in entry else px
                pos[cid] = old + sh
        eq_close = equity_at(i)
        curve.append((d, eq_close))
        if ruleset == "v9" and not sitting and sit_until is None and eq_close <= floor_abs:
            if i == i1:
                tot = cash
                for cid, sh in list(pos.items()):
                    v = mkt.value_close(cid, i)
                    if v: tot += sh * v - sh * v * COST; costs += sh * v * COST; orders += 1
                halts.append({"episode": episode, "halt_date": d, "liquidated_at": round(tot, 2)})
                curve[-1] = (d, tot); cash = tot; pos.clear(); ended = True
            else:
                pending_liq = True
    final = curve[-1][1]
    peak, dd = -1.0, 0.0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0: dd = min(dd, e / peak - 1.0)
    return {"final": round(final, 2), "ret_pct": round((final / POT - 1) * 100, 2),
            "max_dd_pct": round(dd * 100, 2), "orders": orders, "costs": round(costs, 2),
            "events": events, "halts": halts, "ended_by_second_halt": ended,
            "first_rebalance": first_rebalance,
            "curve": [[d, round(e, 4)] for d, e in curve], "picks_log": picks_log}

def btc_hold(mkt, start_d, end_d):
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    sh = (POT * (1 - COST)) / mkt.trade_open(1, i0)
    peak, dd, curve = -1.0, 0.0, []
    for i in range(i0, i1 + 1):
        v = sh * mkt.ff[1][i]; curve.append([cal[i], round(v, 4)])
        peak = max(peak, v)
        if peak > 0: dd = min(dd, v / peak - 1.0)
    final = sh * mkt.ff[1][i1] * (1 - COST)
    return {"final": round(final, 2), "ret_pct": round((final / POT - 1) * 100, 2),
            "max_dd_pct": round(dd * 100, 2), "curve": curve}

def period_stats(curve):
    """Monthly-period distribution from a daily equity curve (REPORTING STANDARD)."""
    month_end = {}
    for d, e in curve: month_end[d[:7]] = e
    months = sorted(month_end)
    vals = [month_end[m] for m in months]
    rets = []
    for a, b in zip(vals, vals[1:]):
        if a > 0: rets.append(b / a - 1.0)
    if not rets: return None
    s = sorted(rets); n = len(rets)
    med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    longest_loss, run = 0, 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        longest_loss = max(longest_loss, run)
    peak, since_high, longest_gap = -1.0, 0, 0
    for v in vals:
        if v >= peak: peak, since_high = v, 0
        else:
            since_high += 1; longest_gap = max(longest_gap, since_high)
    return {"periods": n, "pct_profitable": round(100 * sum(1 for r in rets if r > 0) / n, 1),
            "median_period_pct": round(med * 100, 2),
            "best_period_pct": round(max(rets) * 100, 2),
            "worst_period_pct": round(min(rets) * 100, 2),
            "longest_losing_run_periods": longest_loss,
            "longest_stretch_between_new_highs_periods": longest_gap,
            "average_period_pct_SECONDARY": round(100 * sum(rets) / n, 2)}

def pct(vals, q):
    s = sorted(vals)
    if len(s) == 1: return s[0]
    p = q * (len(s) - 1); lo, hi = int(math.floor(p)), int(math.ceil(p))
    return s[lo] if lo == hi else s[lo] * (1 - (p - lo)) + s[hi] * (p - lo)

def main():
    t0 = time.time()
    reg = load_registry(); weekly = load_weekly(); mkt = Market(reg, weekly)
    print(f"registry coins={len(reg)} mapped={sum(1 for v in reg.values() if v['rows'])} "
          f"weekly snapshots={len(weekly)} cal {mkt.cal[0]}..{mkt.cal[-1]}", flush=True)
    out = {"family": "residual-momentum (coin cross-section)",
           "label": "CONSTRUCTED transplant of Blitz-Huij-Martens (BTC single-factor residualization)",
           "cost_per_side": COST, "pot": POT, "runs": {}, "btc_hold": {}, "placebos": {},
           "period_stats": {}}
    for w, (sd, ed) in WINDOWS.items():
        out["btc_hold"][w] = btc_hold(mkt, sd, ed)
    for ruleset in ("nofloor", "v9"):
        for w, (sd, ed) in WINDOWS.items():
            r = simulate(mkt, sd, ed, ruleset)
            key = f"monthly|{ruleset}|{w}"
            out["runs"][key] = r
            out["period_stats"][key] = period_stats(r["curve"])
            print(f"{key}: ${r['final']} DD {r['max_dd_pct']}% orders {r['orders']} "
                  f"halts {len(r['halts'])} first_reb {r['first_rebalance']} "
                  f"BTC ${out['btc_hold'][w]['final']} ({time.time()-t0:.0f}s)", flush=True)
    out["period_stats"]["btc_hold"] = {w: period_stats(out["btc_hold"][w]["curve"]) for w in WINDOWS}
    for w in ("full", "validation"):
        sd, ed = WINDOWS[w]
        finals, rows = [], []
        for seed in range(1, 21):
            r = simulate(mkt, sd, ed, "nofloor", mode="placebo", seed=seed)
            finals.append(r["final"])
            rows.append({"seed": seed, "final": r["final"], "max_dd_pct": r["max_dd_pct"],
                         "orders": r["orders"]})
        rk = out["runs"][f"monthly|nofloor|{w}"]["final"]
        nb = sum(1 for v in finals if rk > v)
        out["placebos"][w] = {"n_seeds": 20, "median_final": round(pct(finals, .5), 2),
                              "best_final": round(max(finals), 2), "worst_final": round(min(finals), 2),
                              "ranked_final": rk, "ranked_beats_n_of_20": nb, "rows": rows}
        print(f"placebo {w}: median ${pct(finals,.5):.2f} ranked ${rk} beats {nb}/20 "
              f"({time.time()-t0:.0f}s)", flush=True)
    picks_count = {}
    for p in out["runs"]["monthly|nofloor|full"]["picks_log"]:
        for s in p["picks"]: picks_count[s] = picks_count.get(s, 0) + 1
    out["picks_count_full_nofloor"] = picks_count
    elig_counts = [p["n_eligible"] for p in out["runs"]["monthly|nofloor|full"]["picks_log"]]
    out["eligible_summary_full"] = {"rebalances": len(elig_counts),
                                    "min_eligible": min(elig_counts) if elig_counts else None,
                                    "max_eligible": max(elig_counts) if elig_counts else None,
                                    "median_eligible": pct(elig_counts, .5) if elig_counts else None}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"saved results.json in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
