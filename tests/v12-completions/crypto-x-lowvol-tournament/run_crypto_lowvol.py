#!/usr/bin/env python3
"""
CRYPTO-X LOW-VOLATILITY TOURNAMENT (CONSTRUCTED) — v12 Crypto Wing 1.
Frozen spec: see CONSTRUCTION-SPEC.md in this folder (frozen before runs).
Calmest-2 by vol20 among PIT top-20 coins above their ma200, monthly,
next-day-open execution, $0.25 min delta, 0.60%/side, dead coins to zero
after a 30-day grace. Two rule sets: frozen ladder floor as-is, and v9
protections. BTC buy-hold is the bar. 20-seed placebos (random 2 from the
same eligible set), FULL + VALIDATION, both rule sets.
Reads shared v4 / v12 crypto-basket-pit data READ-ONLY. Writes only here.
"""
import json, math, os, random, time, bisect
from datetime import datetime, timedelta
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..", "..")
V4 = os.path.join(ROOT, "v4")
V4CACHE = os.path.join(V4, "crypto-basket-pit-data")
BASKETPIT = os.path.join(HERE, "..", "crypto-basket-pit")
POT = 100.0
COST = 0.006
GRACE_DAYS = 30
MIN_DELTA = 0.25
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
    with open(os.path.join(BASKETPIT, "data", "hype.json")) as f: rows = json.load(f)
    reg[32196] = {"symbol": "HYPE", "slug": "hyperliquid", "source": "hyperliquid:HYPE",
                  "reason": None, "rows": rows}
    return reg

class Market:
    def __init__(self, reg, weekly):
        self.reg = reg
        btc = reg[1]["rows"]
        self.cal = [r["d"] for r in btc]
        self.bars, self.ff, self.lb, self.bc = {}, {}, {}, {}
        self.vol20, self.ma200 = {}, {}
        for cid, info in reg.items():
            if info["source"] == "excluded" or not info["rows"]: continue
            bars = {r["d"]: (r["o"], r["c"]) for r in info["rows"]}
            self.bars[cid] = bars
            n = len(self.cal)
            ff = np.full(n, np.nan); lb = np.full(n, -1, dtype=int); bc = np.zeros(n, dtype=int)
            last, li, cnt = None, -1, 0
            for i, d in enumerate(self.cal):
                if d in bars: last, li, cnt = bars[d][1], i, cnt + 1
                if last is not None: ff[i] = last
                lb[i] = li; bc[i] = cnt
            self.ff[cid], self.lb[cid], self.bc[cid] = ff, lb, bc
            # rolling indicators on forward-filled closes (bar-count tests gate validity)
            cs = np.cumsum(np.where(np.isnan(ff), 0.0, ff))
            ma = np.full(n, np.nan)
            if n >= 200:
                ma[199:] = (cs[199:] - np.concatenate(([0.0], cs[:-200]))[:n-199]) / 200.0
            self.ma200[cid] = ma
            ret = np.full(n, np.nan)
            with np.errstate(divide="ignore", invalid="ignore"):
                ret[1:] = ff[1:] / ff[:-1] - 1.0
            r = np.where(np.isnan(ret), 0.0, ret)
            c1 = np.cumsum(r); c2 = np.cumsum(r * r)
            vol = np.full(n, np.nan)
            if n >= 21:
                s1 = c1[20:] - c1[:-20]
                s2 = c2[20:] - c2[:-20]
                m = s1 / 20.0
                var = s2 / 20.0 - m * m
                # pandas pct_change().rolling(20).std() uses ddof=1
                vol[20:] = np.sqrt(np.maximum(var, 0.0) * 20.0 / 19.0)
            self.vol20[cid] = vol
        self.snap_keys = sorted(weekly.keys())
        self.snap_top = {k: [c["cmc_id"] for c in weekly[k]["top20"]] for k in self.snap_keys}
        self._elig = {}
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
        lb = int(self.lb[cid][i])
        if lb < 0: return None
        return float(self.ff[cid][i]) if i - lb <= GRACE_DAYS else 0.0
    def eligible(self, cid, j):
        """Return vol20 if eligible at close index j, else None. Cached."""
        key = (cid, j)
        if key in self._elig: return self._elig[key]
        out = None
        if cid in self.bars and j >= 200:
            lb = int(self.lb[cid][j])
            if lb >= 0 and j - lb <= 7 and int(self.bc[cid][j]) >= 201:
                # real bars on every day of the ma200 window and vol window:
                # bc increments by at most 1/day, so bc[j]-bc[j-200]==200 iff daily bars
                if int(self.bc[cid][j]) - int(self.bc[cid][j-200]) == 200:
                    c = float(self.ff[cid][j]); ma = float(self.ma200[cid][j]); v = float(self.vol20[cid][j])
                    if not (math.isnan(ma) or math.isnan(v)) and c > ma:
                        out = v
        self._elig[key] = out
        return out

