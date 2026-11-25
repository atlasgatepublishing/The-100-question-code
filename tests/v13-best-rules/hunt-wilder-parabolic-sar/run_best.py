"""V13 BEST-RULES run — Wilder Parabolic SAR.
Rules frozen in BEST-RULES-SPEC.md before this run:
SAR (published math, AF 0.02/+0.02/cap 0.20, untouched) is the EXIT only.
Entry gate: close > 200d SMA AND SAR leg long. Basket of up to 10 pond
names, equal target weight (equity/10 per buy), 126d momentum rank fills
empty slots at weekly checks; SAR flip-down exits daily at next open;
held names sold at weekly check only if ineligible; never sold for rank.
NO -15% floor (SAR is the stop). Costs: 0.10%/side + $0.01 sell fee.
Fills at next bar open. $100 pots. Roads per program standard.
Placebos: basket signals lagged k=7*seed master days (20 seeds);
SPY single-name diagnostic with circular-shift state placebos (20 seeds).
"""
import json, os, time, random, statistics, bisect
from datetime import date

START = 100.0
STK_COST = 0.001; STK_SELL_FEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
OUTDIR = os.path.dirname(os.path.abspath(__file__))
MAXHOLD = 10

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

def pond_symbols():
    return sorted(f[7:-5] for f in os.listdir(PXDIR)
                  if f.startswith("pxfull_") and f[7:-5] != "SPY")

def sar_states(bars):
    """Published Wilder SAR exactly (as v12 BUILDER). states[t]=1 if leg long."""
    n = len(bars)
    h = [b["h"] for b in bars]; l = [b["l"] for b in bars]
    states = [0]*n
    leg = 1; ep = h[0]; sar = l[0]; af = 0.02
    states[0] = 1
    for t in range(1, n):
        s = sar + af*(ep - sar)
        if leg == 1:
            s = min(s, l[t-1], l[t-2] if t >= 2 else l[t-1])
            if l[t] <= s:
                leg = -1; sar = ep; ep = l[t]; af = 0.02
            else:
                sar = s
                if h[t] > ep: ep = h[t]; af = min(af + 0.02, 0.20)
        else:
            s = max(s, h[t-1], h[t-2] if t >= 2 else h[t-1])
            if h[t] >= s:
                leg = 1; sar = ep; ep = h[t]; af = 0.02
            else:
                sar = s
                if l[t] < ep: ep = l[t]; af = min(af + 0.02, 0.20)
        states[t] = 1 if leg == 1 else 0
    return states

def name_signals(bars):
    """Per-bar: sar_long (0/1), trend_ok (close>200d SMA), mom126 (or None)."""
    n = len(bars); c = [b["c"] for b in bars]
    sar = sar_states(bars)
    trend = [0]*n; mom = [None]*n
    run = 0.0
    for t in range(n):
        run += c[t]
        if t >= 200: run -= c[t-200]
        if t >= 199: trend[t] = 1 if c[t] > run/200.0 else 0
        if t >= 126 and c[t-126] > 0: mom[t] = c[t]/c[t-126] - 1.0
    return sar, trend, mom

