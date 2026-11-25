#!/usr/bin/env python3
"""
REVERSALS (short-term + long-term) as COIN CROSS-SECTIONS — v12 Crypto Wing 1.
Implements CONSTRUCTION-SPEC.md exactly as frozen. Reads v4 caches and the
v12 crypto-basket-pit weekly snapshots READ-ONLY. Writes only here.
Chassis adapted from the v12 crypto-basket-pit / crypto-x-low-volatility
plumbing (same Market, v9 floor machinery, dead-coin zero rule).
"""
import bisect, json, math, os, random, statistics, time
from datetime import datetime, timedelta
import requests  # noqa: F401  (kept for chassis parity; no network used)

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
V4CACHE = os.path.join(V4, "crypto-basket-pit-data")
PIT = os.path.join(HERE, "..", "crypto-basket-pit")
POT = 100.0
COST_HEAD = 0.006       # 0.60%/side — midpoint of documented 0.40-0.80% range
GRACE_DAYS = 30
TOP_N = 5
WINDOWS = {"full": ("2017-01-01", "2026-11-20"),
           "design": ("2017-01-01", "2022-12-31"),
           "validation": ("2023-01-01", "2026-11-20")}
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}
# line configs: formation days, start-bar tolerance, min bars in window
LINES = {"st": {"form_days": 30,   "start_tol": 7,  "min_bars": 0},
         "lt": {"form_days": 1095, "start_tol": 14, "min_bars": 900}}

def fetch_hype():
    with open(os.path.join(PIT, "data", "hype.json")) as f: return json.load(f)

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
    reg[32196] = {"symbol": "HYPE", "slug": "hyperliquid", "source": "hyperliquid:HYPE",
                  "reason": None, "rows": fetch_hype()}
    return reg

def load_weekly():
    with open(os.path.join(PIT, "data", "weekly_snapshots.json")) as f:
        return json.load(f)

class Market:
    def __init__(self, reg, weekly):
        self.reg = reg
        btc = reg[1]["rows"]
        self.cal = [r["d"] for r in btc]
        self.bars, self.ff, self.lb = {}, {}, {}
        self.bdates = {}
        for cid, info in reg.items():
            if info["source"] == "excluded" or not info["rows"]: continue
            bars = {r["d"]: (r["o"], r["c"]) for r in info["rows"]}
            self.bars[cid] = bars
            self.bdates[cid] = [r["d"] for r in info["rows"]]
            ff, lb, last, li = [], [], None, -1
            for i, d in enumerate(self.cal):
                if d in bars: last, li = bars[d][1], i
                ff.append(last); lb.append(li)
            self.ff[cid], self.lb[cid] = ff, lb
        self.snap_keys = sorted(weekly.keys())
        self.snap_top = {k: [c["cmc_id"] for c in weekly[k]["top20"]] for k in self.snap_keys}
        self._form = {}
    def universe(self, d):
        k = bisect.bisect_right(self.snap_keys, d) - 1
        return self.snap_top[self.snap_keys[k]] if k >= 0 else []
    def trade_open(self, cid, i):
        d = self.cal[i]
        if cid in self.bars and d in self.bars[cid]: return self.bars[cid][d][0]
        if i > 0 and cid in self.bars and self.cal[i-1] in self.bars[cid]:
            return self.bars[cid][self.cal[i-1]][1]
        return None
    def value_close(self, cid, i):
        lb = self.lb[cid][i]
        if lb < 0: return None
        return self.ff[cid][i] if i - lb <= GRACE_DAYS else 0.0
    def form_return(self, cid, j, cfg):
        """Cumulative close return over trailing cfg['form_days'] calendar days
        ending at signal index j. Eligibility per CONSTRUCTION-SPEC."""
        key = (cid, j, cfg["form_days"])
        if key in self._form: return self._form[key]
        out = None
        if cid in self.bars and j >= 0:
            lb = self.lb[cid]
            if lb[j] >= 0 and j - lb[j] <= 7:
                k = j - cfg["form_days"]
                if k >= 0 and lb[k] >= 0 and k - lb[k] <= cfg["start_tol"]:
                    a, b = self.ff[cid][lb[k]], self.ff[cid][lb[j]]
                    if a and b and a > 0 and b > 0:
                        if cfg["min_bars"]:
                            dates = self.bdates[cid]
                            lo = bisect.bisect_left(dates, self.cal[k])
                            hi = bisect.bisect_right(dates, self.cal[j])
                            if hi - lo < cfg["min_bars"]:
                                self._form[key] = None; return None
                        out = b / a - 1.0
        self._form[key] = out
        return out

def is_rebalance(d, first):
    if first: return True
    return datetime.strptime(d, "%Y-%m-%d").day == 1

