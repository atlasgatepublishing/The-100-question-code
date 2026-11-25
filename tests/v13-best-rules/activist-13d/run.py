"""Activist-13D V13 BEST-RULES run — ONE run of the frozen spec in BEST-RULES-SPEC.md.
Universe: EDGAR census 2010-2026 (v11 census + backward extension), intent-phrase filter,
liquidity floor ($500k median daily $ volume, price >= $3), entry next open after filing,
exit close +126 trading days, 10 slots, costs 0.25%/side (2% if < $5), no floor."""
import sys, os, json, random, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd, numpy as np
from lib import get_bars, spy_calendar, run_event_pot, spy_final, cost_rate

HERE = os.path.dirname(os.path.abspath(__file__))
HOLD_TD = 126; SLOTS = 10; MIN_DV = 500_000; MIN_PX = 3.0
ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-01-01", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}

def load_intent():
    intent = {}
    for f in glob.glob(os.path.join(HERE, "intent_*.json")):
        if "progress" in f: continue
        for adsh, phrases in json.load(open(f)).items():
            intent.setdefault(adsh, set()).update(phrases)
    return intent

def build_events(spy):
    cal = list(spy.index); cal_pos = {d: i for i, d in enumerate(cal)}
    census = json.load(open(os.path.join(HERE, "my_census.json")))
    intent = load_intent()
    rows = sorted(census.values(), key=lambda x: x["file_date"])
    last = {}; campaigns = []
    for r in rows:
        if not r["ticker"]: continue
        fd = pd.Timestamp(r["file_date"])
        if r["cik"] in last and (fd - last[r["cik"]]).days < 365: continue
        last[r["cik"]] = fd; campaigns.append(r)
    stage = {"filings": len(census), "campaigns": len(campaigns), "intent_flagged": 0,
             "no_bars": 0, "no_entry": 0, "illiquid_or_penny": 0, "short_history": 0,
             "stale_bars_start": 0, "tradable": 0}
    events = []
    for r in campaigns:
        if r["adsh"] not in intent: continue
        stage["intent_flagged"] += 1
        df = get_bars(r["ticker"], HERE)
        if df is None or len(df) == 0: stage["no_bars"] += 1; continue
        fd = pd.Timestamp(r["file_date"])
        after = df.index[df.index > fd]
        if len(after) == 0: stage["no_entry"] += 1; continue
        ed = after[0]
        if (ed - fd).days > 10:  # bars begin long after the filing: not a real entry
            stage["stale_bars_start"] += 1; continue
        if ed not in cal_pos:
            nxt = [d for d in cal if d >= ed]
            if not nxt: stage["no_entry"] += 1; continue
            ed = nxt[0]
        ep = df["open"].asof(ed)
        if not ep or ep != ep: stage["no_entry"] += 1; continue
        hist = df.loc[df.index < ed].tail(60)
        if len(hist) < 40: stage["short_history"] += 1; continue
        med_dv = float((hist["volume"] * hist["close"]).median())
        if med_dv < MIN_DV or ep < MIN_PX: stage["illiquid_or_penny"] += 1; continue
        ei = cal_pos[ed]; xi = min(ei + HOLD_TD, len(cal) - 1); xd = cal[xi]
        xp = df["close"].asof(xd)
        if not xp or xp != xp: stage["no_entry"] += 1; continue
        events.append({"ticker": r["ticker"], "adsh": r["adsh"], "file_date": r["file_date"],
                       "phrases": sorted(intent[r["adsh"]]), "entry_date": ed, "entry_price": float(ep),
                       "exit_date": xd, "exit_price": float(xp), "df": df,
                       "truncated": bool(ei + HOLD_TD > len(cal) - 1),
                       "spy_entry": float(spy["close"].asof(ed)), "spy_exit": float(spy["close"].asof(xd))})
        stage["tradable"] += 1
    print("stage:", stage, flush=True)
    return events, stage

def net_excess(e):
    cr_e = cost_rate(e["entry_price"], 0.0025); cr_x = cost_rate(e["exit_price"], 0.0025)
    net = e["exit_price"] * (1 - cr_x) / (e["entry_price"] * (1 + cr_e)) - 1
    return net - (e["spy_exit"] / e["spy_entry"] - 1)

def stats(evs):
    if not evs: return {"n": 0, "mean_excess_pct": None, "median_excess_pct": None, "pct_beat_spy": None}
    ex = np.array([net_excess(e) for e in evs])
    return {"n": len(ex), "mean_excess_pct": round(float(ex.mean()) * 100, 3),
            "median_excess_pct": round(float(np.median(ex)) * 100, 3),
            "pct_beat_spy": round(float((ex > 0).mean()) * 100, 1)}

