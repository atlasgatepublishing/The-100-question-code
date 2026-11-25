#!/usr/bin/env python3
"""CAPE Timing — v13 BEST RULES. Implements BEST-RULES-SPEC.md exactly
(frozen before this run): quarterly checks (last trading day of Mar/Jun/
Sep/Dec, decide at close, execute next open), signal = Shiller CAPE dated
that month (live shillerdata file preserved in the v12 folder, read-only),
graduated band ladder:
  CAPE <=15 -> 100% SPY | 15-20 -> 85% | 20-25 -> 70% | 25-30 -> 55%
  30-35 -> 40% | >35 -> 25%.  Never 0%, never leveraged.
Costs 0.10%/side + $0.01 sell fee (program standard, v12 semantics).
Cash 0%. NO floor. Placebos: circular shifts of the road's quarterly
target-weight series (20 seeds), preserving the weight distribution.
Also re-runs the v12 binary CAPE<=25 form on identical plumbing as an
engine-validation comparator. Simulation only.
Label: Claude-designed rules for a signal whose authors never published
a system — NOT a Shiller/Campbell system."""
import json, os, random, statistics, time
import xlrd

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
XLS = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/cape-timing/data/ie_data_live_shillerdata.xls")
START = 100.0
COST = 0.001
SELLFEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
V12 = {"LONG": 252.59, "DECADE": 114.81, "CONT": 114.81, "VAL": 100.00}


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


def load_cape():
    wb = xlrd.open_workbook(XLS); sh = wb.sheet_by_name("Data")
    out = {}
    for r in range(8, sh.nrows):
        d = sh.cell_value(r, 0); cape = sh.cell_value(r, 12)
        if isinstance(d, (int, float)) and d > 0 and isinstance(cape, (int, float)):
            y = int(d); m = int(round((d - y) * 100))
            out[f"{y}-{m:02d}"] = float(cape)
    return out


def ladder(cape):
    if cape is None: return 0.0
    if cape <= 15: return 1.00
    if cape <= 20: return 0.85
    if cape <= 25: return 0.70
    if cape <= 30: return 0.55
    if cape <= 35: return 0.40
    return 0.25


def month_end_checks(bars):
    seen = {}
    for b in bars:
        seen[b["d"][:7]] = b["d"]
    return sorted((d, m) for m, d in seen.items())


def quarter_checks(checks):
    return [(d, m) for d, m in checks if m[5:7] in ("03", "06", "09", "12")]


def run_ladder(bars, by_date, qchecks, cape, start, end, shift_seed=None):
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    rel = [(d, m) for d, m in qchecks if d < days[0]][-1:] + \
          [(d, m) for d, m in qchecks if days[0] <= d <= end]
    targets = [ladder(cape.get(m)) for d, m in rel]
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

    wdays = 0.0; wsum = 0.0
    for d in days:
        bar = by_date[d]
        if pending is not None:
            rebalance(d, bar["o"], pending); pending = None
        if d in tmap and d >= days[0]:
            pending = tmap[d]
        eq = cash + shares * bar["c"]
        if eq > 0:
            wsum += (shares * bar["c"] / eq); wdays += 1
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
            "weights_used": sorted(set(targets)), "equity_curve": curve}


