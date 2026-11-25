"""V13 BEST RULES — re-index-additions.
Frozen spec: BEST-RULES-SPEC.md in this folder.
Native event form (buy open day after public S&P DJI announcement, sell close of
effective date) + idle capital parked in SPY + slice = equity/3, max 3 concurrent.
Costs 0.10%/side on every leg. No floor, no stop. 20-seed placebos on the same chassis.
Event census read-only from v10-retest engine.py; prices read-only from v10 data cache
/ v3 bars; fresh SPY 2010-> fetch cached into THIS folder only."""
import sys, os, json, random, re, ast, math
import pandas as pd, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
V11 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/re-index-additions")
sys.path.insert(0, V11)
from native_lib import _parse_yahoo, fetch_yahoo, get_bars  # noqa: E402

SRC = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/re-index-additions/engine.py")
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/re-index-additions/data")
COST = 0.001
SLOTS = 3

# ---------------- data ----------------

def load_events_raw():
    txt = open(SRC).read()
    m = re.search(r"EVENTS = \[(.*?)\n\]", txt, re.S)
    return ast.literal_eval("[" + m.group(1) + "]")

V11DIR = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/re-index-additions")
V7DIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/re-index-additions/data")
V3BARS = os.path.expanduser("~/workspace/stock-app/backtests/v3/insider-data/bars")

def _try(path):
    if os.path.exists(path):
        try:
            df = _parse_yahoo(json.load(open(path)))
            if df is not None and len(df): return df
        except Exception:
            pass
    return None

def px(ticker):
    safe = ticker.replace("/", "-")
    for path in (os.path.join(PXDIR, f"px_{safe}.json"), os.path.join(V11DIR, f"yh_{safe}.json"),
                 os.path.join(V7DIR, f"px_{safe}.json"), os.path.join(V3BARS, f"{safe}.json")):
        df = _try(path)
        if df is not None: return df
    return fetch_yahoo(ticker, HERE)  # last resort: network, cached into HERE

def load_spy():
    df = fetch_yahoo("SPY", HERE)  # caches yh_SPY.json in HERE; period starts 2010
    if df is None or len(df) == 0 or df.index[0] > pd.Timestamp("2010-02-01"):
        p = os.path.join(PXDIR, "px_SPY.json")
        df2 = _parse_yahoo(json.load(open(p)))
        print(f"WARN: fresh SPY fetch insufficient; fallback v10 cache starts {df2.index[0].date()}")
        return df2
    return df

def build_events(spy):
    cal = list(spy.index)
    evs_raw = load_events_raw()
    events, dropped = [], {"no_bars": 0, "no_entry": 0}
    for ticker, ann, eff, note in evs_raw:
        df = px(ticker)
        if df is None or len(df) == 0:
            dropped["no_bars"] += 1; continue
        ad = pd.Timestamp(ann)
        after = df.index[df.index > ad]
        if len(after) == 0:
            dropped["no_entry"] += 1; continue
        ed = after[0]
        xd = pd.Timestamp(eff)
        xp = df["close"].asof(xd)
        if not xp or xp != xp:
            dropped["no_entry"] += 1; continue
        entry_price = float(df.loc[ed, "open"]) if ed in df.index else float(df["open"].asof(ed))
        events.append({"ticker": ticker, "entry_date": ed, "entry_price": entry_price,
                       "exit_date": xd, "exit_price": float(xp), "df": df,
                       "spy_entry": float(spy["close"].asof(ed)), "spy_exit": float(spy["close"].asof(xd)),
                       "ann": ann})
    events.sort(key=lambda e: e["entry_date"])
    return events, len(evs_raw), dropped

# ---------------- pot ----------------

