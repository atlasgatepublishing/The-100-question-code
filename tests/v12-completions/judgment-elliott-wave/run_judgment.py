#!/usr/bin/env python3
"""Elliott Wave / Prechter JUDGMENT-CONSTRUCTED run. Implements JUDGMENT-SPEC.md
exactly: weekly zigzag 8% (E1), three inviolable rules enforced, dead counts
never relabeled (E2/E5), primary count only (E3), long SPY or cash monthly
(E4), decide month-end close / execute next open, costs 0.10%/side + $0.01
sell fee, cash 0%. Placebos: 20-seed circular shifts of monthly targets.
JUDGMENT-CONSTRUCTED: our frozen reconstruction of Prechter's documented
decision-making; not Prechter's own trading. Simulation only."""
import json, os, time, random
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
START = 100.0
THR = 0.08
ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}


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


def weekly_closes(bars):
    weeks = OrderedDict()
    for b in bars:
        y, m, d = int(b["d"][:4]), int(b["d"][5:7]), int(b["d"][8:10])
        iso = time.strptime(b["d"], "%Y-%m-%d")
        key = time.strftime("%G-%V", iso)  # ISO year-week
        weeks[key] = (b["d"], b["c"])
    return list(weeks.values())  # [(date, close)] in order


def build_pivots(weeks):
    """Zigzag 8%. Returns pivots: dicts with pivot_date, price, kind, confirm_date."""
    pivots = []
    if not weeks:
        return pivots
    mode = None  # None, 'up' (seeking high), 'down' (seeking low)
    ex_p, ex_d = weeks[0][1], weeks[0][0]
    mn_p, mn_d = weeks[0][1], weeks[0][0]
    mx_p, mx_d = weeks[0][1], weeks[0][0]
    for d, p in weeks:
        if mode is None:
            if p < mn_p: mn_p, mn_d = p, d
            if p > mx_p: mx_p, mx_d = p, d
            if p >= mn_p * (1 + THR) and mn_d != d:
                pivots.append({"pivot_date": mn_d, "price": mn_p, "kind": "low", "confirm_date": d})
                mode, ex_p, ex_d = "up", p, d
            elif p <= mx_p * (1 - THR) and mx_d != d:
                pivots.append({"pivot_date": mx_d, "price": mx_p, "kind": "high", "confirm_date": d})
                mode, ex_p, ex_d = "down", p, d
        elif mode == "up":
            if p > ex_p: ex_p, ex_d = p, d
            if p <= ex_p * (1 - THR):
                pivots.append({"pivot_date": ex_d, "price": ex_p, "kind": "high", "confirm_date": d})
                mode, ex_p, ex_d = "down", p, d
        else:  # down
            if p < ex_p: ex_p, ex_d = p, d
            if p >= ex_p * (1 + THR):
                pivots.append({"pivot_date": ex_d, "price": ex_p, "kind": "low", "confirm_date": d})
                mode, ex_p, ex_d = "up", p, d
    return pivots


def valid_impulse(w):
    """w = 6 pivots. Returns 'bull', 'bear', or None per E2."""
    kinds = [p["kind"] for p in w]
    pr = [p["price"] for p in w]
    if kinds == ["low", "high", "low", "high", "low", "high"]:
        L1, L3, L5 = pr[1]-pr[0], pr[3]-pr[2], pr[5]-pr[4]
        if min(L1, L3, L5) <= 0: return None
        if not (pr[2] > pr[0]): return None          # Rule 1
        if L3 < L1 and L3 < L5: return None           # Rule 2: shortest
        if not (pr[4] > pr[1]): return None           # Rule 3
        return "bull"
    if kinds == ["high", "low", "high", "low", "high", "low"]:
        L1, L3, L5 = pr[0]-pr[1], pr[2]-pr[3], pr[4]-pr[5]
        if min(L1, L3, L5) <= 0: return None
        if not (pr[2] < pr[0]): return None
        if L3 < L1 and L3 < L5: return None
        if not (pr[4] < pr[1]): return None
        return "bear"
    return None


