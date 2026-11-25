"""V13 BEST RULES — Earnings Announcement Premium (pre-announcement run-up form).
Spec frozen in BEST-RULES-SPEC.md before this run.
- Expected announcement date = same-quarter EPS fact filed date one year earlier + 1yr (v11 eps_cache, EDGAR filed dates, point-in-time).
- Entry: close 10 trading days before expected announcement (buy at close of entry day = exit_idx-9).
- Exit: close of last trading day BEFORE the expected announcement date. Never held through.
- Sizing: 10% of current equity per entry slot; announcer exposure capped at 100% of equity.
- Idle capital in SPY (traded only on event days). NO floor, no stop.
- Costs: 0.10%/side large (v3 cache), 0.35%/side small/mid (v4 cache), SPY 0.10%/side.
- Placebos: same event calendar/slot counts, random tickers, seeds 1..20.
"""
import json, os, glob, random, statistics
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V3 = "/home/hatch/workspace/stock-app/backtests/v3/pead-cache"
V4 = "/home/hatch/workspace/stock-app/backtests/v4/pead-small-cache"
EPS = "/home/hatch/workspace/stock-app/backtests/v11-native-rules/gap-a2-earnings-premium/eps_cache"

def load_px(t):
    for c in (V3, V4):
        p = os.path.join(c, f"px_{t}.json")
        if os.path.exists(p):
            d = json.load(open(p))["chart"]["result"][0]
            out = {}
            for i, x in enumerate(d["timestamp"]):
                a = d["indicators"]["adjclose"][0]["adjclose"][i]
                if a: out[date.fromtimestamp(x).isoformat()] = a
            return out
    return {}

large = {os.path.basename(f)[3:-5] for f in glob.glob(os.path.join(V3, "px_*.json"))} - {"SPY"}
tickers = sorted(({os.path.basename(f)[3:-5] for c in (V3, V4)
                   for f in glob.glob(os.path.join(c, "px_*.json"))} - {"SPY"}))
px = {t: load_px(t) for t in tickers}
spy = load_px("SPY")
cal = sorted(spy.keys()); cal_idx = {d: i for i, d in enumerate(cal)}
cost = {t: (0.0010 if t in large else 0.0035) for t in tickers}
SPY_COST = 0.0010

# ---- expected announcement events -------------------------------------------
# For each filed EPS fact, the same quarter next year is expected on filed+1yr.
events = []  # (entry_idx, exit_idx, ticker)
for t in tickers:
    fp = os.path.join(EPS, f"eps_{t}.json")
    if not os.path.exists(fp): continue
    seen = set()
    for f in json.load(open(fp))["facts"]:
        filed = f["filed"]
        if filed in seen: continue
        seen.add(filed)
        y, m, dd = int(filed[:4]), int(filed[5:7]), int(filed[8:10])
        try: exp = date(y + 1, m, dd)
        except ValueError: exp = date(y + 1, m, 28)
        exp_s = exp.isoformat()
        # A = first trading day >= expected date
        a_idx = next((cal_idx[d] for d in cal if d >= exp_s), None)
        if a_idx is None: continue
        exit_idx = a_idx - 1
        entry_idx = exit_idx - 9
        if entry_idx < 0: continue
        if px[t].get(cal[entry_idx]) and px[t].get(cal[exit_idx]):
            events.append((entry_idx, exit_idx, t))
events.sort()
# drop overlapping duplicate windows for same ticker (keep earliest entry)
filtered, last_exit = [], {}
for e in events:
    if e[0] <= last_exit.get(e[2], -1): continue
    filtered.append(e); last_exit[e[2]] = e[1]
events = filtered

