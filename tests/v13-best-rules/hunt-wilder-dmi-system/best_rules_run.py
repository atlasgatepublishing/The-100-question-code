#!/usr/bin/env python3
"""V13 BEST-RULES RUN — Wilder DMI/ADX under Claude-designed rules.
Frozen spec: BEST-RULES-SPEC.md in this folder. Summary:
- SPY, daily, long-only timer. +DI/-DI(14) and ADX(14), Wilder smoothing,
  published constants untouched.
- Entry (next open): +DI crossed above -DI at signal close AND ADX(14) > 25
  at that close (ADX as LEVEL filter, per Wilder's published use; the
  same-day 'rising' conjunction is deliberately NOT required).
- Exit (next open): -DI crossed above +DI at signal close. The published
  extreme-point reversal rule is deliberately DROPPED (see spec).
- All-in/all-out, $100 pots, costs 0.10%/side + $0.01 per sell order.
- NO pot floor. Placebos: 20-seed circular shifts of each road's state
  series, identical execution/costs.
Data (read-only): backtests/v7/long-hold/data/pxfull_SPY.json — Yahoo OHLC
scaled by adjclose/close (dividend/split-adjusted), from 2008-01-02.
Execution: signal at close t -> trade at open t+1 (point-in-time).
Simulation only; no broker orders.
"""
import json, math, os, random, time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
START = 100.0
COST = 0.001
FEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {"LONG": 438.51, "DECADE": 366.54, "CONT": 308.67, "VAL": 189.72}  # v12 Form A literal native

