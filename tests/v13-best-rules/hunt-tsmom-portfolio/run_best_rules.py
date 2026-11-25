#!/usr/bin/env python3
"""
V13 BEST-RULES — TSMOM PORTFOLIO (MOP 2012). Spec: BEST-RULES-SPEC.md (frozen before run).
Universe: 8 cross-asset ETFs (SPY QQQ TLT IEF AGG GLD DBC UUP), shared v3 ETF cache.
Signal: sign of own trailing 252d adjusted-close return (no skip), monthly, next-day-open trades.
Headline sizing: equal weight across positive-sign assets (NO vol scaler).
Attribution control: MOP EWMA vol-scaled weights (lambda=60/61, x sqrt(261)), normalized.
Costs 0.10%/side + $0.01/sell order. No floor. $100 pots. Placebos: 20 seeds, matched breadth.
Confirmation (only if headline beats champion on a road): yearly folds 2011-2025 + half-windows.
"""
import json, os, random, math, statistics
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v3/data_etf")
UNIV = ["SPY", "QQQ", "TLT", "IEF", "AGG", "GLD", "DBC", "UUP"]
COST = 0.0010
SELL_FEE = 0.01
START = 100.0
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {"LONG": 702.52, "DECADE": 286.79, "CONT": 231.64, "VAL": 156.59}  # v12 pond form

def load_series(t):
    with open(os.path.join(CACHE, f"{t}.json")) as f:
        data = json.load(f)
    res = data["chart"]["result"][0]
    ts, q = res["timestamp"], res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"] if "adjclose" in res["indicators"] else None
    out = {}
    for i, tt in enumerate(ts):
        d = datetime.fromtimestamp(tt, tz=timezone.utc).strftime("%Y-%m-%d")
        c, o = q["close"][i], q["open"][i]
        if c is None or o is None:
            continue
        if adj is not None and adj[i]:
            out[d] = (o * adj[i] / c, adj[i])
        else:
            out[d] = (o, c)
    return out

SERIES = {t: load_series(t) for t in UNIV}
CAL = sorted(SERIES["SPY"].keys())
CI = {d: i for i, d in enumerate(CAL)}

def close_on(t, d):
    s = SERIES[t]
    if d in s: return s[d][1]
    i = CI[d]
    for j in range(i - 1, -1, -1):
        if CAL[j] in s: return s[CAL[j]][1]
    return None

def open_on(t, d):
    s = SERIES[t]
    return s[d][0] if d in s else close_on(t, d)

# daily returns per asset on CAL (ffilled close), for EWMA sigma
CLOSES = {}
for t in UNIV:
    arr = []
    last = None
    for d in CAL:
        v = SERIES[t].get(d, (None, None))[1] if d in SERIES[t] else None
        if v is None: v = last
        last = v
        arr.append(v)
    CLOSES[t] = arr
SIGMA = {}
for t in UNIV:
    lam = 60 / 61.0
    var = 0.0; out = [0.0] * len(CAL)
    for i in range(len(CAL)):
        if i > 0 and CLOSES[t][i] is not None and CLOSES[t][i-1]:
            r = CLOSES[t][i] / CLOSES[t][i-1] - 1
            var = lam * var + (1 - lam) * r * r
        out[i] = math.sqrt(var * 261) if var > 0 else 0.0
    SIGMA[t] = out

# month-end signal dates: last trading day of each month -> execute next trading day
ME_EXEC = {}  # exec_date -> signal_date
for i, d in enumerate(CAL):
    if i + 1 < len(CAL) and CAL[i+1][:7] != d[:7]:
        ME_EXEC[CAL[i+1]] = d

def qualifiers(sig_d):
    i = CI[sig_d]
    if i < 252: return []
    out = []
    for t in UNIV:
        a, b = CLOSES[t][i-252], CLOSES[t][i]
        if a and b and b / a - 1 > 0: out.append(t)
    return out

def targets(sig_d, mode, rng=None):
    q = qualifiers(sig_d)
    if mode == "placebo":
        if not q: return {}
        picks = rng.sample(UNIV, len(q))
        return {t: 1.0 / len(picks) for t in picks}
    if not q: return {}
    if mode == "equal":
        return {t: 1.0 / len(q) for t in q}
    if mode == "scaled":
        i = CI[sig_d]
        raw = {t: 1.0 / SIGMA[t][i] for t in q if SIGMA[t][i] > 0}
        tot = sum(raw.values())
        return {t: v / tot for t, v in raw.items()} if tot > 0 else {}
    raise ValueError(mode)

