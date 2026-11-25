#!/usr/bin/env python3
"""
V12 JUDGMENT-CONSTRUCTED — Buffett Qualitative / Moat (lean runner v2).
Frozen per JUDGMENT-SPEC.md. Simulation only. Reads ONLY cached data
(read-only): v7/long-hold pxfull_*.json + EDGAR companyfacts.
Writes only inside this folder. Two stages with on-disk cache:
  stage1: per-formation gate evaluations + rankings -> eval_cache.json
  stage2: simulations from cached rankings -> results.json
"""
import json, os, sys, math, random, statistics, gc
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
sys.path.insert(0, os.path.join(BT, "long-run-2010"))
import lr_common as lr
champ = lr.champ

START_CASH = 100.0
BUY_COST, SELL_COST, SELL_FEE = 0.001, 0.001, 0.01
GRID = [1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"]
NATIVE_N = 5
ROADS = [("LONG", "2010-01-04", "2026-11-20"),
         ("DECADE", "2016-11-21", "2026-11-20"),
         ("CONT", "2019-01-02", "2026-11-20"),
         ("VAL", "2023-01-03", "2026-11-20")]
EVAL_CACHE = os.path.join(HERE, "eval_cache.json")
PRICE_CACHE = os.path.join(HERE, "price_cache.json")

# ------------------------------------------------------------ PIT annuals
def _entries(facts, concept):
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else ("shares" if "shares" in units
                                        else list(units)[0])
    return units[key]

def annual_map(facts, concepts, flow=True):
    out = {}
    for name, prio in concepts:
        for e in _entries(facts, name):
            if "filed" not in e or "val" not in e or "end" not in e:
                continue
            if flow:
                if "start" not in e:
                    continue
                dur = (date.fromisoformat(e["end"]) -
                       date.fromisoformat(e["start"])).days
                if not (300 <= dur <= 400):
                    continue
            out.setdefault(e["end"], []).append(
                (e["filed"], float(e["val"]), prio))
    return out

def build_maps(facts):
    return {
        "ni": annual_map(facts, [("NetIncomeLoss", 1)]),
        "rev": annual_map(facts, [
            ("RevenueFromContractWithCustomerExcludingAssessedTax", 3),
            ("Revenues", 2), ("SalesRevenueNet", 2),
            ("SalesRevenueGoodsNet", 1), ("SalesRevenueServicesNet", 1)]),
        "gp": annual_map(facts, [("GrossProfit", 1)]),
        "ocf": annual_map(facts, [
            ("NetCashProvidedByUsedInOperatingActivities", 2),
            ("NetCashProvidedByUsedInOperatingActivitiesContinuingOperations", 1)]),
        "capex": annual_map(facts, [
            ("PaymentsToAcquirePropertyPlantAndEquipment", 1)]),
        "eq": annual_map(facts, [
            ("StockholdersEquity", 2),
            ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", 1)], flow=False),
        "assets": annual_map(facts, [("Assets", 1)], flow=False),
        "liab": annual_map(facts, [("Liabilities", 1)], flow=False),
    }

def pit_at(amap, end, asof):
    best = None
    for filed, val, prio in amap.get(end, []):
        if filed < asof:
            key = (filed, prio)
            if best is None or key > best[0]:
                best = (key, val)
    return best[1] if best else None

def aligned_years(maps, asof, n=5):
    ends = set()
    for end, rows in maps["ni"].items():
        if any(f < asof for f, _, _ in rows):
            ends.add(end)
    out = []
    for end in sorted(ends):
        row = {"end": end}
        for k, m in maps.items():
            row[k] = pit_at(m, end, asof)
        if row["ni"] is None:
            continue
        out.append(row)
    return out[-n:]

def evaluate(maps, shares_val, px_actual):
    """Gate evaluation for one ticker at one formation.
    shares_val: PIT shares (float) or None; px_actual: actual close."""
    years = aligned_years(maps, CUR_ASOF[0], n=5)
    if len(years) < 4:
        return None, "B1<4yrs"
    if any(y["rev"] is None or y["rev"] <= 0 for y in years):
        return None, "B1 revenue"
    oe_years = [y for y in years if y["ocf"] is not None and y["capex"] is not None]
    if len(oe_years) < 4:
        return None, "B2 OE n/a"
    oes = [y["ocf"] - y["capex"] for y in oe_years]
    if sum(1 for v in oes if v > 0) / len(oes) < 0.60 or sum(oes) <= 0:
        return None, "B2 OE sign"
    roe_years = [y for y in years if y["eq"] is not None and y["eq"] > 0]
    if len(roe_years) < 4:
        return None, "B3 equity n/a"
    roes = [y["ni"] / y["eq"] for y in roe_years]
    med_roe = statistics.median(roes)
    if med_roe < 0.15:
        return None, "B3 median ROE"
    if sum(1 for r in roes if r >= 0.10) / len(roes) < 0.80:
        return None, "B3 ROE persistence"
    if sum(1 for y in years if y["ni"] > 0) / len(years) < 0.80:
        return None, "B3 NI persistence"
    gp_years = [y for y in years if y["gp"] is not None and y["rev"]]
    margin_waived = False
    if len(gp_years) >= 4:
        gms = [y["gp"] / y["rev"] for y in gp_years]
        if gms[-1] < 0.25 or sum(1 for g in gms if g >= 0.20) / len(gms) < 0.80:
            return None, "B3 gross margin"
        latest_gm = gms[-1]
    else:
        margin_waived, latest_gm = True, None
    last = years[-1]
    if last["assets"] is None or last["assets"] <= 0 or last["eq"] is None \
            or last["eq"] <= 0:
        return None, "B4 balance sheet n/a"
    liab = last["liab"] if last["liab"] is not None else last["assets"] - last["eq"]
    lev = liab / last["assets"]
    if lev > 0.90:
        return None, "B4 leverage"
    if shares_val is None or shares_val <= 0 or px_actual is None or px_actual <= 0:
        return None, "no PIT shares/price"
    mcap = shares_val * px_actual
    ey = last["ni"] / mcap
    oey = oes[-1] / mcap
    if not (ey >= 0.04 or oey >= 0.04):
        return None, "B6 price"
    mean_roe = statistics.mean(roes)
    cv = (statistics.pstdev(roes) / abs(mean_roe)) if mean_roe else 9.9
    return {"med_roe": med_roe, "gm": latest_gm,
            "margin_waived": margin_waived, "oey": oey,
            "stab": max(0.0, 1.0 - cv), "lev": lev}, None

CUR_ASOF = [""]  # mutable cell: current formation date for evaluate()

def pct_ranks(vals):
    items = sorted(vals.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 0.5}
    return {t: i / (n - 1) for i, (t, _) in enumerate(items)}

def rank_pool(elig):
    if not elig:
        return []
    r_roe = pct_ranks({t: v["med_roe"] for t, v in elig.items()})
    gm_vals = {t: v["gm"] for t, v in elig.items() if v["gm"] is not None}
    r_gm = pct_ranks(gm_vals) if gm_vals else {}
    med_gm = statistics.median(r_gm.values()) if r_gm else 0.5
    r_oey = pct_ranks({t: v["oey"] for t, v in elig.items()})
    r_stab = pct_ranks({t: v["stab"] for t, v in elig.items()})
    r_lev = pct_ranks({t: -v["lev"] for t, v in elig.items()})
    scored = {t: (r_roe[t] + r_gm.get(t, med_gm) + r_oey[t] + r_stab[t]
                  + r_lev[t]) / 5.0 for t in elig}
    return sorted(scored, key=lambda t: -scored[t])

# ------------------------------------------------------------ stage 1
def stage1():
    if os.path.exists(EVAL_CACHE) and os.path.exists(PRICE_CACHE):
        print("stage1: caches exist, skipping", flush=True)
        return
    # SPY dates first (small)
    spy_payload = lr.yahoo_payload("SPY")
    spy_bars = lr.bars_adj(spy_payload)
    all_dates = [b["d"] for b in spy_bars]
    formations = []
    seen = set()
    for d in all_dates:
        if "2010-01-01" <= d <= "2026-11-20" and d[5:7] == "01" \
                and d[:4] not in seen:
            seen.add(d[:4])
            formations.append(d)
    print(f"stage1: {len(formations)} formations {formations[0]}..{formations[-1]}",
          flush=True)
    evals = {d: {"ranked": [], "fails": {}, "waived": 0} for d in formations}
    prices = {}  # ticker -> {"dates": [...], "o": [...], "c": [...]}
    failures = []
    for t in lr.POOL:
        try:
            cik = lr.cik_for(t)
        except KeyError:
            failures.append((t, "no CIK"))
            continue
        try:
            facts = lr.load_facts(cik)
        except Exception as e:  # noqa
            failures.append((t, f"facts failed: {e}"))
            continue
        ename = facts.get("entityName", "?")
        if t in lr.NAME_HINTS and lr.NAME_HINTS[t].lower() not in ename.lower():
            failures.append((t, f"entityName mismatch: {ename!r}"))
            continue
        try:
            payload = lr.yahoo_payload(t)
            if not payload["chart"]["result"]:
                raise RuntimeError("empty chart")
        except Exception as e:  # noqa
            failures.append((t, f"yahoo failed: {e}"))
            continue
        bars = lr.bars_adj(payload)
        prices[t] = {"dates": [b["d"] for b in bars],
                     "o": [round(b["o"], 4) for b in bars],
                     "c": [round(b["c"], 4) for b in bars]}
        maps = build_maps(facts)
        shares_rows = lr.shares_chain(facts)
        for d in formations:
            CUR_ASOF[0] = d
            so = champ.pit_value(shares_rows, d)
            px, _ = lr.actual_close_on_or_before(payload, d)
            info, why = evaluate(maps, so[2] if so else None, px)
            if info is not None:
                evals[d].setdefault("elig", {})[t] = info
            else:
                evals[d]["fails"][why] = evals[d]["fails"].get(why, 0) + 1
        del facts, payload, maps
        gc.collect()
        print(f"stage1: {t} done", flush=True)
    prices["SPY"] = {"dates": [b["d"] for b in spy_bars],
                     "o": [round(b["o"], 4) for b in spy_bars],
                     "c": [round(b["c"], 4) for b in spy_bars]}
    for d in formations:
        elig = evals[d].pop("elig", {})
        evals[d]["ranked"] = rank_pool(elig)
        evals[d]["eligible"] = len(elig)
        evals[d]["waived"] = sum(1 for v in elig.values() if v["margin_waived"])
    with open(EVAL_CACHE, "w") as f:
        json.dump({"formations": evals, "load_failures": failures}, f)
    with open(PRICE_CACHE, "w") as f:
        json.dump(prices, f)
    print(f"stage1 DONE: failures={failures}", flush=True)

# ------------------------------------------------------------ stage 2
class Book:
    def __init__(self, prices):
        self.dates = prices["SPY"]["dates"]
        self.data = prices
        self.idx = {t: {d: i for i, d in enumerate(p["dates"])}
                    for t, p in prices.items()}

    def bar(self, t, d):
        p = self.data.get(t)
        if not p:
            return None
        i = self.idx[t].get(d)
        return (p["o"][i], p["c"][i]) if i is not None else None

    def close_le(self, t, d):
        p = self.data.get(t)
        if not p:
            return None
        import bisect
        i = bisect.bisect_right(p["dates"], d) - 1
        return p["c"][i] if i >= 0 else None

    def last_date(self, t):
        p = self.data.get(t)
        return p["dates"][-1] if p and p["dates"] else None

def simulate(book, evals, start, end, n_hold, placebo_rng=None):
    cash = START_CASH
    positions = {}
    trades, total_costs = [], 0.0
    curve, pools = [], []
    days = [d for d in book.dates if start <= d <= end]
    form_set = {d for d in days if d in evals}
    pending = None
    floor_breach = None

    def close_val(t, d):
        ld = book.last_date(t)
        if ld is None or d > ld:
            return 0.0
        c = book.close_le(t, d)
        return c if c else 0.0

    def pclose(d):
        return cash + sum(sh * close_val(t, d) for t, sh in positions.items())

    def execute(d, targets):
        nonlocal cash, total_costs
        opens = {}
        for t in set(list(positions) + list(targets)):
            ld = book.last_date(t)
            if ld is None or d > ld:
                continue
            b = book.bar(t, d)
            if b:
                opens[t] = b[0]
        for t in list(positions):
            if t not in opens:
                ld = book.last_date(t)
                if ld is not None and d > ld:
                    del positions[t]
                continue
            cur = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur > tgt + 0.005:
                sv = cur - tgt
                sh = sv / opens[t]
                c = sv * SELL_COST + SELL_FEE
                cash += sv - c
                total_costs += c
                positions[t] -= sh
                trades.append((d, t, "SELL", round(sh, 6), opens[t],
                               round(sv, 2), round(c, 2)))
                if positions[t] < 1e-9:
                    del positions[t]
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur = positions.get(t, 0.0) * opens[t]
            bv = tgt - cur
            if bv > 0.005:
                bv = min(bv, cash / 1.001)
                if bv <= 0.005:
                    continue
                sh = bv / opens[t]
                c = bv * BUY_COST
                cash -= bv + c
                total_costs += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", round(sh, 6), opens[t],
                               round(bv, 2), round(c, 2)))

    for d in days:
        if pending is not None:
            execute(d, pending)
            pending = None
        if d in form_set:
            ranked = evals[d]["ranked"]
            if placebo_rng is not None:
                k = len(ranked) if n_hold == "ALL" else min(n_hold, len(ranked))
                picks = placebo_rng.sample(ranked, k) if k else []
            else:
                picks = ranked if n_hold == "ALL" else ranked[:n_hold]
            pools.append({"date": d, "eligible": evals[d]["eligible"],
                          "picks": picks, "fails": evals[d]["fails"],
                          "waived_margin": evals[d]["waived"]})
            pv = pclose(d)
            pending = {t: pv / len(picks) for t in picks} if picks else {}
        v = pclose(d)
        curve.append((d, round(v, 4)))
        if floor_breach is None and v <= 85.0:
            floor_breach = d
    last = days[-1]
    for t in list(positions):
        c_ = close_val(t, last)
        if c_ > 0:
            val = positions[t] * c_
            cst = val * SELL_COST + SELL_FEE
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", round(positions[t], 6), c_,
                           round(val, 2), round(cst, 2)))
        del positions[t]
    return {"final": round(cash, 2), "costs": round(total_costs, 2),
            "trades": trades, "curve": curve, "pools": pools,
            "floor_breach_diagnostic": floor_breach}

