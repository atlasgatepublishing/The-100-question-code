#!/usr/bin/env python3
"""
STANDALONE QUALITY RANKING (Novy-Marx 2013 gross profitability) — Terry's
AI stock app. Simulation only.

THE RULE (frozen before the run):
  - Universe / engine / costs / protection: IDENTICAL to the champion
    value-momentum-plainfloor.py — honest point-in-time top-30 as of
    Nov 2016, SEC EDGAR point-in-time facts, quarterly selection (first
    trading day of Jan/Apr/Jul/Oct), rebalance at next open, top-5 equal
    weight, costs 0.10%/side + $0.01/sell, plain -15% floor ($85 on the
    $100 pot), no ladder.
  - THE ONLY CHANGE is the ranking. PURE quality, no value leg, no
    momentum leg:
        score = gross profits / total assets
    Gross profits computed with the champion program's established
    machinery (quality-momentum.py / basket-quality-gate.py, verbatim):
    (Revenue - COGS) / Assets from a SINGLE filing (same accession, same
    annual 300-400 day period; Assets from the same filing at the period
    end); if a name has no COGS-based observations at all, the machinery's
    own fallback is Operating Income / Assets from the same structure
    (flagged OPINC). Point-in-time: observations FILED strictly before
    the selection date, with the champion engine's ~18-month (548-day)
    filed-freshness gate.
  - ROA SUBSTITUTION (per the task spec): a name whose gross profit is
    not reported in a comparable way — determined mechanically as having
    NO usable GP/OPINC observation filed on/after 2017-07-03 (548 days
    before the first selection), i.e. banks (no COGS, no operating-income
    line), integrated energy (XOM), and Berkshire (insurer/conglomerate;
    its only OPINC observations were last filed 2013-03-01 and fail the
    freshness gate at every selection date) — is scored instead by
        ROA = trailing filed fiscal-year NetIncomeLoss / Assets
    (income: 300-400 day duration facts, NetIncomeLoss > ProfitLoss
    priority, per value-momentum-ey.py; assets: the Assets fact at the
    same fiscal-year end filed before the selection date, else the most
    recently filed Assets fact, same freshness gate). Every substitution
    is logged by name and date.
  - Names that cannot be scored at a selection date (no usable
    observation yet — e.g. DIS/JNJ/KO, whose current-CIK facts start
    during 2019) are excluded that quarter, never patched — the champion
    engine's standard treatment.

Runs (once, no tuning): ranked + 20-seed placebo on FULL
2019-01-02 -> 2026-11-20 and VALIDATION 2023-01-03 -> 2026-11-20;
walk-forward folds (fresh $100 per calendar year 2020-2026 vs SPY net,
vm-walkforward.py methodology). $100 pots only (the task's judging
frame). A replication check first re-runs the champion V+M spec through
the imported engine and must reproduce $544.47 / $288.05 before any
quality number is trusted.

Data: the champion test's caches, read-only (v4/data +
v4/value-momentum-honest-data) via the imported engine's own loaders.
"""
import importlib.util
import json
import os
import random
import time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
PLACEBO_SEEDS = list(range(1, 21))
START_CASH = 100.0
FLOOR0 = 85.0
FRESH_DAYS = 548
# a GP observation filed before this date can never pass the freshness
# gate at the first selection date (2019-01-02 minus 548 days)
FIRST_SEL_CUTOFF = "2017-07-03"

REV_CONCEPTS = ["RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues", "SalesRevenueNet"]
COGS_CONCEPTS = ["CostOfRevenue", "CostOfGoodsAndServicesSold",
                 "CostOfGoodsSold"]
OPINC_CONCEPT = "OperatingIncomeLoss"
ASSETS_CONCEPT = "Assets"

# ------------------------------------------------------- quality observations
# (build_quality_observations copied verbatim from quality-momentum.py)
def _entries(facts, concept):
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else list(units)[0]
    return units[key]

def _annual(entries):
    """Keep duration entries whose period looks like a fiscal year."""
    out = []
    for e in entries:
        if "start" not in e or "end" not in e or "val" not in e:
            continue
        try:
            days = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days
        except ValueError:
            continue
        if 300 <= days <= 400:
            out.append(e)
    return out

