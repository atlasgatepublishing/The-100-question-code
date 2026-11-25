#!/usr/bin/env python3
"""Hunt-Equity-Share-Issuance — v13 BEST RULES. Implements BEST-RULES-SPEC.md
exactly (frozen before this run):
  Signal = December trailing-12m equity share `s` from the authors'
  maintained SENTIMENT.xlsx (Baker-Wurgler, updated March 2026), certified
  against the authors' Equity_Share_3.xls monthly e/d (trailing-12
  reconstruction == December `s` for every Dec 1972-2007).
  Rule = VETO overlay on SPY buy-and-hold: each January, if the just-ended
  year's December `s` exceeds the point-in-time expanding 75th percentile
  of all December `s` values 1972..that year -> CASH for the year, else
  SPY. Fill at first February trading day's open. Binary, no floor.
  Costs 0.10%/side + $0.01 sell fee (program standard). Cash 0%.
  Comparator on identical plumbing: v12 constructed fixed line 0.27.
  Placebos: 20 seeds/road, random-year states, same cash-year count.
Simulation only. Public data + published signal only."""
import json, os, random, statistics, time
import openpyxl, xlrd

HERE = os.path.dirname(os.path.abspath(__file__))
PROBE = os.path.join(HERE, "data_probe")
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
START = 100.0
COST = 0.001
SELLFEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
HIST_START = 1972  # certified overlap start (spec rule 2)


def load_series():
    wb = openpyxl.load_workbook(os.path.join(PROBE, "SENTIMENT.xlsx"),
                                data_only=True, read_only=True)
    rows = list(wb["DATA"].iter_rows(values_only=True))
    hdr = rows[0]; si = hdr.index("s")
    dec = {}
    for r in rows[1:]:
        if r[si] is not None and r[0] % 100 == 12:
            dec[r[0] // 100] = float(r[si])
    return dec


def certify(dec):
    """Trailing-12 equity share from the authors' monthly e/d in
    Equity_Share_3.xls vs December `s` in SENTIMENT.xlsx, Dec 1972-2007."""
    wb = xlrd.open_workbook(os.path.join(PROBE, "Equity_Share_3.xls"))
    sh = wb.sheet_by_name("S monthly")
    m = {}
    for r in range(sh.nrows):
        ym, e, d = sh.cell_value(r, 0), sh.cell_value(r, 1), sh.cell_value(r, 2)
        if isinstance(ym, float) and isinstance(e, float) and isinstance(d, float):
            m[int(ym)] = (e, d)
    out = {"checked_years": [], "mismatches": []}
    for y in range(1972, 2008):
        es = ds = 0.0; ok = True
        for k in range(12):
            key = y * 100 + 12 - k
            if key not in m: ok = False; break
            es += m[key][0]; ds += m[key][1]
        if not ok: continue
        t12 = es / (es + ds)
        out["checked_years"].append(y)
        if abs(t12 - dec[y]) > 0.0005:
            out["mismatches"].append([y, round(t12, 6), round(dec[y], 6)])
    out["n_checked"] = len(out["checked_years"])
    out["n_matched"] = out["n_checked"] - len(out["mismatches"])
    return out


def load_bars():
    j = json.load(open(PX))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None: continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    return bars


def percentile(vals, q):
    s = sorted(vals); n = len(s)
    if n == 1: return s[0]
    pos = q * (n - 1); lo = int(pos); hi = min(lo + 1, n - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def build_states(dec, mode):
    """state_for_year[Y] = exposure decided in January Y (effective Feb Y
    to Jan Y+1), based on December s of Y-1. True = SPY, False = CASH."""
    states = {}
    for Y in range(2009, 2028):
        prev = dec.get(Y - 1)
        if prev is None: states[Y] = True; continue
        if mode == "expanding_q3":
            hist = [dec[y] for y in range(HIST_START, Y) if y in dec]
            states[Y] = not (prev > percentile(hist, 0.75))
        elif mode == "fixed027":
            states[Y] = not (prev > 0.27)
    return states


def feb_first_days(bars):
    out = {}
    for b in bars:
        y, m = int(b["d"][:4]), b["d"][5:7]
        if m == "02" and y not in out: out[y] = b["d"]
    return out


def run_timer(bars, by_date, feb, states, start, end):
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    # state in effect at road start: latest decision with Feb fill <= start
    y0 = int(days[0][:4])
    cur_state = states[y0] if days[0] >= feb.get(y0, "9999") else states[y0 - 1]
    switches = {feb[y]: states[y] for y in states
                if y in feb and days[0] < feb[y] <= days[-1]}
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []

    def buy(d, price):
        nonlocal cash, shares, costs
        bv = cash / (1 + COST); c = bv * COST
        shares = bv / price; cash -= bv + c; costs += c
        trades.append([d, "BUY", round(price, 4), round(bv, 2), round(c, 2)])

    def sell(d, price):
        nonlocal cash, shares, costs
        val = shares * price; c = val * COST + SELLFEE
        cash += val - c; costs += c; shares = 0.0
        trades.append([d, "SELL", round(price, 4), round(val, 2), round(c, 2)])

    if cur_state and cash > 0: buy(days[0], by_date[days[0]]["o"])
    cash_days = spy_days = 0
    for d in days:
        if d in switches and switches[d] != cur_state:
            if switches[d] and shares == 0.0 and cash > 0: buy(d, by_date[d]["o"])
            elif not switches[d] and shares > 0: sell(d, by_date[d]["o"])
            cur_state = switches[d]
        eq = cash + shares * by_date[d]["c"]
        if shares > 0: spy_days += 1
        else: cash_days += 1
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
            "pct_days_in_spy": round(100.0 * spy_days / (spy_days + cash_days), 1),
            "equity_curve": curve}


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
    rets, base = [], START
    for y in sorted(years):
        s, e = years[y]
        rets.append((y, round(100.0 * (e / base - 1), 2)))
        base = e
    vals = [r for _, r in rets]
    pos = sum(1 for v in vals if v > 0)
    streak = cur = 0
    for v in vals:
        cur = cur + 1 if v < 0 else 0
        streak = max(streak, cur)
    peak = -1.0; last_high = 0; longest = 0
    for i, (_, v) in enumerate(curve):
        if v >= peak: peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(curve) - 1 - last_high)
    return {"median_year_pct": round(statistics.median(vals), 2) if vals else None,
            "share_positive_pct": round(100.0 * pos / len(vals), 1) if vals else None,
            "years": len(vals), "positive_years": pos,
            "best_year": max(rets, key=lambda t: t[1]) if rets else None,
            "worst_year": min(rets, key=lambda t: t[1]) if rets else None,
            "longest_losing_streak_yrs": streak,
            "longest_between_highs_days": longest,
            "mean_year_pct_secondary": round(statistics.mean(vals), 2) if vals else None,
            "year_returns": rets}