def period_stats(curve, tempo="monthly"):
    if not curve: return None
    seen = {}
    for d, v in curve:
        k = d[:7] if tempo == "monthly" else d[:7]
        seen[k] = v
    vals = [seen[k] for k in sorted(seen)]
    series = [START] + vals
    if len(series) < 2: return None
    rets = [(series[i]/series[i-1] - 1.0)*100.0 if series[i-1] > 0 else 0.0
            for i in range(1, len(series))]
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        if r < 0: streak += 1; worst = max(worst, streak)
        else: streak = 0
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak: peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(series)-1-last_high)
    return {"tempo": tempo, "periods": len(rets),
            "pct_positive": round(100.0*pos/len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary_average_only": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak_periods": worst,
            "longest_between_highs_periods": longest}

# ---------------- basket engine ----------------

class NameData:
    """Signals aligned to the master (SPY) calendar."""
    def __init__(self, sym, bars, master_dates):
        self.sym = sym; self.bars = bars
        sar, trend, mom = name_signals(bars)
        dates = [b["d"] for b in bars]
        self.al_sar = []; self.al_trend = []; self.al_mom = []; self.al_close = []
        for d in master_dates:
            j = bisect.bisect_right(dates, d) - 1
            if j < 0:
                self.al_sar.append(0); self.al_trend.append(0)
                self.al_mom.append(None); self.al_close.append(None)
            else:
                self.al_sar.append(sar[j]); self.al_trend.append(trend[j])
                self.al_mom.append(mom[j]); self.al_close.append(bars[j]["c"])
        # next bar (exec) per master index: first bar with date > master date
        self.nextbar = []
        for d in master_dates:
            j = bisect.bisect_right(dates, d)
            self.nextbar.append((bars[j]["d"], bars[j]["o"]) if j < len(bars) else None)

def lag(arr, k, default):
    if k <= 0: return list(arr)
    return [default]*k + list(arr[:-k]) if k < len(arr) else [default]*len(arr)

def run_basket(names, mdates, i0, i1, lag_k=0):
    """names: {sym: NameData}; mdates: full master calendar; road = [i0, i1)."""
    n = i1 - i0
    # per-name road-sliced (possibly lagged) signals
    sig = {}
    for sym, nd in names.items():
        sig[sym] = {
            "sar": lag(nd.al_sar[i0:i1], lag_k, 0),
            "trend": lag(nd.al_trend[i0:i1], lag_k, 0),
            "mom": lag(nd.al_mom[i0:i1], lag_k, None),
            "close": nd.al_close[i0:i1],
            "nextbar": nd.nextbar[i0:i1],
        }
    # weekly decision days: last master day of each ISO week + first day
    dec = set([0])
    for t in range(n):
        d = mdates[i0+t]
        y, m, dd = map(int, d.split("-"))
        wk = date(y, m, dd).isocalendar()[:2]
        if t+1 >= n: dec.add(t)
        else:
            d2 = mdates[i0+t+1]; y2, m2, dd2 = map(int, d2.split("-"))
            if date(y2, m2, dd2).isocalendar()[:2] != wk: dec.add(t)
    cash, pos = START, {}   # sym -> shares
    pending = []            # [exec_date, sym, side, target_value, open_px]
    pend_syms = set()
    trades, costs, curve = [], 0.0, []
    days_invested = 0
    for t in range(n):
        today = mdates[i0+t]
        # execute pending orders due (exec bar date <= today), at that bar's open
        still = []
        for exd, sym, side, tgt, opx in pending:
            if exd <= today:
                if side == "BUY" and sym not in pos and cash > 0:
                    spend = min(tgt, cash)
                    bv = spend/(1+STK_COST)
                    if bv >= 0.50:
                        sh = bv/opx; fee = bv*STK_COST
                        cash -= bv + fee; costs += fee; pos[sym] = sh
                        trades.append([exd, sym, "BUY", round(opx, 4), round(bv, 2)])
                    pend_syms.discard(sym)
                elif side == "SELL" and sym in pos:
                    val = pos[sym]*opx; fee = val*STK_COST + STK_SELL_FEE
                    cash += val - fee; costs += fee; del pos[sym]
                    trades.append([exd, sym, "SELL", round(opx, 4), round(val, 2)])
                    pend_syms.discard(sym)
                else:
                    pend_syms.discard(sym)
            else:
                still.append([exd, sym, side, tgt, opx])
        pending = still
        # mark equity at close
        eq = cash
        for sym, sh in pos.items():
            cl = sig[sym]["close"][t]
            if cl is not None: eq += sh*cl
        if pos: days_invested += 1
        curve.append([today, round(eq, 4)])
        # --- decisions at close ---
        def schedule(sym, side, tgt=0.0):
            nb = sig[sym]["nextbar"][t]
            if nb is None: return False
            pending.append([nb[0], sym, side, tgt, nb[1]])
            pend_syms.add(sym)
            return True
        # daily SAR exit
        for sym in list(pos):
            if sym not in pend_syms and sig[sym]["sar"][t] == 0:
                schedule(sym, "SELL")
        # weekly selection
        if t in dec:
            for sym in list(pos):
                if sym not in pend_syms:
                    if not (sig[sym]["trend"][t] == 1 and sig[sym]["sar"][t] == 1):
                        schedule(sym, "SELL")
            held_after = [s for s in pos if not (s in pend_syms)]
            # slots = cap - (positions not being sold) - (pending buys)
            n_sell_pend = sum(1 for s in pos if s in pend_syms)
            n_buy_pend = sum(1 for p in pending if p[2] == "BUY")
            slots = MAXHOLD - (len(pos) - n_sell_pend) - n_buy_pend
            if slots > 0:
                cands = []
                for sym, sg in sig.items():
                    if sym in pos or sym in pend_syms: continue
                    if sg["trend"][t] == 1 and sg["sar"][t] == 1 and sg["mom"][t] is not None:
                        cands.append((sg["mom"][t], sym))
                cands.sort(reverse=True)
                tgt = eq/MAXHOLD
                for _, sym in cands[:slots]:
                    schedule(sym, "BUY", tgt)
    # final liquidation at last close
    last = mdates[i1-1]
    for sym, sh in list(pos.items()):
        cl = sig[sym]["close"][n-1]
        if cl is None: continue
        val = sh*cl; fee = val*STK_COST + STK_SELL_FEE
        cash += val - fee; costs += fee
        trades.append([last, sym, "SELL-END", round(cl, 4), round(val, 2)])
    pos = {}
    if curve: curve[-1] = [last, round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak-v)/peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd*100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0*days_invested/n, 1) if n else 0.0,
            "equity_curve": curve,
            "period_stats_monthly": period_stats(curve, "monthly")}