def run_pot(events, spy, start, end):
    """SPY-parked event pot. All uncommitted capital in SPY. Entries at open,
    exits at close of effective date (or first cal day >= exit_date)."""
    seg = spy.loc[start:end]
    cal = list(seg.index)
    if not cal:
        return None
    spy_o_arr = seg["open"].to_numpy(); spy_c_arr = seg["close"].to_numpy()
    cal_set = set(cal)
    ev_by_date = {}
    for e in events:
        if start <= e["entry_date"] <= end:
            d = e["entry_date"]
            if d not in cal_set:  # snap to next trading day
                nxt = [c for c in cal if c >= d]
                if not nxt: continue
                d = nxt[0]
            ev_by_date.setdefault(d, []).append(e)
    cash = 100.0
    costs = 0.0; orders = 0; taken = 0; skipped = 0
    # initial SPY purchase at first close
    spy_sh = cash * (1 - COST) / float(spy_c_arr[0]); costs += cash * COST; orders += 1; cash = 0.0
    pos = []  # {shares, exit_date, exit_price, df}
    curve = []
    peak = 100.0; maxdd = 0.0
    prev_close_eq = 100.0
    for i, d in enumerate(cal):
        spy_o = float(spy_o_arr[i]); spy_c = float(spy_c_arr[i])
        # entries at open, sized off prior close equity
        if d in ev_by_date:
            for e in ev_by_date[d]:
                if len(pos) >= SLOTS:
                    skipped += 1; continue
                slice_amt = prev_close_eq / SLOTS
                avail = spy_sh * spy_o
                if slice_amt > avail: slice_amt = avail
                if slice_amt <= 1.0:
                    skipped += 1; continue
                sell_sh = slice_amt / spy_o
                spy_sh -= sell_sh; costs += slice_amt * COST; orders += 1
                net = slice_amt * (1 - COST)
                sh = net * (1 - COST) / e["entry_price"]; costs += net * COST; orders += 1
                pos.append({"ticker": e["ticker"], "shares": sh, "exit_date": e["exit_date"],
                            "exit_price": e["exit_price"], "df": e["df"]})
                taken += 1
        # exits at close
        still = []
        for p in pos:
            if d >= p["exit_date"]:
                proceeds = p["shares"] * p["exit_price"]; costs += proceeds * COST; orders += 1
                net = proceeds * (1 - COST)
                buy = net * (1 - COST) / spy_c; costs += net * COST; orders += 1
                spy_sh += buy
            else:
                still.append(p)
        pos = still
        eq = spy_sh * spy_c
        for p in pos:
            v = p["df"]["close"].asof(d)
            eq += p["shares"] * (v if v == v and v else p["exit_price"])
        curve.append((d, round(eq, 4)))
        prev_close_eq = eq
        peak = max(peak, eq); maxdd = max(maxdd, (peak - eq) / peak if peak else 0)
    return {"final": curve[-1][1], "max_dd_pct": round(maxdd * 100, 2), "costs": round(costs, 2),
            "orders": orders, "taken": taken, "skipped": skipped, "curve": curve}

# ---------------- reporting helpers ----------------

def year_dist(curve):
    """curve: list of (Timestamp, eq). Calendar-year returns within the road."""
    yrs = {}
    for d, v in curve:
        yrs.setdefault(d.year, []).append((d, v))
    rets = {}
    prev_last = None
    for y in sorted(yrs):
        seg = yrs[y]
        base = prev_last if prev_last is not None else seg[0][1]
        # first year: base is road-start 100 if curve starts at year start; use first point's prior = 100 only for first year
        if prev_last is None: base = 100.0
        rets[y] = seg[-1][1] / base - 1
        prev_last = seg[-1][1]
    vals = list(rets.values())
    streak = cur = 0
    for v in vals:
        cur = cur + 1 if v < 0 else 0
        streak = max(streak, cur)
    # longest stretch between new highs (trading days)
    peak = -1; peak_i = 0; longest = 0; unrecovered = False
    for i, (d, v) in enumerate(curve):
        if v >= peak:
            longest = max(longest, i - peak_i); peak = v; peak_i = i
    tail = len(curve) - 1 - peak_i
    if tail > longest:
        longest = tail; unrecovered = True
    return {"years": {str(y): round(r * 100, 2) for y, r in rets.items()},
            "median_year_pct": round(float(np.median(vals)) * 100, 2) if vals else None,
            "share_positive_pct": round(float(np.mean([v > 0 for v in vals])) * 100, 1) if vals else None,
            "best_year_pct": round(max(vals) * 100, 2) if vals else None,
            "worst_year_pct": round(min(vals) * 100, 2) if vals else None,
            "longest_losing_streak_years": streak,
            "longest_between_new_highs_days": longest,
            "ends_below_high": unrecovered}

def spy_bh(spy, start, end):
    s = spy.loc[start:end]
    return round(100.0 * s["close"].iloc[-1] / s["close"].iloc[0], 2)

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

