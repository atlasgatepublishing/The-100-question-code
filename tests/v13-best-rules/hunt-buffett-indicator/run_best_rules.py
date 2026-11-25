#!/usr/bin/env python3
"""Buffett Indicator — v13 BEST RULES. Implements BEST-RULES-SPEC.md exactly
(frozen before this run):
  signal (monthly) = Wilshire 5000 month-end level / nominal GDP x100,
    GDP quarter used from ~1 month after quarter-end (advance-estimate
    timing, v12 rule; current-vintage FRED GDP — named fallback, ALFRED
    vintages need an API key; bias flatters mildly, printed).
  transform = percentile of current monthly ratio within prior 120 monthly
    readings (min 60; current reading excluded — no look-ahead).
  quarterly checks (last trading day Mar/Jun/Sep/Dec, decide at close,
    execute next open); percentile ladder:
      <=20 -> 100% SPY | 20-40 -> 85% | 40-60 -> 70% | 60-80 -> 55%
      80-95 -> 40% | >95 -> 25%.  Never 0%, never leveraged.
Costs 0.10%/side + $0.01 sell fee (program standard, v12 semantics).
Cash 0%. NO floor. Placebos: circular shifts of the road's quarterly
target-weight series (20 seeds), preserving the weight distribution.
Also re-runs the v12 binary form (>=115 cash / <=90 SPY, monthly) on
identical plumbing as an engine-validation comparator — must reproduce
$175.26 / $100.00 / $100.00 / $100.00. Simulation only.
Label: Claude-designed rules for a gauge Buffett never published as a
system — NOT a Buffett system."""
import csv, json, os, random, statistics, time

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
GDP_CSV = os.path.join(HERE, "data", "gdp.csv")
W5_JSON = os.path.join(HERE, "data", "w5000.json")
START = 100.0
COST = 0.001
SELLFEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
V12 = {"LONG": 175.26, "DECADE": 100.00, "CONT": 100.00, "VAL": 100.00}


def load_bars():
    j = json.load(open(PX))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    return bars


def load_gdp():
    gdp = []
    for row in csv.reader(open(GDP_CSV)):
        if row and row[0] and row[0][0].isdigit():
            try: gdp.append((row[0], float(row[1])))
            except ValueError: pass
    gdp.sort()
    return gdp


def gdp_available(gdp, d):
    """Latest GDP quarter whose advance estimate is out by date d:
    quarter starting qd becomes usable 1 month after quarter-END, i.e.
    quarter-start + 4 months (v12 rule: start+3mo to reach quarter end
    month, release at end of that month, approximated as day-28 of
    start+3 months in v12 code — replicated exactly for validation)."""
    val = None
    for qd, v in gdp:
        y, m = int(qd[:4]), int(qd[5:7])
        am = m + 3; ay = y + (am - 1) // 12; am = (am - 1) % 12 + 1
        if f"{ay:04d}-{am:02d}-28" <= d:
            val = v
    return val


def load_w5000_monthly():
    """Yahoo monthly bars for ^W5000 (period1/period2 query, interval=1mo).
    Bar timestamps are Europe/London midnights (the index's exchange tz):
    in BST months the UTC stamp reads 23:00 on the last day of the prior
    month, so the bar's month MUST be taken in Europe/London — a GMT read
    mislabels Apr-Oct bars one month early (caught in QA: Octobers missing,
    Marches doubled). Each monthly bar's close is that month's close."""
    from zoneinfo import ZoneInfo
    from datetime import datetime
    london = ZoneInfo("Europe/London")
    j = json.load(open(W5_JSON))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    try: adj = r["indicators"]["adjclose"][0]["adjclose"]
    except Exception: adj = q["close"]
    monthly = {}
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None:
            continue
        mk = datetime.fromtimestamp(t, london).strftime("%Y-%m")
        monthly[mk] = adj[i]
    return monthly


def build_ratio_monthly(gdp, wmonthly):
    ratio = {}
    for mk in sorted(wmonthly):
        # decision date = last day of month mk; use GDP available by the
        # month-end date approximated as mk + "-28" via a probe date:
        # replicate v12: gdp_available(month_last_trading_day). We do not
        # have W5000 trading days here separate from months, so probe with
        # the 28th — the v12 engine probed with the actual last SPY
        # trading day (>=28th always); the quarter-release boundary in
        # gdp_available is day-28, so any probe date >=28th of the month
        # gives the identical quarter. Safe.
        g = gdp_available(gdp, mk + "-28")
        if g:
            ratio[mk] = wmonthly[mk] / g * 100.0
    return ratio


def build_percentiles(ratio):
    months = sorted(ratio)
    pct = {}
    for i, mk in enumerate(months):
        prior = [ratio[m] for m in months[max(0, i - 120):i]]
        if len(prior) < 60:
            continue
        cur = ratio[mk]
        below = sum(1 for v in prior if v < cur)
        equal = sum(1 for v in prior if v == cur)
        pct[mk] = (below + 0.5 * equal) / len(prior) * 100.0
    return pct


