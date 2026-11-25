#!/usr/bin/env python3
"""Graham Defensive-Investor seven tests (Intelligent Investor ch.14)
— CONSTRUCTED implementation per SPEC-FROZEN.md, on the W04 broad
stack. Annual formation in DECEMBER (spec's constructed cadence) on
data filed by then (snapshot(F) = CY F-1 fundamentals), hold 12
months, equal weight, sell at next formation if failing (the annual
re-formation IS the sell rule). Tests, exactly as published:
 1 sales >= $100M in 1973 dollars, CPI-adjusted (CPI-U 1973 annual
   average 44.4, BLS; formation-year CPI from FRED CPIAUCNS annual
   average of CY F-1) — CONSTRUCTED adjustment per spec;
 2 current ratio >= 2 AND long-term debt <= net current assets
   (missing LTD data = FAIL, conservative);
 3 positive earnings each of the past 10 years (EDGAR frames
   NetIncomeLoss CY2010+; formations therefore start Dec 2020);
 4 uninterrupted dividends for 20 years (Yahoo dividend-event
   history: >= 1 payment in every calendar year F-20..F-1 and no
   gap > 18 months; missing record = FAIL per spec);
 5 EPS up >= 1/3 over 10 years, 3-yr averages both ends
   (EPS = NetIncomeLoss / shares outstanding as filed — the frames
   stack has no diluted-EPS series; approximation printed);
 6 price <= 15 x 3-yr average EPS (raw Dec price, as-filed EPS);
 7 price <= 1.5 x book value, or P/E x P/B <= 22.5 (published offset).
Industrials only (financials/utilities excluded per Graham's variant
split). Rank for grid counts: lowest P/E x P/B (spec's constructed
tiebreak). Costs: W04 tiered rates. NATIVE: no floor (none
published). HOUSE: v9 -15% floor at monthly marks, 3-month sit-out,
one restart, second halt ends. Placebos: 20 seeds, random names from
the data-complete industrial pool at the qualifier count.
50/50 stock/bond split: descriptive line only (spec), not a run.
Simulation only."""
import json, os, sys, random, statistics, importlib.util, csv, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

HERE = os.path.dirname(os.path.abspath(__file__))
ENG = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/engine_w04.py")
spec = importlib.util.spec_from_file_location("engine_w04", ENG)
eng = importlib.util.module_from_spec(spec); spec.loader.exec_module(eng)
eng.D = eng.Data(); D = eng.D
W04F = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/_w04_broad_data/frames")
EXTF = os.path.join(HERE, "data", "frames_ext")

def loadf(name, year, kind):
    for base in (EXTF, W04F):
        p = os.path.join(base, f"{name}_{year}{kind}.json")
        if os.path.exists(p):
            return {int(k): v for k, v in json.load(open(p)).items()}
    return {}
NI = {y: loadf("NetIncomeLoss", y, "D") for y in range(2010, 2026)}
SH = {y: loadf("Shares", y, "I") for y in range(2010, 2026)}

cpi = {}
with open(os.path.join(HERE, "data", "FRED_CPIAUCNS.csv")) as f:
    for row in csv.reader(f):
        if len(row) == 2 and row[0][0].isdigit() and row[1] not in ("", "."):
            cpi.setdefault(row[0][:4], []).append(float(row[1]))
CPI = {y: sum(v) / len(v) for y, v in cpi.items()}
CPI_1973 = 44.4  # BLS CPI-U annual average, 1973

DIVS = {}
def div_years(ticker):
    if ticker not in DIVS:
        p = os.path.join(HERE, "data", "divs", ticker.replace("/", "-") + ".json")
        ev = json.load(open(p)) if os.path.exists(p) else {}
        DIVS[ticker] = sorted(int(k) for k in ev.keys())
    return DIVS[ticker]

def eps(cik, y):
    ni = NI[y].get(cik); sh = SH[y].get(cik)
    if ni is None or not sh: return None
    return ni / sh

