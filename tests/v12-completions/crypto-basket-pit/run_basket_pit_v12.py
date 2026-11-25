#!/usr/bin/env python3
"""
CRYPTO-BASKET-PIT — V12 COMPLETION RUNS (program's own CONSTRUCTED form).

Frozen form = v4 crypto-basket-pit.py, verbatim signals (see
CONSTRUCTION-SPEC.md). v12 adds, all frozen before runs:
  - weekly CMC Sunday snapshots (same source as v4, native cadence),
  - HYPE price series from Hyperliquid's public API (hunt addition),
  - cadence grid: daily / weekly / monthly / quarterly / semiannual / annual,
  - both rule sets: native no-floor, and v9 protections (episode floor,
    90-day cash sit, one restart, episode-2 floor, second halt ends),
  - headline cost 0.60%/side (midpoint of documented US-retail 0.40-0.80%),
    plus 0.40%/side bridge cells at monthly cadence to reproduce v4/v9.

Reads v4 caches READ-ONLY. Writes only inside this folder.
"""
import json, math, os, random, time
from datetime import datetime, timedelta, timezone
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
V4CACHE = os.path.join(V4, "crypto-basket-pit-data")
POT = 100.0
SMA_N, MOM_FAR, MOM_NEAR, GRACE_DAYS = 200, 365, 30, 30
WINDOWS = {"full": ("2017-01-01", "2026-11-20"),
           "design": ("2017-01-01", "2022-12-31"),
           "validation": ("2023-01-01", "2026-11-20")}
CADENCES = ["daily", "weekly", "monthly", "quarterly", "semiannual", "annual"]
PLACEBO_CADENCES = ["daily", "weekly", "monthly", "quarterly"]
PLACEBO_SEEDS = list(range(1, 21))
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}

