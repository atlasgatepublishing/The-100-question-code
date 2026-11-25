#!/usr/bin/env python3
"""
SIZE PREMIUM — v13 BEST RULES. Frozen form: see BEST-RULES-SPEC.md.
ANNUAL reconstitution (each January): hold ALL tradeable non-stablecoin
coins in the bottom half (ranks 11-20) of the PIT CMC Sunday snapshot
top-20, equal-weighted across held names, drift untouched between
formations. No floor, no halt, no trend gate. Dead coins: last close
30 days, then ZERO. Headline cost 0.80%/side (top of documented retail
range; bottom-of-top-20 liquidity), 0.60%/side sensitivity. BTC
buy-and-hold beside every number. 20-seed placebos: random same-size
baskets from the same PIT tradeable non-stablecoin top-20 set.

Reads v4 caches + crypto-basket-pit data READ-ONLY (paths adjusted to
this folder's depth). Writes only here.
"""
import json, math, os, random, time
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
V4CACHE = os.path.join(V4, "crypto-basket-pit-data")
PITDATA = os.path.join(HERE, "..", "..", "v12-completions", "crypto-basket-pit", "data")  # canonical PIT snapshot store (read-only)
POT = 100.0
GRACE_DAYS = 30
WINDOWS = {"full": ("2017-01-01", "2026-11-20"),
           "design": ("2017-01-01", "2022-12-31"),
           "validation": ("2023-01-01", "2026-11-20")}
PLACEBO_SEEDS = list(range(1, 21))
STABLECOINS = {"USDT", "USDC", "DAI", "BUSD", "UST", "TUSD", "USD1"}
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
    with open(os.path.join(PITDATA, "hype.json")) as f: rows = json.load(f)
    reg[32196] = {"symbol": "HYPE", "slug": "hyperliquid",
                  "source": "hyperliquid:HYPE", "reason": None, "rows": rows}
    return reg

def load_weekly():
    with open(os.path.join(PITDATA, "weekly_snapshots.json")) as f:
        return json.load(f)

# ------------------------------------------------------------- market -----
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
            ff, lb = [], []
            last, li = None, -1
            for i, d in enumerate(self.cal):
                if d in bars: last, li = bars[d][1], i
                ff.append(last); lb.append(li)
            self.ff[cid], self.lb[cid] = ff, lb
        self.snap_keys = sorted(weekly.keys())
        # snapshot -> list of (rank, cmc_id), rank order = PIT cap order
        self.snap_top = {k: [(c["rank"], c["cmc_id"]) for c in weekly[k]["top20"]]
                         for k in self.snap_keys}
    def universe_ranked(self, d):
        import bisect
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
    def tradeable(self, cid, j):
        """Fresh real bar within 7 days before signal day j, series mapped."""
        if cid not in self.bars or j < 0: return False
        lb = self.lb[cid][j]
        return lb >= 0 and j - lb <= 7 and (self.ff[cid][j] or 0) > 0

def is_rebalance(cadence, d, first):
    if first: return True
    dt = datetime.strptime(d, "%Y-%m-%d")
    if cadence == "annual": return dt.day == 1 and dt.month == 1
    if cadence == "monthly": return dt.day == 1
    if cadence == "quarterly": return dt.day == 1 and dt.month in (1, 4, 7, 10)
    raise ValueError(cadence)