def evaluate(F):
    """Returns (qualifiers ranked by PExPB, pool of data-complete
    industrials, per-test pass counts). F = December formation year;
    fundamentals = snapshot(F) (CY F-1)."""
    s = eng.snapshot(F)
    thr = 100e6 * CPI[str(F - 1)] / CPI_1973
    quals = []; pool = []
    counts = {i: 0 for i in range(1, 8)}
    for cik, v in s.items():
        sic = v["sic"]
        if eng.is_fin(sic) or eng.is_util(sic) or sic in (0, 9999): continue
        pxr = D.price(cik, f"{F}-12", adj=False)
        if not pxr or not v["equity"] or v["equity"] <= 0: continue
        nis = [NI[y].get(cik) for y in range(F - 10, F)]
        if any(x is None for x in nis): continue
        epss = [eps(cik, y) for y in range(F - 10, F)]
        if any(x is None for x in epss): continue
        pool.append(cik)
        t = [False] * 7
        t[0] = v["rev"] is not None and v["rev"] >= thr
        t[1] = (v["ca"] is not None and v["cl"] not in (None, 0) and v["ltd"] is not None
                and v["ca"] >= 2 * v["cl"] and v["ltd"] <= v["ca"] - v["cl"])
        t[2] = all(x > 0 for x in nis)
        ev = div_years(v["ticker"])
        yrs = {time.gmtime(ts).tm_year for ts in ev}
        t[3] = all(y in yrs for y in range(F - 20, F))
        if t[3]:
            win = [ts for ts in ev if F - 20 <= time.gmtime(ts).tm_year <= F - 1]
            gaps = [b - a for a, b in zip(win, win[1:])]
            if gaps and max(gaps) > 548 * 86400: t[3] = False
        e_first = sum(epss[:3]) / 3; e_last = sum(epss[-3:]) / 3
        t[4] = e_first > 0 and e_last >= (4 / 3) * e_first
        pe = pxr / e_last if e_last > 0 else None
        t[5] = pe is not None and pe <= 15
        shares = SH[F - 1].get(cik)
        pb = (pxr * shares / v["equity"]) if shares else None
        t[6] = pb is not None and (pb <= 1.5 or (pe is not None and pe * pb <= 22.5))
        for i in range(7): counts[i + 1] += 1 if t[i] else 0
        if all(t):
            quals.append((pe * pb, cik))
    quals.sort()
    return [c for _, c in quals], pool, counts

def annual_run(formations, form="native", count="ALL", seed=None):
    cash = 100.0; curve = []; costs = 0.0; trades = 0; yearly = []
    anchor = 100.0; halts = 0; sitout_until = None; ended = False
    QUALS = {}
    for F in formations:
        q, pool, _ = evaluate(F)
        QUALS[F] = (q, pool)
    for F in formations:
        q, pool = QUALS[F]
        if seed is not None:
            rng = random.Random(seed * 7919 + F)
            keys = list(pool); rng.shuffle(keys)
            picks = keys[:len(q)] if count == "ALL" else keys[:count]
        else:
            picks = q if count == "ALL" else q[:count]
        months = [f"{F}-12"] + [f"{F+1}-{m:02d}" for m in range(1, 13)]
        months = [m for m in months if m <= "2026-11"]
        start_val = cash
        if ended or not picks:
            for m in months[1:]: curve.append([m, round(cash, 4)])
            yearly.append({"formation": F, "n": len(picks), "ret": 0.0})
            continue
        if sitout_until and months[0] < sitout_until:
            for m in months[1:]: curve.append([m, round(cash, 4)])
            yearly.append({"formation": F, "n": len(picks), "ret": 0.0, "note": "sit-out"})
            continue
        s = eng.snapshot(F)
        w = cash / len(picks); pos = {}
        for c in picks:
            p0 = D.price(c, f"{F}-12", adj=True)
            if not p0: continue
            rate = eng.cost_rate(s[c]["cap"]); costs += w * rate; trades += 1
            pos[c] = (w - w * rate) / p0
        halted_mid = False
        for m in months[1:]:
            val = 0.0
            for c, shn in pos.items():
                p = D.price(c, m, adj=True)
                if p is None: p = D.price(c, f"{F}-12", adj=True)
                if not D.has_price_month(c, m) and max(D.px.get(c, {"": 0}).keys() or [""]) < m:
                    p = 0.0  # delisted: written to zero
                val += shn * (p or 0.0)
            curve.append([m, round(val, 4)])
            if form == "house" and val <= 0.85 * anchor and not halted_mid:
                # liquidate at this mark
                c_cost = sum((val / len(pos)) * eng.cost_rate(s[c]["cap"]) for c in pos)
                costs += c_cost; trades += len(pos); val -= c_cost
                curve[-1] = [m, round(val, 4)]
                halts += 1; halted_mid = True
                if halts >= 2: ended = True
                else:
                    y2, m2 = int(m[:4]), int(m[5:7]) + 3
                    if m2 > 12: y2 += 1; m2 -= 12
                    sitout_until = f"{y2:04d}-{m2:02d}"
                    anchor = val
                cash = val
                pos = {}
                # remaining months flat
                idx = months.index(m)
                for m3 in months[idx + 1:]: curve.append([m3, round(cash, 4)])
                break
        if halted_mid:
            yearly.append({"formation": F, "n": len(picks), "ret": round(cash / start_val - 1, 4), "note": "halted"})
            continue
        end_val = 0.0
        last_m = months[-1]
        for c, shn in pos.items():
            p = D.price(c, last_m, adj=True)
            if p is None: p = D.price(c, f"{F}-12", adj=True)
            if not D.has_price_month(c, last_m) and max(D.px.get(c, {"": 0}).keys() or [""]) < last_m:
                p = 0.0
            gross = shn * (p or 0.0)
            rate = eng.cost_rate(s[c]["cap"]); costs += gross * rate; trades += 1
            end_val += gross - gross * rate
        cash = end_val
        yearly.append({"formation": F, "n": len(picks), "ret": round(cash / start_val - 1, 4)})
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    return {"final": round(cash, 2), "curve": curve, "costs": round(costs, 2),
            "trades": trades, "halts": halts, "max_dd": round(maxdd, 4), "yearly": yearly}