def build_quality_observations(facts):
    """Return sorted list of (filed, end, quality, method).
    GP observations: (Revenue - COGS)/Assets within one filing (accn) and one
    annual period, Assets from the same filing at the period end.
    OPINC observations (fallback): OperatingIncomeLoss/Assets, same structure.
    """
    assets_by_accn = {}
    for e in _entries(facts, ASSETS_CONCEPT):
        if "val" not in e or "end" not in e:
            continue
        accn = e.get("accn", "")
        assets_by_accn.setdefault(accn, {})[e["end"]] = (float(e["val"]), e.get("filed", ""))

    def assets_for(accn, period_end):
        m = assets_by_accn.get(accn, {})
        if period_end in m:
            return m[period_end][0]
        earlier = [en for en in m if en <= period_end]
        if earlier:
            return m[max(earlier)][0]
        return None

    def by_accn_period(concepts):
        """accn -> {(start,end): (val, filed)} using concept priority order."""
        out = {}
        for concept in concepts:
            for e in _annual(_entries(facts, concept)):
                accn = e.get("accn", "")
                key = (e["start"], e["end"])
                slot = out.setdefault(accn, {})
                if key not in slot:  # higher-priority concept wins
                    slot[key] = (float(e["val"]), e.get("filed", ""))
        return out

    rev = by_accn_period(REV_CONCEPTS)
    cogs = by_accn_period(COGS_CONCEPTS)
    obs = []
    for accn, periods in rev.items():
        for (start, end), (rval, rfiled) in periods.items():
            c = cogs.get(accn, {}).get((start, end))
            if c is None:
                continue
            a = assets_for(accn, end)
            if a is None or a <= 0:
                continue
            filed = max(rfiled, c[1])
            obs.append((filed, end, (rval - c[0]) / a, "GP"))
    if not obs:
        op = by_accn_period([OPINC_CONCEPT])
        for accn, periods in op.items():
            for (start, end), (oval, ofiled) in periods.items():
                a = assets_for(accn, end)
                if a is None or a <= 0:
                    continue
                obs.append((ofiled, end, oval / a, "OPINC"))
    obs.sort()
    return obs

def pit_series_income(facts):
    """Trailing ANNUAL NetIncomeLoss rows: (filed, end, val, prio).
    Copied from value-momentum-ey.py: NetIncomeLoss (prio 2) merged with
    ProfitLoss (prio 1); only 300-400 day (fiscal-year) periods."""
    rows = []
    for concept, prio in (("NetIncomeLoss", 2), ("ProfitLoss", 1)):
        try:
            units = facts["facts"]["us-gaap"][concept]["units"]
        except KeyError:
            continue
        key = "USD" if "USD" in units else list(units)[0]
        for e in units[key]:
            if "filed" not in e or "val" not in e or "start" not in e or "end" not in e:
                continue
            dur = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days
            if 300 <= dur <= 400:
                rows.append((e["filed"], e["end"], float(e["val"]), prio))
    return rows