def sim(start, end, mode, seed=None):
    rng = random.Random(seed) if seed is not None else None
    si = next(i for i, d in enumerate(CAL) if d >= start)
    ei = max(i for i, d in enumerate(CAL) if d <= end)
    cash = START; shares = {t: 0.0 for t in UNIV}; curve = []; costs = 0.0; ntrades = 0
    for i in range(si, ei + 1):
        d = CAL[i]
        if d in ME_EXEC:
            tgt = targets(ME_EXEC[d], mode, rng)
            eq = cash + sum(shares[t] * close_on(t, d) for t in UNIV)
            # sell all at open
            for t in UNIV:
                if shares[t] > 0:
                    px = open_on(t, d)
                    amt = shares[t] * px
                    cash += amt * (1 - COST) - SELL_FEE; costs += amt * COST + SELL_FEE
                    shares[t] = 0.0; ntrades += 1
            eq = cash
            for t, w in tgt.items():
                px = open_on(t, d)
                amt = eq * w
                if px and amt > 0:
                    shares[t] = amt * (1 - COST) / px; cash -= amt; costs += amt * COST; ntrades += 1
        eq = cash + sum(shares[t] * (close_on(t, d) or 0) for t in UNIV)
        curve.append((d, round(eq, 4)))
    return {"final": round(curve[-1][1], 2), "curve": curve, "costs": round(costs, 2),
            "max_dd_pct": max_dd(curve), "trades": ntrades}

def spy_bh(start, end):
    si = next(i for i, d in enumerate(CAL) if d >= start)
    ei = max(i for i, d in enumerate(CAL) if d <= end)
    px0 = open_on("SPY", CAL[si])
    sh = START * (1 - COST) / px0
    curve = [(CAL[i], round(sh * close_on("SPY", CAL[i]), 4)) for i in range(si, ei + 1)]
    return {"final": round(curve[-1][1], 2), "curve": curve, "max_dd_pct": max_dd(curve)}

def max_dd(curve):
    peak = -1e18; mdd = 0.0
    for _, e in curve:
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak if peak > 0 else 0)
    return round(mdd * 100, 2)

def period_stats(curve, freq="monthly"):
    by = {}
    for d, e in curve: by[d[:7] if freq == "monthly" else d[:4]] = e
    keys = sorted(by)
    rets = [by[keys[i]] / by[keys[i-1]] - 1 for i in range(1, len(keys))]
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    peak = -1e18; since = 0; longest = 0
    for k in keys:
        if by[k] >= peak: peak = by[k]; since = 0
        else: since += 1
        longest = max(longest, since)
    return {"periods": len(rets), "share_positive": round(pos / len(rets), 4),
            "median": round(statistics.median(rets), 5), "best": round(max(rets), 5),
            "worst": round(min(rets), 5), "longest_losing_streak": streak,
            "longest_between_highs_periods": longest,
            "average_secondary": round(statistics.mean(rets), 5)}

def main():
    out = {"family": "hunt-tsmom-portfolio", "program": "v13-best-rules",
           "label": "Long-only ETF translation of MOP long/short futures form; short leg absent, unlevered.",
           "roads": {}}
    champ_beaten = []
    for road, (a, b) in ROADS.items():
        eq = sim(a, b, "equal"); sc = sim(a, b, "scaled"); spy = spy_bh(a, b)
        pb = [sim(a, b, "placebo", seed=s)["final"] for s in range(20)]
        beaten = sum(1 for x in pb if eq["final"] > x)
        out["roads"][road] = {
            "equal_headline": eq, "scaled_control": sc, "spy_in_plumbing": spy,
            "placebos_20": pb, "placebos_beaten": beaten,
            "period_stats_monthly_equal": period_stats(eq["curve"]),
            "period_stats_monthly_scaled": period_stats(sc["curve"]),
            "champion_vm": CHAMP[road], "spy_ref_program": SPYREF[road],
            "published_v12_pond_form": PUBLISHED[road]}
        if eq["final"] > CHAMP[road]: champ_beaten.append(road)
        print(road, "equal", eq["final"], "dd", eq["max_dd_pct"], "| scaled", sc["final"], "dd", sc["max_dd_pct"],
              "| spy(plumb)", spy["final"], "| beaten", beaten, "/20", flush=True)
    if champ_beaten:
        conf = {}
        # yearly folds 2011-2025
        yrs = {}
        for y in range(2011, 2026):
            a, b = f"{y}-01-02", f"{y}-12-31"
            r = sim(a, b, "equal"); s = spy_bh(a, b)
            yrs[str(y)] = {"final": r["final"], "spy": s["final"]}
        wins = sum(1 for v in yrs.values() if v["final"] > 100)
        spy_wins = sum(1 for v in yrs.values() if v["final"] > v["spy"])
        halves = {}
        for name, (a, b) in {"H1_2010_2018": ("2010-01-04", "2018-12-31"),
                             "H2_2013_2022": ("2013-01-02", "2022-12-30")}.items():
            r = sim(a, b, "equal"); s = spy_bh(a, b)
            halves[name] = {"final": r["final"], "spy": s["final"], "beats_spy": r["final"] > s["final"]}
        conf = {"yearly_folds": yrs, "years_profitable": wins, "years_beat_spy": spy_wins,
                "bar_years": ">=10/15 profitable AND >=8/15 beat SPY",
                "year_bar_pass": wins >= 10 and spy_wins >= 8,
                "half_windows": halves, "bar_halves": "beat SPY on both",
                "half_bar_pass": all(v["beats_spy"] for v in halves.values())}
        conf["confirmed"] = conf["year_bar_pass"] and conf["half_bar_pass"]
        out["confirmation"] = conf
        print("CONFIRMATION", json.dumps(conf)[:400], flush=True)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("done", flush=True)

if __name__ == "__main__":
    main()
