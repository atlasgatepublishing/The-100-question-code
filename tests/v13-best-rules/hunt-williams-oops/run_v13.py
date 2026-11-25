"""V13 BEST RULES — hunt-williams-oops (Larry Williams Oops! pattern).
Implements BEST-RULES-SPEC.md exactly (frozen before this run):
  signal: open >=2% below prior low AND same-day high reclaims prior low
          AND prior close > trailing 200-close mean (bars strictly before t)
  entry:  prior low x 1.001 (pre-placed buy stop), exit: SAME DAY close
  pond pot: one position/day, largest gap wins, ties alphabetical, all-in
  SPY diagnostic: identical rules on SPY alone
  costs: 0.10%/side + $0.01 sell fee; $100 pots; NO floor/halt/restart
Loaders/cost conventions copied from the v12 family script (read-only)."""
import json, os, random, statistics, sys
from datetime import date

START = 100.0
COST = 0.001; SELL_FEE = 0.01
GAP_MIN = 0.02; TICK = 1.001; MA_N = 200
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
OUT = os.path.dirname(os.path.abspath(__file__))

import time
def load_stock(sym):
    j = json.load(open(os.path.join(PXDIR, f"pxfull_{sym}.json")))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if None in (q["close"][i], adj[i], q["open"][i], q["high"][i], q["low"][i]):
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i]*ratio, "h": q["high"][i]*ratio,
                     "l": q["low"][i]*ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    return bars

def signals_for(bars):
    """date -> signal dict, computed PIT (uses bars[t-1] and earlier for
    filter/gap level; bars[t] open known at open; bars[t] high only confirms
    the pre-placed stop fill)."""
    sig = {}
    closes = [b["c"] for b in bars]
    csum = [0.0]
    for c in closes: csum.append(csum[-1] + c)
    for t in range(1, len(bars)):
        if t < MA_N: continue
        ma = (csum[t] - csum[t-MA_N]) / MA_N  # closes of bars[t-200 .. t-1]
        if bars[t-1]["c"] <= ma: continue
        pl = bars[t-1]["l"]; o = bars[t]["o"]
        if o > pl * (1 - GAP_MIN): continue
        if bars[t]["h"] < pl: continue
        sig[bars[t]["d"]] = {"gap_pct": (pl - o) / pl, "entry_px": pl * TICK,
                            "exit_px": bars[t]["c"], "open": o}
    return sig

