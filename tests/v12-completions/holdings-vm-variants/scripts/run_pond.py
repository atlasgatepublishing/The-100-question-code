#!/usr/bin/env python3
"""HOLDINGS-COUNT SWEEP — pond families: vm-buffer, vm-composite,
vm-twosleeve (house form). Spec: ../SPEC.md (frozen before runs).

Plumbing copied from the v12 vm-buffer runner (itself the v10/v5 host
engine): FastBook on full-history pxfull payloads, FastPIT proven equal
to E.pit_value on sampled pairs, champion scores precomputed once per
quarterly selection date and shared by every count/form/placebo.
Composite scores add the v9 bundle's income/OCF PIT series.
Costs 0.10%/side + $0.01/sell. $100 pots. Simulation only.
Writes only ../results_pond.json.
"""
import bisect, importlib.util, json, math, os, random, time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "results_pond.json")
BT = os.path.expanduser("~/workspace/stock-app/backtests")
START_CASH = 100.0
SEEDS = list(range(1, 21))
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
ROADS = {"LONG": ("2010-01-04", "2026-11-20"),
         "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20"),
         "CONFIRM": ("2010-01-04", "2016-11-18")}

def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

V5 = load_module("vm_buffer_v5", os.path.join(BT, "v5", "vm-buffer", "vm-buffer.py"))
E = V5.E
UNIVERSE = E.UNIVERSE
V9C = load_module("vm_composite_v9", os.path.join(BT, "v9-muse-rules", "vm-composite", "vm-composite-v9.py"))

class FastBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}
        self._dl = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}
    def bar(self, t, d): return self.idx.get(t, {}).get(d)
    def close_on_or_before(self, t, d):
        dl = self._dl.get(t, []); i = bisect.bisect_right(dl, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None

def bars_adj(payload):
    res = payload["chart"]["result"][0]; ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t)); o, c = q["open"][i], q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c; ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"]); return bars

def build_book():
    lh = os.path.join(BT, "v7", "long-hold", "data")
    fallback = os.path.join(BT, "v10-retest", "vm-buffer", "cache")
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        p = os.path.join(lh, f"pxfull_{t}.json")
        if not os.path.exists(p): p = os.path.join(fallback, f"pxfull_{t}.json")
        with open(p, "rb") as f: bars[t] = bars_adj(json.loads(f.read()))
    return FastBook(bars)

class FastPIT:
    def __init__(self, rows):
        indexed = list(enumerate(rows))
        indexed.sort(key=lambda ir: (ir[1][0], ir[1][3], ir[1][1], -ir[0]))
        self.rows = [r for _i, r in indexed]; self.filed = [r[0] for r in self.rows]
    def pit(self, asof):
        i = bisect.bisect_left(self.filed, asof) - 1
        if i < 0: return None
        filed, end, val, _prio = self.rows[i]
        ay, am, ad = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
        fy, fm, fd = int(filed[:4]), int(filed[5:7]), int(filed[8:10])
        if _date(fy, fm, fd).toordinal() < _date(ay, am, ad).toordinal() - 548: return None
        return (filed, end, val)

# ---------------------------------------------------------------- pickers
def pick_plain(order, held, n):
    return list(order) if n == "ALL" else list(order[:n])
def make_buffer(form):
    def picker(order, held, n):
        if n == "ALL": return list(order)
        rank = {t: i + 1 for i, t in enumerate(order)}
        kept = [t for t in held if rank.get(t, 10**9) <= 2 * n]
        if form == "set":
            new = [t for t in order[:n] if t not in held]
            return kept + new
        # slot: fill to n
        picks = list(kept[:n])
        for t in order:
            if len(picks) >= n: break
            if t not in picks: picks.append(t)
        return picks
    return picker