def spy_net(book, start, end):
    days = [d for d in book.dates if start <= d <= end]
    o = book.bar("SPY", days[0])[0]
    sh = (START_CASH / 1.001) / o
    val = sh * book.close_le("SPY", days[-1])
    return round(val - (val * 0.001 + 0.01), 2)

def period_stats(curve, freq):
    ends = {}
    for d, v in curve:
        ends[d[:4] if freq == "A" else d[:7]] = v
    keys = sorted(ends)
    vals = [START_CASH] + [ends[k] for k in keys]
    rets = [(vals[i] / vals[i - 1] - 1) * 100 for i in range(1, len(vals))
            if vals[i - 1] > 0]
    if not rets:
        return None
    pos = sum(1 for r in rets if r > 0)
    run = worst = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        worst = max(worst, run)
    peak, since, longest = vals[0], 0, 0
    for v in vals[1:]:
        if v > peak:
            peak, longest, since = v, max(longest, since), 0
        else:
            since += 1
    return {"periods": len(rets),
            "pct_periods_profitable": round(100 * pos / len(rets), 1),
            "median_period_pct": round(statistics.median(rets), 3),
            "best_period_pct": round(max(rets), 2),
            "worst_period_pct": round(min(rets), 2),
            "longest_losing_run_periods": worst,
            "longest_stretch_between_new_highs_periods": max(longest, since),
            "average_period_pct_SECONDARY_LABELED_AVERAGE":
                round(statistics.mean(rets), 3)}