def spy_final(a, b):
    va = D.spy.get(a); vb = D.spy.get(b)
    return round(100 * vb / va, 2) if va and vb else None

def astats(yearly):
    rets = [y["ret"] for y in yearly]
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    return {"periods": len(rets), "share_positive": round(pos / len(rets), 3),
            "median": round(statistics.median(rets), 4), "best": round(max(rets), 4),
            "worst": round(min(rets), 4), "longest_losing_streak": streak,
            "average_secondary": round(sum(rets) / len(rets), 4)}

def main():
    out = {"family": "hunt-graham-defensive", "constructed": True, "roads": {}}
    census = {}
    for F in range(2020, 2026):
        q, pool, counts = evaluate(F)
        census[F] = {"qualifiers": len(q), "pool": len(pool), "per_test_pass": counts}
        print("formation", F, census[F], flush=True)
    out["census"] = census
    ROADS = {"FULL": list(range(2020, 2026)), "VAL": list(range(2023, 2026))}
    for road, forms_ in ROADS.items():
        ent = {}
        for form in ("native", "house"):
            r = annual_run(forms_, form)
            ent[form] = {k: v for k, v in r.items() if k != "curve"}
            ent[form]["period_stats_annual"] = astats(r["yearly"])
            if form == "native": ent["curve_native"] = r["curve"]
        a = f"{forms_[0]}-12"; b = "2026-11"
        ent["spy_buy_hold_same_window"] = spy_final(a, b)
        out["roads"][road] = ent
        print(road, "native", ent["native"]["final"], "house", ent["house"]["final"], "spy", ent["spy_buy_hold_same_window"])
    out["placebos"] = {}
    for road, forms_ in ROADS.items():
        finals = [annual_run(forms_, "native", seed=s)["final"] for s in range(1, 21)]
        sysf = out["roads"][road]["native"]["final"]
        out["placebos"][road] = {"finals": finals, "median": round(statistics.median(finals), 2),
                                 "system_native_final": sysf,
                                 "beats": sum(1 for f in finals if sysf > f)}
        print("placebo", road, out["placebos"][road])
    grid = {}
    for count in (1, 2, 3, 5, 8, 10, 15, 20, 30, "ALL"):
        grid[str(count)] = {}
        for road, forms_ in ROADS.items():
            ent = {}
            for form in ("native", "house"):
                r = annual_run(forms_, form, count=count)
                ent[form] = {k: v for k, v in r.items() if k != "curve"}
                ent[form]["period_stats_annual"] = astats(r["yearly"])
                if form == "native": ent["curve_native"] = r["curve"]
            grid[str(count)][road] = ent
        print("grid", count, {r: grid[str(count)][r]["native"]["final"] for r in ROADS}, flush=True)
    out["holdings_grid"] = grid
    os.makedirs(os.path.join(HERE, "grid"), exist_ok=True)
    json.dump(grid, open(os.path.join(HERE, "grid", "grid_results.json"), "w"), indent=1)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
