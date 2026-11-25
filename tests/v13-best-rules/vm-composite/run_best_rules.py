#!/usr/bin/env python3
"""
V13 BEST-RULES — VM-COMPOSITE. Simulation only.
Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES: composite-lite ranking — value = mean(B/M percentile rank,
E/P percentile rank); combined = (value + 12-1 momentum percentile)/2;
hold top 3, equal weight, quarterly re-pick, next-open execution,
NO floor. Pond = the family's honest 30-name program pond. Costs
0.10%/side + $0.01 per sell order. PIT EDGAR facts only.

Chassis: the v12 holdings-vm-variants pond engine (run_pond.py),
imported read-only in spirit — its FastBook/FastPIT/run_episode/
run_rules machinery is copied here verbatim in behaviour; order-books
for BOTH the published composite (B/M+E/P+CF/P) and my lite form are
built from the same PIT series in one pass.

INTEGRITY GATE: published form (3-measure composite, count 5, house
floor) must reproduce LONG $2,713.38 / DECADE $651.27 / CONT $511.48 /
VAL $265.38 before any v13 number counts.

CONFIRMATION (frozen in spec): if my rules beat champion V+M on any
road -> fresh-$100 calendar folds 2017-2026 + DECADE half-windows,
my rules vs the published pond form (composite count 5, house floor).
Confirmed requires >=6/10 folds AND >=1/2 halves.
"""
import bisect, importlib.util, json, os, random, time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
START_CASH = 100.0
SEEDS = list(range(1, 21))
END = "2026-11-20"
ROADS = {"LONG": ("2010-01-04", END), "DECADE": ("2016-11-21", END),
         "CONT": ("2019-01-02", END), "VAL": ("2023-01-03", END)}
PUBLISHED = {"LONG": 2713.38, "DECADE": 651.27, "CONT": 511.48, "VAL": 265.38}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
BASE_V13 = {"LONG": 2923.60, "DECADE": 906.90, "CONT": 691.73, "VAL": 461.20}
MY_COUNT = 3

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

CUR = [MY_COUNT]
def pick_plain(order, held, n):
    return list(order) if n == "ALL" else list(order[:n])

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

def run_rules(fb, orders, sel_all, start, end, picker, rules, rng=None):
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