# ---------------- SPY single-name diagnostic (chassis) ----------------

def simulate_states(bars, states, start, end, cost, sell_fee, shift_seed=None):
    idx = [i for i, b in enumerate(bars) if b["d"] >= start and b["d"] <= end]
    if not idx: return None
    st = list(states)
    if shift_seed is not None:
        seg = [states[i] for i in idx]
        pre = states[idx[0]-1] if idx[0] > 0 else 0
        rng = random.Random(shift_seed)
        if len(seg) > 1:
            k = rng.randrange(1, len(seg)); seg = seg[k:] + seg[:k]
        for j, i in enumerate(idx): st[i] = seg[j]
        entry_state = pre
    else:
        entry_state = states[idx[0]-1] if idx[0] > 0 else 0
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    pending = entry_state
    days_invested = 0
    for i in idx:
        b = bars[i]
        if pending is not None:
            if pending == 1 and shares == 0.0 and cash > 0:
                bv = cash/(1+cost); fee = bv*cost
                shares = bv/b["o"]; cash -= bv + fee; costs += fee
                trades.append([b["d"], "BUY", round(b["o"], 4), round(bv, 2), round(fee, 2)])
            elif pending == 0 and shares > 0:
                val = shares*b["o"]; fee = val*cost + sell_fee
                cash += val - fee; costs += fee; shares = 0.0
                trades.append([b["d"], "SELL", round(b["o"], 4), round(val, 2), round(fee, 2)])
            pending = None
        if st[i] != (1 if shares > 0 else 0): pending = st[i]
        eq = cash + shares*b["c"]
        if shares > 0: days_invested += 1
        curve.append([b["d"], round(eq, 4)])
    if shares > 0:
        last = bars[idx[-1]]; val = shares*last["c"]; fee = val*cost + sell_fee
        cash += val - fee; costs += fee; shares = 0.0
        trades.append([last["d"], "SELL-END", round(last["c"], 4), round(val, 2), round(fee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak-v)/peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd*100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0*days_invested/len(idx), 1),
            "equity_curve": curve}