def period_stats(curve, tempo="monthly"):
    if not curve: return None
    seen = {}
    for d, v in curve: seen[d[:7]] = v
    vals = [seen[k] for k in sorted(seen)]
    series = [START] + vals
    if len(series) < 2: return None
    rets = [(series[i]/series[i-1]-1)*100 if series[i-1] > 0 else 0.0
            for i in range(1, len(series))]
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        if r < 0: streak += 1; worst = max(worst, streak)
        else: streak = 0
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak: peak = v; longest = max(longest, i-last_high); last_high = i
    longest = max(longest, len(series)-1-last_high)
    return {"tempo": tempo, "periods": len(rets),
            "pct_positive": round(100.0*pos/len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary_average_only": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak_periods": worst,
            "longest_between_highs_periods": longest}

def maxdd(curve):
    peak, m = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: m = max(m, (peak-v)/peak)
    return round(m*100, 2)

def day_trade(cash, entry_px, exit_px):
    bv = cash / (1 + COST); fee_b = bv * COST
    sh = bv / entry_px
    val = sh * exit_px; fee_s = val * COST + SELL_FEE
    return val - fee_s, fee_b + fee_s, val - bv  # new cash, costs, gross pnl approx

def run_pond(cal, sig_by_sym, bars_by_sym, start, end):
    days = [d for d in cal if start <= d <= end]
    cash, costs, trades, curve = START, 0.0, [], []
    for d in days:
        cands = [(s, sig_by_sym[s][d]) for s in sig_by_sym if d in sig_by_sym[s]]
        if cands:
            cands.sort(key=lambda x: (-x[1]["gap_pct"], x[0]))
            sym, sg = cands[0]
            new_cash, cst, _ = day_trade(cash, sg["entry_px"], sg["exit_px"])
            trades.append([d, sym, round(sg["gap_pct"]*100, 2), round(sg["entry_px"], 4),
                           round(sg["exit_px"], 4), round(new_cash - cash, 2)])
            costs += cst; cash = new_cash
        curve.append([d, round(cash, 4)])
    wins = sum(1 for t in trades if t[5] > 0)
    return {"final": round(cash, 2), "max_dd_pct": maxdd(curve), "costs": round(costs, 2),
            "trades_taken": len(trades),
            "win_rate_pct_secondary": round(100.0*wins/len(trades), 1) if trades else None,
            "expectancy_per_trade": round((cash-START)/len(trades), 2) if trades else None,
            "trades": trades, "equity_curve": curve,
            "period_stats_monthly": period_stats(curve, "monthly")}

def run_pond_placebo(cal, bars_by_sym, trade_days, start, end, seed):
    rng = random.Random(seed)
    by_date = {}
    for s, bars in bars_by_sym.items():
        for b in bars: by_date.setdefault(b["d"], []).append((s, b["o"], b["c"]))
    cash, costs = START, 0.0
    for d in trade_days:
        opts = by_date.get(d)
        if not opts: continue
        s, o, c = opts[rng.randrange(len(opts))]
        cash, cst, _ = day_trade(cash, o, c); costs += cst
    return round(cash, 2)

def run_single(cal, bars, sig, start, end):
    by = {b["d"]: b for b in bars}
    days = [d for d in cal if start <= d <= end]
    cash, costs, trades, curve = START, 0.0, [], []
    for d in days:
        if d in sig:
            sg = sig[d]
            new_cash, cst, _ = day_trade(cash, sg["entry_px"], sg["exit_px"])
            trades.append([d, round(sg["gap_pct"]*100, 2), round(sg["entry_px"], 4),
                           round(sg["exit_px"], 4), round(new_cash-cash, 2)])
            costs += cst; cash = new_cash
        curve.append([d, round(cash, 4)])
    wins = sum(1 for t in trades if t[4] > 0)
    return {"final": round(cash, 2), "max_dd_pct": maxdd(curve), "costs": round(costs, 2),
            "trades_taken": len(trades),
            "win_rate_pct_secondary": round(100.0*wins/len(trades), 1) if trades else None,
            "expectancy_per_trade": round((cash-START)/len(trades), 2) if trades else None,
            "trades": trades, "equity_curve": curve,
            "period_stats_monthly": period_stats(curve, "monthly")}

def run_single_placebo(cal, bars, trade_days, start, end, seed):
    """Circular shift of the invested-day series within the road (v12
    convention); shifted days enter at the open, exit at the close."""
    by = {b["d"]: b for b in bars}
    days = [d for d in cal if start <= d <= end]
    if len(days) < 2 or not trade_days: return START
    idx = [days.index(d) for d in trade_days if d in days]
    rng = random.Random(seed)
    k = rng.randrange(1, len(days))
    cash = START
    for i in idx:
        b = by[days[(i+k) % len(days)]]
        cash, _, _ = day_trade(cash, b["o"], b["c"])
    return round(cash, 2)

def buy_hold(bars, start, end):
    days = [b for b in bars if b["d"] >= start and b["d"] <= end]
    sh = (START/(1+COST)) / days[0]["o"]
    curve = [[b["d"], round(sh*b["c"], 4)] for b in days]
    val = sh * days[-1]["c"]; final = val - (val*COST + SELL_FEE)
    curve[-1] = [days[-1]["d"], round(final, 4)]
    return {"final": round(final, 2), "max_dd_pct": maxdd(curve), "equity_curve": curve}

def main():
    syms = sorted(f[7:-5] for f in os.listdir(PXDIR)
                  if f.startswith("pxfull_") and f[7:-5] != "SPY")
    spy = load_stock("SPY"); cal = [b["d"] for b in spy]
    bars_by_sym, sig_by_sym = {}, {}
    for s in syms:
        try: bars = load_stock(s)
        except Exception: continue
        if len(bars) < 300: continue
        bars_by_sym[s] = bars; sig_by_sym[s] = signals_for(bars)
    spy_sig = signals_for(spy)
    print(f"pond names: {len(bars_by_sym)}; total pond signals: "
          f"{sum(len(v) for v in sig_by_sym.values())}; SPY signals: {len(spy_sig)}", flush=True)
    out = {"family": "hunt-williams-oops (Larry Williams Oops!) — V13 BEST RULES",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "chassis": "$100; 0.10%/side + $0.01 sell fee; no floor; entry prior low x1.001 on reclaim; exit same-day close; gap>=2% below prior low; prior close > 200-close mean",
           "pond_names": len(bars_by_sym), "roads": {}}
    for name, (s, e) in ROADS.items():
        pond = run_pond(cal, sig_by_sym, bars_by_sym, s, e)
        trade_days = [t[0] for t in pond["trades"]]
        pf = [run_pond_placebo(cal, bars_by_sym, trade_days, s, e, seed)
              for seed in range(1, 21)]
        sp = run_single(cal, spy, spy_sig, s, e)
        spf = [run_single_placebo(cal, spy, [t[0] for t in sp["trades"]], s, e, seed)
               for seed in range(1, 21)]
        bh = buy_hold(spy, s, e)
        rec = {"pond_pot": pond,
               "pond_placebo": {"seed_finals": pf,
                                "beaten_of_20": sum(1 for p in pf if pond["final"] > p)},
               "spy_diagnostic": sp,
               "spy_placebo": {"seed_finals": spf,
                               "beaten_of_20": sum(1 for p in spf if sp["final"] > p)},
               "spy_buy_hold": {"final": bh["final"], "max_dd_pct": bh["max_dd_pct"]},
               "champion_vm": CHAMP[name], "spy_program_ref": SPYREF[name],
               "published_v12_spy_native": {"LONG": 8.30, "DECADE": 35.09,
                                            "CONT": 46.31, "VAL": 77.66}[name]}
        out["roads"][name] = rec
        print(f"{name}: POND ${pond['final']} (DD {pond['max_dd_pct']}%, trades "
              f"{pond['trades_taken']}, costs ${pond['costs']}, placebos "
              f"{rec['pond_placebo']['beaten_of_20']}/20) | SPY-diag ${sp['final']} "
              f"(trades {sp['trades_taken']}, costs ${sp['costs']}, placebos "
              f"{rec['spy_placebo']['beaten_of_20']}/20) | hold ${bh['final']} | "
              f"champ ${CHAMP[name]}", flush=True)
    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