def ladder(p):
    if p is None: return None
    if p <= 20: return 1.00
    if p <= 40: return 0.85
    if p <= 60: return 0.70
    if p <= 80: return 0.55
    if p <= 95: return 0.40
    return 0.25


def month_end_checks(bars):
    seen = {}
    for b in bars:
        seen[b["d"][:7]] = b["d"]
    return sorted((d, m) for m, d in seen.items())


def run_ladder(bars, by_date, qchecks, pct, start, end, shift_seed=None):
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    rel = [(d, m) for d, m in qchecks if d < days[0]][-1:] + \
          [(d, m) for d, m in qchecks if days[0] <= d <= end]
    targets = [ladder(pct.get(m)) for d, m in rel]
    assert all(t is not None for t in targets), f"missing percentile for a check in {start}..{end}"
    if shift_seed is not None and len(targets) > 1:
        rng = random.Random(shift_seed)
        k = rng.randrange(1, len(targets))
        targets = targets[k:] + targets[:k]
    tmap = {d: w for (d, m), w in zip(rel, targets)}
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    pending = None
    if rel and rel[0][0] < days[0]:
        pending = tmap[rel[0][0]]

    def rebalance(d, price, w):
        nonlocal cash, shares, costs
        eq = cash + shares * price
        want = w * eq
        have = shares * price
        if want > have + 1e-9:
            bv = min(want - have, cash / (1 + COST))
            if bv > 0.01:
                c = bv * COST; shares += bv / price; cash -= bv + c; costs += c
                trades.append([d, "BUY", round(price, 4), round(bv, 2), round(c, 2)])
        elif want < have - 1e-9:
            sv = have - want
            c = sv * COST + SELLFEE; shares -= sv / price; cash += sv - c; costs += c
            trades.append([d, "SELL", round(price, 4), round(sv, 2), round(c, 2)])

    wdays = 0.0; wsum = 0.0; floor_days = 0
    cur_w = pending
    for d in days:
        bar = by_date[d]
        if pending is not None:
            rebalance(d, bar["o"], pending); cur_w = pending; pending = None
        if d in tmap and d >= days[0]:
            pending = tmap[d]
        eq = cash + shares * bar["c"]
        if eq > 0:
            w = shares * bar["c"] / eq
            wsum += w; wdays += 1
            if cur_w is not None and abs(cur_w - 0.25) < 1e-9:
                floor_days += 1
        curve.append([d, round(eq, 4)])
    if shares > 0:
        last = days[-1]; val = shares * by_date[last]["c"]; c = val * COST + SELLFEE
        cash += val - c; costs += c; shares = 0.0
        trades.append([last, "SELL-END", round(by_date[last]["c"], 4), round(val, 2), round(c, 2)])
        curve[-1] = [last, round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "checks": len(rel), "avg_weight_pct": round(100.0 * wsum / wdays, 1) if wdays else 0.0,
            "floor_weight_days_pct": round(100.0 * floor_days / wdays, 1) if wdays else 0.0,
            "weights_used": sorted(set(targets)), "equity_curve": curve}


def run_binary_v12(bars, ratio, start, end):
    """v12 constructed form on identical plumbing: monthly check at last
    trading day; ratio>=115 -> cash; <=90 -> SPY; between -> hold; next open.
    State decided in month M applies during month M+1 (v12 semantics)."""
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    by_date = {b["d"]: b for b in bars}
    month_last = {}
    for b in bars:
        month_last[b["d"][:7]] = b["d"]
    state_by_month = {}
    pos = 0
    for mk in sorted(month_last):
        if mk in ratio:
            r = ratio[mk]
            if r >= 115: pos = 0
            elif r <= 90: pos = 1
        state_by_month[mk] = pos
    states = []
    for d in [b["d"] for b in bars]:
        mk = d[:7]; y, m = int(mk[:4]), int(mk[5:7]); pm = m - 1; py = y
        if pm == 0: pm = 12; py -= 1
        states.append(state_by_month.get(f"{py:04d}-{pm:02d}", 0))
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    cash, shares, costs = START, 0.0, 0.0
    for j, i in enumerate(idx):
        b = bars[i]
        if j > 0:
            want = states[idx[j - 1]]
            if want == 1 and shares == 0:
                spend = cash * (1 - COST); costs += cash * COST
                shares = spend / b["o"]; cash = 0.0
            elif want == 0 and shares > 0:
                proceeds = shares * b["o"] * (1 - COST) - SELLFEE
                costs += shares * b["o"] * COST + SELLFEE
                cash = proceeds; shares = 0.0
    final = cash + shares * bars[idx[-1]]["c"]
    if shares > 0:
        final = cash + shares * bars[idx[-1]]["c"] * (1 - COST) - SELLFEE
    return round(final, 2)


