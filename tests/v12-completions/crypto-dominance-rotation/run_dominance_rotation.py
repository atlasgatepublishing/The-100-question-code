#!/usr/bin/env python3
"""
CRYPTO-DOMINANCE-ROTATION — V12 (CONSTRUCTED).
Frozen form: CONSTRUCTION-SPEC.md. Dominance built as-known-then from CMC
Sunday snapshot pages (data/dominance.json, scrape_dominance.py).
Prices/universe: v4 PIT registry + v12 basket-pit weekly snapshots, READ-ONLY.
Market/death-rule machinery adapted from v12 crypto-basket-pit (same program).
"""
import bisect, json, math, os, random
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
V4CACHE = os.path.join(V4, "crypto-basket-pit-data")
SIB = os.path.join(HERE, "..", "crypto-basket-pit")
POT = 100.0
COST = 0.006
GRACE_DAYS = 30
WINDOWS = {"full": ("2017-01-01", "2026-11-20"),
           "design": ("2017-01-01", "2022-12-31"),
           "validation": ("2023-01-01", "2026-11-20")}
STABLES = {825, 3408, 4943, 4687, 7129, 29470, 36148, 3717}
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}
ALLOC = {"BTC": {1: 1.0}, "LARGE": "large", "ALT": "alt"}

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
    return reg

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
        self.snap_keys = sorted(weekly.keys())
        self.snap_top = {k: [c["cmc_id"] for c in weekly[k]["top20"]] for k in self.snap_keys}
    def universe(self, d):
        k = bisect.bisect_right(self.snap_keys, d) - 1
        return self.snap_top[self.snap_keys[k]] if k >= 0 else []
    def trade_open(self, cid, i):
        if cid not in self.bars: return None
        d = self.cal[i]
        if d in self.bars[cid]: return self.bars[cid][d][0]
        if i > 0 and self.cal[i-1] in self.bars[cid]: return self.bars[cid][self.cal[i-1]][1]
        return None
    def value_close(self, cid, i):
        lb = self.lb[cid][i]
        if lb < 0: return None
        return self.ff[cid][i] if i - lb <= GRACE_DAYS else 0.0

# ------------------------------------------------------------ dominance ----
def load_dominance():
    with open(os.path.join(HERE, "data", "dominance.json")) as f:
        dom = json.load(f)
    keys = sorted(dom.keys())
    return keys, dom

def state_at(dom_keys, dom, asof):
    """State from most recent Sunday <= asof. Returns (state, D) or BTC default."""
    k = bisect.bisect_right(dom_keys, asof) - 1
    if k < 26: return "BTC", (dom[dom_keys[k]]["dominance_top20"] if k >= 0 else None)
    D = dom[dom_keys[k]]["dominance_top20"]
    if D is None: return "BTC", None
    last26 = [dom[dom_keys[k-i]]["dominance_top20"] for i in range(26)]
    if any(v is None for v in last26): return "BTC", D
    D26 = sum(last26) / 26.0
    D13ago = dom[dom_keys[k-13]]["dominance_top20"]
    MKT = dom[dom_keys[k]]["top20_mcap"]; MKT13 = dom[dom_keys[k-13]]["top20_mcap"]
    if D >= D26: return "BTC", D
    if (D - D13ago) < 0 and (MKT - MKT13) > 0: return "ALT", D
    return "LARGE", D

def target_weights(state, universe, mkt):
    if state == "BTC": return {1: 1.0}
    basket = [c for c in universe if c not in (1, 1027) and c not in STABLES and c in mkt.bars]
    w = {}
    if state == "LARGE":
        w[1027] = 0.50; alt_w = 0.50
    else:
        w[1027] = 0.25; alt_w = 0.75
    if basket:
        for c in basket: w[c] = alt_w / len(basket)
    else:
        w[1] = w.get(1, 0.0) + alt_w
    return w

def ew_weights(universe, mkt):
    coins = [c for c in universe if c in mkt.bars]
    return {c: 1.0/len(coins) for c in coins} if coins else {}

