"""Re-index-additions NATIVE run (v11): buy open day after S&P DJI announcement, sell close of effective date.
No floor, no stop. Event list parsed (read-only) from v10-retest engine EVENTS table."""
import sys, os, json, random, re, ast
sys.path.insert(0, os.path.dirname(__file__))
import shutil; shutil.copy("/tmp/w07/native_lib.py", os.path.join(os.path.dirname(__file__), "native_lib.py"))
from native_lib import get_bars, spy_calendar, run_event_pot, spy_final, cost_rate
import pandas as pd, numpy as np

HERE = os.path.dirname(__file__)
SRC = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/re-index-additions/engine.py")
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/re-index-additions/data")

def load_events():
    txt = open(SRC).read()
    m = re.search(r"EVENTS = \[(.*?)\n\]", txt, re.S)
    return ast.literal_eval("[" + m.group(1) + "]")

def px(ticker):
    p = os.path.join(PXDIR, f"px_{ticker}.json")
    if os.path.exists(p):
        import native_lib
        return native_lib._parse_yahoo(json.load(open(p)))
    return get_bars(ticker, HERE)

def main():
    spy = spy_calendar(HERE); cal = list(spy.index); cal_pos = {d: i for i, d in enumerate(cal)}
    evs_raw = load_events()
    events, dropped = [], {"no_bars": 0, "no_entry": 0}
    for ticker, ann, eff, note in evs_raw:
        df = px(ticker)
        if df is None or len(df) == 0: dropped["no_bars"] += 1; continue
        ad = pd.Timestamp(ann)
        after = df.index[df.index > ad]
        if len(after) == 0: dropped["no_entry"] += 1; continue
        ed = after[0]
        if ed not in cal_pos:
            nxt = [d for d in cal if d >= ed]
            if not nxt: dropped["no_entry"] += 1; continue
            ed = nxt[0]
        xd = pd.Timestamp(eff)
        xp = df["close"].asof(xd)
        if not xp or xp != xp: dropped["no_entry"] += 1; continue
        events.append({"ticker": ticker, "entry_date": ed, "entry_price": float(df.loc[ed, "open"]) if ed in df.index else float(df["open"].asof(ed)),
                       "exit_date": xd, "exit_price": float(xp), "df": df,
                       "spy_entry": float(spy["close"].asof(ed)), "spy_exit": float(spy["close"].asof(xd)), "ann": ann})
    start, end = pd.Timestamp("2016-11-21"), pd.Timestamp("2026-11-20")
    pot = run_event_pot(events, spy, start, end, slots=10, base_cost=0.001)
    val = [e for e in events if e["entry_date"] >= pd.Timestamp("2023-01-01")]
    pot_val = run_event_pot(val, spy, pd.Timestamp("2023-01-03"), end, slots=10, base_cost=0.001)
    def stats(evs):
        ex = np.array([(e["exit_price"] * 0.999 / (e["entry_price"] * 1.001) - 1) - (e["spy_exit"] / e["spy_entry"] - 1) for e in evs])
        raw = np.array([e["exit_price"] * 0.999 / (e["entry_price"] * 1.001) - 1 for e in evs])
        return {"n": len(ex), "mean_net_pct": round(float(raw.mean()) * 100, 3), "mean_excess_pct": round(float(ex.mean()) * 100, 3),
                "median_excess_pct": round(float(np.median(ex)) * 100, 3), "pct_beat_spy": round(float((ex > 0).mean()) * 100, 1)}
    folds = {str(y): stats([e for e in events if e["entry_date"].year == y]) for y in range(2019, 2027)}
    pool = [p[:-5] for p in os.listdir(os.path.expanduser("~/workspace/stock-app/backtests/v3/insider-data/bars")) if p.endswith(".json") and re.fullmatch(r"[A-Z]{1,5}", p[:-5])]
    base = stats(events)["mean_excess_pct"]; beaten = 0; twins = []
    for seed in range(20):
        r = random.Random(7000 + seed); tex = []
        for e in events:
            for _ in range(8):
                t = r.choice(pool); df = get_bars(t, HERE)
                if df is None or len(df)==0: continue
                ep = df["open"].asof(e["entry_date"]); xp = df["close"].asof(e["exit_date"])
                if ep and xp and ep == ep and xp == xp:
                    tex.append((xp / ep - 1) - (e["spy_exit"] / e["spy_entry"] - 1)); break
        m = round(float(np.mean(tex)) * 100, 3) if tex else None; twins.append(m)
        if m is not None and base > m: beaten += 1
    out = {"family": "re-index-additions", "events_in_census": len(evs_raw), "events_tradable": len(events), "dropped": dropped,
           "event_study": stats(events), "pot_full_road": {k: v for k, v in pot.items() if k != "curve"},
           "pot_validation_2023": {k: v for k, v in pot_val.items() if k != "curve"},
           "pot_curve": pot["curve"], "spy_decade": spy_final(spy, start, end),
           "spy_cont_2019": spy_final(spy, pd.Timestamp("2019-01-02"), end), "spy_val_2023": spy_final(spy, pd.Timestamp("2023-01-03"), end),
           "folds_by_announcement_year": folds, "placebo_random_ticker": {"beaten": f"{beaten}/20", "twin_mean_excess_pct": twins}}
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k != "pot_curve"}, indent=1))

if __name__ == "__main__": main()
