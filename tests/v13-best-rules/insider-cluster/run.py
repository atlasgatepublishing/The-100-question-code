"""Insider-cluster BEST-RULES run (v13). Spec: BEST-RULES-SPEC.md (frozen before this run).
>=3 distinct buyers, code P, filings within 10 trading days, each buyer >=$25k, cluster >=$150k,
CMP opportunistic gate (no routine buyer), price>=$5, ADV>=$5M, entry next open, hold 63 trading days,
10 slots, same-day priority by aggregate cluster dollars, no floor/stop, costs 0.10%/side.
Sales clusters (identical density/dollar construction, no routine gate) = control diagnostic."""
import sys, os, json, random, re
V11 = os.path.expanduser("~/workspace/stock-app/backtests/v11-native-rules/insider-cluster")
sys.path.insert(0, V11)
from native_lib import _parse_yahoo, run_event_pot, spy_final, cost_rate
import pandas as pd, numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EV = os.path.expanduser("~/workspace/stock-app/backtests/v3/insider-data/events.csv")
V3BARS = os.path.expanduser("~/workspace/stock-app/backtests/v3/insider-data/bars")
CACHE = {}

def get_bars(ticker):
    if ticker in CACHE: return CACHE[ticker]
    safe = ticker.replace("/", "-")
    df = None
    for path in [os.path.join(V3BARS, f"{safe}.json"),
                 os.path.join(V11, f"yh_{safe}.json"),
                 os.path.join(HERE, f"yh_{safe}.json")]:
        if os.path.exists(path):
            try: df = _parse_yahoo(json.load(open(path)))
            except Exception: df = None
            if df is not None and len(df): break
            df = None
    # Cache-only (v3 bars + v11 fetched files, both read-only). A ticker with no cached
    # bars is dropped as no_bars — same survivorship caveat v11 carried, stated in RESULTS.
    CACHE[ticker] = df
    return df

spy = get_bars("SPY")
cal = list(spy.index)
cal_pos = {d: i for i, d in enumerate(cal)}
cal_arr = np.array(cal, dtype="datetime64[ns]")

def filing_cal_idx(ts):
    """Index in SPY calendar of first trading day on/after the filing date."""
    i = int(np.searchsorted(cal_arr, np.datetime64(ts)))
    return i if i < len(cal) else None

ev_all = pd.read_csv(EV, parse_dates=["filing_date", "trans_date"])
# CMP routine history: (owner_cik, issuer_cik) -> set of (year, month) with a code-P purchase
routine_hist = {}
for (oc, ic), g in ev_all[ev_all.code == "P"].groupby(["owner_cik", "issuer_cik"]):
    routine_hist[(int(oc), int(ic))] = set(zip(g.filing_date.dt.year, g.filing_date.dt.month))

def is_routine(owner, issuer, completion):
    s = routine_hist.get((int(owner), int(issuer)), set())
    return any(m == completion.month and y < completion.year for (y, m) in s)

def build_clusters(code, use_routine_gate):
    ev = ev_all[ev_all.code == code].copy()
    ev["ci"] = [filing_cal_idx(t) for t in ev.filing_date]
    ev = ev[ev.ci.notna()].sort_values(["issuer_cik", "symbol", "filing_date"])
    out, gated_out = [], 0
    for (cik, sym), g in ev.groupby(["issuer_cik", "symbol"], sort=False):
        rows = list(g.itertuples())
        left = 0; last_fire_ci = -10**9
        from collections import defaultdict
        val = defaultdict(float)
        for i, r in enumerate(rows):
            val[r.owner_cik] += float(r.value)
            while rows[i].ci - rows[left].ci > 10:
                val[rows[left].owner_cik] -= float(rows[left].value)
                if val[rows[left].owner_cik] <= 0: del val[rows[left].owner_cik]
                left += 1
            big = {o: v for o, v in val.items() if v >= 25_000}
            if len(big) >= 3 and sum(big.values()) >= 150_000:
                if rows[i].ci - last_fire_ci < 22:  # ~30 calendar day cooldown in trading days
                    continue
                completion = pd.Timestamp(r.filing_date)
                if use_routine_gate and any(is_routine(o, cik, completion) for o in big):
                    gated_out += 1
                    last_fire_ci = rows[i].ci; val = defaultdict(float); left = i + 1
                    continue
                out.append({"ticker": sym, "cik": int(cik), "completion": completion,
                            "agg_value": round(sum(big.values()), 2), "n_buyers": len(big)})
                last_fire_ci = rows[i].ci; val = defaultdict(float); left = i + 1
    return out, gated_out