# ---------------------------------------------------------------- episode
def run_episode(fb, orders, sel_set, start, end, start_cash, floor, picker, rng=None):
    cash = start_cash; positions = {}; trades = []; total_costs = 0.0
    halted = None; halt_info = None; curve = []; pools = []
    days = [d for d in fb.dates if start <= d <= end]
    if not days: return None
    pending = None
    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = fb.close_on_or_before(t, d)
            if c: v += sh * c
        return v
    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = fb.bar(t, d)
            if b: opens[t] = b["o"]
        for t in list(positions):
            if t not in opens: continue
            cur_val = positions[t] * opens[t]; tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt; sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01; cash += sell_val - c; total_costs += c
                positions[t] -= sh; trades.append((d, t, "SELL"))
                if positions[t] < 1e-9: del positions[t]
        for t, tgt in targets.items():
            if t not in opens: continue
            cur_val = positions.get(t, 0.0) * opens[t]; buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005: continue
                sh = buy_val / opens[t]; c = buy_val * 0.001
                cash -= buy_val + c; total_costs += c
                positions[t] = positions.get(t, 0.0) + sh; trades.append((d, t, "BUY"))
    for di, d in enumerate(days):
        if pending is not None: execute_rebalance(d, pending); pending = None
        if d in sel_set and d in orders:
            order, pool = orders[d]
            if len(pool) >= 5:
                o = list(order)
                if rng is not None: rng.shuffle(o)
                picks = picker(o, list(positions), CUR[0])
                pools.append((d, len(pool), list(picks)))
                pv = portfolio_close(d); each = pv / len(picks)
                pending = {t: each for t in picks}
        v = portfolio_close(d); curve.append((d, v))
        if floor is not None and v <= floor and di < len(days) - 1:
            halted = d; halt_info = {"signal_date": d, "signal_close": round(v, 2)}
            nd = days[di + 1]
            for t in list(positions):
                b = fb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]; c = val * 0.001 + 0.01
                    cash += val - c; total_costs += c; trades.append((nd, t, "SELL-HALT"))
            positions = {}
            return {"final": cash, "costs": total_costs, "orders": len(trades),
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "curve": curve, "pools": pools}
    last = days[-1]
    for t in list(positions):
        c_ = fb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_; cst = val * 0.001 + 0.01
            cash += val - cst; total_costs += cst; trades.append((last, t, "SELL-END"))
    return {"final": cash, "costs": total_costs, "orders": len(trades),
            "halted": None, "end": last, "halt_info": None, "curve": curve, "pools": pools}

CUR = [5]  # current count cell (picker reads it)

def run_rules(fb, orders, sel_all, start, end, picker, rules, rng=None):
    """rules: 'house' = v9 wrapper; 'native' = single episode, no floor."""
    sel = [d for d in sel_all if start <= d <= end]
    if rules == "native":
        r = run_episode(fb, orders, set(sel), start, end, START_CASH, None, picker, rng)
        return {"final": r["final"], "costs": r["costs"], "orders": r["orders"],
                "curve": r["curve"], "pools": r["pools"], "halts": 0, "episodes": 1}
    floor1 = round(0.85 * START_CASH, 2)
    r1 = run_episode(fb, orders, set(sel), start, end, START_CASH, floor1, picker, rng)
    out = {"final": r1["final"], "costs": r1["costs"], "orders": r1["orders"],
           "curve": list(r1["curve"]), "pools": list(r1["pools"]), "halts": 0, "episodes": 1}
    if r1["halted"] is None: return out
    out["halts"] = 1; liq = r1["end"]; cash = r1["final"]
    day90 = _date(int(liq[:4]), int(liq[5:7]), int(liq[8:10])).toordinal() + 90
    restart = None
    for cand in sel:
        if _date(int(cand[:4]), int(cand[5:7]), int(cand[8:10])).toordinal() >= day90:
            restart = cand; break
    if restart is None:
        out["curve"].append((end, cash)); out["curve"].sort(); return out
    for d in fb.dates:
        if liq < d < restart: out["curve"].append((d, cash))
    r2 = run_episode(fb, orders, {d for d in sel if restart <= d <= end},
                     restart, end, cash, round(0.85 * cash, 2), picker, rng)
    out["episodes"] = 2; out["final"] = r2["final"]; out["costs"] += r2["costs"]
    out["orders"] += r2["orders"]; out["curve"] += list(r2["curve"]); out["pools"] += list(r2["pools"])
    if r2["halted"] is not None: out["halts"] = 2
    out["curve"].sort(); return out

