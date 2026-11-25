"""Spinoffs NATIVE run (v11, CMW form): ALL completed US spin-offs 2020+ (Spinoff Tracker census),
buy child at close of first regular-way day, hold 36 months, no stop/floor."""
import sys, os, json, random, re
sys.path.insert(0, os.path.dirname(__file__))
import shutil; shutil.copy("/tmp/w07/native_lib.py", os.path.join(os.path.dirname(__file__), "native_lib.py"))
from native_lib import get_bars, spy_calendar, run_event_pot, spy_final, cost_rate
import pandas as pd, numpy as np, requests

HERE = os.path.dirname(__file__)

def census():
    cache = os.path.join(HERE, "census.json")
    if os.path.exists(cache): return json.load(open(cache))
    html = requests.get("https://spinofftracker.com/completed/", headers={"User-Agent": "Mozilla/5.0"}, timeout=40).text
    html = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", html, flags=re.S)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S)
    out = []
    for r in rows[1:]:
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", c)).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, flags=re.S)]
        if len(cells) < 2: continue
        m = re.match(r"^(.*?)\s+([A-Z][A-Z.\-]{0,9})\s*$", cells[0].split("→")[-1].strip())
        if not m: continue
        try: dist = pd.Timestamp(cells[1])
        except Exception: continue
        out.append({"child": cells[0].split("→")[-1].strip(), "ticker": m.group(2), "distribution": str(dist.date())})
    json.dump(out, open(cache, "w"), indent=1)
    return out

def main():
    spy = spy_calendar(HERE); cal = list(spy.index); cal_pos = {d: i for i, d in enumerate(cal)}
    cen = census()
    events, dropped = [], {"no_bars": 0, "no_entry": 0}
    for c in cen:
        dist = pd.Timestamp(c["distribution"])
        if dist < pd.Timestamp("2020-01-01") or dist > pd.Timestamp("2026-11-20"): continue
        df = get_bars(c["ticker"], HERE)
        if df is None or len(df) == 0: dropped["no_bars"] += 1; continue
        after = df.index[df.index >= dist]
        if len(after) == 0: dropped["no_entry"] += 1; continue
        ed = after[0]
        if ed not in cal_pos:
            nxt = [d for d in cal if d >= ed]
            if not nxt: dropped["no_entry"] += 1; continue
            ed = nxt[0]
        ei = cal_pos[ed]
        def at(months):
            xi = min(ei + int(months * 21), len(cal) - 1); xd = cal[xi]
            return xd, df["close"].asof(xd), spy["close"].asof(xd)
        xd36, xp36, spy36 = at(36)
        if not xp36 or xp36 != xp36: dropped["no_entry"] += 1; continue
        xd12, xp12, spy12 = at(12)
        events.append({"ticker": c["ticker"], "entry_date": ed, "entry_price": float(df.loc[ed, "close"]) if ed in df.index else float(df["close"].asof(ed)),
                       "exit_date": xd36, "exit_price": float(xp36), "df": df, "distribution": c["distribution"],
                       "spy_entry": float(spy["close"].asof(ed)), "spy_exit": float(spy36),
                       "exit12_date": xd12, "exit12_price": float(xp12) if xp12 else None, "spy12": float(spy12) if spy12 else None,
                       "complete36": bool(ei + 756 <= len(cal) - 1)})
    start, end = pd.Timestamp("2020-01-01"), pd.Timestamp("2026-11-20")
    pot = run_event_pot(events, spy, start, end, slots=10, base_cost=0.0025)
    def stats(evs, k_exit, k_spy, complete_only=False):
        ex = []
        for e in evs:
            if complete_only and not e["complete36"]: continue
            if not e[k_exit]: continue
            ex.append((e[k_exit] * (1 - cost_rate(e[k_exit], 0.0025)) / (e["entry_price"] * (1 + cost_rate(e["entry_price"], 0.0025))) - 1) - (e[k_spy] / e["spy_entry"] - 1))
        ex = np.array(ex)
        return {"n": len(ex), "mean_excess_pct": round(float(ex.mean()) * 100, 3) if len(ex) else None,
                "median_excess_pct": round(float(np.median(ex)) * 100, 3) if len(ex) else None,
                "pct_beat_spy": round(float((ex > 0).mean()) * 100, 1) if len(ex) else None}
    folds = {str(y): stats([e for e in events if e["entry_date"].year == y], "exit12_price", "spy12") for y in range(2020, 2027)}
    pool = [p[:-5] for p in os.listdir(os.path.expanduser("~/workspace/stock-app/backtests/v3/insider-data/bars")) if p.endswith(".json") and re.fullmatch(r"[A-Z]{1,5}", p[:-5])]
    base = stats(events, "exit12_price", "spy12")["mean_excess_pct"]; beaten = 0; twins = []
    ev12 = [e for e in events if e["exit12_price"]]
    for seed in range(20):
        r = random.Random(5000 + seed); tex = []
        for e in ev12:
            for _ in range(8):
                t = r.choice(pool); df = get_bars(t, HERE)
                if df is None or len(df)==0: continue
                ep = df["close"].asof(e["entry_date"]); xp = df["close"].asof(e["exit12_date"])
                if ep and xp and ep == ep and xp == xp:
                    tex.append((xp / ep - 1) - (e["spy12"] / e["spy_entry"] - 1)); break
        m = round(float(np.mean(tex)) * 100, 3) if tex else None; twins.append(m)
        if m is not None and base is not None and base > m: beaten += 1
    out = {"family": "spinoffs", "census_rows": len(cen), "events_tradable": len(events), "dropped": dropped,
           "event_study_12mo": stats(events, "exit12_price", "spy12"),
           "event_study_36mo_all_marked": stats(events, "exit_price", "spy_exit"),
           "event_study_36mo_complete_only": stats(events, "exit_price", "spy_exit", complete_only=True),
           "pot": {k: v for k, v in pot.items() if k != "curve"}, "pot_curve": pot["curve"],
           "spy_final_same_road": spy_final(spy, start, end), "folds_by_distribution_year_12mo": folds,
           "placebo_random_ticker_12mo": {"beaten": f"{beaten}/20", "twin_mean_excess_pct": twins},
           "events": [{"ticker": e["ticker"], "distribution": e["distribution"], "entry": str(e["entry_date"].date()), "complete36": e["complete36"]} for e in events]}
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k not in ("pot_curve", "events")}, indent=1))

if __name__ == "__main__": main()