def run(start, end, evts):
    s_idx, e_idx = cal_idx[start], cal_idx[end]
    by_entry, by_exit = {}, {}
    for (en, ex, t) in evts:
        if s_idx <= en and ex <= e_idx:
            by_entry.setdefault(en, []).append(t)
            by_exit.setdefault(ex, []).append(t)
    cash, holdings, spy_sh, curve, total_cost, n_trades = 100.0, {}, 0.0, [], 0.0, 0
    pending_exit = set()
    # day 0: park everything in SPY
    p0 = spy[cal[s_idx]]
    spy_sh = cash * (1 - SPY_COST) / p0; total_cost += cash * SPY_COST; cash = 0.0; n_trades += 1
    for i in range(s_idx, e_idx + 1):
        d = cal[i]
        # exits at close (retry on later days if that day's price is missing)
        pending_exit |= {t for t in by_exit.get(i, []) if t in holdings}
        for t in list(pending_exit):
            if t in holdings:
                p = px[t].get(d)
                if p:
                    v = holdings.pop(t) * p
                    cash += v * (1 - cost[t]); total_cost += v * cost[t]; n_trades += 1
                    pending_exit.discard(t)
        # entries at close
        entries = [t for t in by_entry.get(i, []) if t not in holdings and px[t].get(d)]
        if entries:
            eq = cash + spy_sh * spy[d] + sum(sh * px[t].get(d, 0) for t, sh in holdings.items())
            ann_val = sum(sh * px[t].get(d, 0) for t, sh in holdings.items())
            room = max(0.0, eq - ann_val)
            per = min(0.10 * eq, room / len(entries))
            for t in entries:
                want = per
                # fund from cash first, then sell SPY for the shortfall
                need = want - cash
                if need > 0 and spy_sh > 0:
                    sell_v = min(spy_sh * spy[d], need / (1 - SPY_COST))
                    spy_sh -= sell_v / spy[d]; cash += sell_v * (1 - SPY_COST)
                    total_cost += sell_v * SPY_COST; n_trades += 1
                buy = min(cash, want)
                if buy > 1.0:
                    holdings[t] = buy * (1 - cost[t]) / px[t][d]
                    total_cost += buy * cost[t]; cash -= buy; n_trades += 1
        # leftover cash -> SPY (event days only)
        if (i in by_entry or i in by_exit) and cash > 1.0:
            spy_sh += cash * (1 - SPY_COST) / spy[d]; total_cost += cash * SPY_COST; cash = 0.0; n_trades += 1
        eq = cash + spy_sh * spy[d] + sum(sh * px[t].get(d, 0) for t, sh in holdings.items())
        curve.append([d, round(eq, 2)])
    final = curve[-1][1]
    peak, mdd = 100.0, 0.0
    for _, v in curve: peak = max(peak, v); mdd = min(mdd, v / peak - 1)
    # per-year distribution
    yr_eq = {}
    for d, v in curve: yr_eq[int(d[:4])] = v
    years = sorted(yr_eq); prev, yr_ret = 100.0, {}
    for y in years:
        yr_ret[y] = round((yr_eq[y] / prev - 1) * 100, 2) if prev else None; prev = yr_eq[y]
    rets = [yr_ret[y] for y in years if yr_ret[y] is not None]
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    # longest stretch between new highs (trading days)
    peak_v, peak_i, max_gap = 0.0, 0, 0
    for i, (_, v) in enumerate(curve):
        if v >= peak_v: peak_v, peak_i = v, i
        max_gap = max(max_gap, i - peak_i)
    dist = {"median_year_pct": round(statistics.median(rets), 2) if rets else None,
            "share_years_positive": f"{sum(1 for r in rets if r > 0)}/{len(rets)}",
            "best_year_pct": max(rets) if rets else None, "worst_year_pct": min(rets) if rets else None,
            "longest_losing_streak_years": streak,
            "longest_days_between_new_highs": max_gap,
            "mean_year_pct_secondary": round(statistics.mean(rets), 2) if rets else None,
            "year_returns_pct": {str(y): yr_ret[y] for y in years}}
    s0, s1 = spy[cal[s_idx]], spy[cal[e_idx]]
    return {"final": final, "max_dd_pct": round(mdd * 100, 2), "costs": round(total_cost, 2),
            "trades": n_trades, "spy_final": round(100 * s1 / s0, 2),
            "distribution": dist, "curve": curve}

if __name__ == "__main__":
    ROADS = {"FULL_2018_2026": (cal[0], "2026-11-20"),
             "CONT_2019_2026": ("2019-01-02", "2026-11-20"),
             "VAL_2023_2026": ("2023-01-03", "2026-11-20")}
    out = {"universe_n": len(tickers), "n_events_total": len(events), "roads": {}}
    for name, (a, b) in ROADS.items():
        r = run(a, b, events)
        out["roads"][name] = r
        print(name, "final", r["final"], "dd", r["max_dd_pct"], "costs", r["costs"],
              "trades", r["trades"], "spy", r["spy_final"])

    # placebos on FULL and CONT: same calendar/slots, random tickers
    for name in ("FULL_2018_2026", "CONT_2019_2026"):
        a, b = ROADS[name]; finals = []
        for s in range(1, 21):
            rng = random.Random(s)
            pev = []
            for (en, ex, t) in events:
                for _ in range(50):
                    cand = rng.choice(tickers)
                    if px[cand].get(cal[en]) and px[cand].get(cal[ex]): break
                pev.append((en, ex, cand))
            pev.sort()
            f2, lx = [], {}
            for e in pev:
                if e[0] <= lx.get(e[2], -1): continue
                f2.append(e); lx[e[2]] = e[1]
            finals.append(run(a, b, f2)["final"])
        real = out["roads"][name]["final"]
        out.setdefault("placebos", {})[name] = {
            "finals": finals, "beaten": sum(1 for x in finals if real > x),
            "median": round(statistics.median(finals), 2)}
        print(name, "placebo beaten", out["placebos"][name]["beaten"], "/20 median",
              out["placebos"][name]["median"])

    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved results.json")