def primary_target(pivots, price):
    """E3/E4 at one month-end. pivots already filtered confirm_date <= month-end."""
    if len(pivots) < 6:
        return "CASH", None
    latest_confirm = pivots[-1]["confirm_date"]
    best = None  # candidates must end at the most recently confirmed pivot (E3)
    for i in range(len(pivots) - 5):
        w = pivots[i:i+6]
        if w[5]["confirm_date"] != latest_confirm: continue
        d = valid_impulse(w)
        if d is None: continue
        key = (w[5]["confirm_date"], i)
        if best is None or key > best[0]:
            best = (key, d, w)
    if best is None:
        return "CASH", None
    _, d, w = best
    if d == "bear":
        return "CASH", {"dir": "bear", "p0": w[0]["price"], "p5": w[5]["price"]}
    # bull: E4 conditions
    p0, p4, p5 = w[0]["price"], w[4]["price"], w[5]["price"]
    info = {"dir": "bull", "p0": p0, "p4": p4, "p5": p5,
            "p0_date": w[0]["pivot_date"], "p5_date": w[5]["pivot_date"]}
    if price <= p4: return "CASH", info
    if p5 > p0 and (p5 - price) / (p5 - p0) > 0.618: return "CASH", info
    return "SPY", info


def month_end_checks(bars):
    seen = {}
    for b in bars:
        seen[b["d"][:7]] = b["d"]
    return sorted((d, m) for m, d in seen.items())


def run(bars, by_date, checks, targets_by_check, start, end, shift_targets=None):
    days = [b["d"] for b in bars if start <= b["d"] <= end]
    rel = [(d, m) for d, m in checks if d < days[0]][-1:] + \
          [(d, m) for d, m in checks if days[0] <= d <= end]
    targets = [targets_by_check[d] for d, m in rel]
    if shift_targets is not None:
        targets = shift_targets
    tmap = {d: t for (d, m), t in zip(rel, targets)}
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    pending = None
    days_invested = 0
    if rel and rel[0][0] < days[0]:
        pending = tmap[rel[0][0]]
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
            if tmap[d] != cur:
                pending = tmap[d]
        if shares > 0: days_invested += 1
        curve.append([d, round(cash + shares * bar["c"], 4)])
    if shares > 0:
        last = days[-1]; val = shares * by_date[last]["c"]; c = val * 0.001 + 0.01
        cash += val - c; costs += c; shares = 0.0
        trades.append([last, "SELL-END", round(by_date[last]["c"], 4), round(val, 2), round(c, 2)])
        curve[-1] = [last, round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0 * days_invested / len(days), 1) if days else 0,
            "equity_curve": curve}


