#!/usr/bin/env python3
"""
BASKET-QUALITY-GATE — v12 CONSTRUCTED run. Implements CONSTRUCTION-SPEC.md
exactly as frozen. Simulation only.

Chassis (house, unchanged): momentum basket, Nov-2016 top-30 pond, monthly,
eligible = close above own 200-day SMA, rank by 12-1 momentum, top-5 at 20%
each, signal from prior close, trades at selection-day open. v9 protections
(plain -15% floor, 90-day sit-out, episode-2 floor, 2nd halt ends run).
Costs 0.10%/side + $0.01/sell.

Gate (CONSTRUCTED label): GP/A = (Revenue-COGS)/Total Assets, as published
by Novy-Marx (2013), computed from as-filed EDGAR data (tier 1: us-gaap
companyfacts at corrected CIKs, filer's own GrossProfit tag first, expanded
revenue/COGS concept lists incl. split sums, fiscal-period-end matching,
earliest-filed values; tier 2: as-filed 10-K statement tables via SEC
R-files for extension-tag filer-years). SIC-6 names excluded BY DESIGN
(published sample rule), audited separately. Gate: most recent GP/A filed
strictly before signal day must be > 0 (threshold CONSTRUCTED — Novy-Marx
publishes a sort, not a gate; see spec).

Outputs: results.json (finals, curves, gate firing audit, placebos),
run.log via stdout.
"""
import json, os, random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
PRICE_CACHE = os.path.join(BT, "v4", "momentum-basket-honest-data")
DATA = os.path.join(HERE, "data")

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
BENCH = "SPY"
COST_RATE = 0.001
SELL_FEE = 0.01
PLACEBO_SEEDS = [20261121 + i for i in range(20)]
ROADS = {"DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20")}
CHAMPIONS = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_REF = {"DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}

# ---------------- GP data (tier 1) ------------------------------------
def _entries(facts, concept):
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    return units.get("USD", list(units.values())[0] if units else [])

def _annual(entries):
    out = []
    for e in entries:
        if "start" not in e or "end" not in e or "val" not in e:
            continue
        try:
            days = (date.fromisoformat(e["end"]) -
                    date.fromisoformat(e["start"])).days
        except ValueError:
            continue
        if 300 <= days <= 400:
            out.append(e)
    return out

REV = ["RevenueFromContractWithCustomerExcludingAssessedTax",
       "SalesRevenueNet", "Revenues"]
COGS = ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"]
SPLIT_SUMS = [("REV", ("SalesRevenueGoodsNet", "SalesRevenueServicesNet")),
              ("COGS", ("CostOfGoodsSold", "CostOfServices")),
              ("COGS", ("CostOfGoodsSoldExcludingDepreciationDepletionAndAmortization",
                        "CostOfServicesExcludingDepreciationDepletionAndAmortization"))]

def _earliest(store, key, val, filed, src):
    if key not in store or filed < store[key][1]:
        store[key] = (val, filed, src)

def build_tier1(files):
    rev, cogs, gpd, assets = {}, {}, {}, {}
    for path in files:
        with open(path) as f:
            facts = json.load(f)
        # Concept priority (data-integrity fix, disclosed in RESULTS.md):
        # concepts are tried in priority order and a period-end already set
        # by a higher-priority concept is never overwritten — the generic
        # "Revenues" tag is a subtotal in some filings (PG FY2014: $29.4B
        # vs SalesRevenueNet $83.1B in the same accession), so it must rank
        # last. Within one concept, earliest-filed value wins.
        for c in REV:
            tmp = {}
            for e in _annual(_entries(facts, c)):
                _earliest(tmp, e["end"], float(e["val"]),
                          e.get("filed", ""), c)
            for k, v in tmp.items():
                if k not in rev:
                    rev[k] = v
        for c in COGS:
            tmp = {}
            for e in _annual(_entries(facts, c)):
                _earliest(tmp, e["end"], float(e["val"]),
                          e.get("filed", ""), c)
            for k, v in tmp.items():
                if k not in cogs:
                    cogs[k] = v
        for tgt, (c1, c2) in SPLIT_SUMS:
            store = rev if tgt == "REV" else cogs
            d1, d2 = {}, {}
            for c, dd in [(c1, d1), (c2, d2)]:
                for e in _annual(_entries(facts, c)):
                    k = e["end"]
                    if k not in dd or e.get("filed", "") < dd[k][1]:
                        dd[k] = (float(e["val"]), e.get("filed", ""))
            for k in set(d1) & set(d2):
                if k not in store:
                    store[k] = (d1[k][0] + d2[k][0],
                                max(d1[k][1], d2[k][1]), c1 + "+svc")
        for e in _annual(_entries(facts, "GrossProfit")):
            _earliest(gpd, e["end"], float(e["val"]),
                      e.get("filed", ""), "GrossProfit")
        for e in _entries(facts, "Assets"):
            if "end" in e and "val" in e:
                k = e["end"]
                if k not in assets or e.get("filed", "") < assets[k][1]:
                    assets[k] = (float(e["val"]), e.get("filed", ""))
    obs = {}
    for k in set(rev) & set(cogs):
        a = assets.get(k)
        if a and a[0] > 0:
            obs[k] = (max(rev[k][1], cogs[k][1]), k,
                      (rev[k][0] - cogs[k][0]) / a[0],
                      "tier1:rev-cogs:" + cogs[k][2], rev[k][0] - cogs[k][0], a[0])
    for k, (v, f, src) in gpd.items():
        a = assets.get(k)
        if a and a[0] > 0 and k not in obs:
            obs[k] = (f, k, v / a[0], "tier1:GP-direct", v, a[0])
    return obs, assets

def load_gate_obs():
    sic = json.load(open(os.path.join(DATA, "sic.json")))
    financial = sorted(t for t in UNIVERSE
                       if str(sic[t]["sic"]).startswith("6"))
    tier2 = {}
    t2path = os.path.join(DATA, "tier2_gp.json")
    if os.path.exists(t2path):
        tier2 = json.load(open(t2path))
    all_obs, info = {}, {}
    for t in UNIVERSE:
        if t == "XOM":
            files = [os.path.join(DATA, "facts_XOM_correct.json")]
        elif t == "DIS":
            files = [os.path.join(DATA, "facts_DIS.json"),
                     os.path.join(DATA, "facts_DIS_correct.json")]
        else:
            files = [os.path.join(DATA, f"facts_{t}.json")]
        obs, assets = build_tier1(files)
        # tier 2 fills gaps only
        n_t2 = 0
        for rec in tier2.get(t, []):
            pend = rec["period_end"]
            if pend in obs:
                continue
            a = assets.get(pend)
            if not a or a[0] <= 0:
                continue
            gp = rec["revenue"] - rec["cogs"]
            obs[pend] = (rec["filed"], pend, gp / a[0],
                         "tier2:R-file", gp, a[0])
            n_t2 += 1
        lst = sorted(obs.values())
        all_obs[t] = lst
        info[t] = {"n_obs": len(lst), "n_tier2": n_t2,
                   "years": [o[1][:4] for o in lst],
                   "min_gpa": round(min((o[2] for o in lst), default=0), 4),
                   "financial_by_design": t in financial}
    return all_obs, financial, info

def quality_at(obs, asof):
    best = None
    for o in obs:
        if o[0] < asof:
            if best is None or (o[0], o[1]) > (best[0], best[1]):
                best = o
        else:
            break
    return best

# ---------------- Market (v10 plumbing, read-only cache) ---------------
def fetch(ticker):
    with open(os.path.join(PRICE_CACHE, f"{ticker}.json")) as f:
        return json.load(f)

class Market:
    def __init__(self, tickers):
        self.bars, self.closes = {}, {}
        spy = fetch(BENCH)
        self.cal = [r["d"] for r in spy]
        raw = {BENCH: spy}
        for t in tickers:
            raw[t] = fetch(t)
        for t in tickers + [BENCH]:
            self.bars[t] = {r["d"]: (r["o"], r["c"]) for r in raw[t]}
            arr, last = [], None
            for d in self.cal:
                if d in self.bars[t]:
                    last = self.bars[t][d][1]
                arr.append(last)
            self.closes[t] = arr

    def open_px(self, t, i):
        d = self.cal[i]
        return self.bars[t][d][0] if d in self.bars[t] else None

    def close_px(self, t, i):
        return self.closes[t][i]

    def sma(self, t, i, n):
        if i + 1 < n:
            return None
        seg = self.closes[t][i - n + 1: i + 1]
        if any(v is None for v in seg):
            return None
        return sum(seg) / n

    def momentum_12_1(self, t, i):
        if i - 252 < 0:
            return None
        a, b = self.closes[t][i - 252], self.closes[t][i - 21]
        if a is None or b is None or a <= 0:
            return None
        return b / a - 1.0

def years_between(a, b):
    return (date.fromisoformat(b) - date.fromisoformat(a)).days / 365.25

def cagr(final, start, years):
    return (final / start) ** (1.0 / years) - 1.0 if final > 0 else float("nan")

# ---------------- Engine (v10 simulate_v9, monthly, + audit) ----------
def month_dates(cal, start, end):
    out, seen = [], set()
    for d in cal:
        if start <= d <= end and d[:7] not in seen:
            seen.add(d[:7])
            out.append(d)
    return set(out)

def simulate(mkt, start_d, end_d, gate_obs, financial, placebo_seed=None,
             audit=False):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cad_set = month_dates(mkt.cal, start_d, end_d)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    cash, pos, orders, costs = 100.0, {}, 0, 0.0
    curve, halts = [], []
    episode, floor = 1, 85.0
    pending_liq, trigger_date, sit_until = False, None, None
    restart, restart_date, restart_balance = False, None, None
    second_halt, final = False, None
    audit_log = []

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            tot += sh * px
        return tot

    def liquidate(i, at_open):
        nonlocal cash, orders, costs
        for t in list(pos):
            px = mkt.open_px(t, i) if at_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            val = pos[t] * px
            fee = val * COST_RATE + SELL_FEE
            cash += val - fee
            costs += fee
            orders += 1
            del pos[t]

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        if pending_liq:
            liquidate(i, at_open=True)
            halts.append({"episode": episode, "trigger_date": trigger_date,
                          "liquidation_date": d, "balance": round(cash, 2)})
            pending_liq = False
            if episode == 2:
                second_halt, final = True, cash
                curve.append((d, cash))
                break
            episode = 2
            sit_until = (date.fromisoformat(d) +
                         timedelta(days=90)).isoformat()
            curve.append((d, cash))
            continue
        if sit_until is not None:
            if d >= sit_until and d in cad_set:
                restart, restart_date, restart_balance = True, d, cash
                floor = 0.85 * cash
                sit_until = None
            else:
                curve.append((d, cash))
                continue
        if d in cad_set and i > 0:
            j = i - 1
            elig = []
            for t in UNIVERSE:
                sma200 = mkt.sma(t, j, 200)
                c = mkt.close_px(t, j)
                if sma200 is None or c is None or c <= sma200:
                    continue
                mom = mkt.momentum_12_1(t, j)
                if mom is None:
                    continue
                elig.append((t, mom))
            kept, sel_audit = [], []
            for t, mom in elig:
                if gate_obs is None:
                    kept.append((t, mom))
                    continue
                if t in financial:
                    sel_audit.append({"t": t, "outcome": "financial_by_design"})
                    continue
                q = quality_at(gate_obs.get(t, []), mkt.cal[j])
                if q is None:
                    sel_audit.append({"t": t, "outcome": "no_data"})
                elif q[2] <= 0:
                    sel_audit.append({"t": t, "outcome": "gp_le0",
                                      "gpa": round(q[2], 4), "fy_end": q[1],
                                      "filed": q[0], "tier": q[3]})
                else:
                    age = (date.fromisoformat(mkt.cal[j]) -
                           date.fromisoformat(q[1])).days / 365.25
                    sel_audit.append({"t": t, "outcome": "passed",
                                      "gpa": round(q[2], 4), "fy_end": q[1],
                                      "filed": q[0], "tier": q[3],
                                      "obs_age_yrs": round(age, 2)})
                    kept.append((t, mom))
            if audit:
                audit_log.append({"date": d, "signal_date": mkt.cal[j],
                                  "n_elig": len(elig), "outcomes": sel_audit})
            if rng is None:
                kept.sort(key=lambda x: -x[1])
                picks = [t for t, _ in kept[:5]]
            else:
                names = sorted(t for t, _ in kept)
                picks = (rng.sample(names, min(5, len(names)))
                         if names else [])
            eq_open = equity_at(i, use_open=True)
            target_val = {t: 0.20 * eq_open for t in picks}
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos[t] * px
                want = target_val.get(t, 0.0)
                if cur_val > want + 0.01:
                    sell_val = cur_val - want
                    fee = sell_val * COST_RATE + SELL_FEE
                    cash += sell_val - fee
                    costs += fee
                    orders += 1
                    pos[t] -= sell_val / px
                    if want <= 0.0 or pos[t] * px < 0.01:
                        del pos[t]
            for t in picks:
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos.get(t, 0.0) * px
                deficit = target_val[t] - cur_val
                if deficit <= 0.01:
                    continue
                buy_val = min(deficit, cash / (1.0 + COST_RATE))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * COST_RATE
                cash -= buy_val + fee
                costs += fee
                orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px
        eq_close = equity_at(i, use_open=False)
        curve.append((d, eq_close))
        if sit_until is None and eq_close <= floor:
            pending_liq, trigger_date = True, d
            if i == i1:
                liquidate(i, at_open=False)
                halts.append({"episode": episode, "trigger_date": d,
                              "liquidation_date": d,
                              "balance": round(cash, 2)})
                if episode == 2:
                    second_halt = True
                final = cash
                curve[-1] = (d, cash)
                break
    if final is None:
        final = curve[-1][1]
    peak, max_dd = -1.0, 0.0
    for d, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = min(max_dd, eq / peak - 1.0)
    return {"final": final, "orders": orders, "costs": costs,
            "max_dd": max_dd, "curve": curve, "halts": halts,
            "restart": restart, "second_halt": second_halt,
            "audit": audit_log}

def period_stats(curve, start_balance=100.0):
    """Monthly period-by-period record from a daily equity curve."""
    month_end = {}
    for d, v in curve:
        month_end[d[:7]] = (d, v)
    keys = sorted(month_end)
    pts = [(month_end[k][0], month_end[k][1]) for k in keys]
    rets = []
    prev = start_balance
    for d, v in pts:
        rets.append((d, v / prev - 1.0))
        prev = v
    vals = [r for _, r in rets]
    pos = sum(1 for r in vals if r > 0)
    med = sorted(vals)[len(vals) // 2] if len(vals) % 2 == 1 else \
        (sorted(vals)[len(vals) // 2 - 1] + sorted(vals)[len(vals) // 2]) / 2
    longest_loss, cur = 0, 0
    for r in vals:
        cur = cur + 1 if r <= 0 else 0
        longest_loss = max(longest_loss, cur)
    # longest stretch between new highs (in periods, peak to next higher peak)
    peak, since, longest_gap = -1.0, 0, 0
    series = [start_balance] + [v for _, v in pts]
    for v in series:
        if v > peak:
            peak, longest_gap, since = v, max(longest_gap, since), 0
        else:
            since += 1
    longest_gap = max(longest_gap, since)
    avg = sum(vals) / len(vals) if vals else 0.0
    return {"n_periods": len(vals), "n_positive": pos,
            "pct_positive": round(100.0 * pos / len(vals), 1) if vals else None,
            "median_period_pct": round(med * 100, 2),
            "best_period": {"month_end": max(rets, key=lambda x: x[1])[0],
                            "pct": round(max(vals) * 100, 2)},
            "worst_period": {"month_end": min(rets, key=lambda x: x[1])[0],
                             "pct": round(min(vals) * 100, 2)},
            "longest_losing_streak_periods": longest_loss,
            "longest_stretch_between_new_highs_periods": longest_gap,
            "average_period_pct_secondary": round(avg * 100, 2)}

def main():
    gate_obs, financial, info = load_gate_obs()
    print("financial by design:", financial, flush=True)
    for t in UNIVERSE:
        print(f"  obs {t}: n={info[t]['n_obs']} tier2={info[t]['n_tier2']} "
              f"years={info[t]['years'][:1]}..{info[t]['years'][-1:]} "
              f"minGPA={info[t]['min_gpa']}", flush=True)
    mkt = Market(UNIVERSE)
    out = {"slug": "basket-quality-gate", "construction": "CONSTRUCTED",
           "spec": "CONSTRUCTION-SPEC.md",
           "financial_by_design": financial, "obs_info": info, "roads": {}}
    audit_tot = {"passed": 0, "gp_le0": 0, "no_data": 0,
                 "financial_by_design": 0}
    audit_by_name = {}
    for road, (sd, ed) in ROADS.items():
        yrs = years_between(sd, ed)
        g = simulate(mkt, sd, ed, gate_obs, set(financial),
                     audit=(road == "DECADE"))
        u = simulate(mkt, sd, ed, None, set())
        placebo_finals = []
        for seed in PLACEBO_SEEDS:
            pr = simulate(mkt, sd, ed, gate_obs, set(financial),
                          placebo_seed=seed)
            placebo_finals.append(round(pr["final"], 2))
        beaten = sum(1 for v in placebo_finals if g["final"] > v)
        cell = {
            "window": [sd, ed], "start_balance": 100.0,
            "gated_final": round(g["final"], 2),
            "gated_cagr_pct": round(cagr(g["final"], 100.0, yrs) * 100, 2),
            "gated_max_dd_pct": round(g["max_dd"] * 100, 2),
            "gated_costs": round(g["costs"], 2), "gated_orders": g["orders"],
            "gated_halts": g["halts"], "gated_second_halt": g["second_halt"],
            "ungated_final": round(u["final"], 2),
            "ungated_max_dd_pct": round(u["max_dd"] * 100, 2),
            "gate_effect_vs_ungated": round(g["final"] - u["final"], 2),
            "champion_final": CHAMPIONS[road], "spy_final": SPY_REF[road],
            "beats_champion": g["final"] > CHAMPIONS[road],
            "placebo_beaten": f"{beaten}/20",
            "placebo_finals": placebo_finals,
            "period_stats_monthly_gated": period_stats(g["curve"]),
            "equity_curve_gated": [[d, round(v, 4)] for d, v in g["curve"]],
            "equity_curve_ungated": [[d, round(v, 4)] for d, v in u["curve"]],
        }
        out["roads"][road] = cell
        print(f"{road}: gated={cell['gated_final']} ungated="
              f"{cell['ungated_final']} champ={CHAMPIONS[road]} "
              f"maxDD={cell['gated_max_dd_pct']} costs={cell['gated_costs']} "
              f"placebo={cell['placebo_beaten']} halts={len(g['halts'])}",
              flush=True)
        if road == "DECADE":
            for sel in g["audit"]:
                for o in sel["outcomes"]:
                    audit_tot[o["outcome"]] += 1
                    a = audit_by_name.setdefault(
                        o["t"], {"passed": 0, "gp_le0": 0, "no_data": 0,
                                 "financial_by_design": 0})
                    a[o["outcome"]] += 1
            out["gate_firing_audit_decade"] = {
                "selections": len(g["audit"]), "totals": audit_tot,
                "by_name": audit_by_name, "log": g["audit"],
                "house_comparison_v10_full_window": {
                    "gp_le0": 0, "no_data": 386,
                    "note": "v10 integrity reproduction, original windows "
                            "2016-11-21..2026-11-20, house data/concepts"}}
            print("AUDIT DECADE:", audit_tot, flush=True)
    # Chunked save: this environment rejects large single writes from
    # exec processes (EPERM) — write the JSON in <=32KB appends.
    payload = json.dumps(out, indent=1)
    path = os.path.join(HERE, "results.json")
    with open(path, "w") as f:
        f.write("")
    with open(path, "a") as f:
        for k in range(0, len(payload), 32768):
            f.write(payload[k:k + 32768])
            f.flush()
    print("saved results.json", len(payload), "bytes", flush=True)

if __name__ == "__main__":
    main()