# ------------------------------------------------------------- twosleeve
class Sleeve:
    def __init__(self, cash): self.cash = cash; self.positions = {}; self.costs = 0.0; self.orders = 0
    def close_value(self, fb, d):
        v = self.cash
        for t, sh in self.positions.items():
            c = fb.close_on_or_before(t, d)
            if c: v += sh * c
        return v

def ts_episode(fb, ordersV, ordersM, sel, jan_set, start, end, start_cash, floor, k, rng=None):
    sA, sB = Sleeve(start_cash / 2.0), Sleeve(start_cash / 2.0)
    sel_set = set(sel); days = [d for d in fb.dates if start <= d <= end]
    pending = None; curve = []; pools = []
    def sleeve_sells(sl, d, targets):
        opens = {}
        for t in set(list(sl.positions) + list(targets)):
            b = fb.bar(t, d)
            if b: opens[t] = b["o"]
        for t in list(sl.positions):
            if t not in opens: continue
            cur = sl.positions[t] * opens[t]; tgt = targets.get(t, 0.0)
            if cur > tgt + 0.005:
                sv = cur - tgt; sh = sv / opens[t]; c = sv * 0.001 + 0.01
                sl.cash += sv - c; sl.costs += c; sl.orders += 1; sl.positions[t] -= sh
                if sl.positions[t] < 1e-9: del sl.positions[t]
        return opens
    def sleeve_buys(sl, d, targets, opens):
        for t, tgt in targets.items():
            if t not in opens: continue
            cur = sl.positions.get(t, 0.0) * opens[t]; bv = tgt - cur
            if bv > 0.005:
                bv = min(bv, sl.cash / 1.001)
                if bv <= 0.005: continue
                sh = bv / opens[t]; c = bv * 0.001
                sl.cash -= bv + c; sl.costs += c; sl.orders += 1
                sl.positions[t] = sl.positions.get(t, 0.0) + sh
    for di, d in enumerate(days):
        if pending is not None:
            tA, tB, jan = pending
            oA = sleeve_sells(sA, d, tA); oB = sleeve_sells(sB, d, tB)
            if jan:  # v10 January reset: cash transfer equalizing sleeve open values
                def open_value(sl):
                    v = sl.cash
                    for t, sh in sl.positions.items():
                        b = fb.bar(t, d)
                        if b: v += sh * b["o"]
                    return v
                diff = (open_value(sA) - open_value(sB)) / 2.0
                if diff > 0.005:
                    amt = min(diff, sA.cash); sA.cash -= amt; sB.cash += amt
                elif diff < -0.005:
                    amt = min(-diff, sB.cash); sB.cash -= amt; sA.cash += amt
            sleeve_buys(sA, d, tA, oA); sleeve_buys(sB, d, tB, oB)
            pending = None
        if d in sel_set and d in ordersV and d in ordersM:
            oV, pool = ordersV[d]; oM, _ = ordersM[d]
            if len(pool) >= 5:
                kk = len(pool) if k == "ALL" else min(k, len(pool))
                if rng is not None:
                    pA = rng.sample(pool, kk); pB = rng.sample(pool, kk)
                else:
                    pA = list(oV[:kk]); pB = list(oM[:kk])
                vA, vB = sA.close_value(fb, d), sB.close_value(fb, d); total = vA + vB
                jan = d in jan_set
                eachA = (total / 2.0) / kk if jan else vA / kk
                eachB = (total / 2.0) / kk if jan else vB / kk
                pending = ({t: eachA for t in pA}, {t: eachB for t in pB}, jan)
                pools.append((d, len(pool), pA + pB))
        v = sA.close_value(fb, d) + sB.close_value(fb, d); curve.append((d, v))
        if floor is not None and v <= floor and di < len(days) - 1:
            nd = days[di + 1]
            for sl in (sA, sB):
                for t in list(sl.positions):
                    b = fb.bar(t, nd)
                    if b:
                        val = sl.positions[t] * b["o"]; c = val * 0.001 + 0.01
                        sl.cash += val - c; sl.costs += c; sl.orders += 1
                sl.positions = {}
            return {"final": sA.cash + sB.cash, "costs": sA.costs + sB.costs,
                    "orders": sA.orders + sB.orders, "halted": d, "end": nd,
                    "curve": curve, "pools": pools}
    last = days[-1]
    for sl in (sA, sB):
        for t in list(sl.positions):
            c_ = fb.close_on_or_before(t, last)
            if c_:
                val = sl.positions[t] * c_; cst = val * 0.001 + 0.01
                sl.cash += val - cst; sl.costs += cst; sl.orders += 1
        sl.positions = {}
    return {"final": sA.cash + sB.cash, "costs": sA.costs + sB.costs,
            "orders": sA.orders + sB.orders, "halted": None, "end": last,
            "curve": curve, "pools": pools}