def max_dd(curve):
    peak, mdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return round(mdd * 100, 2)

def stage2():
    with open(EVAL_CACHE) as f:
        ec = json.load(f)
    evals = ec["formations"]
    with open(PRICE_CACHE) as f:
        prices = json.load(f)
    book = Book(prices)
    out = {"label": "JUDGMENT-CONSTRUCTED — Buffett qualitative/moat",
           "native_N": NATIVE_N, "grid": [str(g) for g in GRID],
           "load_failures": ec["load_failures"], "roads": {}}
    for rname, ws, we in ROADS:
        spy = spy_net(book, ws, we)
        road = {"spy_net": spy, "by_N": {}, "placebos_N5": None}
        for n in GRID:
            r = simulate(book, evals, ws, we, n)
            road["by_N"][str(n)] = {
                "final": r["final"], "costs": r["costs"],
                "orders": len(r["trades"]),
                "max_drawdown_pct": max_dd(r["curve"]),
                "floor_breach_diagnostic": r["floor_breach_diagnostic"],
                "pools": r["pools"], "curve": r["curve"],
                "trades": r["trades"]}
            print(f"{rname} N={n}: final=${r['final']:,.2f} "
                  f"costs=${r['costs']:.2f} orders={len(r['trades'])} "
                  f"maxDD={max_dd(r['curve'])}% spy=${spy}", flush=True)
        finals = []
        for seed in range(1, 21):
            rng = random.Random(1000 + seed)
            rp = simulate(book, evals, ws, we, NATIVE_N, placebo_rng=rng)
            finals.append(round(rp["final"], 2))
        real5 = road["by_N"]["5"]["final"]
        sfin = sorted(finals)
        road["placebos_N5"] = {
            "seeds": 20, "finals": finals,
            "median": round(statistics.median(sfin), 2),
            "best": sfin[-1], "worst": sfin[0],
            "strategy_beats_n_of_20": sum(1 for v in finals if real5 > v)}
        print(f"{rname} placebos: median=${statistics.median(sfin):,.2f} "
              f"best=${sfin[-1]:,.2f} worst=${sfin[0]:,.2f} "
              f"beats {sum(1 for v in finals if real5 > v)}/20", flush=True)
        curve5 = road["by_N"]["5"]["curve"]
        road["period_stats_N5"] = {
            "annual_native_tempo": period_stats(curve5, "A"),
            "monthly_secondary": period_stats(curve5, "M")}
        out["roads"][rname] = road
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE — results.json written", flush=True)

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "stage1"):
        stage1()
    if which in ("all", "stage2"):
        stage2()
