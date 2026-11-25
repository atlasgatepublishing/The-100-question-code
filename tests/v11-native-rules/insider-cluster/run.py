"""Insider-cluster NATIVE run (v11): >=3 distinct insiders, code P, 30-calendar-day filing window,
entry next open, hold 126 trading days, NO stop, NO floor. Sales clusters = identical control."""
import sys, os, json, random, re
sys.path.insert(0, os.path.dirname(__file__))
import shutil; shutil.copy("/tmp/w07/native_lib.py", os.path.join(os.path.dirname(__file__), "native_lib.py"))
from native_lib import get_bars, spy_calendar, run_event_pot, spy_final, cost_rate
import pandas as pd, numpy as np

HERE = os.path.dirname(__file__)
EV = os.path.expanduser("~/workspace/stock-app/backtests/v3/insider-data/events.csv")
spy = spy_calendar(HERE); cal = list(spy.index)
cal_pos = {d: i for i, d in enumerate(cal)}

def build_clusters(code, window_days=30, cooldown_days=30):
    ev = pd.read_csv(EV, parse_dates=["filing_date", "trans_date"])
    ev = ev[ev.code == code].sort_values(["issuer_cik", "symbol", "filing_date"])
    out = []
    for (cik, sym), g in ev.groupby(["issuer_cik", "symbol"], sort=False):
        dates = g.filing_date.values; owners = g.owner_cik.values
        from collections import Counter
        cnt = Counter(); left = 0; last_fire = None
        for i in range(len(dates)):
            cnt[owners[i]] += 1
            while (dates[i] - dates[left]) > np.timedelta64(window_days, "D"):
                cnt[owners[left]] -= 1
                if cnt[owners[left]] == 0: del cnt[owners[left]]
                left += 1
            if len(cnt) >= 3:
                fd = pd.Timestamp(dates[i])
                if last_fire is not None and (fd - last_fire).days < cooldown_days: continue
                out.append({"ticker": sym, "cik": cik, "completion": fd}); last_fire = fd
                cnt = Counter(); left = i + 1
    return out

def to_events(clusters, adv_min=2_000_000):
    events, dropped = [], {"no_bars": 0, "no_entry": 0, "low_adv": 0}
    for c in clusters:
        df = get_bars(c["ticker"], HERE)
        if df is None or len(df) == 0: dropped["no_bars"] += 1; continue
        after = [d for d in cal if d > c["completion"]]
        if not after: dropped["no_entry"] += 1; continue
        ed = after[0]
        if ed not in df.index:
            nxt = df.index[df.index >= ed]
            if len(nxt) == 0: dropped["no_entry"] += 1; continue
            ed = nxt[0]
        ei = cal_pos[ed]
        pre = df.loc[(df.index >= ed - pd.Timedelta(days=100)) & (df.index < ed)]
        if len(pre) >= 20:
            adv = (pre["close"] * pre["volume"]).tail(60).mean()
            if adv < adv_min: dropped["low_adv"] += 1; continue
        xi = min(ei + 126, len(cal) - 1); xd = cal[xi]
        xp = df["close"].asof(xd)
        if not xp or xp != xp: dropped["no_entry"] += 1; continue
        events.append({"ticker": c["ticker"], "entry_date": ed, "entry_price": float(df.loc[ed, "open"]),
                       "exit_date": xd, "exit_price": float(xp), "df": df, "completion": c["completion"],
                       "spy_entry": float(spy.loc[ed, "close"]), "spy_exit": float(spy["close"].asof(xd))})
    return events, dropped

def event_stats(events):
    ex = [(e["exit_price"] * (1 - cost_rate(e["exit_price"], 0.001)) / (e["entry_price"] * (1 + cost_rate(e["entry_price"], 0.001))) - 1) -
          (e["spy_exit"] / e["spy_entry"] - 1) for e in events]
    ex = np.array(ex)
    return {"n": len(ex), "mean_excess_pct": round(float(ex.mean()) * 100, 3) if len(ex) else None,
            "median_excess_pct": round(float(np.median(ex)) * 100, 3) if len(ex) else None,
            "pct_beat_spy": round(float((ex > 0).mean()) * 100, 1) if len(ex) else None}