def buy_hold(bars, start, end, cost, sell_fee):
    days = [b for b in bars if b["d"] >= start and b["d"] <= end]
    if not days: return None
    sh = (START/(1+cost))/days[0]["o"]
    curve = [[b["d"], round(sh*b["c"], 4)] for b in days]
    val = sh*days[-1]["c"]; final = val - (val*cost + sell_fee)
    curve[-1] = [days[-1]["d"], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: maxdd = max(maxdd, (peak-v)/peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd*100, 2), "equity_curve": curve}

def main():
    spy = load_stock("SPY")
    master = [b["d"] for b in spy if "2010-01-04" <= b["d"] <= "2026-11-20"]
    midx = {d: i for i, d in enumerate(master)}
    print(f"master calendar: {len(master)} days {master[0]}..{master[-1]}", flush=True)
    names = {}
    for sym in pond_symbols():
        try: bars = load_stock(sym)
        except Exception: continue
        if len(bars) < 300: continue
        names[sym] = NameData(sym, bars, master)
    print(f"pond names with data: {len(names)}", flush=True)
    out = {"family": "hunt-wilder-parabolic-sar (Wilder Parabolic SAR, 1978)",
           "program": "v13 BEST RULES — spec frozen in BEST-RULES-SPEC.md before run",
           "label": "CANDIDATE ceiling — every road has been seen before",
           "rules_summary": "SAR exit-only (published math); entry gate close>200d SMA & SAR long; basket <=10 names equal target weight; 126d momentum fills slots at weekly checks; SAR exits daily; no floor",
           "pond_names": len(names), "roads": {}}
    for rname, (s, e) in ROADS.items():
        i0 = midx[s]; i1 = midx[e] + 1
        real = run_basket(names, master, i0, i1, lag_k=0)
        pf = []
        for seed in range(1, 21):
            r = run_basket(names, master, i0, i1, lag_k=7*seed)
            pf.append(r["final"])
        beaten = sum(1 for p in pf if real["final"] > p)
        # SPY diagnostic: same rules all-in on SPY
        sar, trend, _ = name_signals(spy)
        states = [1 if (sar[t] == 1 and trend[t] == 1) else 0 for t in range(len(spy))]
        diag = simulate_states(spy, states, s, e, STK_COST, STK_SELL_FEE)
        dpf = []
        for seed in range(1, 21):
            r = simulate_states(spy, states, s, e, STK_COST, STK_SELL_FEE, shift_seed=seed)
            dpf.append(r["final"] if r else None)
        dbeaten = sum(1 for p in dpf if diag["final"] > p)
        bh = buy_hold(spy, s, e, STK_COST, STK_SELL_FEE)
        rec = {"basket": real,
               "basket_placebo_lag": {"seed_finals": pf, "beaten_of_20": beaten,
                                      "design": "identical basket machinery, all signals lagged k=7*seed master-calendar days"},
               "spy_single_name_diagnostic": {**diag,
                    "period_stats_monthly": period_stats(diag["equity_curve"], "monthly")},
               "spy_diag_placebo": {"seed_finals": dpf, "beaten_of_20": dbeaten,
                                    "design": "circular shift of daily in/out state within road"},
               "spy_buy_hold": {"final": bh["final"], "max_dd_pct": bh["max_dd_pct"]},
               "champion_vm": CHAMP[rname], "spy_program_ref": SPYREF[rname],
               "beats_champion": real["final"] > CHAMP[rname]}
        out["roads"][rname] = rec
        print(f"{rname}: basket ${real['final']} DD {real['max_dd_pct']}% orders {real['orders']} "
              f"placebos {beaten}/20 | SPY-diag ${diag['final']} ({dbeaten}/20) | hold ${bh['final']} | champ ${CHAMP[rname]}",
              flush=True)
    with open(os.path.join(OUTDIR, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