def simulate(mkt, start_d, end_d, ruleset, cfg, cost, mode="ranked", seed=42):
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    cash, pos, entry = float(POT), {}, {}
    wo = {}
    orders, costs, traded = 0, 0.0, 0.0
    curve, events, halts, picks_log = [], [], [], []
    n_reb, elig_sum = 0, 0
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
            if lb >= 0 and i - lb == GRACE_DAYS + 1 and not wo.get(cid):
                events.append({"type": "write_off", "coin": mkt.reg[cid]["symbol"],
                               "cmc_id": cid, "date": d, "last_bar_date": cal[lb],
                               "last_px": mkt.ff[cid][lb],
                               "written_off_value": round(pos[cid]*mkt.ff[cid][lb], 2)})
                wo[cid] = True
            if lb >= 0 and i - lb <= GRACE_DAYS and wo.get(cid): wo[cid] = False
        if pending_liq:
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    note_exit(cid, 0.0, d); del pos[cid]; entry.pop(cid, None); continue
                val = pos[cid]*px; fee = val*cost; cash += val - fee
                costs += fee; orders += 1; traded += val; note_exit(cid, px, d)
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
            elig = [(cid, mkt.form_return(cid, j, cfg)) for cid in universe]
            elig = [(c, r) for c, r in elig if r is not None]
            n_reb += 1; elig_sum += len(elig)
            if mode == "ranked":
                elig.sort(key=lambda x: x[1]); chosen = [c for c, _ in elig[:TOP_N]]
            else:
                names = sorted(c for c, _ in elig)
                chosen = rng.sample(names, min(TOP_N, len(names))) if names else []
            if mode == "ranked":
                picks_log.append({"date": d, "n_eligible": len(elig),
                                  "picks": [{"coin": mkt.reg[c]["symbol"],
                                             "form_ret_pct": round(dict(elig)[c]*100, 2)} for c in chosen]})
            eq = equity_at(i)
            target = {c: 0.20 * eq for c in chosen}
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    lb = mkt.lb[cid][i]
                    if lb >= 0 and i - lb > GRACE_DAYS:
                        note_exit(cid, 0.0, d); del pos[cid]; entry.pop(cid, None)
                    continue
                cur = pos[cid]*px; want = target.get(cid, 0.0)
                if want <= 0.0 and cur <= 0.01:
                    note_exit(cid, px, d); del pos[cid]; entry.pop(cid, None); continue
                if cur > want + 0.01:
                    sv = cur - want; fee = sv*cost; cash += sv - fee
                    costs += fee; orders += 1; traded += sv; pos[cid] -= sv/px
                    if want <= 0.0 or pos[cid]*px < 0.01:
                        note_exit(cid, px, d); del pos[cid]; entry.pop(cid, None)
            for cid in chosen:
                px = mkt.trade_open(cid, i)
                if px is None: continue
                deficit = target[cid] - pos.get(cid, 0.0)*px
                if deficit <= 0.01: continue
                bv = min(deficit, cash/(1.0+cost))
                if bv <= 0.01: continue
                fee = bv*cost; cash -= bv + fee; costs += fee; orders += 1; traded += bv
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
                    if v: tot += sh*v - sh*v*cost; costs += sh*v*cost; orders += 1; traded += sh*v
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
            "traded_notional": round(traded, 2),
            "turnover_x_pot": round(traded/POT, 2),
            "avg_eligible": round(elig_sum/n_reb, 2) if n_reb else None,
            "n_rebalances": n_reb,
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

def period_stats(curve):
    """Monthly period distribution from a daily equity curve (native tempo)."""
    pts = {}
    for d, e in curve: pts[d] = e
    dates = [d for d, _ in curve]
    bounds = [dates[0]]
    for d in dates[1:]:
        dt = datetime.strptime(d, "%Y-%m-%d")
        if dt.day <= 3 and d[:7] != bounds[-1][:7]:
            bounds.append(d)
    if bounds[-1] != dates[-1]: bounds.append(dates[-1])
    bounds = sorted(set(bounds))
    rets = []
    for a, b in zip(bounds, bounds[1:]):
        va, vb = pts[a], pts[b]
        if va > 0: rets.append(vb/va - 1.0)
    if not rets: return None
    n = len(rets); wins = sum(1 for r in rets if r > 0)
    run = longest = 0
    for r in rets:
        run = run + 1 if r <= 0 else 0
        longest = max(longest, run)
    eqs = [pts[b] for b in bounds]
    peak, since, max_s = -1.0, 0, 0
    for e in eqs:
        if e > peak: peak, since = e, 0
        else:
            since += 1; max_s = max(max_s, since)
    return {"periods": n, "pct_profitable": round(100*wins/n, 1),
            "median_pct": round(statistics.median(rets)*100, 2),
            "best_pct": round(max(rets)*100, 2), "worst_pct": round(min(rets)*100, 2),
            "longest_losing_run_periods": longest,
            "longest_stretch_between_new_highs_periods": max_s,
            "average_pct_secondary": round(100*sum(rets)/n, 2),
            "period_returns_pct": [round(r*100, 2) for r in rets]}

def pct(vals, q):
    s = sorted(vals)
    if len(s) == 1: return s[0]
    p = q*(len(s)-1); lo, hi = int(math.floor(p)), int(math.ceil(p))
    return s[lo] if lo == hi else s[lo]*(1-(p-lo)) + s[hi]*(p-lo)