# ------------------------------------------------------------ simulate -----
def simulate(mkt, dom_keys, dom, start_d, end_d, ruleset="nofloor",
             mode="ranked", seed=42, state_freq=None):
    rng = random.Random(seed)
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    cash, pos, entry = float(POT), {}, {}
    orders, costs = 0, 0.0
    curve, events, halts, states_log = [], [], [], []
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
        if pending_liq:
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    note_exit(cid, 0.0, d); del pos[cid]; entry.pop(cid, None); continue
                val = pos[cid]*px; fee = val*COST; cash += val - fee
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
        dt = datetime.strptime(d, "%Y-%m-%d")
        if not sitting and (i == i0 or dt.day == 1):
            if sit_until is not None and d >= sit_until:
                floor_abs = 0.85 * cash; sit_until = None
                halts[-1]["restart_date"] = d; halts[-1]["restart_balance"] = round(cash, 2)
            prev = cal[i-1] if i > 0 else d
            universe = mkt.universe(prev)
            if mode == "ew":
                target = ew_weights(universe, mkt); st = "EW"
            else:
                st, D = state_at(dom_keys, dom, prev)
                if mode == "placebo":
                    r = rng.random(); acc = 0.0; st = "ALT"
                    for sname in ("BTC", "LARGE", "ALT"):
                        acc += state_freq[sname]
                        if r <= acc: st = sname; break
                target = target_weights(st, universe, mkt)
            states_log.append({"date": d, "state": st})
            eq = equity_at(i)
            tw = {cid: w * eq for cid, w in target.items()}
            for cid in list(pos):
                px = mkt.trade_open(cid, i)
                if px is None:
                    lb = mkt.lb[cid][i]
                    if lb >= 0 and i - lb > GRACE_DAYS:
                        note_exit(cid, 0.0, d); del pos[cid]; entry.pop(cid, None)
                    continue
                cur = pos[cid]*px; want = tw.get(cid, 0.0)
                if cur > want + 0.01:
                    sv = cur - want; fee = sv*COST; cash += sv - fee
                    costs += fee; orders += 1; pos[cid] -= sv/px
                    if want <= 0.0 or pos[cid]*px < 0.01:
                        note_exit(cid, px, d); del pos[cid]; entry.pop(cid, None)
            for cid, want_val in tw.items():
                px = mkt.trade_open(cid, i)
                if px is None: continue
                deficit = want_val - pos.get(cid, 0.0)*px
                if deficit <= 0.01: continue
                bv = min(deficit, cash/(1.0+COST))
                if bv <= 0.01: continue
                fee = bv*COST; cash -= bv + fee; costs += fee; orders += 1
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
                    if v: tot += sh*v - sh*v*COST; costs += sh*v*COST; orders += 1
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
            "events": events, "halts": halts, "ended_by_second_halt": ended,
            "states_log": states_log,
            "curve": [[d, round(e, 4)] for d, e in curve]}

