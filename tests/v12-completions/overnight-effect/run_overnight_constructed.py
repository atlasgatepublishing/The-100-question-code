#!/usr/bin/env python3
"""Overnight Effect CONSTRUCTED forms (v12). Implements CONSTRUCTION-SPEC.md
exactly: SPY, dividend-adjusted bars (program lr_common convention), two
frozen forms -- OVERNIGHT (buy every close, sell next open) and INTRADAY
(buy every open, sell same close) -- whole pot, no floor, program costs at
full weight (0.10%/side + $0.01 per sell order), idle cash 0%. Placebos:
20-seed permutations of the road's segment-return sequence through the
identical cost machinery. Frictionless twins reported beside net.
Simulation only."""
import json, os, random, time

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
COST = 0.001; SELL_FEE = 0.01; START = 100.0

def load():
    j = json.load(open(PX))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["open"][i] is None or q["close"][i] is None or adj[i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"date": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "open": q["open"][i] * ratio, "close": adj[i]})
    return bars

def segments(bars, start, end, form):
    """Ordered list of (date, gross_multiplier) for each traded segment in
    the road, plus the road's day index list for curve building."""
    idx = [i for i, b in enumerate(bars) if start <= b["date"] <= end]
    segs = []
    if form == "overnight":
        for k in range(len(idx) - 1):
            i = idx[k]
            segs.append((bars[i]["date"], bars[idx[k + 1]]["open"] / bars[i]["close"]))
    else:  # intraday
        for i in idx:
            segs.append((bars[i]["date"], bars[i]["close"] / bars[i]["open"]))
    return idx, segs

def run_sequence(segs, with_costs=True):
    """Compound the pot through an ordered segment sequence. Each segment is
    one round trip: buy (COST on notional), segment move, sell (COST +
    SELL_FEE). Returns final, costs, per-segment equity list, death info.
    A cash pot cannot go negative: if a sale's proceeds net of costs are
    <= 0 the pot is dead -- cash is set to 0 and no further segment trades
    (the flat $0.01 sell fee is what delivers the killing blow once costs
    have ground the pot to cents; that is the honest arithmetic, not a
    patch -- a real pot at $0.00 cannot place the next order)."""
    cash = START; costs = 0.0; eqs = []; died = False; death_date = None
    for d, m in segs:
        if died:
            eqs.append(0.0); continue
        if with_costs:
            notional = cash / (1.0 + COST); c1 = notional * COST
            value = notional * m
            c2 = value * COST + SELL_FEE
            cash = value - c2; costs += c1 + c2
            if cash <= 0:
                cash = 0.0; died = True; death_date = d
        else:
            cash = cash * m
        eqs.append(cash)
    return cash, costs, eqs, died, death_date

def run_form(bars, start, end, form):
    idx, segs = segments(bars, start, end, form)
    final, costs, seg_eq, died, death_date = run_sequence(segs, with_costs=True)
    gross_final, _, _, _, _ = run_sequence(segs, with_costs=False)
    # daily equity curve: equity marked at each road day's close.
    # overnight: seg k's sale lands at the open of day idx[k+1]; that day's
    # close equity is the post-rebuy notional (seg-end cash / (1+COST)),
    # except on the road's last day, where no rebuy happens and equity is
    # the cash itself. intraday: flat at every close -> seg-end equity.
    curve = []
    if form == "overnight":
        eq_by_day = {}
        for k, e in enumerate(seg_eq):
            d = bars[idx[k + 1]]["date"]
            eq_by_day[d] = e / (1.0 + COST) if k < len(segs) - 1 else e
        last_eq = START / (1.0 + COST)  # first day: bought at its close
        for i in idx:
            d = bars[i]["date"]
            if d in eq_by_day:
                last_eq = eq_by_day[d]
            curve.append({"date": d, "equity": round(last_eq, 4)})
    else:
        eq_by_day = {d: e for (d, _), e in zip(segs, seg_eq)}
        for i in idx:
            curve.append({"date": bars[i]["date"], "equity": round(eq_by_day[bars[i]["date"]], 4)})
    peak = START; mdd = 0.0
    for pt in curve:
        peak = max(peak, pt["equity"])
        if peak > 0: mdd = max(mdd, (peak - pt["equity"]) / peak)
    wins = sum(1 for _, m in segs if m > 1.0)
    avg_bp = (sum(m - 1.0 for _, m in segs) / len(segs)) * 10000 if segs else 0.0
    # placebos: 20 seeded permutations of the segment sequence, same machinery
    twins = []
    base = list(segs)
    for seed in range(20):
        rng = random.Random(31000 + seed)
        perm = base[:]; rng.shuffle(perm)
        tf, _, _, _, _ = run_sequence(perm, with_costs=True)
        twins.append(round(tf, 2))
    return {"final": round(final, 2), "gross_final_no_costs": round(gross_final, 2),
            "costs": round(costs, 2), "round_trips": len(segs), "orders": 2 * len(segs),
            "pot_died": died, "death_segment_date": death_date,
            "segment_win_rate_pct": round(100 * wins / len(segs), 1) if segs else None,
            "avg_segment_bp_gross": round(avg_bp, 2),
            "max_dd_pct": round(mdd * 100, 2),
            "placebo_finals": twins,
            "placebos_beaten": sum(1 for t in twins if final > t),
            "equity_curve": curve}

def buyhold(bars, start, end):
    idx = [i for i, b in enumerate(bars) if start <= b["date"] <= end]
    sh = (START * (1 - COST)) / bars[idx[0]]["open"]
    gross = sh * bars[idx[-1]]["close"]
    return round(gross - gross * COST - SELL_FEE, 2)

def main():
    bars = load()
    roads = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
    champions = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
    spy_ref = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
    out = {"family": "overnight-effect", "label": "CONSTRUCTED (v12) -- not a published system",
           "forms": {}, "roads_meta": roads}
    for form in ("overnight", "intraday"):
        out["forms"][form] = {}
        for name, (s, e) in roads.items():
            r = run_form(bars, s, e, form)
            r["spy_buyhold_computed"] = buyhold(bars, s, e)
            r["spy_reference_program"] = spy_ref[name]
            r["champion_reference"] = champions[name]
            r["beats_champion"] = r["final"] > champions[name]
            r["beats_spy_computed"] = r["final"] > r["spy_buyhold_computed"]
            out["forms"][form][name] = r
            print(form, name, "net", r["final"], "gross", r["gross_final_no_costs"],
                  "costs", r["costs"], "trips", r["round_trips"], "avg_bp", r["avg_segment_bp_gross"],
                  "WR", r["segment_win_rate_pct"], "DD", r["max_dd_pct"],
                  "placebo", r["placebos_beaten"], "/20", "SPYbh", r["spy_buyhold_computed"],
                  "died", r["pot_died"], r["death_segment_date"])
    folds = {}
    for form in ("overnight", "intraday"):
        folds[form] = {}
        for y in range(2010, 2027):
            s = f"{y}-01-01"; e = f"{y}-12-31" if y < 2026 else "2026-11-20"
            idx, segs = segments(bars, s, e, form)
            if len(segs) < 10: continue
            f, c, _, _, _ = run_sequence(segs, with_costs=True)
            g, _, _, _, _ = run_sequence(segs, with_costs=False)
            folds[form][str(y)] = {"final": round(f, 2), "gross_final": round(g, 2), "costs": round(c, 2)}
        print(form, "folds", {k: v["final"] for k, v in folds[form].items()})
    out["year_folds"] = folds
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("wrote results.json")

if __name__ == "__main__":
    main()