# ---------------------------------------------------------------- data ----
def fetch_hype():
    path = os.path.join(HERE, "data", "hype.json")
    if os.path.exists(path):
        with open(path) as f: return json.load(f)
    rows = {}
    start = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    end = int(datetime(2026, 11, 22, tzinfo=timezone.utc).timestamp() * 1000)
    step = 400 * 86400 * 1000
    t = start
    while t < end:
        payload = {"type": "candleSnapshot", "req": {"coin": "HYPE", "interval": "1d",
                   "startTime": t, "endTime": min(t + step, end)}}
        r = requests.post("https://api.hyperliquid.xyz/info", json=payload, timeout=30)
        for x in r.json():
            d = datetime.fromtimestamp(x["t"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
            o, c = float(x["o"]), float(x["c"])
            if c > 0: rows[d] = {"d": d, "o": o, "c": c}
        t += step; time.sleep(0.3)
    out = [rows[d] for d in sorted(rows)]
    with open(path, "w") as f: json.dump(out, f)
    return out

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
    rows = fetch_hype()
    reg[32196] = {"symbol": "HYPE", "slug": "hyperliquid", "source": "hyperliquid:HYPE",
                  "reason": None, "rows": rows}
    return reg

def load_weekly():
    with open(os.path.join(HERE, "data", "weekly_snapshots.json")) as f:
        return json.load(f)

# ------------------------------------------------------------- market -----
class Market:
    def __init__(self, reg, weekly):
        self.reg = reg
        btc = reg[1]["rows"]
        self.cal = [r["d"] for r in btc]
        self.ci = {d: i for i, d in enumerate(self.cal)}
        self.bars, self.ff, self.lb, self.bc = {}, {}, {}, {}
        self.psum, self.pcnt = {}, {}
        for cid, info in reg.items():
            if info["source"] == "excluded" or not info["rows"]: continue
            bars = {r["d"]: (r["o"], r["c"]) for r in info["rows"]}
            self.bars[cid] = bars
            ff, lb, bc, ps, pc = [], [], [], [0.0], [0]
            last, li, n = None, -1, 0
            for i, d in enumerate(self.cal):
                if d in bars: last, li, n = bars[d][1], i, n + 1
                ff.append(last); lb.append(li); bc.append(n)
                ps.append(ps[-1] + (last or 0.0)); pc.append(pc[-1] + (1 if last is not None else 0))
            self.ff[cid], self.lb[cid], self.bc[cid] = ff, lb, bc
            self.psum[cid], self.pcnt[cid] = ps, pc
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
        if i > 0 and self.cal[i-1] in self.bars[cid]: return self.bars[cid][self.cal[i-1]][1]
        return None
    def value_close(self, cid, i):
        lb = self.lb[cid][i]
        if lb < 0: return None
        return self.ff[cid][i] if i - lb <= GRACE_DAYS else 0.0
    def sma(self, cid, i, n):
        if self.pcnt[cid][i+1] - self.pcnt[cid][i-n+1] < n: return None
        return (self.psum[cid][i+1] - self.psum[cid][i-n+1]) / n
    def eligible(self, cid, j):
        key = (cid, j)
        if key in self._elig: return self._elig[key]
        out = self._eligible(cid, j); self._elig[key] = out; return out
    def _eligible(self, cid, j):
        if cid not in self.bars or j < 0: return None
        lb = self.lb[cid]
        if lb[j] < 0 or j - lb[j] > 7: return None
        if self.bc[cid][j] < 300: return None
        c = self.ff[cid][j]
        if c is None: return None
        s = self.sma(cid, j, SMA_N)
        if s is None or c <= s: return None
        ai, bi = lb[j-MOM_FAR], lb[j-MOM_NEAR]
        if ai < 0 or bi < 0: return None
        if (j-MOM_FAR)-ai > 7 or (j-MOM_NEAR)-bi > 7: return None
        a, b = self.ff[cid][ai], self.ff[cid][bi]
        if a is None or b is None or a <= 0: return None
        return b/a - 1.0

def is_rebalance(cadence, d, first):
    if first: return True
    dt = datetime.strptime(d, "%Y-%m-%d")
    if cadence == "daily": return True
    if cadence == "weekly": return dt.isoweekday() == 1
    if cadence == "monthly": return dt.day == 1
    if cadence == "quarterly": return dt.day == 1 and dt.month in (1, 4, 7, 10)
    if cadence == "semiannual": return dt.day == 1 and dt.month in (1, 7)
    if cadence == "annual": return dt.day == 1 and dt.month == 1
    raise ValueError(cadence)

# ----------------------------------------------------------- simulate -----
def simulate(mkt, start_d, end_d, cadence, ruleset, cost, mode="ranked", seed=42):
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    cash, pos, entry = float(POT), {}, {}
    wo = {}
    orders, costs = 0, 0.0
    curve, events, halts = [], [], []
    picks_log, elig_sum, elig_n, inv_sum = [], 0, 0, 0.0
    # v9 state
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
        # death-rule write-off logging
        for cid in list(pos):
            lb = mkt.lb[cid][i]
            if lb >= 0 and i - lb == GRACE_DAYS + 1 and not wo.get(cid):
                events.append({"type": "write_off", "coin": mkt.reg[cid]["symbol"],
                               "cmc_id": cid, "date": d, "last_bar_date": cal[lb],
                               "last_px": mkt.ff[cid][lb],
                               "written_off_value": round(pos[cid]*mkt.ff[cid][lb], 2)})
                wo[cid] = True
            if lb >= 0 and i - lb <= GRACE_DAYS and wo.get(cid): wo[cid] = False
        # pending v9 liquidation at today's open
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
        # rebalance
        sitting = sit_until is not None and d < sit_until
        if not sitting and is_rebalance(cadence, d, i == i0):
            if sit_until is not None and d >= sit_until:
                floor_abs = 0.85 * cash; sit_until = None
                halts[-1]["restart_date"] = d; halts[-1]["restart_balance"] = round(cash, 2)
            universe = mkt.universe(d)
            j = i - 1
            elig = [(cid, mkt.eligible(cid, j)) for cid in universe]
            elig = [(c, m) for c, m in elig if m is not None]
            elig_sum += len(elig); elig_n += 1
            if mode == "ranked":
                elig.sort(key=lambda x: -x[1]); picks = [c for c, _ in elig[:5]]
            else:
                names = sorted(c for c, _ in elig)
                picks = rng.sample(names, min(5, len(names))) if names else []
            inv_sum += 0.20 * len(picks)
            if mode == "ranked" and cadence in ("monthly", "weekly"):
                picks_log.append({"date": d, "picks": [mkt.reg[c]["symbol"] for c in picks],
                                  "n_eligible": len(elig)})
            eq = equity_at(i)
            target = {cid: 0.20*eq for cid in picks}
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
    out = {"family": "crypto-basket-pit", "label": "CONSTRUCTED (program's own form)",
           "cost_headline": 0.006, "pot": POT, "runs": {}, "btc_hold": {}, "placebos": {}}
    # BTC bars per cost
    for cost, tag in ((0.006, "c060"), (0.004, "c040")):
        out["btc_hold"][tag] = {w: btc_hold(mkt, sd, ed, cost) for w, (sd, ed) in WINDOWS.items()}
    # ranked grid: both rule sets, headline cost
    for cadence in CADENCES:
        for ruleset in ("nofloor", "v9"):
            for w, (sd, ed) in WINDOWS.items():
                r = simulate(mkt, sd, ed, cadence, ruleset, 0.006)
                key = f"{cadence}|{ruleset}|{w}"
                out["runs"][key] = r
                print(f"{key}: ${r['final']} DD {r['max_dd_pct']}% orders {r['orders']} "
                      f"halts {len(r['halts'])} BTC ${out['btc_hold']['c060'][w]['final']} "
                      f"({time.time()-t0:.0f}s)", flush=True)
    # bridge cells: monthly, 0.40%/side
    for ruleset in ("nofloor", "v9"):
        for w, (sd, ed) in WINDOWS.items():
            r = simulate(mkt, sd, ed, "monthly", ruleset, 0.004)
            key = f"monthly|{ruleset}|{w}|bridge040"
            out["runs"][key] = r
            print(f"{key}: ${r['final']} halts {r['halts']} ({time.time()-t0:.0f}s)", flush=True)
    # placebos
    for cadence in PLACEBO_CADENCES:
        for w in ("full", "validation"):
            sd, ed = WINDOWS[w]
            finals, rows = [], []
            for seed in PLACEBO_SEEDS:
                r = simulate(mkt, sd, ed, cadence, "nofloor", 0.006, mode="placebo", seed=seed)
                finals.append(r["final"])
                rows.append({"seed": seed, "final": r["final"], "max_dd_pct": r["max_dd_pct"],
                             "orders": r["orders"], "n_events": len(r["events"])})
            rk = out["runs"][f"{cadence}|nofloor|{w}"]["final"]
            nb = sum(1 for v in finals if rk > v)
            out["placebos"][f"{cadence}|{w}"] = {
                "n_seeds": 20, "median_final": round(pct(finals, .5), 2),
                "p25_final": round(pct(finals, .25), 2), "p75_final": round(pct(finals, .75), 2),
                "best_final": round(max(finals), 2), "worst_final": round(min(finals), 2),
                "ranked_final": rk, "ranked_beats_n_of_20": nb,
                "ranked_percentile": round(100*nb/20, 1), "rows": rows}
            print(f"placebo {cadence}|{w}: median ${pct(finals,.5):.2f} ranked ${rk} beats {nb}/20 "
                  f"({time.time()-t0:.0f}s)", flush=True)
    # per-coin table (FULL window)
    sd, ed = WINDOWS["full"]
    picks_count = {}
    for p in out["runs"]["monthly|nofloor|full"]["picks_log"]:
        for s in p["picks"]: picks_count[s] = picks_count.get(s, 0) + 1
    weeks_in = {}
    for k, info in weekly.items():
        for c in info["top20"]: weeks_in[c["symbol"]] = weeks_in.get(c["symbol"], 0) + 1
    table = []
    for cid, info in sorted(reg.items()):
        rows = info["rows"]
        row = {"cmc_id": cid, "symbol": info["symbol"], "slug": info["slug"],
               "source": info["source"], "excluded_reason": info["reason"],
               "bars": len(rows), "first": rows[0]["d"] if rows else None,
               "last": rows[-1]["d"] if rows else None,
               "weeks_in_top20": weeks_in.get(info["symbol"], 0),
               "times_picked_monthly_full": picks_count.get(info["symbol"], 0),
               "standalone_hold_final": None, "standalone_hold_dd_pct": None}
        if rows and cid in mkt.bars:
            i0 = next(i for i, d in enumerate(mkt.cal) if d >= sd)
            px = mkt.trade_open(cid, i0)
            if px is None or px <= 0:  # series starts later: buy at its first real bar
                fi = next(i for i, d in enumerate(mkt.cal) if d in mkt.bars[cid])
                px = mkt.bars[cid][mkt.cal[fi]][0]; i0 = fi
            if px is None or px <= 0:
                table.append(row); continue
            sh = (POT*(1-0.006))/px
            i1 = max(i for i, d in enumerate(mkt.cal) if d <= ed)
            peak, dd = -1.0, 0.0
            for i in range(i0, i1+1):
                v = sh*(mkt.value_close(cid, i) or 0.0)
                peak = max(peak, v)
                if peak > 0: dd = min(dd, v/peak-1.0)
            fin = sh*(mkt.value_close(cid, i1) or 0.0)*(1-0.006)
            row["standalone_hold_final"] = round(fin, 2)
            row["standalone_hold_dd_pct"] = round(dd*100, 2)
        table.append(row)
    out["per_coin"] = table
    out["registry_summary"] = {str(cid): {"symbol": v["symbol"], "source": v["source"],
        "bars": len(v["rows"]), "first": v["rows"][0]["d"] if v["rows"] else None,
        "last": v["rows"][-1]["d"] if v["rows"] else None} for cid, v in reg.items()}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"saved results.json in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