# ----------------------------------------------------------- simulate -----
def simulate(mkt, start_d, end_d, cadence, ruleset, cost, n_hold,
             mode="ranked", seed=42):
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    cash, pos, entry = float(POT), {}, {}
    wo = {}
    orders, costs = 0, 0.0
    curve, events, halts = [], [], []
    picks_log = []
    episode, floor_abs = 1, 85.0
    pending_liq, sit_until, ended = False, None, False

    def equity_at(i):
        return cash + sum(sh * (mkt.value_close(cid, i) or 0.0)
                          for cid, sh in pos.items())
    def note_exit(cid, px, when):
        if cid in entry and entry[cid] > 0 and px <= 0.10 * entry[cid]:
            events.append({"type": "collapse_exit",
                           "coin": mkt.reg[cid]["symbol"], "cmc_id": cid,
                           "date": when, "entry_px": entry[cid], "exit_px": px,
                           "loss_pct": round((px/entry[cid]-1)*100, 2)})

    for i in range(i0, i1+1):
        d = cal[i]
        for cid in list(pos):
            if cid not in mkt.lb: continue
            lb = mkt.lb[cid][i]
            if lb >= 0 and i - lb == GRACE_DAYS + 1 and not wo.get(cid):
                events.append({"type": "write_off",
                               "coin": mkt.reg[cid]["symbol"], "cmc_id": cid,
                               "date": d, "last_bar_date": cal[lb],
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
                costs += fee; orders += 1; note_exit(cid, px, d)
                del pos[cid]; entry.pop(cid, None)
            pending_liq = False
            halts.append({"episode": episode, "halt_date": d,
                          "liquidated_at": round(cash, 2)})
            if episode == 1:
                episode = 2
                sit_until = (datetime.strptime(d, "%Y-%m-%d")
                             + timedelta(days=90)).strftime("%Y-%m-%d")
            else:
                ended = True
            curve.append((d, cash))
            if ended:
                for k in range(i+1, i1+1): curve.append((cal[k], cash))
                break
            continue
        sitting = sit_until is not None and d < sit_until
        if not sitting and is_rebalance(cadence, d, i == i0):
            if sit_until is not None and d >= sit_until:
                floor_abs = 0.85 * cash; sit_until = None
                halts[-1]["restart_date"] = d
                halts[-1]["restart_balance"] = round(cash, 2)
            ranked = mkt.universe_ranked(d)          # [(rank, cid)] ascending cap
            j = i - 1
            def ok(cid):
                return mkt.tradeable(cid, j) and \
                    mkt.reg[cid]["symbol"] not in STABLECOINS
            bottom_half = [cid for rk, cid in ranked if rk >= 11 and ok(cid)]
            pool = [cid for rk, cid in ranked if ok(cid)]
            if mode == "ranked":
                picks = bottom_half
            else:
                picks = rng.sample(pool, min(len(bottom_half), len(pool))) \
                    if pool else []
            if mode == "ranked":
                picks_log.append({"date": d,
                                  "picks": [mkt.reg[c]["symbol"] for c in picks],
                                  "n_tradeable": len(pool)})
            eq = equity_at(i)
            w = 1.0 / len(picks) if picks else 0.0
            target = {cid: w*eq for cid in picks}
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    lb = mkt.lb[cid][i] if cid in mkt.lb else -1
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
                entry[cid] = (entry[cid]*old + px*sh)/(old+sh) \
                    if old > 0 and cid in entry else px
                pos[cid] = old + sh
        eq_close = equity_at(i)
        curve.append((d, eq_close))
        if ruleset == "v9" and not sitting and sit_until is None \
                and eq_close <= floor_abs:
            if i == i1:
                tot = cash
                for cid, sh in list(pos.items()):
                    v = mkt.value_close(cid, i)
                    if v: tot += sh*v - sh*v*cost; costs += sh*v*cost; orders += 1
                halts.append({"episode": episode, "halt_date": d,
                              "liquidated_at": round(tot, 2)})
                curve[-1] = (d, tot); cash = tot; pos.clear(); ended = True
            else:
                pending_liq = True
    final = curve[-1][1]
    peak, dd = -1.0, 0.0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0: dd = min(dd, e/peak - 1.0)
    yrs = (datetime.strptime(end_d, "%Y-%m-%d")
           - datetime.strptime(start_d, "%Y-%m-%d")).days/365.25
    return {"final": round(final, 2), "ret_pct": round((final/POT-1)*100, 2),
            "cagr_pct": round(((final/POT)**(1/yrs)-1)*100, 2) if final > 0 else None,
            "max_dd_pct": round(dd*100, 2), "orders": orders,
            "costs": round(costs, 2), "events": events, "halts": halts,
            "ended_by_second_halt": ended,
            "curve": [[d, round(e, 4)] for d, e in curve],
            "picks_log": picks_log}

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
    out = {"family": "size-premium (coin cross-section) — v13 BEST RULES",
           "label": "v13 best-rules: annual formation, bottom half (ranks 11-20) "
                    "equal-weight, stablecoins excluded, no floor",
           "cost_headline": 0.008, "pot": POT, "runs": {}, "btc_hold": {},
           "placebos": {},
           "universe_fence": "PIT CMC top-20-by-construction; 'small' = ranks 11-20, "
                             "small-relative-to-giants only; true small-cap crypto "
                             "(rank 100+) has no PIT pond and is untested",
           "structural_note": "BTC is rank 1; the size basket never holds BTC "
                              "(except the Jan-Nov 2017 two-coin data fence) — "
                              "the trade is structurally short BTC vs the BTC-hold bar",
           "stablecoin_exclusion": sorted(STABLECOINS)}
    for cost, tag in ((0.008, "c080"), (0.006, "c060")):
        out["btc_hold"][tag] = {w: btc_hold(mkt, sd, ed, cost)
                                for w, (sd, ed) in WINDOWS.items()}
    # headline: annual bottom-half, no floor, 0.80; sensitivity at 0.60
    for cost, tag in ((0.008, "c080"), (0.006, "c060")):
        for w, (sd, ed) in WINDOWS.items():
            r = simulate(mkt, sd, ed, "annual", "nofloor", cost, 10)
            key = f"annual|bottomhalf|nofloor|{w}|{tag}"
            out["runs"][key] = r
            print(f"{key}: ${r['final']} DD {r['max_dd_pct']}% orders "
                  f"{r['orders']} costs ${r['costs']} BTC "
                  f"${out['btc_hold'][tag][w]['final']} ({time.time()-t0:.0f}s)",
                  flush=True)
    # placebos: annual, random same-size from PIT tradeable non-stable top-20,
    # nofloor, 0.80, FULL + VALIDATION
    for w in ("full", "validation"):
        sd, ed = WINDOWS[w]
        finals, rows = [], []
        for seed in PLACEBO_SEEDS:
            r = simulate(mkt, sd, ed, "annual", "nofloor", 0.008,
                         10, mode="placebo", seed=seed)
            finals.append(r["final"])
            rows.append({"seed": seed, "final": r["final"],
                         "max_dd_pct": r["max_dd_pct"], "orders": r["orders"]})
        rk = out["runs"][f"annual|bottomhalf|nofloor|{w}|c080"]["final"]
        nb = sum(1 for v in finals if rk > v)
        out["placebos"][f"annual|bottomhalf|{w}|c080"] = {
            "n_seeds": 20, "median_final": round(pct(finals, .5), 2),
            "p25_final": round(pct(finals, .25), 2),
            "p75_final": round(pct(finals, .75), 2),
            "best_final": round(max(finals), 2),
            "worst_final": round(min(finals), 2),
            "ranked_final": rk, "ranked_beats_n_of_20": nb,
            "ranked_percentile": round(100*nb/20, 1), "rows": rows}
        print(f"placebo annual|bottomhalf|{w}: median ${pct(finals,.5):.2f} "
              f"ranked ${rk} beats {nb}/20 ({time.time()-t0:.0f}s)", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"saved results.json in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