def simulate(mkt, start_d, end_d, ruleset, mode="ranked", seed=42):
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    cash, pos, entry = float(POT), {}, {}
    orders, costs = 0, 0.0
    curve, events, halts, picks_log = [], [], [], []
    elig_sum, elig_n = 0, 0
    # ladder state (frozen form)
    ladder_floor = 85.0
    # v9 state
    episode, floor_abs = 1, 85.0
    pending_liq, sit_until, ended = False, None, False

    def equity_at(i):
        return cash + sum(sh * (mkt.value_close(cid, i) or 0.0) for cid, sh in pos.items())
    def note_exit(cid, px, when):
        if cid in entry and entry[cid] > 0 and px <= 0.10 * entry[cid]:
            events.append({"type": "collapse_exit", "coin": mkt.reg[cid]["symbol"],
                           "cmc_id": cid, "date": when, "entry_px": entry[cid],
                           "exit_px": px, "loss_pct": round((px / entry[cid] - 1) * 100, 2)})

    for i in range(i0, i1 + 1):
        d = cal[i]
        if pending_liq:
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    note_exit(cid, 0.0, d); del pos[cid]; entry.pop(cid, None); continue
                val = pos[cid] * px; fee = val * COST; cash += val - fee
                costs += fee; orders += 1; note_exit(cid, px, d)
                del pos[cid]; entry.pop(cid, None)
            pending_liq = False
            if ruleset == "ladder":
                halts.append({"halt_date": d, "liquidated_at": round(cash, 2), "floor": ladder_floor})
                ended = True
            else:
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
        sitting = ruleset == "v9" and sit_until is not None and d < sit_until
        is_reb = (i == i0) or (datetime.strptime(d, "%Y-%m-%d").day == 1)
        if not sitting and is_reb:
            if ruleset == "v9" and sit_until is not None and d >= sit_until:
                floor_abs = 0.85 * cash; sit_until = None
                halts[-1]["restart_date"] = d; halts[-1]["restart_balance"] = round(cash, 2)
            universe = mkt.universe(d)
            j = i - 1
            elig = [(cid, mkt.eligible(cid, j)) for cid in universe]
            elig = [(c, v) for c, v in elig if v is not None]
            elig_sum += len(elig); elig_n += 1
            if mode == "ranked":
                elig.sort(key=lambda x: x[1]); picks = [c for c, _ in elig[:2]]
            else:
                names = sorted(c for c, _ in elig)
                picks = rng.sample(names, min(2, len(names))) if names else []
            picks_log.append({"date": d, "picks": [mkt.reg[c]["symbol"] for c in picks],
                              "n_eligible": len(elig),
                              "vols": {mkt.reg[c]["symbol"]: round(v, 6) for c, v in elig}})
            eq = equity_at(i)
            n_t = len(picks)
            target = {cid: eq / n_t for cid in picks} if n_t else {}
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    lb = int(mkt.lb[cid][i])
                    if lb >= 0 and i - lb > GRACE_DAYS:
                        note_exit(cid, 0.0, d); del pos[cid]; entry.pop(cid, None)
                    continue
                cur = pos[cid] * px; want = target.get(cid, 0.0)
                if cur > want + MIN_DELTA:
                    sv = cur - want; fee = sv * COST; cash += sv - fee
                    costs += fee; orders += 1; pos[cid] -= sv / px
                    if want <= 0.0 or pos[cid] * px < 0.01:
                        note_exit(cid, px, d); del pos[cid]; entry.pop(cid, None)
                elif want <= 0.0 and cur <= MIN_DELTA and cur > 0.01:
                    pass  # frozen spec: sub-$0.25 dust is not traded
                elif want <= 0.0:
                    note_exit(cid, px, d); del pos[cid]; entry.pop(cid, None)
            for cid in picks:
                px = mkt.trade_open(cid, i)
                if px is None: continue
                deficit = target[cid] - pos.get(cid, 0.0) * px
                if deficit <= MIN_DELTA: continue
                bv = min(deficit, cash / (1.0 + COST))
                if bv <= 0.01: continue
                fee = bv * COST; cash -= bv + fee; costs += fee; orders += 1
                sh = bv / px; old = pos.get(cid, 0.0)
                entry[cid] = (entry[cid] * old + px * sh) / (old + sh) if old > 0 and cid in entry else px
                pos[cid] = old + sh
        eq_close = equity_at(i)
        curve.append((d, eq_close))
        if ruleset == "ladder":
            if eq_close >= 150.0: ladder_floor = max(ladder_floor, 125.0)
            elif eq_close >= 125.0: ladder_floor = max(ladder_floor, 100.0)
            if eq_close <= ladder_floor:
                if i == i1:
                    tot = cash
                    for cid, sh in list(pos.items()):
                        v = mkt.value_close(cid, i)
                        if v: tot += sh * v - sh * v * COST; costs += sh * v * COST; orders += 1
                    halts.append({"halt_date": d, "liquidated_at": round(tot, 2), "floor": ladder_floor})
                    curve[-1] = (d, tot); cash = tot; pos.clear(); ended = True
                else:
                    pending_liq = True
        elif ruleset == "v9" and not sitting and sit_until is None and eq_close <= floor_abs:
            if i == i1:
                tot = cash
                for cid, sh in list(pos.items()):
                    v = mkt.value_close(cid, i)
                    if v: tot += sh * v - sh * v * COST; costs += sh * v * COST; orders += 1
                halts.append({"episode": episode, "halt_date": d, "liquidated_at": round(tot, 2)})
                curve[-1] = (d, tot); cash = tot; pos.clear(); ended = True
            else:
                pending_liq = True
    # end of window: liquidate at last close (frozen stock spec)
    if not ended and pos:
        i = i1
        tot = cash
        for cid, sh in list(pos.items()):
            v = mkt.value_close(cid, i)
            if v: tot += sh * v - sh * v * COST; costs += sh * v * COST; orders += 1
        curve[-1] = (cal[i1], tot); cash = tot; pos.clear()
    final = curve[-1][1]
    peak, dd = -1.0, 0.0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0: dd = min(dd, e / peak - 1.0)
    yrs = (datetime.strptime(end_d, "%Y-%m-%d") - datetime.strptime(start_d, "%Y-%m-%d")).days / 365.25
    return {"final": round(final, 2), "ret_pct": round((final / POT - 1) * 100, 2),
            "cagr_pct": round(((final / POT) ** (1 / yrs) - 1) * 100, 2) if final > 0 else None,
            "max_dd_pct": round(dd * 100, 2), "orders": orders, "costs": round(costs, 2),
            "avg_eligible": round(elig_sum / elig_n, 2) if elig_n else None,
            "events": events, "halts": halts, "ended_by_halt": ended,
            "curve": [[d, round(e, 4)] for d, e in curve], "picks_log": picks_log}