def btc_hold(mkt, start_d, end_d):
    cal = mkt.cal
    i0 = next(i for i, d in enumerate(cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(cal) if d <= end_d)
    sh = (POT*(1-COST))/mkt.trade_open(1, i0)
    peak, dd, curve = -1.0, 0.0, []
    for i in range(i0, i1+1):
        v = sh*mkt.ff[1][i]; curve.append([cal[i], round(v, 4)])
        peak = max(peak, v)
        if peak > 0: dd = min(dd, v/peak-1.0)
    final = sh*mkt.ff[1][i1]*(1-COST)
    return {"final": round(final, 2), "ret_pct": round((final/POT-1)*100, 2),
            "max_dd_pct": round(dd*100, 2), "curve": curve}

def pct(vals, q):
    s = sorted(vals)
    p = q*(len(s)-1); lo, hi = int(math.floor(p)), int(math.ceil(p))
    return s[lo] if lo == hi else s[lo]*(1-(p-lo)) + s[hi]*(p-lo)

def per_year(curve):
    out = {}
    by = {}
    for d, e in curve: by.setdefault(d[:4], []).append((d, e))
    prev_end = POT
    for y in sorted(by):
        last = by[y][-1][1]
        out[y] = round((last/prev_end - 1)*100, 2) if prev_end > 0 else None
        prev_end = last
    return out

def main():
    reg = load_registry()
    with open(os.path.join(SIB, "data", "weekly_snapshots.json")) as f:
        weekly = json.load(f)
    dom_keys, dom = load_dominance()
    mkt = Market(reg, weekly)
    print(f"registry={len(reg)} mapped={sum(1 for v in reg.values() if v['rows'])} "
          f"dominance Sundays={len(dom_keys)} cal {mkt.cal[0]}..{mkt.cal[-1]}", flush=True)
    out = {"family": "crypto-dominance-rotation",
           "label": "CONSTRUCTED (practitioner phase narrative; all numeric rules constructed)",
           "cost_per_side": COST, "pot": POT, "runs": {}, "btc_hold": {},
           "ew_hold": {}, "placebos": {}, "dominance_sample": {}}
    for k in ("2017-01-01", "2018-01-07", "2021-01-03", "2022-05-01", "2025-01-05"):
        if k in dom: out["dominance_sample"][k] = dom[k]["dominance_top20"]
    for w, (sd, ed) in WINDOWS.items():
        out["btc_hold"][w] = btc_hold(mkt, sd, ed)
        ew = simulate(mkt, dom_keys, dom, sd, ed, mode="ew")
        out["ew_hold"][w] = {kk: ew[kk] for kk in ("final", "ret_pct", "max_dd_pct", "orders", "costs", "events")}
        out["ew_hold"][w]["curve"] = ew["curve"]
        for ruleset in ("nofloor", "v9"):
            r = simulate(mkt, dom_keys, dom, sd, ed, ruleset=ruleset)
            out["runs"][f"{ruleset}|{w}"] = r
            print(f"{ruleset}|{w}: ${r['final']} DD {r['max_dd_pct']}% orders {r['orders']} "
                  f"halts {len(r['halts'])} | BTC ${out['btc_hold'][w]['final']} EW ${ew['final']}", flush=True)
    # state frequencies + placebos
    for w in ("full", "validation"):
        sd, ed = WINDOWS[w]
        log = out["runs"][f"nofloor|{w}"]["states_log"]
        freq = {s: sum(1 for x in log if x["state"] == s)/len(log) for s in ("BTC", "LARGE", "ALT")}
        finals, rows = [], []
        for seed in range(1, 21):
            r = simulate(mkt, dom_keys, dom, sd, ed, mode="placebo", seed=seed, state_freq=freq)
            finals.append(r["final"])
            rows.append({"seed": seed, "final": r["final"], "max_dd_pct": r["max_dd_pct"], "orders": r["orders"]})
        rk = out["runs"][f"nofloor|{w}"]["final"]
        nb = sum(1 for v in finals if rk > v)
        out["placebos"][w] = {"state_freq": {k: round(v, 3) for k, v in freq.items()},
            "n_seeds": 20, "median_final": round(pct(finals, .5), 2),
            "p25_final": round(pct(finals, .25), 2), "p75_final": round(pct(finals, .75), 2),
            "best_final": round(max(finals), 2), "worst_final": round(min(finals), 2),
            "ranked_final": rk, "ranked_beats_n_of_20": nb,
            "ranked_percentile": round(100*nb/20, 1), "rows": rows}
        print(f"placebo {w}: median ${pct(finals,.5):.2f} ranked ${rk} beats {nb}/20 freq {freq}", flush=True)
    out["per_year"] = {
        "rotation_native_full": per_year(out["runs"]["nofloor|full"]["curve"]),
        "btc_full": per_year(out["btc_hold"]["full"]["curve"]),
        "ew_full": per_year(out["ew_hold"]["full"]["curve"])}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved results.json", flush=True)

if __name__ == "__main__":
    main()