def diagnostics(curve):
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak: peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd: maxdd, maxdd_d = dd, d
    return {"max_dd_pct": round(maxdd * 100, 2), "max_dd_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d}

def period_distribution(curve, sel_dates):
    closes = dict(curve); pts = []
    for d in sel_dates:
        if d in closes: pts.append((d, closes[d]))
    if curve and (not pts or pts[-1][0] != curve[-1][0]): pts.append(curve[-1])
    periods = []
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        periods.append({"start": d0, "end": d1, "start_value": round(v0, 2),
                        "end_value": round(v1, 2), "profit": round(v1 - v0, 2),
                        "return_pct": round((v1 / v0 - 1) * 100, 2) if v0 else None})
    profits = [p["profit"] for p in periods]; n = len(profits)
    if n == 0: return {"periods": [], "n_periods": 0}
    srt = sorted(profits)
    median = srt[n // 2] if n % 2 else round((srt[n // 2 - 1] + srt[n // 2]) / 2, 2)
    longest_loss = cur = 0
    for p in profits:
        cur = cur + 1 if p < 0 else 0; longest_loss = max(longest_loss, cur)
    peak = -1.0; last_high = -1; longest_gap = 0
    vals = [pts[0][1]] + [p["end_value"] for p in periods]
    for i, v in enumerate(vals):
        if v >= peak:
            peak = v
            longest_gap = max(longest_gap, i - last_high - 1) if last_high >= 0 else longest_gap
            last_high = i
    longest_gap = max(longest_gap, len(vals) - 1 - last_high)
    best = max(periods, key=lambda p: p["profit"]); worst = min(periods, key=lambda p: p["profit"])
    return {"periods": periods, "n_periods": n,
            "median_profit": median,
            "pct_profitable": round(100.0 * sum(1 for p in profits if p > 0) / n, 1),
            "best_period": best, "worst_period": worst,
            "longest_losing_streak": longest_loss,
            "longest_stretch_between_new_highs_periods": longest_gap,
            "mean_profit_secondary": round(sum(profits) / n, 2)}

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
    rng = random.Random(7); days = [d for d in fb.dates if "2010-01-04" <= d <= END]
    for t in UNIVERSE:
        for rows, fast in ((equity_rows[t], EQF[t]), (shares_rows[t], SHF[t])):
            for d in rng.sample(days, 8):
                a = E.pit_value(rows, d); b = fast.pit(d)
                assert (a is None) == (b is None) and (a is None or a == b), (t, d)
    print("FastPIT verified vs E.pit_value", flush=True)
    didx = {t: {b["d"]: i for i, b in enumerate(fb.bars[t])} for t in UNIVERSE}
    sel_by_road = {n: E.quarter_selection_dates(fb, ws, we) for n, (ws, we) in ROADS.items()}
    all_sel = sorted({d for v in sel_by_road.values() for d in v})
    # also every quarterly date 2010..2026 for confirmation folds/halves
    conf_sel_all = E.quarter_selection_dates(fb, "2010-01-04", END)
    all_needed = sorted(set(all_sel) | set(conf_sel_all))
    comp_orders, lite_orders = {}, {}
    for d in all_needed:
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
            ni = INCF[t].pit(d)
            if ni is not None:
                sc[t] = (bm, ni[2] / mcap, mom)
            ocf = OCFF[t].pit(d)
            if ni is not None and ocf is not None:
                scc[t] = (bm, ni[2] / mcap, ocf[2] / mcap, mom)
        if len(sc) >= 5:
            rb = E.percentile_ranks({t: v[0] for t, v in sc.items()})
            re_ = E.percentile_ranks({t: v[1] for t, v in sc.items()})
            mr = E.percentile_ranks({t: v[2] for t, v in sc.items()})
            vs = {t: (rb[t] + re_[t]) / 2.0 for t in sc}
            comb = {t: (vs[t] + mr[t]) / 2.0 for t in sc}
            lite_orders[d] = (sorted(comb, key=lambda t: -comb[t]), sorted(sc))
        if len(scc) >= 5:
            rb = E.percentile_ranks({t: v[0] for t, v in scc.items()})
            re_ = E.percentile_ranks({t: v[1] for t, v in scc.items()})
            rc = E.percentile_ranks({t: v[2] for t, v in scc.items()})
            mr2 = E.percentile_ranks({t: v[3] for t, v in scc.items()})
            vs = {t: (rb[t] + re_[t] + rc[t]) / 3.0 for t in scc}
            comb2 = {t: (vs[t] + mr2[t]) / 2.0 for t in scc}
            comp_orders[d] = (sorted(comb2, key=lambda t: -comb2[t]), sorted(scc))
    print(f"orders built: lite {len(lite_orders)} dates, composite {len(comp_orders)} dates ({time.time()-t0:.0f}s)", flush=True)

    results = {"program": "v13-best-rules", "family": "vm-composite",
               "spec": "BEST-RULES-SPEC.md (frozen before run)",
               "my_rules": {"count": MY_COUNT, "floor": None, "cadence": "quarterly",
                            "value": "mean(B/M rank, E/P rank)", "combined": "(value+12-1 momentum rank)/2",
                            "costs": "0.10%/side + $0.01 per sell order", "start_cash": 100.0},
               "published_form": {"count": 5, "rules": "house (-15% floor chassis)",
                                  "value": "mean(B/M, E/P, CF/P ranks)", "finals": PUBLISHED},
               "champion_vm": CHAMPION, "base_v13_top2": BASE_V13, "spy_reference": SPY_REF,
               "integrity": {}, "roads": {}, "confirmation": None}

    # ---- integrity gate: published composite count5 house
    CUR[0] = 5
    pub_runs = {}
    for name, (ws, we) in ROADS.items():
        r = run_rules(fb, comp_orders, sel_by_road[name], ws, we, pick_plain, "house")
        ok = abs(round(r["final"], 2) - PUBLISHED[name]) < 0.02
        results["integrity"][name] = {"expected": PUBLISHED[name], "reproduced": round(r["final"], 2), "match": ok}
        print(f"INTEGRITY {name} published-5-house: ${r['final']:,.2f} expected ${PUBLISHED[name]} match={ok}", flush=True)
        assert ok, f"integrity failed on {name}"
        pub_runs[name] = r

    # ---- my rules + placebos + published reference
    CUR[0] = MY_COUNT
    beat_champ_any = False
    for name, (ws, we) in ROADS.items():
        sel = sel_by_road[name]
        spy, _ = E.spy_net(fb, ws, we, START_CASH); spy = round(spy, 2)
        r = run_rules(fb, lite_orders, sel, ws, we, pick_plain, "native")
        diag = diagnostics(r["curve"]); dist = period_distribution([(d, v) for d, v in r["curve"]], sel)
        pfinals = []
        for seed in SEEDS:
            prng = random.Random(seed)
            pfinals.append(round(run_rules(fb, lite_orders, sel, ws, we, pick_plain, "native", rng=prng)["final"], 2))
        beaten = sum(1 for f in pfinals if f < r["final"])
        pr5 = pub_runs[name]; pdiag = diagnostics(pr5["curve"]); pdist = period_distribution([(d, v) for d, v in pr5["curve"]], sel)
        beat_champ = round(r["final"], 2) > CHAMPION[name]
        beat_champ_any = beat_champ_any or beat_champ
        results["roads"][name] = {
            "window": [ws, we], "spy_final": spy,
            "my_rules": {"final": round(r["final"], 2), "costs": round(r["costs"], 2),
                         "orders": r["orders"], "max_dd_pct": diag["max_dd_pct"], "max_dd_date": diag["max_dd_date"],
                         "worst_close": diag["worst_close"], "worst_close_date": diag["worst_close_date"],
                         "placebo_beaten": beaten, "placebo_finals": pfinals,
                         "beats_published_composite": round(r["final"], 2) > PUBLISHED[name],
                         "beats_champion_vm": beat_champ,
                         "beats_base_v13_top2": round(r["final"], 2) > BASE_V13[name],
                         "period_distribution": dist,
                         "curve": [[d, round(v, 4)] for d, v in r["curve"]]},
            "published_form_house5": {"final": round(pr5["final"], 2), "costs": round(pr5["costs"], 2),
                                      "orders": pr5["orders"], "halts": pr5["halts"],
                                      "max_dd_pct": pdiag["max_dd_pct"], "max_dd_date": pdiag["max_dd_date"],
                                      "period_distribution": pdist,
                                      "curve": [[d, round(v, 4)] for d, v in pr5["curve"]]}}
        print(f"{name} MY-RULES lite-3/nofloor: ${r['final']:,.2f} (published ${PUBLISHED[name]:,.2f}, champion ${CHAMPION[name]:,.2f}, base-top2 ${BASE_V13[name]:,.2f}, SPY ${spy:,.2f}) placebos {beaten}/20 maxDD {diag['max_dd_pct']}% orders={r['orders']} costs=${r['costs']:,.2f}", flush=True)

    # ---- confirmation (frozen design)
    if beat_champ_any:
        CUR[0] = MY_COUNT
        folds = {}
        for yr in range(2017, 2027):
            s = f"{yr}-01-01"; e = END if yr == 2026 else f"{yr}-12-31"
            sel = E.quarter_selection_dates(fb, s, e)
            rc = run_rules(fb, lite_orders, sel, s, e, pick_plain, "native")
            CUR[0] = 5
            rp = run_rules(fb, comp_orders, sel, s, e, pick_plain, "house")
            CUR[0] = MY_COUNT
            folds[str(yr)] = {"my_rules_final": round(rc["final"], 2), "published_final": round(rp["final"], 2),
                              "my_rules_max_dd_pct": diagnostics(rc["curve"])["max_dd_pct"],
                              "my_rules_win": rc["final"] > rp["final"]}
        halves = {}
        for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"), "H2_2022-2026": ("2022-01-01", END)}.items():
            sel = E.quarter_selection_dates(fb, s, e)
            rc = run_rules(fb, lite_orders, sel, s, e, pick_plain, "native")
            CUR[0] = 5
            rp = run_rules(fb, comp_orders, sel, s, e, pick_plain, "house")
            CUR[0] = MY_COUNT
            halves[hn] = {"my_rules_final": round(rc["final"], 2), "published_final": round(rp["final"], 2),
                          "my_rules_max_dd_pct": diagnostics(rc["curve"])["max_dd_pct"],
                          "my_rules_win": rc["final"] > rp["final"]}
        wins = sum(1 for v in folds.values() if v["my_rules_win"]); hwins = sum(1 for v in halves.values() if v["my_rules_win"])
        results["confirmation"] = {"design": "fresh-$100 calendar-year folds 2017-2026 + DECADE half-windows; my full rule set vs published pond form (composite count 5 + house floor)",
                                   "year_folds": folds, "fold_wins": f"{wins}/10",
                                   "half_windows": halves, "half_wins": f"{hwins}/2",
                                   "confirmed": wins >= 6 and hwins >= 1}
        print(f"CONFIRMATION: folds {wins}/10 halves {hwins}/2 confirmed={results['confirmation']['confirmed']}", flush=True)

    results["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, "results.json"), "w") as f: json.dump(results, f, indent=1)
    print("DONE", results["elapsed_sec"], flush=True)

if __name__ == "__main__":
    main()
