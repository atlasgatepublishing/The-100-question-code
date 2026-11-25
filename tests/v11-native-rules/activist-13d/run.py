"""Activist-13D NATIVE run (v11): market-wide initial SC 13D from EDGAR full-text search,
entry next open after filing, hold 252 trading days, no stop/floor."""
import sys, os, json, random, time
sys.path.insert(0, os.path.dirname(__file__))
import shutil; shutil.copy("/tmp/w07/native_lib.py", os.path.join(os.path.dirname(__file__), "native_lib.py"))
from native_lib import get_bars, spy_calendar, run_event_pot, spy_final, cost_rate
import pandas as pd, numpy as np, requests, re

HERE = os.path.dirname(__file__)
H = {"User-Agent": "Atlas Gate Publishing research@example.com", "Accept-Encoding": "gzip, deflate", "Host": "efts.sec.gov"}

def harvest():
    cache = os.path.join(HERE, "census.json")
    seen = json.load(open(cache)) if os.path.exists(cache) else {}
    done_years = set()
    prog = os.path.join(HERE, "harvest_progress.json")
    if os.path.exists(prog): done_years = set(json.load(open(prog)))
    for year in range(2019, 2027):
        if year in done_years: continue
        for month in range(1, 13):
            start = f"{year}-{month:02d}-01"
            end = f"{year + (month==12)}-{(month % 12) + 1:02d}-01"
            frm = 0
            while True:
                d = None
                for attempt in range(4):
                    try:
                        r = requests.get("https://efts.sec.gov/LATEST/search-index",
                                         params={"q": '"beneficial ownership"', "forms": "SC 13D", "dateRange": "custom",
                                                 "startdt": start, "enddt": end, "from": frm, "size": 100},
                                         headers=H, timeout=40)
                        dj = r.json()
                        if "hits" in dj: d = dj; break
                    except Exception:
                        pass
                    time.sleep(2 + attempt * 2)
                if d is None: break
                hits = d["hits"]["hits"]
                for h in hits:
                    s = h["_source"]
                    if s["form"] != "SC 13D": continue
                    adsh = s["adsh"]
                    if adsh in seen: continue
                    names = s.get("display_names") or []
                    subj = names[0] if names else ""
                    m = re.search(r"\(([A-Z][A-Z.\-]{0,9})\)\s+\(CIK", subj)
                    seen[adsh] = {"adsh": adsh, "file_date": s["file_date"], "subject": subj,
                                  "ticker": m.group(1) if m else None, "cik": (s.get("ciks") or [None])[0]}
                total = d["hits"]["total"]["value"]
                frm += 100
                if frm >= min(total, 10000) or not hits: break
                time.sleep(0.12)
        done_years.add(year)
        json.dump(seen, open(cache, "w")); json.dump(sorted(done_years), open(prog, "w"))
        print("harvested through", year, len(seen), flush=True)
    return seen

def main():
    spy = spy_calendar(HERE); cal = list(spy.index); cal_pos = {d: i for i, d in enumerate(cal)}
    seen = harvest()
    # first filing per subject CIK per 365 days
    rows = sorted(seen.values(), key=lambda x: x["file_date"])
    last = {}; events_raw = []
    for r in rows:
        if not r["ticker"]: continue
        fd = pd.Timestamp(r["file_date"])
        if r["cik"] in last and (fd - last[r["cik"]]).days < 365: continue
        last[r["cik"]] = fd; events_raw.append(r)
    events, dropped = [], {"no_bars": 0, "no_entry": 0}
    for r in events_raw:
        df = get_bars(r["ticker"], HERE)
        if df is None or len(df) == 0: dropped["no_bars"] += 1; continue
        fd = pd.Timestamp(r["file_date"])
        after = df.index[df.index > fd]
        if len(after) == 0: dropped["no_entry"] += 1; continue
        ed = after[0]
        if ed not in cal_pos: 
            nxt = [d for d in cal if d >= ed]
            if not nxt: dropped["no_entry"] += 1; continue
            ed = nxt[0]
        ei = cal_pos[ed]; xi = min(ei + 252, len(cal) - 1); xd = cal[xi]
        xp = df["close"].asof(xd)
        if not xp or xp != xp: dropped["no_entry"] += 1; continue
        events.append({"ticker": r["ticker"], "entry_date": ed, "entry_price": float(df["close"].asof(ed) if ed not in df.index else df.loc[ed, "open"]),
                       "exit_date": xd, "exit_price": float(xp), "df": df,
                       "spy_entry": float(spy["close"].asof(ed)), "spy_exit": float(spy["close"].asof(xd)), "file_date": r["file_date"]})
    start, end = pd.Timestamp("2019-01-01"), pd.Timestamp("2026-11-20")
    pot = run_event_pot(events, spy, start, end, slots=20, base_cost=0.0025)
    def stats(evs):
        ex = np.array([(e["exit_price"] * (1 - cost_rate(e["exit_price"], 0.0025)) / (e["entry_price"] * (1 + cost_rate(e["entry_price"], 0.0025))) - 1) - (e["spy_exit"] / e["spy_entry"] - 1) for e in evs])
        return {"n": len(ex), "mean_excess_pct": round(float(ex.mean()) * 100, 3) if len(ex) else None,
                "median_excess_pct": round(float(np.median(ex)) * 100, 3) if len(ex) else None,
                "pct_beat_spy": round(float((ex > 0).mean()) * 100, 1) if len(ex) else None}
    folds = {str(y): stats([e for e in events if e["entry_date"].year == y]) for y in range(2019, 2027)}
    pool = [p[:-5] for p in os.listdir(os.path.expanduser("~/workspace/stock-app/backtests/v3/insider-data/bars")) if p.endswith(".json") and re.fullmatch(r"[A-Z]{1,5}", p[:-5])]
    base = stats(events)["mean_excess_pct"]; beaten = 0; twins = []
    for seed in range(20):
        r = random.Random(3000 + seed); tex = []
        for e in events:
            for _ in range(8):
                t = r.choice(pool); df = get_bars(t, HERE)
                if df is None or len(df)==0: continue
                ep = df["open"].asof(e["entry_date"]); xp = df["close"].asof(e["exit_date"])
                if ep and xp and ep == ep and xp == xp:
                    tex.append((xp / ep - 1) - (e["spy_exit"] / e["spy_entry"] - 1)); break
        m = round(float(np.mean(tex)) * 100, 3) if tex else None; twins.append(m)
        if m is not None and base is not None and base > m: beaten += 1
    out = {"family": "activist-13d", "filings_harvested": len(seen), "campaigns_after_365d_dedupe_and_ticker": len(events_raw),
           "events_tradable": len(events), "dropped": dropped, "event_study": stats(events),
           "pot": {k: v for k, v in pot.items() if k != "curve"}, "pot_curve": pot["curve"],
           "spy_final_same_road": spy_final(spy, start, end), "folds_by_entry_year": folds,
           "placebo_random_ticker": {"beaten": f"{beaten}/20", "twin_mean_excess_pct": twins},
           "events": [{"ticker": e["ticker"], "file_date": e["file_date"], "entry": str(e["entry_date"].date())} for e in events]}
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k not in ("pot_curve", "events")}, indent=1))

if __name__ == "__main__": main()