def ts_rules(fb, ordersV, ordersM, sel_all, start, end, k, rules, rng=None):
    sel = [d for d in sel_all if start <= d <= end]
    jan = set()
    seen_years = set()
    for d in sel:
        if d[5:7] == "01" and d[:4] not in seen_years: jan.add(d); seen_years.add(d[:4])
    if rules == "native":
        r = ts_episode(fb, ordersV, ordersM, sel, jan, start, end, START_CASH, None, k, rng)
        return {"final": r["final"], "costs": r["costs"], "orders": r["orders"],
                "curve": r["curve"], "pools": r["pools"], "halts": 0, "episodes": 1}
    r1 = ts_episode(fb, ordersV, ordersM, sel, jan, start, end, START_CASH, round(0.85 * START_CASH, 2), k, rng)
    out = {"final": r1["final"], "costs": r1["costs"], "orders": r1["orders"],
           "curve": list(r1["curve"]), "pools": list(r1["pools"]), "halts": 0, "episodes": 1}
    if r1["halted"] is None: return out
    out["halts"] = 1; liq = r1["end"]; cash = r1["final"]
    day90 = _date(int(liq[:4]), int(liq[5:7]), int(liq[8:10])).toordinal() + 90
    restart = None
    for cand in sel:
        if _date(int(cand[:4]), int(cand[5:7]), int(cand[8:10])).toordinal() >= day90:
            restart = cand; break
    if restart is None:
        out["curve"].append((end, cash)); out["curve"].sort(); return out
    for d in fb.dates:
        if liq < d < restart: out["curve"].append((d, cash))
    r2 = ts_episode(fb, ordersV, ordersM, [d for d in sel if restart <= d <= end], jan,
                    restart, end, cash, round(0.85 * cash, 2), k, rng)
    out["episodes"] = 2; out["final"] = r2["final"]; out["costs"] += r2["costs"]
    out["orders"] += r2["orders"]; out["curve"] += list(r2["curve"]); out["pools"] += list(r2["pools"])
    if r2["halted"] is not None: out["halts"] = 2
    out["curve"].sort(); return out