_POOL = None
def _pool_dfs():
    """Random-ticker pool pre-parsed ONCE from local caches only (no network):
    the program bars pool (v3 insider-data) tickers whose files parse."""
    global _POOL
    if _POOL is not None: return _POOL
    import re as _re
    from lib import _parse_yahoo
    pool = {}
    v3 = os.path.expanduser("~/workspace/stock-app/backtests/v3/insider-data/bars")
    for p in os.listdir(v3):
        if p.endswith(".json") and _re.fullmatch(r"[A-Z]{1,5}", p[:-5]):
            try: df = _parse_yahoo(json.load(open(os.path.join(v3, p))))
            except Exception: df = None
            if df is not None and len(df) > 0: pool[p[:-5]] = df
    _POOL = pool
    return pool

def placebos(evs, spy):
    pool = _pool_dfs(); tickers = sorted(pool)
    base = stats(evs)["mean_excess_pct"]; beaten = 0; twins = []
    for seed in range(20):
        r = random.Random(4000 + seed); tex = []
        for e in evs:
            for _ in range(8):
                df = pool[r.choice(tickers)]
                ep = df["open"].asof(e["entry_date"]); xp = df["close"].asof(e["exit_date"])
                if ep and xp and ep == ep and xp == xp:
                    tex.append((xp / ep - 1) - (e["spy_exit"] / e["spy_entry"] - 1)); break
        m = round(float(np.mean(tex)) * 100, 3) if tex else None; twins.append(m)
        if m is not None and base is not None and base > m: beaten += 1
    return {"beaten": f"{beaten}/20", "twin_mean_excess_pct": twins, "pool_size": len(tickers)}

def period_distribution(curve):
    """curve: [(date_str, equity)] daily. Calendar-year returns + time-between-highs."""
    if not curve: return {}
    eq = pd.Series({pd.Timestamp(d): v for d, v in curve}).sort_index()
    years = {}
    prev = 100.0
    for y, grp in eq.groupby(eq.index.year):
        years[int(y)] = round((grp.iloc[-1] / prev - 1) * 100, 2); prev = grp.iloc[-1]
    rets = list(years.values())
    streak = cur = 0
    for r in rets: cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    peak = -1e18; last_high = eq.index[0]; max_gap = 0
    for d, v in eq.items():
        if v >= peak: peak = v; last_high = d
        else: max_gap = max(max_gap, (d - last_high).days)
    return {"yearly_returns_pct": years, "median_year_pct": round(float(np.median(rets)), 2) if rets else None,
            "share_years_positive": round(float(np.mean([r > 0 for r in rets])) * 100, 1) if rets else None,
            "best_year_pct": max(rets) if rets else None, "worst_year_pct": min(rets) if rets else None,
            "longest_losing_streak_years": streak, "longest_between_new_highs_days": int(max_gap)}

def main():
    spy = spy_calendar(HERE)
    events, stage = build_events(spy)
    out = {"family": "activist-13d", "program": "v13-best-rules", "stage": stage,
           "spec": {"hold_td": HOLD_TD, "slots": SLOTS, "min_median_dollar_vol": MIN_DV,
                    "min_price": MIN_PX, "costs": "0.25%/side, 2%/side if < $5", "floor": None},
           "roads": {}}
    for name, (s, e) in ROADS.items():
        start, end = pd.Timestamp(s), pd.Timestamp(e)
        evs = [ev for ev in events if start <= ev["entry_date"] <= end]
        pot = run_event_pot(evs, spy, start, end, slots=SLOTS, base_cost=0.0025)
        folds = {str(y): stats([ev for ev in evs if ev["entry_date"].year == y])
                 for y in range(start.year, end.year + 1)}
        road = {"pot": {k: v for k, v in pot.items() if k != "curve"}, "pot_curve": pot["curve"],
                "spy_final": spy_final(spy, start, end), "event_study": stats(evs),
                "folds_by_entry_year": folds, "placebo_random_ticker": placebos(evs, spy),
                "period_distribution": period_distribution(pot["curve"]),
                "n_events_in_road": len(evs),
                "n_truncated_holds": sum(1 for ev in evs if ev["truncated"])}
        out["roads"][name] = road
        print(name, json.dumps({k: road[k] for k in ("pot", "spy_final", "event_study", "n_events_in_road")}), flush=True)
    out["events"] = [{"ticker": e["ticker"], "adsh": e["adsh"], "file_date": e["file_date"],
                      "entry": str(e["entry_date"].date()), "exit": str(e["exit_date"].date()),
                      "phrases": e["phrases"], "net_excess_pct": round(net_excess(e) * 100, 3)}
                     for e in events]
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
    print("WROTE results.json", flush=True)

if __name__ == "__main__":
    main()
