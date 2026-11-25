#!/usr/bin/env python3
"""V13 BEST RULES — hunt-dividend-seasonality. Design frozen in
BEST-RULES-SPEC.md BEFORE this run. Universe: PIT S&P 500 members that paid
a dividend in trailing 12m. Signal: expected payer in month m of year y iff
ex-date in month m of year y-1 (own history, PIT). Holdings: top-20 expected
payers ranked by most-recent payment amount / adjusted price at formation,
equal weight at entry. Monthly formation (first trading day); membership-
change trading only (no re-equalization); NO floor. Costs: 0.10%/side +
$0.01 per sell order. Returns on adjusted (total-return) closes.
Placebo: phase-shifted calendars (each name's expected-month pattern
shifted by a random 1..11 months), 20 seeds, DECADE + VAL.
Data: cache.pkl built by prep_cache.py from the v12 gap-a10 Yahoo cache
(read-only) — raw payloads with dividend events + PIT membership file."""
import bisect, json, os, pickle, random, statistics
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
COST = 0.001; SELL_FEE = 0.01; TOPN = 20
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}

C = pickle.load(open(os.path.join(HERE, "cache.pkl"), "rb"))
MEMBER, DATA = C["member"], C["data"]
for t, rec in DATA.items():
    rec["adjmap"] = dict(zip(rec["dates"], rec["adj"]))
    rec["div_dates"] = [d for d, _ in rec["divs"]]
SPY_DATES, SPY_ADJ = C["spy_dates"], dict(zip(C["spy_dates"], C["spy_adj"]))

def is_member(t, d):
    return any(s <= d <= e for s, e in MEMBER.get(t, []))

def last_amt(rec, asof):
    """Most recent dividend amount with ex-date in (asof-365d, asof]; None if none."""
    lo = (date.fromisoformat(asof) - timedelta(days=365)).isoformat()
    i = bisect.bisect_right(rec["div_dates"], asof) - 1
    if i < 0 or rec["div_dates"][i] <= lo: return None
    return rec["divs"][i][1]

def formation_candidates(d):
    """All PIT member payers with a price at formation d:
    (ticker, imminent_yield, set_of_expected_months_this_year)."""
    y = int(d[:4])
    out = []
    for t, rec in DATA.items():
        px = rec["adjmap"].get(d)
        if not px or not is_member(t, d): continue
        amt = last_amt(rec, d)
        if amt is None: continue
        out.append((t, amt / px, rec["pay_months"].get(y - 1, set())))
    out.sort(key=lambda x: (-x[1], x[0]))
    return out

def run(start, end, shifts=None):
    days = [d for d in SPY_DATES if start <= d <= end]
    formations = {}
    for d in days: formations.setdefault(d[:7], d)
    form_days = set(formations.values())
    cand_cache = {}
    cash = 100.0; pos = {}; curve = []; ntr = 0; costs = 0.0; lastpx = {}
    for d in days:
        for t in pos:
            p = DATA[t]["adjmap"].get(d)
            if p: lastpx[t] = p
        if d in form_days:
            if d not in cand_cache: cand_cache[d] = formation_candidates(d)
            m = int(d[5:7])
            keep = []
            for t, yld, months in cand_cache[d]:
                sh = (shifts or {}).get(t, 0)
                mm = ((m - 1 + sh) % 12) + 1
                if mm in months: keep.append(t)
                if len(keep) >= TOPN: break
            keep_t = set(keep)
            for t in list(pos):
                if t not in keep_t:
                    v = pos[t] * lastpx.get(t, 0)
                    cash += v * (1 - COST) - SELL_FEE; costs += v * COST + SELL_FEE
                    del pos[t]; ntr += 1
            eq = cash + sum(sh * lastpx.get(t, 0) for t, sh in pos.items())
            if keep_t:
                target = eq / len(keep_t)
                for t in keep:
                    if t in pos: continue
                    px = DATA[t]["adjmap"][d]
                    buy = min(target, cash / (1 + COST))
                    if buy <= 0: continue
                    pos[t] = buy / px; cash -= buy * (1 + COST)
                    costs += buy * COST; ntr += 1; lastpx[t] = px
        eq = cash + sum(sh * lastpx.get(t, 0) for t, sh in pos.items())
        curve.append((d, round(eq, 4)))
    if pos and curve:
        liq = sum(sh * lastpx.get(t, 0) for t, sh in pos.items())
        costs += liq * COST + SELL_FEE * len(pos); ntr += len(pos)
        curve[-1] = (curve[-1][0], round(curve[-1][1] - liq * COST - SELL_FEE * len(pos), 4))
    return {"final": round(curve[-1][1], 2) if curve else 100.0, "curve": curve,
            "trades": ntr, "costs": round(costs, 2)}

def buyhold(start, end):
    days = [d for d in SPY_DATES if start <= d <= end]
    sh = (100.0 / (1 + COST)) / SPY_ADJ[days[0]]
    v = sh * SPY_ADJ[days[-1]]
    return round(v - v * COST - SELL_FEE, 2)

def max_dd(curve):
    peak, mdd = -1.0, 0.0
    for _d, v in curve:
        peak = max(peak, v)
        if peak > 0: mdd = max(mdd, (peak - v) / peak)
    return round(mdd * 100, 2)

def period_stats(curve):
    ends, order = {}, []
    for d, v in curve:
        if d[:7] not in ends: order.append(d[:7])
        ends[d[:7]] = v
    vals = [ends[k] for k in order]
    rets, prev = [], 100.0
    for v in vals:
        rets.append(v / prev - 1.0); prev = v
    if not rets: return None
    ll, cur = 0, 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; ll = max(ll, cur)
    peak, since, gap = -1.0, 0, 0
    for v in vals:
        if v >= peak: peak, since = v, 0
        else: since += 1; gap = max(gap, since)
    return {"periods": len(rets), "pct_positive": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2), "best_pct": round(max(rets) * 100, 2),
            "worst_pct": round(min(rets) * 100, 2), "longest_losing_streak": ll,
            "longest_between_new_highs": gap, "average_pct_secondary": round(statistics.mean(rets) * 100, 2)}

def main():
    print(f"tickers with data: {len(DATA)}", flush=True)
    out = {"family": "hunt-dividend-seasonality", "program": "v13-best-rules",
           "form": "PIT SP500 payers; expected-month signal (y-1 pattern); top-20 by imminent yield; monthly; membership-change trading only; NO floor; costs 0.10%/side + $0.01/sell"}
    cells = {}
    for road, (s, e) in ROADS.items():
        r = run(s, e)
        cells[road] = {"final": r["final"], "maxdd_pct": max_dd(r["curve"]), "trades": r["trades"],
                       "costs": r["costs"], "spy_buyhold": buyhold(s, e),
                       "periods_monthly": period_stats(r["curve"]), "curve": r["curve"]}
        print(road, r["final"], "DD", cells[road]["maxdd_pct"], "trades", r["trades"], "costs", r["costs"], flush=True)
    out["roads"] = cells
    for road in ["DECADE", "VAL"]:
        s, e = ROADS[road]
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed * 31)
            shifts = {t: rng.randrange(1, 12) for t in DATA}
            finals.append(run(s, e, shifts=shifts)["final"])
        out[f"placebo_phase_shift_{road}"] = {"median": round(statistics.median(finals), 2),
            "n_beaten_by_real": sum(1 for f in finals if cells[road]["final"] > f), "finals": finals}
        print("placebo", road, out[f"placebo_phase_shift_{road}"]["median"],
              out[f"placebo_phase_shift_{road}"]["n_beaten_by_real"], flush=True)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