def run_binary(bars, by_date, checks, cape, start, end):
    """v12 constructed form, identical semantics to run_cape_constructed.py."""
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    rel = [(d, m) for d, m in checks if d < days[0]][-1:] + \
          [(d, m) for d, m in checks if days[0] <= d <= end]
    tmap = {d: ("SPY" if (cape.get(m) is not None and cape.get(m) <= 25.0) else "CASH")
            for d, m in rel}
    cash, shares, costs = START, 0.0, 0.0
    trades = []; pending = None
    if rel and rel[0][0] < days[0]:
        pending = tmap[rel[0][0]]
    final = START
    for d in days:
        bar = by_date[d]
        if pending is not None:
            if pending == "SPY" and shares == 0.0 and cash > 0:
                bv = cash / 1.001; c = bv * 0.001
                shares = bv / bar["o"]; cash -= bv + c; costs += c
                trades.append([d, "BUY", round(bar["o"], 4), round(bv, 2), round(c, 2)])
            elif pending == "CASH" and shares > 0:
                val = shares * bar["o"]; c = val * 0.001 + 0.01
                cash += val - c; costs += c; shares = 0.0
                trades.append([d, "SELL", round(bar["o"], 4), round(val, 2), round(c, 2)])
            pending = None
        if d in tmap and d >= days[0]:
            cur = "SPY" if shares > 0 else "CASH"
            if tmap[d] != cur: pending = tmap[d]
        final = cash + shares * bar["c"]
    if shares > 0:
        val = shares * by_date[days[-1]]["c"]; c = val * 0.001 + 0.01
        final = cash + val - c
    return round(final, 2)


def spy_hold(bars, by_date, start, end):
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    o = by_date[days[0]]["o"]; sh = (START / 1.001) / o
    val = sh * by_date[days[-1]]["c"]
    return round(val - (val * 0.001 + 0.01), 2)


def distribution(curve):
    """Calendar-year distribution from an equity curve."""
    years = {}
    prev = None
    for d, v in curve:
        y = d[:4]
        if y not in years: years[y] = [v, v]
        years[y][1] = v
    rets = []
    base = START
    for y in sorted(years):
        s, e = years[y]
        start_v = base
        rets.append((y, round(100.0 * (e / start_v - 1), 1)))
        base = e
    vals = [r for _, r in rets]
    pos = sum(1 for v in vals if v > 0)
    streak = cur = 0
    for v in vals:
        cur = cur + 1 if v < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (trading days)
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
    cape = load_cape(); checks = month_end_checks(bars); qc = quarter_checks(checks)
    print(f"bars {bars[0]['d']}->{bars[-1]['d']} ({len(bars)}); CAPE months {len(cape)}; quarter checks {len(qc)}")
    out = {"family": "cape-timing", "program": "v13-best-rules",
           "form": "MY RULES: quarterly checks, CAPE band ladder 100/85/70/55/40/25% SPY, live shillerdata CAPE, program costs, no floor",
           "label": "Claude-designed rules; Campbell & Shiller published no system. Comparison form is the v12 CONSTRUCTED binary CAPE-25 timer.",
           "roads": {}}
    for name, (s, e) in ROADS.items():
        r = run_ladder(bars, by_date, qc, cape, s, e)
        spy = spy_hold(bars, by_date, s, e)
        binc = run_binary(bars, by_date, checks, cape, s, e)
        placebos, beaten = [], None
        if len(r["weights_used"]) <= 1:
            pnote = "degenerate: target weight never changes on this road; shifted twins are identical"
        else:
            for seed in range(1, 21):
                pr = run_ladder(bars, by_date, qc, cape, s, e, shift_seed=seed)
                placebos.append(pr["final"])
            beaten = sum(1 for p in placebos if r["final"] > p)
            pnote = f"real beats {beaten}/20 shifted-weight twins"
        dist = distribution(r["equity_curve"])
        out["roads"][name] = {**r, "spy_same_plumbing": spy, "spy_program_ref": SPYREF[name],
                              "champion_vm": CHAMP[name], "v12_constructed_ref": V12[name],
                              "v12_binary_same_plumbing": binc,
                              "placebo_finals": placebos, "placebos_beaten": beaten,
                              "placebo_note": pnote, "distribution": dist}
        print(f"{name}: mine ${r['final']} maxDD {r['max_dd_pct']}% costs ${r['costs']} orders {r['orders']} "
              f"avgW {r['avg_weight_pct']}% | v12 same-plumbing ${binc} (ref ${V12[name]}) SPY ${spy} "
              f"champ ${CHAMP[name]} placebos beaten {beaten}")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