def main():
    spy = load_spy()
    print(f"SPY bars: {spy.index[0].date()} -> {spy.index[-1].date()} n={len(spy)}")
    events, census, dropped = build_events(spy)
    print(f"events: census={census} tradable={len(events)} dropped={dropped}")
    ex = np.array([(e["exit_price"] * 0.999 / (e["entry_price"] * 1.001) - 1) - (e["spy_exit"] / e["spy_entry"] - 1) for e in events])
    raw = np.array([e["exit_price"] * 0.999 / (e["entry_price"] * 1.001) - 1 for e in events])
    evstats = {"n": len(events), "mean_net_pct": round(float(raw.mean()) * 100, 3),
               "mean_excess_pct": round(float(ex.mean()) * 100, 3),
               "median_excess_pct": round(float(np.median(ex)) * 100, 3),
               "pct_beat_spy": round(float((ex > 0).mean()) * 100, 1)}

    results = {"family": "re-index-additions", "program": "v13-best-rules",
               "spec": "native event form + SPY parking + equity/3 slices, max 3 concurrent, 0.10%/side, no floor",
               "events_census": census, "events_tradable": len(events), "dropped": dropped,
               "event_study": evstats, "roads": {}}
    strat_curves = {}
    for name, (s, e) in ROADS.items():
        st, en = pd.Timestamp(s), pd.Timestamp(e)
        pot = run_pot(events, spy, st, en)
        strat_curves[name] = pot["curve"]
        results["roads"][name] = {"final": pot["final"], "max_dd_pct": pot["max_dd_pct"],
                                  "costs": pot["costs"], "orders": pot["orders"], "taken": pot["taken"],
                                  "skipped": pot["skipped"], "spy_buyhold": spy_bh(spy, st, en),
                                  "champion_vm": CHAMP[name], "dist": year_dist(pot["curve"]),
                                  "curve": [(str(d.date()), v) for d, v in pot["curve"]]}
        print(f"{name}: final={pot['final']} dd={pot['max_dd_pct']}% spy={results['roads'][name]['spy_buyhold']} taken={pot['taken']} skipped={pot['skipped']}")

    # ---- placebos: 20 seeds, random tickers, same schedule/slices/parking ----
    # Pool preloaded from LOCAL v3 cache files only (no network in the placebo stage).
    pool, pool_bars = [], {}
    for p in sorted(os.listdir(V3BARS)):
        if len(pool) >= 800: break
        fp = os.path.join(V3BARS, p)
        if p.endswith(".json") and re.fullmatch(r"[A-Z]{1,5}", p[:-5]) and os.path.getsize(fp) > 30000:
            df = _try(fp)
            if df is not None and len(df) > 200:
                pool.append(p[:-5]); pool_bars[p[:-5]] = df
    print(f"placebo pool: {len(pool)} tickers preloaded")
    twin_sets = []
    for seed in range(20):
        r = random.Random(13000 + seed); tev = []
        for e in events:
            for _ in range(8):
                t = r.choice(pool); df = pool_bars[t]
                after = df.index[df.index > pd.Timestamp(e["ann"])]
                if len(after) == 0: continue
                ed = after[0]
                xp = df["close"].asof(e["exit_date"])
                if xp and xp == xp:
                    tev.append({"ticker": t, "entry_date": ed, "entry_price": float(df.loc[ed, "open"]),
                                "exit_date": e["exit_date"], "exit_price": float(xp), "df": df,
                                "ann": e["ann"]}); break
        twin_sets.append(tev)
    results["placebos"] = {}
    for name, (s, e) in ROADS.items():
        st, en = pd.Timestamp(s), pd.Timestamp(e)
        finals = []
        for tev in twin_sets:
            tp = run_pot(tev, spy, st, en)
            finals.append(tp["final"] if tp else None)
        mine = results["roads"][name]["final"]
        beaten = sum(1 for f in finals if f is not None and mine > f)
        results["placebos"][name] = {"beaten": f"{beaten}/20", "twin_finals": finals,
                                     "twin_median": round(float(np.median([f for f in finals if f is not None])), 2)}
        print(f"placebo {name}: beaten {beaten}/20 twin_median={results['placebos'][name]['twin_median']}")

    # ---- confirmation (only if a road beats champion V+M) ----
    beaten_roads = [n for n in ROADS if results["roads"][n]["final"] > CHAMP[n]]
    results["champion_beats"] = beaten_roads
    if beaten_roads:
        print("CHAMPION BEAT on", beaten_roads, "— running frozen confirmation")
        conf = {}
        for y in range(2019, 2027):
            pot = run_pot(events, spy, pd.Timestamp(f"{y}-01-01"), pd.Timestamp(f"{y}-12-31"))
            conf[f"fold_{y}"] = pot["final"] if pot else None
        for lbl, (s, e) in {"halfA_2019_2022": ("2019-01-02", "2022-12-30"), "halfB_2023_2026": ("2023-01-03", "2026-11-20"),
                            "halfA_dec_2016_2021": ("2016-11-21", "2021-12-31"), "halfB_dec_2022_2026": ("2022-01-03", "2026-11-20")}.items():
            pot = run_pot(events, spy, pd.Timestamp(s), pd.Timestamp(e))
            conf[lbl] = pot["final"] if pot else None
        results["confirmation"] = conf
        print(json.dumps(conf, indent=1))
    json.dump(results, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