def to_events(clusters, hold=63):
    events, dropped = [], {"no_bars": 0, "no_entry": 0, "low_adv": 0, "penny": 0, "short_hist": 0}
    for c in clusters:
        df = get_bars(c["ticker"])
        if df is None or len(df) == 0: dropped["no_bars"] += 1; continue
        after = [d for d in cal if d > c["completion"]]
        if not after: dropped["no_entry"] += 1; continue
        ed = after[0]
        if ed not in df.index:
            nxt = df.index[df.index >= ed]
            if len(nxt) == 0: dropped["no_entry"] += 1; continue
            ed = nxt[0]
        ep = float(df.loc[ed, "open"])
        if ep < 5: dropped["penny"] += 1; continue
        pre = df.loc[(df.index >= ed - pd.Timedelta(days=100)) & (df.index < ed)]
        if len(pre) < 20: dropped["short_hist"] += 1; continue
        adv = (pre["close"] * pre["volume"]).tail(60).mean()
        if adv < 5_000_000: dropped["low_adv"] += 1; continue
        ei = cal_pos[ed]; xi = min(ei + hold, len(cal) - 1); xd = cal[xi]
        xp = df["close"].asof(xd)
        if not xp or xp != xp: dropped["no_entry"] += 1; continue
        events.append({"ticker": c["ticker"], "entry_date": ed, "entry_price": ep,
                       "exit_date": xd, "exit_price": float(xp), "df": df, "completion": c["completion"],
                       "agg_value": c["agg_value"], "n_buyers": c["n_buyers"],
                       "spy_entry": float(spy.loc[ed, "close"]), "spy_exit": float(spy["close"].asof(xd))})
    # same-day priority: largest aggregate cluster first (spec)
    events.sort(key=lambda e: (e["entry_date"], -e["agg_value"]))
    return events, dropped

def event_stats(events):
    if not events: return {"n": 0, "mean_excess_pct": None, "median_excess_pct": None, "pct_beat_spy": None}
    ex = np.array([(e["exit_price"] * (1 - cost_rate(e["exit_price"], 0.001)) / (e["entry_price"] * (1 + cost_rate(e["entry_price"], 0.001))) - 1) -
                   (e["spy_exit"] / e["spy_entry"] - 1) for e in events])
    return {"n": len(ex), "mean_excess_pct": round(float(ex.mean()) * 100, 3),
            "median_excess_pct": round(float(np.median(ex)) * 100, 3),
            "pct_beat_spy": round(float((ex > 0).mean()) * 100, 1)}

def monthly_distribution(curve):
    s = pd.Series({pd.Timestamp(d): v for d, v in curve}).sort_index()
    me = s.resample("M").last()  # mechanical fix: this box's pandas predates the "ME" alias
    rets = me.pct_change().dropna()
    if not len(rets): return {}
    # longest losing streak (consecutive negative months)
    streak = mx = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0; mx = max(mx, streak)
    # longest stretch between new highs (trading days, daily curve)
    peak = -1; last_high = 0; longest = 0
    for i, v in enumerate(s.values):
        if v >= peak: peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(s) - 1 - last_high)
    return {"months": int(len(rets)), "median_month_pct": round(float(rets.median()) * 100, 2),
            "share_months_positive_pct": round(float((rets > 0).mean()) * 100, 1),
            "best_month_pct": round(float(rets.max()) * 100, 2), "worst_month_pct": round(float(rets.min()) * 100, 2),
            "mean_month_pct_secondary": round(float(rets.mean()) * 100, 2),
            "longest_losing_streak_months": int(mx),
            "longest_stretch_between_new_highs_trading_days": int(longest)}

