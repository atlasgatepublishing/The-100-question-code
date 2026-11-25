#!/usr/bin/env python3
"""
HOLDINGS-COUNT SWEEP — champion Value+Momentum (v12 wing). Simulation only.

Family: AMP signals — book-to-market (EDGAR PIT StockholdersEquity /
shares x close) + 12-1 momentum, percentile-rank averaged, equal weight,
QUARTERLY re-pick. NATIVE COUNT = 5. Universe = the program pond (30).

GRID (pre-registered, fixed, identical for every family):
  counts 1, 2, 3, 5, 8, 10, 15, 20, 30, ALL-ELIGIBLE (ALL = whole scored
  pool that quarter). Count semantics: hold min(count, pool size);
  selection requires >=5 scored names (the champion's own viability
  gate). Equal weight = pot value / actual holdings.

RULE SETS:
  house  = v9 protections: plain -15% floor per episode (close check),
           liquidate next open; first halt -> 90-day cash sit-out,
           restart at next quarterly selection date, episode-2 floor
           -15% from restart balance; second halt ends the run.
  native = the published AMP form carries NO floor / stop / restart
           (v11 vm-composite/vm-broad: AMP portfolios publish none) —
           so native here = same ranking/cadence/costs, NO protection
           layer. (The literal AMP broad long-short form is
           UNBUILDABLE-NATIVE per v11 — delisting-inclusive broad data
           + short leg; this sweep varies COUNT inside the buildable
           champion chassis, which is the wing's stated scope.)

ROADS:
  Fixed Nov-2016 pond (v4 UNIVERSE, 30 names — point-in-time at the
  DECADE start; CONT/VAL are its continuation windows, program
  convention): DECADE 2016-11-21, CONT 2019-01-02, VAL 2023-01-03,
  all -> 2026-11-20. Plumbing = v10 vm-breadth10 (full-history Yahoo
  payloads, PitIndex = exact pit_value replica). INTEGRITY: house
  count-5 must reproduce $667.35 / $544.47 / $288.05.
  LONG 2010-01-04 -> 2026-11-20 uses the long-run-2010 plumbing: the
  pond REBUILT point-in-time at 2010 (30 different names, GOOG not
  GOOGL) — a 2010 run on the 2016 pond would be lookahead. INTEGRITY:
  house count-5 must reproduce $1,415.62 (SPY $822.94).

Costs: program standard 0.10%/side + $0.01 per sell order. $100 pots.
Placebos: 20 seeds (1..20) per cell — random count-sized draws from
the same scored pool at each selection, same rules; one Random(seed)
flows through both v9 episodes (v10 convention). For ALL-ELIGIBLE the
random draw IS the pool, so placebos degenerate to the strategy
itself (beaten = 0 by construction, marked degenerate).

CONFIRMATION (Terry's rule, pre-registered): a non-native count that
beats count 5 on at least 3 of 4 roads under house rules (and on the
4-road sum) is re-run on different years: fresh-$100 calendar-year
folds 2017..2026 (fixed pond, house) head-to-head vs count 5, plus
DECADE half-windows. Only a confirmed winner is VARIANT-CANDIDATE.

Decisions (scores/rankings) are precomputed once per pond and shared
by every count/ruleset/placebo — the count changes only how many of
the ranked list are held.
"""
import bisect
import importlib.util
import json
import os
import random
import sys
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
START_CASH = 100.0
SEEDS = list(range(1, 21))
COUNTS = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
NATIVE_COUNT = 5
END = "2026-11-20"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


E = load_module("vm_plainfloor", os.path.join(BT, "v4", "value-momentum-plainfloor.py"))
UNIVERSE = E.UNIVERSE  # fixed Nov-2016 pond, 30 names

sys.path.insert(0, os.path.join(BT, "long-run-2010"))
import lr_common as LC  # noqa: E402