# ---------- data ----------
def load_bars():
    j = json.load(open(SRC))
    r = j["chart"]["result"][0]
    ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None \
           or q["high"][i] is None or q["low"][i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "h": q["high"][i] * ratio,
                     "l": q["low"][i] * ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    return bars

BARS = load_bars()
N = len(BARS)
DATES = [b["d"] for b in BARS]
IDX = {d: i for i, d in enumerate(DATES)}

# ---------- Wilder DMI (identical formulas to the v12 run) ----------
def dmi(bars, n=14):
    m = len(bars)
    tr = [0.0] * m; pdm = [0.0] * m; ndm = [0.0] * m
    for i in range(1, m):
        h, l, pc = bars[i]["h"], bars[i]["l"], bars[i - 1]["c"]
        up = h - bars[i - 1]["h"]; dn = bars[i - 1]["l"] - l
        pdm[i] = up if (up > dn and up > 0) else 0.0
        ndm[i] = dn if (dn > up and dn > 0) else 0.0
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
    def smooth(x):
        out = [0.0] * m; s = 0.0
        for i in range(m):
            if i == n: s = sum(x[1:n + 1])
            elif i > n: s = s - s / n + x[i]
            out[i] = s
        return out
    str_, sp, sn = smooth(tr), smooth(pdm), smooth(ndm)
    pdi = [100 * sp[i] / str_[i] if str_[i] > 0 else 0.0 for i in range(m)]
    ndi = [100 * sn[i] / str_[i] if str_[i] > 0 else 0.0 for i in range(m)]
    dx = [100 * abs(pdi[i] - ndi[i]) / (pdi[i] + ndi[i]) if (pdi[i] + ndi[i]) > 0 else 0.0 for i in range(m)]
    adx = [0.0] * m; s = 0.0
    for i in range(m):
        if i == 2 * n: s = sum(dx[n + 1:2 * n + 1]) / n; adx[i] = s
        elif i > 2 * n: s = (s * (n - 1) + dx[i]) / n; adx[i] = s
    return pdi, ndi, adx

PDI, NDI, ADX = dmi(BARS)

# ---------- my-rules state series (desired position AFTER close t) ----------
def build_states():
    state = [0] * N
    pos = 0
    diag = {"cross_up": 0, "cross_up_adx_gt25": 0, "entries": 0, "exits": 0}
    for i in range(1, N):
        cross_up = PDI[i] > NDI[i] and PDI[i - 1] <= NDI[i - 1]
        cross_dn = NDI[i] > PDI[i] and NDI[i - 1] <= PDI[i - 1]
        if cross_up:
            diag["cross_up"] += 1
            if ADX[i] > 25: diag["cross_up_adx_gt25"] += 1
        if pos == 0:
            if cross_up and ADX[i] > 25:
                pos = 1; diag["entries"] += 1
        else:
            if cross_dn:
                pos = 0; diag["exits"] += 1
        state[i] = pos
    return state, diag

STATES, DIAG = build_states()

# ---------- simulation: state at close t executes at open t+1 ----------
def sim(states, start_d, end_d):
    s_i, e_i = IDX[start_d], IDX[end_d]
    cash, shares = START, 0.0
    costs = 0.0; orders = 0; trades = []
    open_trade = None
    curve = []
    invested = 0
    for i in range(s_i, e_i + 1):
        if i > s_i:
            want = states[i - 1]
            holding = 1 if shares > 0 else 0
            if want == 1 and holding == 0:
                spend = cash * (1 - COST); costs += cash * COST
                shares = spend / BARS[i]["o"]; cash = 0.0; orders += 1
                open_trade = {"entry_date": DATES[i], "entry_px": BARS[i]["o"], "equity_in": spend + cash * 0 + (costs and 0)}
                open_trade["cash_in"] = spend
            elif want == 0 and holding == 1:
                proceeds = shares * BARS[i]["o"] * (1 - COST) - FEE
                costs += shares * BARS[i]["o"] * COST + FEE
                cash = proceeds; shares = 0.0; orders += 1
                if open_trade is not None:
                    trades.append({"entry_date": open_trade["entry_date"], "exit_date": DATES[i],
                                   "pnl": round(proceeds - open_trade["cash_in"], 2)})
                    open_trade = None
        eq = cash + shares * BARS[i]["c"]
        if shares > 0: invested += 1
        curve.append((DATES[i], round(eq, 4)))
    if open_trade is not None:
        trades.append({"entry_date": open_trade["entry_date"], "exit_date": None,
                       "pnl": round(curve[-1][1] - open_trade["cash_in"], 2), "open": True})
    return {"final": round(curve[-1][1], 2), "curve": curve, "costs": round(costs, 2),
            "orders": orders, "trades": trades,
            "max_dd_pct": max_dd(curve), "invested_share": round(invested / max(1, len(curve)), 3)}

def buy_hold(start_d, end_d):
    s_i, e_i = IDX[start_d], IDX[end_d]
    sh = START * (1 - COST) / BARS[s_i]["o"]
    curve = [(DATES[i], round(sh * BARS[i]["c"], 4)) for i in range(s_i, e_i + 1)]
    final = sh * BARS[e_i]["c"] * (1 - COST) - FEE
    curve[-1] = (DATES[e_i], round(final, 4))
    return {"final": round(final, 2), "curve": curve, "max_dd_pct": max_dd(curve)}

def max_dd(curve):
    peak = -1e18; mdd = 0.0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0: mdd = max(mdd, (peak - e) / peak * 100)
    return round(mdd, 2)

def period_stats(curve):
    """Monthly distribution from a daily equity curve."""
    months = {}
    for d, e in curve:
        months[d[:7]] = e  # last value in month wins (curve is date-ordered)
    keys = sorted(months)
    rets = []
    for a, b in zip(keys, keys[1:]):
        rets.append(months[b] / months[a] - 1)
    if not rets:
        return {}
    pos_share = sum(1 for r in rets if r > 0) / len(rets)
    # longest losing streak (months <= 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs, in months and in days
    peak = -1e18; since = 0; longest_m = 0
    for k in keys:
        if months[k] >= peak: peak = months[k]; since = 0
        else: since += 1
        longest_m = max(longest_m, since)
    peak = -1e18; last_high = 0; longest_d = 0
    for i, (_, e) in enumerate(curve):
        if e >= peak: peak = e; last_high = i
        longest_d = max(longest_d, i - last_high)
    longest_days = (date.fromisoformat(curve[-1][0]) - date.fromisoformat(curve[max(0, len(curve) - 1 - longest_d)][0])).days if longest_d else 0
    # exact: recompute longest underwater span in calendar days
    peak = -1e18; peak_d = curve[0][0]; longest_span = 0
    for d, e in curve:
        if e >= peak: peak = e; peak_d = d
        else:
            span = (date.fromisoformat(d) - date.fromisoformat(peak_d)).days
            longest_span = max(longest_span, span)
    srt = sorted(rets)
    median = srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2
    return {"periods": len(rets), "median": round(median, 5), "share_positive": round(pos_share, 4),
            "best": round(max(rets), 5), "worst": round(min(rets), 5),
            "longest_losing_streak_months": streak,
            "longest_between_highs_months": longest_m,
            "longest_between_highs_days": longest_span,
            "average_secondary": round(sum(rets) / len(rets), 5)}

def expectancy(trades):
    closed = [t for t in trades if not t.get("open")]
    if not closed: return {}
    wins = [t["pnl"] for t in closed if t["pnl"] > 0]
    losses = [t["pnl"] for t in closed if t["pnl"] <= 0]
    return {"trades_closed": len(closed), "win_rate": round(len(wins) / len(closed), 4),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "expectancy_per_trade": round(sum(t["pnl"] for t in closed) / len(closed), 2),
            "best_trade": round(max(t["pnl"] for t in closed), 2),
            "worst_trade": round(min(t["pnl"] for t in closed), 2)}

# ---------- run ----------
out = {"family": "hunt-wilder-dmi-system", "program": "v13-best-rules",
       "spec": "BEST-RULES-SPEC.md (frozen before run)",
       "execution_note": "signal at close t executes at open t+1; adjusted OHLC (adjclose ratio); costs 0.10%/side + $0.01/sell; no floor; long-only",
       "diagnostics_full_history": DIAG,
       "roads": {}}
print("diagnostics:", DIAG, flush=True)
for road, (a, b) in ROADS.items():
    real = sim(STATES, a, b)
    bh = buy_hold(a, b)
    s_i, e_i = IDX[a], IDX[b]
    seg = STATES[s_i:e_i + 1]
    rng = random.Random(20261122)
    pb = []
    for s in range(20):
        sh = rng.randint(30, max(31, len(seg) - 30))
        rot = seg[-sh:] + seg[:-sh]
        shifted = list(STATES)
        for k, i in enumerate(range(s_i, e_i + 1)):
            shifted[i] = rot[k]
        pb.append(sim(shifted, a, b)["final"])
    beaten = sum(1 for x in pb if real["final"] > x)
    out["roads"][road] = {"window": [a, b], "my_rules": real, "buy_hold": bh,
                          "placebos_20": [round(x, 2) for x in pb], "placebos_beaten": beaten,
                          "placebo_median": round(sorted(pb)[10], 2),
                          "period_stats_monthly": period_stats(real["curve"]),
                          "buy_hold_period_stats_monthly": period_stats(bh["curve"]),
                          "expectancy": expectancy(real["trades"]),
                          "champion_vm": CHAMP[road], "spy_reference": SPYREF[road],
                          "published_formA_native": PUBLISHED[road]}
    print(road, "mine", real["final"], "dd", real["max_dd_pct"], "orders", real["orders"],
          "| BH", bh["final"], "| pb beaten", beaten, "/20", flush=True)

# ---------- confirmation (only if a road beats the champion) ----------
conf = {}
for road, (a, b) in ROADS.items():
    if out["roads"][road]["my_rules"]["final"] > CHAMP[road]:
        s_i, e_i = IDX[a], IDX[b]
        mid = (s_i + e_i) // 2
        halves = {}
        for name, (hs, he) in {"H1": (DATES[s_i], DATES[mid]), "H2": (DATES[mid + 1], DATES[e_i])}.items():
            halves[name] = {"mine": sim(STATES, hs, he)["final"], "spy": buy_hold(hs, he)["final"]}
        years = {}
        y0, y1 = int(a[:4]), int(b[:4])
        for y in range(y0, y1 + 1):
            ys = max(a, f"{y}-01-01"); ye = min(b, f"{y}-12-31")
            if ys <= a or ye >= b and y == y1 and b[5:] != "12-31":
                pass
            if ys < a or ye > b: continue
            # only full calendar years fully inside the road
            if ys != f"{y}-01-01" or ye != f"{y}-12-31": continue
            # first trading day >= ys, last <= ye
            cand_s = [d for d in DATES if d >= ys]
            cand_e = [d for d in DATES if d <= ye]
            if not cand_s or not cand_e: continue
            years[str(y)] = {"mine": sim(STATES, cand_s[0], cand_e[-1])["final"],
                             "spy": buy_hold(cand_s[0], cand_e[-1])["final"]}
        wins = sum(1 for v in years.values() if v["mine"] > v["spy"])
        med_m = sorted(v["mine"] for v in years.values())
        med_s = sorted(v["spy"] for v in years.values())
        med_mine = med_m[len(med_m) // 2] if len(med_m) % 2 else (med_m[len(med_m)//2-1] + med_m[len(med_m)//2]) / 2
        med_spy = med_s[len(med_s) // 2] if len(med_s) % 2 else (med_s[len(med_s)//2-1] + med_s[len(med_s)//2]) / 2
        folds_pass = bool(years) and wins > len(years) / 2 and med_mine >= med_spy
        halves_pass = all(v["mine"] > v["spy"] for v in halves.values())
        conf[road] = {"yearly_folds": years, "folds_wins": wins, "folds_n": len(years),
                      "median_year_mine": round(med_mine, 2), "median_year_spy": round(med_spy, 2),
                      "folds_pass": folds_pass, "halves": halves, "halves_pass": halves_pass,
                      "confirmed": bool(folds_pass and halves_pass)}
        print("CONFIRM", road, conf[road], flush=True)
out["confirmation"] = conf

json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("done")