def main():
    dec = load_series()
    cert = certify(dec)
    print(f"certification: {cert['n_matched']}/{cert['n_checked']} Decembers "
          f"1972-2007 match trailing-12 reconstruction; mismatches={cert['mismatches']}")
    with open(os.path.join(HERE, "equity_share_series.csv"), "w") as f:
        f.write("year,december_equity_share_s\n")
        for y in sorted(dec): f.write(f"{y},{dec[y]:.6f}\n")
    bars = load_bars(); by_date = {b["d"]: b for b in bars}; feb = feb_first_days(bars)
    states_mine = build_states(dec, "expanding_q3")
    states_fixed = build_states(dec, "fixed027")
    # decision table for the log
    dtable = []
    for Y in range(2010, 2027):
        hist = [dec[y] for y in range(HIST_START, Y) if y in dec]
        dtable.append({"decision_year": Y, "dec_s_prior": round(dec[Y - 1], 4),
                       "expanding_q3": round(percentile(hist, 0.75), 4),
                       "my_state": "SPY" if states_mine[Y] else "CASH",
                       "fixed027_state": "SPY" if states_fixed[Y] else "CASH"})
    out = {"family": "hunt-equity-share-issuance", "program": "v13-best-rules",
           "form": "MY RULES: PIT expanding-Q3 veto on SPY host, annual, Feb fill, binary, no floor, program costs",
           "label": "Claude-designed rules for Baker-Wurgler (2000) predictor; comparator = v12 constructed fixed-0.27 form on identical plumbing. v12 verdict was STILL UNBUILDABLE (no finals).",
           "certification": cert, "decision_table": dtable, "roads": {}}
    for name, (s, e) in ROADS.items():
        r = run_timer(bars, by_date, feb, states_mine, s, e)
        comp = run_timer(bars, by_date, feb, states_fixed, s, e)
        spy = spy_hold(bars, by_date, s, e)
        # cash-year count among decision years affecting this road
        y0, y1 = int(s[:4]), int(e[:4])
        rel_years = list(range(y0, y1 + 1))
        n_cash = sum(1 for Y in rel_years if not states_mine[Y])
        placebos = []
        for seed in range(1, 21):
            rng = random.Random(1000 * seed + len(rel_years))
            cash_years = set(rng.sample(rel_years, n_cash)) if n_cash else set()
            pst = {Y: (Y not in cash_years) for Y in range(2009, 2028)}
            pr = run_timer(bars, by_date, feb, pst, s, e)
            placebos.append(pr["final"])
        beaten = sum(1 for p in placebos if r["final"] > p)
        dist = distribution(r["equity_curve"])
        out["roads"][name] = {**r, "spy_same_plumbing": spy, "spy_program_ref": SPYREF[name],
                              "champion_vm": CHAMP[name],
                              "fixed027_comparator": {"final": comp["final"],
                                  "max_dd_pct": comp["max_dd_pct"], "costs": comp["costs"],
                                  "orders": comp["orders"]},
                              "cash_decision_years": [Y for Y in rel_years if not states_mine[Y]],
                              "placebo_finals": placebos, "placebos_beaten": beaten,
                              "distribution": dist}
        print(f"{name}: mine ${r['final']} maxDD {r['max_dd_pct']}% costs ${r['costs']} "
              f"orders {r['orders']} inSPY {r['pct_days_in_spy']}% | fixed027 ${comp['final']} "
              f"SPY ${spy} champ ${CHAMP[name]} placebos beaten {beaten}/20 cashyrs "
              f"{out['roads'][name]['cash_decision_years']}")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