# ------------------------------------------------------------------ books
class FastBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}
        self.dlist = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}
        self.didx = {t: {d: i for i, d in enumerate(ds)}
                     for t, ds in self.dlist.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        ds = self.dlist.get(t, [])
        i = bisect.bisect_right(ds, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None


class PitIndex:
    """Exact replica of E.pit_value (see v10 vm-breadth10)."""

    def __init__(self, rows):
        best = {}
        for filed, end, val, prio in rows:
            cur = best.get(filed)
            if cur is None or (prio, end) > (cur[0], cur[1]):
                best[filed] = (prio, end, val)
        self.fileds = sorted(best)
        self.vals = [best[f] for f in self.fileds]
        self.ords = [date.fromisoformat(f).toordinal() for f in self.fileds]

    def value(self, asof):
        i = bisect.bisect_left(self.fileds, asof) - 1
        if i < 0:
            return None
        cutoff = date.fromisoformat(asof).toordinal() - 548
        if self.ords[i] < cutoff:
            return None
        prio, end, val = self.vals[i]
        return (self.fileds[i], end, val)


def parse_payload(blob):
    j = json.loads(blob)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


# ------------------------------------------------------------------ inputs
def build_fixed_inputs():
    ciks = E.get_ciks()
    overrides = {"XOM": 34088}
    pit_eq, pit_sh = {}, {}
    for t in UNIVERSE:
        cik = overrides.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        pit_eq[t] = PitIndex(
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        pit_sh[t] = PitIndex(
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    lh = os.path.join(BT, "v7", "long-hold", "data")
    lr = os.path.join(BT, "long-run-2010", "data")
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        path = os.path.join(lh, f"pxfull_{t}.json")
        if not os.path.exists(path):
            path = os.path.join(lr, f"pxfull_{t}.json")
        with open(path, "rb") as f:
            bars[t] = parse_payload(f.read())
    return FastBook(bars), pit_eq, pit_sh, list(UNIVERSE)


def build_long_inputs():
    """Pond = the published long-run-2010 pond_build (rebuilt PIT at
    2010-01-04 by that program and saved in its results_champion.json,
    read-only). Loading only the 30 pond names' facts/payloads (via
    lr_common's own loaders/chains) keeps memory bounded; the house
    count-5 integrity check ($1,415.62) validates this plumbing
    end-to-end against that program's published run."""
    with open(os.path.join(BT, "long-run-2010", "results_champion.json")) as f:
        pub = json.load(f)
    pond = pub["pond_build"]["pond"]
    info = {"price_date": pub["pond_build"]["price_date"]}
    pit_eq, pit_sh = {}, {}
    bars = {}
    for t in pond:
        facts = LC.load_facts(LC.cik_for(t))
        pit_eq[t] = PitIndex(LC.equity_chain(facts))
        pit_sh[t] = PitIndex(LC.shares_chain(facts))
        del facts
        bars[t] = LC.bars_adj(LC.yahoo_payload(t))
    bars["SPY"] = LC.bars_adj(LC.yahoo_payload("SPY"))
    return FastBook(bars), pit_eq, pit_sh, pond, info


# ------------------------------------------------------------------ engine
def quarter_dates(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end and d[5:7] in ("01", "04", "07", "10"):
            k = (d[:4], d[5:7])
            if k not in seen:
                seen.add(k)
                out.append(d)
    return out


def compute_decisions(pb, pit_eq, pit_sh, universe, sel_dates):
    dec = {}
    for d in sel_dates:
        scores = {}
        for t in universe:
            be = pit_eq[t].value(d)
            so = pit_sh[t].value(d)
            px = pb.close_on_or_before(t, d)
            if be is None or so is None or px is None or so[2] <= 0:
                continue
            mcap = so[2] * px
            if mcap <= 0:
                continue
            bm = be[2] / mcap
            bl = pb.bars.get(t, [])
            didx = pb.didx.get(t, {}).get(d)
            if didx is None or didx < 253:
                continue
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            scores[t] = (bm, mom)
        if len(scores) >= 5:
            vr = E.percentile_ranks({t: v[0] for t, v in scores.items()})
            mr = E.percentile_ranks({t: v[1] for t, v in scores.items()})
            combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
            ranked = sorted(combined, key=lambda t: -combined[t])
        else:
            ranked = []
        dec[d] = {"ranked": ranked, "pool": sorted(scores)}
    return dec


def run_episode(pb, dec, sel_set, start, end, start_cash, floor, count,
                placebo_rng=None):
    cash = start_cash
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        for t in list(positions):
            if t not in opens:
                continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c
                cost += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9:
                    del positions[t]
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c
                cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
        total_costs += cost
        return cost

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            dd = dec.get(d)
            if dd and dd["ranked"]:
                pool = dd["pool"]
                k = len(pool) if count == "ALL" else min(count, len(pool))
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(pool), k)
                else:
                    picks = dd["ranked"][:k]
                pv = portfolio_close(d)
                each = pv / k
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
        if floor is not None and v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "halt_info": None, "curve": curve}


def run_house(pb, dec, sel_dates, start, end, count, placebo_seed=None):
    sel_set = set(sel_dates)
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    floor1 = round(0.85 * START_CASH, 2)
    r1 = run_episode(pb, dec, sel_set, start, end, START_CASH, floor1,
                     count, placebo_rng=rng)
    out = {"final": r1["final"], "costs": r1["costs"],
           "orders": len(r1["trades"]), "curve": list(r1["curve"]),
           "halts": 0, "restart": None, "second_halt": None}
    if r1["halted"] is None:
        return out
    out["halts"] = 1
    liq = r1["end"]
    cash = r1["final"]
    day90 = date.fromisoformat(liq).toordinal() + 90
    restart = None
    for cand in sel_dates:
        if date.fromisoformat(cand).toordinal() >= day90:
            restart = cand
            break
    out["restart"] = {"halt_signal_date": r1["halted"],
                      "liquidation_date": liq, "restart_date": restart,
                      "restart_balance": round(cash, 2),
                      "episode2_floor": round(0.85 * cash, 2)}
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    r2 = run_episode(pb, dec, sel_set, restart, end, cash,
                     round(0.85 * cash, 2), count, placebo_rng=rng)
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["orders"] += len(r2["trades"])
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["halts"] = 2
        out["second_halt"] = {"signal_date": r2["halted"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out


def run_native(pb, dec, sel_dates, start, end, count, placebo_seed=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    r = run_episode(pb, dec, set(sel_dates), start, end, START_CASH, None,
                    count, placebo_rng=rng)
    return {"final": r["final"], "costs": r["costs"],
            "orders": len(r["trades"]), "curve": list(r["curve"]),
            "halts": 0, "restart": None, "second_halt": None}


def diagnostics(curve):
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return {"max_dd_pct": round(maxdd * 100, 2), "max_dd_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d}


def period_distribution(curve, sel_dates):
    """Quarterly periods: equity at each selection date (close) to the
    next; final period ends at the curve's last close (pre-liquidation
    values are the curve closes; the final liquidation is at close on
    the last day, so the last curve point is used as period end)."""
    closes = dict(curve)
    pts = []
    for d in sel_dates:
        if d in closes:
            pts.append((d, closes[d]))
    if curve and (not pts or pts[-1][0] != curve[-1][0]):
        pts.append(curve[-1])
    periods = []
    for (d0, v0), (d1, v1) in zip(pts, pts[1:]):
        periods.append({"start": d0, "end": d1, "start_value": round(v0, 2),
                        "end_value": round(v1, 2),
                        "profit": round(v1 - v0, 2),
                        "return_pct": round((v1 / v0 - 1) * 100, 2) if v0 else None})
    profits = [p["profit"] for p in periods]
    n = len(profits)
    if n == 0:
        return {"periods": [], "n_periods": 0}
    srt = sorted(profits)
    median = srt[n // 2] if n % 2 else round((srt[n // 2 - 1] + srt[n // 2]) / 2, 2)
    longest_loss = cur = 0
    for p in profits:
        cur = cur + 1 if p < 0 else 0
        longest_loss = max(longest_loss, cur)
    # longest stretch between new highs (in periods, on period-end values)
    peak = -1.0
    last_high = -1
    longest_gap = 0
    vals = [pts[0][1]] + [p["end_value"] for p in periods]
    for i, v in enumerate(vals):
        if v >= peak:
            peak = v
            longest_gap = max(longest_gap, i - last_high - 1) if last_high >= 0 else longest_gap
            last_high = i
    longest_gap = max(longest_gap, len(vals) - 1 - last_high)
    return {"periods": periods, "n_periods": n,
            "pct_profitable": round(100.0 * sum(1 for p in profits if p > 0) / n, 1),
            "median_profit": median,
            "mean_profit_secondary": round(sum(profits) / n, 2),
            "best_profit": max(profits), "worst_profit": min(profits),
            "best_period": max(periods, key=lambda p: p["profit"]),
            "worst_period": min(periods, key=lambda p: p["profit"]),
            "longest_losing_run_periods": longest_loss,
            "longest_stretch_between_new_highs_periods": longest_gap}


def spy_final(pb, start, end):
    s, _ = E.spy_net(pb, start, end, START_CASH)
    return round(s, 2)


def main():
    t0 = time.time()
    results = {"family": "champion-vm (Value+Momentum, AMP B/M + 12-1 momentum)",
               "native_count": NATIVE_COUNT, "counts_grid": COUNTS,
               "costs": "0.10%/side + $0.01 per sell order",
               "roads": {}, "integrity": {}}

    # ---------- fixed pond roads
    pb, pit_eq, pit_sh, universe = build_fixed_inputs()
    fixed_roads = {"DECADE": ("2016-11-21", END), "CONT": ("2019-01-02", END),
                   "VAL": ("2023-01-03", END)}
    all_sel = quarter_dates(pb, "2016-11-21", END)
    dec_fixed = compute_decisions(pb, pit_eq, pit_sh, universe, all_sel)
    pool_sizes = {d: len(v["pool"]) for d, v in dec_fixed.items()}
    print("fixed pond pool sizes:", sorted(set(pool_sizes.values())), flush=True)

    # ---------- LONG pond
    pbL, pit_eqL, pit_shL, pondL, pond_info = build_long_inputs()
    selL_all = quarter_dates(pbL, "2010-01-04", END)
    dec_long = compute_decisions(pbL, pit_eqL, pit_shL, pondL, selL_all)
    print("LONG pond:", pondL, flush=True)
    print("LONG pool sizes:", sorted({len(v['pool']) for v in dec_long.values()}), flush=True)
    results["long_pond"] = pondL
    results["long_pond_build"] = {"price_date": pond_info["price_date"]}

    road_specs = []
    for name, (s, e) in fixed_roads.items():
        road_specs.append((name, pb, dec_fixed, s, e))
    road_specs.append(("LONG", pbL, dec_long, "2010-01-04", END))

    # ---------- integrity: house count 5
    expect = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05, "LONG": 1415.62}
    for name, pbx, decx, s, e in road_specs:
        sel = quarter_dates(pbx, s, e)
        r = run_house(pbx, decx, sel, s, e, 5)
        ok = abs(round(r["final"], 2) - expect[name]) < 0.02
        results["integrity"][name] = {"expected_house_count5": expect[name],
                                      "reproduced": round(r["final"], 2), "match": ok}
        print(f"INTEGRITY {name} house-5: ${r['final']:,.2f} expected "
              f"${expect[name]} match={ok}", flush=True)
        assert ok, f"integrity failed on {name}"

    # ---------- full grid
    for name, pbx, decx, s, e in road_specs:
        sel = quarter_dates(pbx, s, e)
        spy = spy_final(pbx, s, e)
        road = {"window": [s, e], "spy_final": spy, "house": {}, "native": {}}
        for rules, runner in (("house", run_house), ("native", run_native)):
            for count in COUNTS:
                key = str(count)
                r = runner(pbx, decx, sel, s, e, count)
                diag = diagnostics(r["curve"])
                pfinals = []
                for seed in SEEDS:
                    pr = runner(pbx, decx, sel, s, e, count, placebo_seed=seed)
                    pfinals.append(round(pr["final"], 2))
                beaten = sum(1 for f in pfinals if f < r["final"])
                road[rules][key] = {
                    "final": round(r["final"], 2), "costs": round(r["costs"], 2),
                    "orders": r["orders"], "halts": r["halts"],
                    "restart": r["restart"], "second_halt": r["second_halt"],
                    "max_dd_pct": diag["max_dd_pct"], "max_dd_date": diag["max_dd_date"],
                    "worst_close": diag["worst_close"],
                    "placebo_beaten": beaten, "placebo_finals": pfinals,
                    "placebo_degenerate": count == "ALL",
                    "_curve": [[d, round(v, 4)] for d, v in r["curve"]]}
                print(f"{name} {rules} count={key}: ${r['final']:,.2f} "
                      f"placebos {beaten}/20 maxDD {diag['max_dd_pct']}% "
                      f"halts={r['halts']}", flush=True)
        results["roads"][name] = road

    # ---------- winner determination (house rules, pre-registered)
    sums = {}
    for count in COUNTS:
        sums[str(count)] = round(sum(results["roads"][rn]["house"][str(count)]["final"]
                                     for rn in ("LONG", "DECADE", "CONT", "VAL")), 2)
    winner = max(sums, key=lambda k: sums[k])
    native_key = str(NATIVE_COUNT)
    beats = {str(c): sum(1 for rn in ("LONG", "DECADE", "CONT", "VAL")
                          if results["roads"][rn]["house"][str(c)]["final"] >
                          results["roads"][rn]["house"][native_key]["final"])
             for c in COUNTS}
    results["house_road_sums"] = sums
    results["roads_beating_native_house"] = beats
    results["overall_winner_house"] = winner
    print("house sums:", sums, "winner:", winner, "beats:", beats, flush=True)

    # ---------- confirmation (different years) if triggered
    cand = None
    if winner != native_key and beats[winner] >= 3:
        cand = int(winner) if winner != "ALL" else "ALL"
    results["confirmation"] = None
    if cand is not None:
        folds = {}
        for yr in range(2017, 2027):
            s = f"{yr}-01-01"
            e = END if yr == 2026 else f"{yr}-12-31"
            sel = quarter_dates(pb, s, e)
            # decisions for fold start dates not in dec_fixed (Jan 1 may
            # not be a trading day; quarter_dates gives first trading
            # days, all in dec_fixed's superset window? folds start
            # 2017+ so their sel dates are within all_sel)
            decf = dec_fixed
            rc = run_house(pb, decf, sel, s, e, cand)
            r5 = run_house(pb, decf, sel, s, e, 5)
            folds[str(yr)] = {"candidate_final": round(rc["final"], 2),
                              "native5_final": round(r5["final"], 2),
                              "candidate_wins": rc["final"] > r5["final"]}
        halves = {}
        for hn, (s, e) in {"H1_2016-2021": ("2016-11-21", "2021-12-31"),
                           "H2_2022-2026": ("2022-01-01", END)}.items():
            sel = quarter_dates(pb, s, e)
            rc = run_house(pb, dec_fixed, sel, s, e, cand)
            r5 = run_house(pb, dec_fixed, sel, s, e, 5)
            halves[hn] = {"candidate_final": round(rc["final"], 2),
                          "native5_final": round(r5["final"], 2),
                          "candidate_wins": rc["final"] > r5["final"]}
        wins = sum(1 for v in folds.values() if v["candidate_wins"])
        hwins = sum(1 for v in halves.values() if v["candidate_wins"])
        confirmed = wins >= 6 and hwins >= 1
        results["confirmation"] = {"candidate_count": cand,
                                   "year_folds": folds, "fold_wins": f"{wins}/10",
                                   "half_windows": halves,
                                   "confirmed": confirmed}
        print(f"CONFIRMATION count={cand}: folds {wins}/10 halves {hwins}/2 "
              f"confirmed={confirmed}", flush=True)

    # ---------- period distributions (quarterly tempo)
    dist = {}
    keys = {winner, native_key}
    for rn, pbx, decx in (("DECADE", pb, dec_fixed), ("LONG", pbL, dec_long)):
        s, e = ("2016-11-21", END) if rn == "DECADE" else ("2010-01-04", END)
        sel = quarter_dates(pbx, s, e)
        dist[rn] = {}
        for k in keys:
            curve = [(d, v) for d, v in results["roads"][rn]["house"][k]["_curve"]]
            dist[rn][k] = period_distribution(curve, sel)
    results["period_distributions_house"] = dist

    # strip curves except winner/native (keep those for the record)
    for rn, road in results["roads"].items():
        for rules in ("house", "native"):
            for k, cell in road[rules].items():
                curve = cell.pop("_curve")
                if rules == "house" and k in keys:
                    cell["curve"] = curve
    results["elapsed_sec"] = round(time.time() - t0, 1)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("DONE", results["elapsed_sec"], flush=True)


if __name__ == "__main__":
    main()