def spy_hold(bars, by_date, start, end):
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    o = by_date[days[0]]["o"]; sh = (START / 1.001) / o
    val = sh * by_date[days[-1]]["c"]
    return round(val - (val * 0.001 + 0.01), 2)


def distribution(curve):
    years = {}
    for d, v in curve:
        y = d[:4]
        if y not in years: years[y] = [v, v]
        years[y][1] = v
    rets = []
    base = START
    for y in sorted(years):
        s, e = years[y]
        rets.append((y, round(100.0 * (e / base - 1), 1)))
        base = e
    vals = [r for _, r in rets]
    pos = sum(1 for v in vals if v > 0)
    streak = cur = 0
    for v in vals:
        cur = cur + 1 if v < 0 else 0
        streak = max(streak, cur)
    peak = -1.0; last_high = 0; longest = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak:
            peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(curve) - 1 - last_high)
    return {"median_year_pct": round(statistics.median(vals), 1) if vals else None,
            "share_positive_pct": round(100.0 * pos / len(vals), 1) if vals else None,
            "years": len(vals), "positive_years": pos,
            "best_year": max(rets, key=lambda t: t[1]) if rets else None,
            "worst_year": min(rets, key=lambda t: t[1]) if rets else None,
            "longest_losing_streak_yrs": streak,
            "longest_between_highs_days": longest,
            "mean_year_pct_secondary": round(statistics.mean(vals), 1) if vals else None,
            "year_returns": rets}


def main():
    bars = load_bars(); by_date = {b["d"]: b for b in bars}
    gdp = load_gdp(); wmonthly = load_w5000_monthly()
    ratio = build_ratio_monthly(gdp, wmonthly)
    pct = build_percentiles(ratio)
    checks = month_end_checks(bars)
    qc = [(d, m) for d, m in checks if m[5:7] in ("03", "06", "09", "12")]
    print(f"bars {bars[0]['d']}->{bars[-1]['d']} ({len(bars)}); GDP rows {len(gdp)}; "
          f"W5000 months {len(wmonthly)}; ratio months {len(ratio)} "
          f"({min(ratio)}->{max(ratio)}); percentile months {len(pct)}; quarter checks {len(qc)}")
    print("ratio sample:", {k: round(ratio[k], 1) for k in sorted(ratio)[-4:]})
    print("pct sample:", {k: round(pct[k], 1) for k in sorted(pct)[-4:]})
    out = {"family": "hunt-buffett-indicator", "program": "v13-best-rules",
           "form": "MY RULES: quarterly checks, trailing-120mo percentile of Wilshire/GDP ratio, ladder 100/85/70/55/40/25% SPY, advance-timing GDP (current vintage, named fallback), program costs, no floor",
           "label": "Claude-designed rules; Buffett published a gauge, never a system. Comparison form is the v12 CONSTRUCTED binary 115/90 timer.",
           "data_note": "GDP: FRED current vintage (ALFRED vintage retrieval requires API key — v12 spec fallback, bias FLATTERS mildly). Numerator: Yahoo ^W5000 level as WILL5000INDFC-equivalent. Copies in data/.",
           "ratio_sample_end": {k: round(ratio[k], 1) for k in sorted(ratio)[-6:]},
           "roads": {}}
    for name, (s, e) in ROADS.items():
        r = run_ladder(bars, by_date, qc, pct, s, e)
        spy = spy_hold(bars, by_date, s, e)
        binc = run_binary_v12(bars, ratio, s, e)
        placebos, beaten = [], None
        if len(r["weights_used"]) <= 1:
            pnote = "degenerate: target weight never changes on this road; shifted twins are identical"
        else:
            for seed in range(1, 21):
                pr = run_ladder(bars, by_date, qc, pct, s, e, shift_seed=seed)
                placebos.append(pr["final"])
            beaten = sum(1 for p in placebos if r["final"] > p)
            pnote = f"real beats {beaten}/20 shifted-weight twins"
        dist = distribution(r["equity_curve"])
        out["roads"][name] = {**r, "spy_same_plumbing": spy, "spy_program_ref": SPYREF[name],
                              "champion_vm": CHAMP[name], "v12_constructed_ref": V12[name],
                              "v12_binary_same_plumbing": binc,
                              "validation_ok": (binc == V12[name]),
                              "drag_vs_spy": round(r["final"] - spy, 2),
                              "placebo_finals": placebos, "placebos_beaten": beaten,
                              "placebo_note": pnote, "distribution": dist}
        print(f"{name}: mine ${r['final']} maxDD {r['max_dd_pct']}% costs ${r['costs']} orders {r['orders']} "
              f"avgW {r['avg_weight_pct']}% floorDays {r['floor_weight_days_pct']}% | "
              f"v12 same-plumbing ${binc} (ref ${V12[name]}, ok={binc == V12[name]}) SPY ${spy} "
              f"champ ${CHAMP[name]} placebos beaten {beaten}")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