def period_stats(curve):
    """Monthly distribution at native tempo (E8)."""
    by_month = {}
    for d, v in curve:
        by_month[d[:7]] = v
    months = sorted(by_month)
    rets, prev = [], START
    for m in months:
        v = by_month[m]
        rets.append(v / prev - 1.0); prev = v
    if not rets: return {}
    s = sorted(rets)
    n = len(s)
    med = s[n//2] if n % 2 else (s[n//2-1] + s[n//2]) / 2
    win = sum(1 for r in rets if r > 0)
    # longest losing run
    longest = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        longest = max(longest, cur)
    # longest stretch between new highs (months)
    peak, stretch, maxstretch = -1, 0, 0
    for m in months:
        if by_month[m] >= peak: peak, stretch = by_month[m], 0
        else: stretch += 1; maxstretch = max(maxstretch, stretch)
    return {"periods": n, "pct_profitable": round(100*win/n, 1),
            "median_pct": round(med*100, 2), "mean_pct_secondary": round(100*sum(rets)/n, 2),
            "best_pct": round(max(rets)*100, 2), "worst_pct": round(min(rets)*100, 2),
            "longest_losing_run": longest, "longest_months_between_highs": maxstretch}


def weekly_curve(curve):
    out, seen = [], set()
    for d, v in curve:
        iso = time.strptime(d, "%Y-%m-%d")
        key = time.strftime("%G-%V", iso)
        if key in seen and out:
            out[-1] = [d, v]
        else:
            seen.add(key); out.append([d, v])
    if curve and out[-1] != curve[-1]:
        out.append(curve[-1])
    return out


def main():
    import sys
    bars = load_bars()
    by_date = {b["d"]: b for b in bars}
    weeks = weekly_closes(bars)
    pivots = build_pivots(weeks)
    checks = month_end_checks(bars)
    targets_by_check, count_log = {}, []
    for d, m in checks:
        avail = [p for p in pivots if p["confirm_date"] <= d]
        t, info = primary_target(avail, by_date[d]["c"])
        targets_by_check[d] = t
        count_log.append([d, t, info])
    out = {"label": "JUDGMENT-CONSTRUCTED: our frozen reconstruction of Prechter's documented decision-making; not Prechter's own trading.",
           "pivots_total": len(pivots), "roads": {}}
    for road, (s, e) in ROADS.items():
        res = run(bars, by_date, checks, targets_by_check, s, e)
        # placebos: circular shifts of this road's monthly target series
        days = [b["d"] for b in bars if s <= b["d"] <= e]
        rel = [(d, m) for d, m in checks if d < days[0]][-1:] + \
              [(d, m) for d, m in checks if days[0] <= d <= e]
        base_targets = [targets_by_check[d] for d, m in rel]
        placebo_finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            if len(base_targets) > 1:
                k = rng.randrange(1, len(base_targets))
                shifted = base_targets[k:] + base_targets[:k]
            else:
                shifted = base_targets
            pr = run(bars, by_date, checks, targets_by_check, s, e, shift_targets=shifted)
            placebo_finals.append(pr["final"])
        beats = sum(1 for f in placebo_finals if res["final"] > f)
        res["period_stats_monthly"] = period_stats(res["equity_curve"])
        res["placebo"] = {"seeds": 20, "finals": placebo_finals,
                          "median": sorted(placebo_finals)[10], "beat_count": beats}
        res["champion_vm"] = CHAMP[road]; res["spy_ref_program"] = SPYREF[road]
        res["equity_curve_weekly"] = weekly_curve(res.pop("equity_curve"))
        out["roads"][road] = res
        print(road, res["final"], "DD", res["max_dd_pct"], "inv%", res["invested_pct"],
              "orders", res["orders"], "placebo beat", beats, "/20, placebo median",
              sorted(placebo_finals)[10])
    # NOTE: this sandbox blocks exec file writes (EPERM); results are printed
    # to stdout and assembled into results.json by the file tool.
    if len(sys.argv) > 1 and sys.argv[1] == "--road":
        print(json.dumps(out["roads"][sys.argv[2]]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--mcurve":
        res = out["roads"][sys.argv[2]]
        mc = {}
        # rebuild month-end equity from the weekly curve's source: rerun period walk
        curve = res["equity_curve_weekly"]
        # weekly curve is insufficient for month-ends; recompute from daily run:
        full = run(bars, by_date, checks, targets_by_check,
                   ROADS[sys.argv[2]][0], ROADS[sys.argv[2]][1])
        for d, v in full["equity_curve"]:
            mc[d[:7]] = v
        print(json.dumps([[m, mc[m]] for m in sorted(mc)]))
        print("TRADES", json.dumps(full["trades"]))
    elif len(sys.argv) > 1 and sys.argv[1] == "--meta":
        print(json.dumps({"label": out["label"], "pivots_total": out["pivots_total"]}))
        print(json.dumps(count_log))
    elif len(sys.argv) > 1 and sys.argv[1] == "--summary":
        print(json.dumps({r: {k: v for k, v in res.items()
                              if k not in ("equity_curve_weekly", "trades")}
                          for r, res in out["roads"].items()}, indent=1))


if __name__ == "__main__":
    main()