def _ord(dstr):
    return date(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()

def quality_value(qdata, t, asof):
    """(value, method) for ticker t at selection date asof, or None.
    GP/OPINC names: most recently filed observation strictly before asof
    passing the 548-day freshness gate. ROA names: trailing filed
    fiscal-year net income / assets (assets matched to the income
    period end where available)."""
    q = qdata[t]
    if not q["roa"]:
        cutoff = _ord(asof) - FRESH_DAYS
        best = None
        for filed, end, val, method in q["obs"]:
            if filed < asof and _ord(filed) >= cutoff:
                if best is None or (filed, end) > (best[0], best[1]):
                    best = (filed, end, val, method)
        if best is None:
            return None
        return best[2], best[3]
    # ROA substitution
    inc = E.pit_value(q["income_rows"], asof, max_age_days=FRESH_DAYS)
    if inc is None:
        return None
    inc_filed, inc_end, inc_val = inc
    # assets at the same fiscal-year end, filed before asof
    cand = None
    cutoff = _ord(asof) - FRESH_DAYS
    for filed, end, val, prio in q["assets_rows"]:
        if end == inc_end and filed < asof and _ord(filed) >= cutoff and val > 0:
            if cand is None or (filed, prio) > (cand[0], cand[1]):
                cand = (filed, prio, val)
    if cand is not None:
        assets = cand[2]
    else:
        a = E.pit_value(q["assets_rows"], asof, max_age_days=FRESH_DAYS)
        if a is None or a[2] <= 0:
            return None
        assets = a[2]
    return inc_val / assets, "ROA"

# ------------------------------------------------------------------ engine
# run_pot copied from value-momentum-plainfloor.py with ONLY the selection
# block changed (quality score instead of book-to-market + momentum).
# Execution, costs, floor, halt and liquidation mechanics are byte-identical
# in behavior.
def run_pot_q(pb, qdata, start, end, start_cash, floor0, ladder,
              placebo_rng=None, label="", quiet=False, record_pools=False):
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    pools = []
    sel_dates = E.quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
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
            scores = {}
            methods = {}
            for t in UNIVERSE:
                qv = quality_value(qdata, t, d)
                if qv is None:
                    continue
                scores[t] = qv[0]
                methods[t] = qv[1]
            if len(scores) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    picks = sorted(scores, key=lambda t: (-scores[t], t))[:5]
                if record_pools:
                    pools.append({"date": d, "pool": sorted(scores),
                                  "methods": {t: methods[t] for t in sorted(scores)},
                                  "scores": {t: round(scores[t], 6) for t in sorted(scores)},
                                  "picks": list(picks)})
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                if not quiet:
                    print(f"  [{label}] {d} pool={len(scores)} picks={picks} pot=${pv:,.2f}", flush=True)
        v = portfolio_close(d)
        curve.append((d, v))
        for thresh, newfloor in ladder:
            if v >= thresh and newfloor > floor:
                floor = newfloor
        if v <= floor and di < len(days) - 1:
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
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "pools": pools, "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "pools": pools, "curve": curve}

def curve_stats(r):
    curve = r["curve"]
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return {"max_drawdown_pct": round(maxdd * 100, 2), "max_drawdown_date": maxdd_d,
            "orders": len(r["trades"]), "costs": round(r["costs"], 2),
            "halted": r["halted"], "final": round(r["final"], 2)}

def placebo_block(pb, qdata, ws, we, ranked_final):
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = run_pot_q(pb, qdata, ws, we, START_CASH, FLOOR0, [],
                       placebo_rng=rng, label=f"PLACEBO {seed}", quiet=True)
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"], "orders": len(pr["trades"]),
                     "costs": round(pr["costs"], 2)})
        print(f"  PLACEBO seed {seed:2d}: final=${pr['final']:,.2f} halted={pr['halted']}", flush=True)
    srt = sorted(finals)
    below = sum(1 for f in finals if f < ranked_final)
    return {"median": round(E._pct(srt, 0.50), 2), "q1": round(E._pct(srt, 0.25), 2),
            "q3": round(E._pct(srt, 0.75), 2), "best": round(srt[-1], 2),
            "worst": round(srt[0], 2), "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for p in rows if p["halted"]),
            "ranked_final": round(ranked_final, 2), "seeds_beaten": below,
            "rows": rows}