def main():
    start, end = pd.Timestamp("2019-01-01"), pd.Timestamp("2026-11-20")
    cachef = os.path.join(HERE, "events_cache.json")
    if os.path.exists(cachef):
        cc = json.load(open(cachef))
        def revive(rows):
            out = []
            for r in rows:
                df = get_bars(r["ticker"], HERE)
                out.append({"ticker": r["ticker"], "entry_date": pd.Timestamp(r["entry_date"]), "entry_price": r["entry_price"],
                            "exit_date": pd.Timestamp(r["exit_date"]), "exit_price": r["exit_price"], "df": df,
                            "spy_entry": r["spy_entry"], "spy_exit": r["spy_exit"]})
            return out
        ev_p, ev_s = revive(cc["P"]), revive(cc["S"]); dr_p, dr_s = cc["dr_p"], cc["dr_s"]
        clusters_p = [0]*cc["n_clusters_p"]; clusters_s = [0]*cc["n_clusters_s"]
    else:
        clusters_p = build_clusters("P"); clusters_s = build_clusters("S")
        ev_p, dr_p = to_events(clusters_p); ev_s, dr_s = to_events(clusters_s)
        def ser(evs): return [{"ticker": e["ticker"], "entry_date": str(e["entry_date"].date()), "entry_price": e["entry_price"],
                               "exit_date": str(e["exit_date"].date()), "exit_price": e["exit_price"],
                               "spy_entry": e["spy_entry"], "spy_exit": e["spy_exit"]} for e in evs]
        json.dump({"P": ser(ev_p), "S": ser(ev_s), "dr_p": dr_p, "dr_s": dr_s,
                   "n_clusters_p": len(clusters_p), "n_clusters_s": len(clusters_s)}, open(cachef, "w"))
    pot = run_event_pot(ev_p, spy, start, end, slots=20, base_cost=0.001)
    pot_s = run_event_pot(ev_s, spy, start, end, slots=20, base_cost=0.001)
    # folds by entry year (event-study excess)
    folds = {}
    for y in range(2019, 2027):
        folds[str(y)] = event_stats([e for e in ev_p if e["entry_date"].year == y])
    # 20-seed random-ticker placebos (event-study): same dates/hold, random tradable ticker
    pool = [p[:-5] for p in os.listdir(os.path.expanduser("~/workspace/stock-app/backtests/v3/insider-data/bars")) if p.endswith(".json") and re.fullmatch(r"[A-Z]{1,5}", p[:-5])]
    rng = random.Random(20261122); beaten = 0; twin_means = []
    base_mean = event_stats(ev_p)["mean_excess_pct"]
    for seed in range(20):
        r = random.Random(1000 + seed); tex = []
        for e in ev_p:
            for _ in range(8):
                t = r.choice(pool); df = get_bars(t, HERE)
                if df is None or e["entry_date"] not in df.index: continue
                xp = df["close"].asof(e["exit_date"])
                if xp and xp == xp:
                    tex.append((xp / float(df.loc[e["entry_date"], "open"]) - 1) - (e["spy_exit"] / e["spy_entry"] - 1)); break
        m = float(np.mean(tex)) * 100 if tex else None; twin_means.append(round(m, 3) if m is not None else None)
        if m is not None and base_mean is not None and base_mean > m: beaten += 1
    out = {"family": "insider-cluster", "spec": ">=3 distinct insiders code P within 30 calendar days (filing dates); entry next open; hold 126 trading days; no stop/floor",
           "clusters_raw_P": len(clusters_p), "clusters_raw_S": len(clusters_s),
           "events_tradable_P": len(ev_p), "events_tradable_S": len(ev_s), "dropped_P": dr_p,
           "event_study_P": event_stats(ev_p), "event_study_S_control": event_stats(ev_s),
           "pot_P": {k: v for k, v in pot.items() if k != "curve"}, "pot_S_control": {k: v for k, v in pot_s.items() if k != "curve"},
           "pot_curve": pot["curve"], "spy_final_same_road": spy_final(spy, start, end),
           "folds_by_entry_year": folds, "placebo_random_ticker": {"beaten": f"{beaten}/20", "twin_mean_excess_pct": twin_means}}
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k != "pot_curve"}, indent=1, default=str))

if __name__ == "__main__": main()