def btc_hold(mkt, start_d, end_d):
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    sh = (POT * (1 - COST)) / mkt.trade_open(1, i0)
    peak, dd, curve = -1.0, 0.0, []
    for i in range(i0, i1 + 1):
        v = sh * float(mkt.ff[1][i]); curve.append([cal[i], round(v, 4)])
        peak = max(peak, v)
        if peak > 0: dd = min(dd, v / peak - 1.0)
    final = sh * float(mkt.ff[1][i1]) * (1 - COST)
    return {"final": round(final, 2), "ret_pct": round((final / POT - 1) * 100, 2),
            "max_dd_pct": round(dd * 100, 2), "curve": curve}

def pct(vals, q):
    s = sorted(vals)
    if len(s) == 1: return s[0]
    p = q * (len(s) - 1); lo, hi = int(math.floor(p)), int(math.ceil(p))
    return s[lo] if lo == hi else s[lo] * (1 - (p - lo)) + s[hi] * (p - lo)

def main():
    t0 = time.time()
    reg = load_registry()
    with open(os.path.join(BASKETPIT, "data", "weekly_snapshots.json")) as f:
        weekly = json.load(f)
    mkt = Market(reg, weekly)
    print(f"registry={len(reg)} cal {mkt.cal[0]}..{mkt.cal[-1]} ({time.time()-t0:.0f}s)", flush=True)
    out = {"family": "crypto-x-lowvol-tournament", "label": "CONSTRUCTED",
           "cost_per_side": COST, "pot": POT, "runs": {}, "btc_hold": {}, "placebos": {}}
    for w, (sd, ed) in WINDOWS.items():
        out["btc_hold"][w] = btc_hold(mkt, sd, ed)
    for ruleset in ("ladder", "v9"):
        for w, (sd, ed) in WINDOWS.items():
            r = simulate(mkt, sd, ed, ruleset)
            key = f"{ruleset}|{w}"
            out["runs"][key] = r
            print(f"{key}: ${r['final']} DD {r['max_dd_pct']}% orders {r['orders']} "
                  f"halts {r['halts']} avg_elig {r['avg_eligible']} BTC ${out['btc_hold'][w]['final']} "
                  f"({time.time()-t0:.0f}s)", flush=True)
    for ruleset in ("ladder", "v9"):
        for w in ("full", "validation"):
            sd, ed = WINDOWS[w]
            finals, rows = [], []
            for seed in range(1, 21):
                r = simulate(mkt, sd, ed, ruleset, mode="placebo", seed=seed)
                finals.append(r["final"])
                rows.append({"seed": seed, "final": r["final"], "max_dd_pct": r["max_dd_pct"],
                             "orders": r["orders"]})
            rk = out["runs"][f"{ruleset}|{w}"]["final"]
            nb = sum(1 for v in finals if rk > v)
            out["placebos"][f"{ruleset}|{w}"] = {
                "n_seeds": 20, "median_final": round(pct(finals, .5), 2),
                "p25_final": round(pct(finals, .25), 2), "p75_final": round(pct(finals, .75), 2),
                "best_final": round(max(finals), 2), "worst_final": round(min(finals), 2),
                "ranked_final": rk, "ranked_beats_n_of_20": nb,
                "ranked_percentile": round(100 * nb / 20, 1), "rows": rows}
            print(f"placebo {ruleset}|{w}: median ${pct(finals,.5):.2f} ranked ${rk} beats {nb}/20 "
                  f"({time.time()-t0:.0f}s)", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(f"saved results.json in {time.time()-t0:.0f}s", flush=True)

if __name__ == "__main__":
    main()