# --------------------------------------------------------------------- main
def main():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    qdata = {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        obs = build_quality_observations(facts)
        usable = [o for o in obs if o[0] >= FIRST_SEL_CUTOFF]
        qdata[t] = {"obs": obs,
                    "roa": len(usable) == 0,
                    "income_rows": pit_series_income(facts),
                    "assets_rows": E.pit_series(facts, "us-gaap", "Assets")}
        print(f"{t}: GP/OPINC obs={len(obs)} (usable {len(usable)}) "
              f"roa_substitution={qdata[t]['roa']} income_rows={len(qdata[t]['income_rows'])} "
              f"assets_rows={len(qdata[t]['assets_rows'])}", flush=True)
        time.sleep(0.05)
    roa_names = sorted(t for t in UNIVERSE if qdata[t]["roa"])
    print("ROA SUBSTITUTION NAMES:", roa_names, flush=True)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    pb = E.PriceBook(bars)

    out = {"strategy": "standalone quality ranking (gross profits/assets; ROA substitution documented)",
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0,
           "roa_substitution_names": roa_names,
           "quality_data": {t: {"n_obs": len(qdata[t]["obs"]),
                                "methods_present": sorted({o[3] for o in qdata[t]["obs"]}),
                                "first_filed": qdata[t]["obs"][0][0] if qdata[t]["obs"] else None,
                                "last_filed": qdata[t]["obs"][-1][0] if qdata[t]["obs"] else None,
                                "roa": qdata[t]["roa"]} for t in UNIVERSE}}

    # ---- replication check: champion V+M through the imported engine
    rep = {}
    for wname, ws, we in (("FULL", "2019-01-02", "2026-11-20"),
                          ("VALIDATION", "2023-01-03", "2026-11-20")):
        r = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                      FLOOR0, [], label=f"REPL {wname}", quiet=True)
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        rep[wname] = {"vm_final": round(r["final"], 2), "spy_net": round(s, 2)}
        print(f"REPLICATION {wname}: V+M=${r['final']:,.2f} SPY=${s:,.2f} "
              f"(expect 544.47/313.62 FULL, 288.05/187.77 VALIDATION)", flush=True)
    out["replication_champion"] = rep

    # ---- ranked quality runs + placebo
    for wname, ws, we in (("FULL", "2019-01-02", "2026-11-20"),
                          ("VALIDATION", "2023-01-03", "2026-11-20")):
        r = run_pot_q(pb, qdata, ws, we, START_CASH, FLOOR0, [],
                      label=f"QUALITY {wname}", quiet=True, record_pools=True)
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        st = curve_stats(r)
        st.update({"start": ws, "end": we,
                   "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
                   "spy_net_final": round(s, 2),
                   "spy_return_pct": round(s / START_CASH * 100 - 100, 2),
                   "diag": E.diagnostics(r, FLOOR0),
                   "pools": r["pools"]})
        print(f"== QUALITY {wname}: final=${r['final']:,.2f} ({st['return_pct']:+.2f}%) "
              f"maxDD={st['max_drawdown_pct']}% orders={st['orders']} costs=${st['costs']} "
              f"halted={r['halted']} | SPY net=${s:,.2f}", flush=True)
        st["placebo"] = placebo_block(pb, qdata, ws, we, r["final"])
        print(f"   PLACEBO {wname}: median=${st['placebo']['median']:,.2f} "
              f"best=${st['placebo']['best']:,.2f} worst=${st['placebo']['worst']:,.2f} "
              f"halted={st['placebo']['halted_count']}/20 | ranked beats "
              f"{st['placebo']['seeds_beaten']}/20", flush=True)
        out[wname] = st

    # ---- walk-forward folds (fresh $100 per calendar year)
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot_q(pb, qdata, fs, fe, START_CASH, FLOOR0, [],
                       label=f"FOLD {y}", quiet=True)
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        fst = curve_stats(fr)
        row = {"year": y, "start": fs, "end": fe, "final": fst["final"],
               "return_pct": round(fr["final"] / START_CASH * 100 - 100, 2),
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "max_drawdown_pct": fst["max_drawdown_pct"],
               "orders": fst["orders"], "costs": fst["costs"],
               "halted": fst["halted"]}
        folds.append(row)
        print(f"FOLD {y}: QUALITY ${fr['final']:,.2f} ({row['return_pct']:+.2f}%) vs "
              f"SPY ${fspy:,.2f} ({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"maxDD={row['max_drawdown_pct']}% halted={row['halted']}", flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    # fold-compounded (chain the yearly returns)
    comp = START_CASH
    for f in folds:
        comp *= 1 + f["return_pct"] / 100.0
    out["fold_compounded_final"] = round(comp, 2)
    spy_comp = START_CASH
    for f in folds:
        spy_comp *= 1 + f["spy_return_pct"] / 100.0
    out["fold_compounded_spy"] = round(spy_comp, 2)

    with open(os.path.join(HERE, "quality-standalone-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