def main():
    t0 = time.time()
    reg = load_registry(); weekly = load_weekly()
    mkt = Market(reg, weekly)
    print(f"registry coins={len(reg)} mapped={sum(1 for v in reg.values() if v['rows'])} "
          f"snapshots={len(weekly)} cal {mkt.cal[0]}..{mkt.cal[-1]}", flush=True)
    out = {"family": "short-term-reversal + long-term-reversal (coin cross-sections)",
           "label": "CONSTRUCTED coin adaptations of Jegadeesh (1990) monthly ST reversal and De Bondt & Thaler (1985) LT reversal, long-only",
           "cost_headline_per_side": COST_HEAD, "pot": POT,
           "runs": {}, "btc_hold": {}, "placebos": {}, "period_stats": {}}
    for cost, tag in ((0.006, "c060"), (0.004, "c040"), (0.008, "c080")):
        out["btc_hold"][tag] = {w: btc_hold(mkt, sd, ed, cost) for w, (sd, ed) in WINDOWS.items()}
    for line, cfg in LINES.items():
        for ruleset in ("nofloor", "v9"):
            for w, (sd, ed) in WINDOWS.items():
                r = simulate(mkt, sd, ed, ruleset, cfg, COST_HEAD)
                key = f"{line}|monthly|{ruleset}|{w}"
                out["runs"][key] = r
                out["period_stats"][key] = period_stats(r["curve"])
                print(f"{key}: ${r['final']} DD {r['max_dd_pct']}% orders {r['orders']} "
                      f"costs ${r['costs']} traded ${r['traded_notional']} halts {len(r['halts'])} "
                      f"BTC ${out['btc_hold']['c060'][w]['final']} ({time.time()-t0:.0f}s)", flush=True)
        for cost, tag in ((0.004, "c040"), (0.008, "c080")):
            for w in ("full", "validation"):
                sd, ed = WINDOWS[w]
                r = simulate(mkt, sd, ed, "nofloor", cfg, cost)
                key = f"{line}|monthly|nofloor|{w}|{tag}"
                out["runs"][key] = r
                out["period_stats"][key] = period_stats(r["curve"])
                print(f"{key}: ${r['final']} DD {r['max_dd_pct']}% costs ${r['costs']} "
                      f"BTC ${out['btc_hold'][tag][w]['final']} ({time.time()-t0:.0f}s)", flush=True)
    out["period_stats"]["btc_hold_c060"] = {w: period_stats(out["btc_hold"]["c060"][w]["curve"]) for w in WINDOWS}
    for line, cfg in LINES.items():
        for w in ("full", "validation"):
            sd, ed = WINDOWS[w]
            finals, rows = [], []
            for seed in range(1, 21):
                r = simulate(mkt, sd, ed, "nofloor", cfg, COST_HEAD, mode="placebo", seed=seed)
                finals.append(r["final"])
                rows.append({"seed": seed, "final": r["final"], "max_dd_pct": r["max_dd_pct"],
                             "orders": r["orders"], "costs": r["costs"]})
            rk = out["runs"][f"{line}|monthly|nofloor|{w}"]["final"]
            nb = sum(1 for v in finals if rk > v)
            out["placebos"][f"{line}|monthly|{w}"] = {
                "n_seeds": 20, "median_final": round(pct(finals, .5), 2),
                "p25_final": round(pct(finals, .25), 2), "p75_final": round(pct(finals, .75), 2),
                "best_final": round(max(finals), 2), "worst_final": round(min(finals), 2),
                "ranked_final": rk, "ranked_beats_n_of_20": nb, "rows": rows}
            print(f"placebo {line}|{w}: median ${pct(finals,.5):.2f} ranked ${rk} beats {nb}/20 "
                  f"({time.time()-t0:.0f}s)", flush=True)
    # confirmation folds for any line whose FULL no-floor beat BTC FULL
    for line, cfg in LINES.items():
        if out["runs"][f"{line}|monthly|nofloor|full"]["final"] > out["btc_hold"]["c060"]["full"]["final"]:
            folds = {}
            for y in range(2018, 2027):
                sd, ed = f"{y}-01-01", min(f"{y}-12-31", "2026-11-20")
                r = simulate(mkt, sd, ed, "nofloor", cfg, COST_HEAD); b = btc_hold(mkt, sd, ed, COST_HEAD)
                folds[str(y)] = {"strategy_final": r["final"], "btc_final": b["final"]}
            out.setdefault("confirmation_year_folds", {})[line] = folds
            print(f"confirmation folds {line}:", folds, flush=True)
    out["registry_summary"] = {str(cid): {"symbol": v["symbol"], "source": v["source"],
        "bars": len(v["rows"]), "first": v["rows"][0]["d"] if v["rows"] else None,
        "last": v["rows"][-1]["d"] if v["rows"] else None} for cid, v in reg.items()}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"saved results.json in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