# ---------------------------------------------------------------- helpers
def quarter_sample(curve):
    out = {}
    for d, v in curve: out[(d[:4], (int(d[5:7]) - 1) // 3)] = (d, v)
    return [[d, round(v, 4)] for d, v in sorted(out.values())]
def maxdd(curve):
    peak = -1.0; m = 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: m = max(m, 1 - v / peak)
    return round(m * 100, 2)
def cell_stats(r):
    sizes = [len(p[2]) for p in r["pools"]]
    return {"final": round(r["final"], 2), "max_dd_pct": maxdd(r["curve"]),
            "costs": round(r["costs"], 2), "orders": r["orders"],
            "halts": r["halts"], "episodes": r["episodes"],
            "holdings_mean": round(sum(sizes) / len(sizes), 2) if sizes else None,
            "holdings_min": min(sizes) if sizes else None,
            "holdings_max": max(sizes) if sizes else None,
            "curve_q": quarter_sample(r["curve"])}

def main():
    t0 = time.time()
    _pb4, equity_rows, shares_rows = V5.build_inputs()
    EQF = {t: FastPIT(equity_rows[t]) for t in UNIVERSE}
    SHF = {t: FastPIT(shares_rows[t]) for t in UNIVERSE}
    ciks = E.get_ciks(); overrides = {"XOM": 34088}
    INCF, OCFF = {}, {}
    for t in UNIVERSE:
        cik = overrides.get(t, ciks[t][0]); facts = E.get_companyfacts(cik)
        INCF[t] = FastPIT(V9C.pit_series_income(facts))
        OCFF[t] = FastPIT(V9C.pit_series_ocf(facts))
    fb = build_book()
    # verify FastPIT vs E.pit_value on samples
    rng = random.Random(7); days = [d for d in fb.dates if "2010-01-04" <= d <= "2026-11-20"]
    for t in UNIVERSE:
        for rows, fast in ((equity_rows[t], EQF[t]), (shares_rows[t], SHF[t])):
            for d in rng.sample(days, 8):
                a = E.pit_value(rows, d); b = fast.pit(d)
                assert (a is None) == (b is None) and (a is None or a == b), (t, d)
    print("FastPIT verified", flush=True)
    didx = {t: {b["d"]: i for i, b in enumerate(fb.bars[t])} for t in UNIVERSE}
    sel_by_road = {n: E.quarter_selection_dates(fb, ws, we) for n, (ws, we) in ROADS.items()}
    all_sel = sorted({d for v in sel_by_road.values() for d in v})
    champ_orders, comp_orders, val_orders, mom_orders = {}, {}, {}, {}
    for d in all_sel:
        sc = {}; scc = {}
        for t in UNIVERSE:
            be = EQF[t].pit(d); so = SHF[t].pit(d)
            if be is None or so is None: continue
            b = fb.bar(t, d)
            if b is None: continue
            px = b["c"]
            if so[2] <= 0 or be[2] is None: continue
            mcap = so[2] * px
            if mcap <= 0: continue
            bl = fb.bars[t]; di = didx[t].get(d)
            if di is None or di < 253: continue
            mom = bl[di - 21]["c"] / bl[di - 252]["c"] - 1.0
            bm = be[2] / mcap
            sc[t] = (bm, mom)
            ni = INCF[t].pit(d); ocf = OCFF[t].pit(d)
            if ni is not None and ocf is not None:
                scc[t] = (bm, ni[2] / mcap, ocf[2] / mcap, mom)
        if len(sc) >= 5:
            vr = E.percentile_ranks({t: v[0] for t, v in sc.items()})
            mr = E.percentile_ranks({t: v[1] for t, v in sc.items()})
            comb = {t: (vr[t] + mr[t]) / 2.0 for t in sc}
            champ_orders[d] = (sorted(comb, key=lambda t: -comb[t]), sorted(sc))
            val_orders[d] = (sorted(sc, key=lambda t: -vr[t]), sorted(sc))
            mom_orders[d] = (sorted(sc, key=lambda t: -mr[t]), sorted(sc))
        if len(scc) >= 5:
            rb = E.percentile_ranks({t: v[0] for t, v in scc.items()})
            re_ = E.percentile_ranks({t: v[1] for t, v in scc.items()})
            rc = E.percentile_ranks({t: v[2] for t, v in scc.items()})
            mr2 = E.percentile_ranks({t: v[3] for t, v in scc.items()})
            vs = {t: (rb[t] + re_[t] + rc[t]) / 3.0 for t in scc}
            comb2 = {t: (vs[t] + mr2[t]) / 2.0 for t in scc}
            comp_orders[d] = (sorted(comb2, key=lambda t: -comb2[t]), sorted(scc))
    print(f"orders built for {len(champ_orders)} dates ({time.time()-t0:.0f}s)", flush=True)

    results = {"program": "v12 holdings-count sweep — pond families", "counts": [str(c) for c in COUNTS]}
    def sweep_plain(fam, orders, roads, picker, label_rules):
        fam_out = {}
        for rname in roads:
            ws, we = ROADS[rname]; sel = sel_by_road[rname]
            spy, _ = E.spy_net(fb, ws, we, START_CASH)
            cells = {}
            for cnt in COUNTS:
                CUR[0] = cnt
                for rules in label_rules:
                    r = run_rules(fb, orders, sel, ws, we, picker, rules)
                    twins = []
                    for seed in SEEDS:
                        prng = random.Random(seed)
                        twins.append(round(run_rules(fb, orders, sel, ws, we, picker, rules, rng=prng)["final"], 2))
                    st = cell_stats(r)
                    st["placebo_finals"] = twins
                    st["placebos_beaten"] = sum(1 for x in twins if st["final"] > x)
                    cells[f"{cnt}|{rules}"] = st
                    print(f"{fam} {rname} n={cnt} {rules}: ${st['final']} beat {st['placebos_beaten']}/20 ({time.time()-t0:.0f}s)", flush=True)
            fam_out[rname] = {"window": [ws, we], "spy": round(spy, 2), "cells": cells}
        return fam_out

    # --- vm-buffer: slot (house) + set (constructed) ; rules house + set-native
    buf = {}
    for form, picker in (("slot", make_buffer("slot")), ("set", make_buffer("set"))):
        rules_list = ["house"] if form == "slot" else ["house", "native"]
        buf[form] = sweep_plain(f"buffer-{form}", champ_orders, list(ROADS), picker, rules_list)
    results["vm-buffer"] = buf
    with open(OUT + ".partial", "w") as f: json.dump(results, f, indent=1)
    print("partial saved after buffer", flush=True)
    # --- vm-composite: plain top-N of composite ranking
    results["vm-composite"] = sweep_plain("composite", comp_orders, list(ROADS), pick_plain, ["house", "native"])
    with open(OUT + ".partial", "w") as f: json.dump(results, f, indent=1)
    print("partial saved after composite", flush=True)
    # --- vm-twosleeve house: per-sleeve k
    ts_out = {}
    for rname in ("DECADE", "CONT", "VAL", "CONFIRM"):
        ws, we = ROADS[rname]; sel = sel_by_road[rname]
        spy, _ = E.spy_net(fb, ws, we, START_CASH)
        cells = {}
        for k in COUNTS:
            for rules in ("house", "native"):
                r = ts_rules(fb, val_orders, mom_orders, sel, ws, we, k, rules)
                twins = []
                for seed in SEEDS:
                    prng = random.Random(seed)
                    twins.append(round(ts_rules(fb, val_orders, mom_orders, sel, ws, we, k, rules, rng=prng)["final"], 2))
                st = cell_stats(r); st["placebo_finals"] = twins
                st["placebos_beaten"] = sum(1 for x in twins if st["final"] > x)
                cells[f"{k}|{rules}"] = st
                print(f"twosleeve {rname} k={k} {rules}: ${st['final']} beat {st['placebos_beaten']}/20 ({time.time()-t0:.0f}s)", flush=True)
        ts_out[rname] = {"window": [ws, we], "spy": round(spy, 2), "cells": cells}
    results["vm-twosleeve-house"] = ts_out
    results["runtime_s"] = round(time.time() - t0, 1)
    with open(OUT, "w") as f: json.dump(results, f, indent=1)
    print("DONE", OUT, flush=True)

if __name__ == "__main__":
    main()