def run_road(events, start, end):
    evs = [e for e in events if start <= e["entry_date"] <= end]
    pot = run_event_pot(evs, spy, start, end, slots=10, base_cost=0.001)
    return pot, evs

def main():
    cl_p, gated = build_clusters("P", use_routine_gate=True)
    cl_p_nogate, _ = build_clusters("P", use_routine_gate=False)
    cl_s, _ = build_clusters("S", use_routine_gate=False)
    ev_p, dr_p = to_events(cl_p)
    ev_s, dr_s = to_events(cl_s)
    roads = {}
    for name, (st, en) in {"CONT": (pd.Timestamp("2019-01-01"), pd.Timestamp("2026-11-20")),
                           "VAL": (pd.Timestamp("2023-01-01"), pd.Timestamp("2026-11-20"))}.items():
        pot, evs = run_road(ev_p, st, en)
        pot_s, _ = run_road(ev_s, st, en)
        roads[name] = {"pot": {k: v for k, v in pot.items() if k != "curve"},
                       "pot_curve": pot["curve"],
                       "monthly_distribution": monthly_distribution(pot["curve"]),
                       "event_study": event_stats(evs),
                       "sales_control_pot": {k: v for k, v in pot_s.items() if k != "curve"},
                       "spy_final": spy_final(spy, st, en)}
    folds = {str(y): event_stats([e for e in ev_p if e["entry_date"].year == y]) for y in range(2019, 2027)}
    # 20-seed random-ticker placebos (event study, same dates/hold as tradable P events)
    pool = [p[:-5] for p in os.listdir(V3BARS) if p.endswith(".json") and re.fullmatch(r"[A-Z]{1,5}", p[:-5])]
    base_mean = event_stats(ev_p)["mean_excess_pct"]
    beaten = 0; twin_means = []
    for seed in range(20):
        r = random.Random(1000 + seed); tex = []
        for e in ev_p:
            for _ in range(8):
                t = r.choice(pool); df = get_bars(t)
                if df is None or e["entry_date"] not in df.index: continue
                xp = df["close"].asof(e["exit_date"])
                if xp and xp == xp:
                    tex.append((xp / float(df.loc[e["entry_date"], "open"]) - 1) - (e["spy_exit"] / e["spy_entry"] - 1)); break
        m = float(np.mean(tex)) * 100 if tex else None; twin_means.append(round(m, 3) if m is not None else None)
        if m is not None and base_mean is not None and base_mean > m: beaten += 1
    out = {"family": "insider-cluster", "program": "v13-best-rules",
           "spec": ">=3 distinct buyers code P, filings within 10 trading days, each buyer >=$25k, cluster agg >=$150k, CMP routine gate, price>=$5, ADV60>=$5M, entry next open, hold 63 trading days, 10 slots, priority by agg $, no floor/stop, costs 0.10%/side",
           "clusters_raw_P_gated": len(cl_p), "clusters_raw_P_no_gate": len(cl_p_nogate),
           "clusters_killed_by_routine_gate": gated, "clusters_raw_S_control": len(cl_s),
           "events_tradable_P": len(ev_p), "events_tradable_S": len(ev_s),
           "dropped_P": dr_p, "dropped_S": dr_s,
           "event_study_P_all": event_stats(ev_p), "event_study_S_control_all": event_stats(ev_s),
           "roads": roads, "folds_by_entry_year": folds,
           "placebo_random_ticker": {"beaten_by_signal": f"{beaten}/20", "signal_mean_excess_pct": base_mean,
                                     "twin_mean_excess_pct": twin_means}}
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
    print(json.dumps({k: (v if k != "roads" else {rn: {kk: vv for kk, vv in rv.items() if kk != "pot_curve"} for rn, rv in v.items()}) for k, v in out.items()}, indent=1, default=str))

if __name__ == "__main__": main()
