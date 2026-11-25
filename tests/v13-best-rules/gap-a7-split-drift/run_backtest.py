"""V13 BEST-RULES run for gap-a7-split-drift, per BEST-RULES-SPEC.md (frozen).

Deltas vs the v12 constructed engine (everything else identical):
  1. Idle capital is parked in SPY (buy at road start; sell to fund entries;
     exit proceeds return to SPY). Every SPY leg pays 0.25%/side.
  2. Max concurrent event positions: 20 (was 5).
Slice = marked equity/5 at entry; entry = close of first trading day strictly
after the EDGAR announcement date; hold 252 trading days; costs 0.25%/side
(2% if entry price < $5); vanishing series -> zero; NO floor.
Data: v12 folder's verified census + Yahoo price cache, READ-ONLY.
Placebos: 20 seeds/road, random fence tickers, same dates, same chassis
(including SPY parking). Shifted control: real tickers, entries +126 td.
"""
import json, os, random
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/gap-a7-split-drift")
CACHE = os.path.join(V12, "cache")
MAXPOS = 20

def load_bars(t):
    safe = t.replace("/", "-")
    p = os.path.join(CACHE, f"yh_{safe}.json")
    if not os.path.exists(p): return None
    try:
        raw = json.load(open(p)); res = raw["chart"]["result"][0]
        ts = res["timestamp"]; q = res["indicators"]["quote"][0]
        adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
        dates = pd.to_datetime(pd.Series(ts), unit="s", utc=True).dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
        c = pd.Series(q["close"], dtype="float64"); a = pd.Series(adj, dtype="float64") if adj else c.copy()
        ratio = a / c
        df = pd.DataFrame({"date": dates, "close": a, "open": pd.Series(q["open"], dtype="float64") * ratio})
        df = df[(df["close"] > 0) & (df["open"] > 0)].dropna()
        return df.drop_duplicates("date").set_index("date").sort_index()
    except Exception:
        return None

BARS = {}
def bars(t):
    if t not in BARS: BARS[t] = load_bars(t)
    return BARS[t]

def cost_rate(px): return 0.02 if px < 5 else 0.0025
SPY_CR = 0.0025

def run_pot(events, start, end, hold_td=252):
    s = bars("SPY"); cal = list(s.loc[start:end].index)
    if not cal: return None
    ev_by = {}
    for e in events:
        df = bars(e["ticker"])
        if df is None: continue
        idx = df.index
        pos = idx.searchsorted(e["entry_date"])
        if pos >= len(idx): continue
        ed = idx[pos]
        if ed < cal[0] or ed > cal[-1]: continue
        xi = min(pos + hold_td, len(idx) - 1)
        ev_by.setdefault(ed, []).append({"ticker": e["ticker"], "df": df,
            "entry_price": float(df["close"].iloc[pos]), "exit_date": idx[xi], "exit_pos": xi})
    spy_df = s
    def spy_px(d):
        v = spy_df["close"].asof(d)
        return float(v) if pd.notna(v) else None
    # start fully parked in SPY (buy at first cal close, net of cost)
    costs = 0.0
    p0 = spy_px(cal[0]); costs += 100.0 * SPY_CR
    spy_sh = 100.0 * (1 - SPY_CR) / p0
    pos_list, curve, orders, taken, skipped, maxconc = [], [], 0, 0, 0, 0
    peak, maxdd = 100.0, 0.0
    for d in cal:
        sp = spy_px(d)
        # exits first: proceeds return to SPY
        still = []
        for p in pos_list:
            df = p["df"]
            if d >= p["exit_date"]:
                if df.index[-1] < p["exit_date"]:
                    val = 0.0
                else:
                    px = float(df["close"].asof(p["exit_date"]))
                    cr = cost_rate(px); val = p["shares"] * px * (1 - cr); costs += p["shares"] * px * cr
                if val > 0 and sp:
                    costs += val * SPY_CR
                    spy_sh += val * (1 - SPY_CR) / sp
                orders += 1
            else:
                still.append(p)
        pos_list = still
        if d in ev_by:
            marked = spy_sh * sp + sum(
                p["shares"] * (float(p["df"]["close"].asof(d)) if pd.notna(p["df"]["close"].asof(d)) else p["entry_price"])
                for p in pos_list)
            for e in ev_by[d]:
                if len(pos_list) >= MAXPOS: skipped += 1; continue
                amt = marked / 5.0
                avail = spy_sh * sp
                if amt <= 0 or avail <= 0: skipped += 1; continue
                amt = min(amt, avail / (1 - SPY_CR) * (1 - SPY_CR))  # cannot spend more than sleeve
                amt = min(amt, avail)
                # sell SPY gross G so that G*(1-cr) = amt
                G = amt / (1 - SPY_CR)
                if G > avail: G = avail; amt = G * (1 - SPY_CR)
                costs += G * SPY_CR; spy_sh -= G / sp
                cr = cost_rate(e["entry_price"])
                sh = amt * (1 - cr) / e["entry_price"]; costs += amt * cr; orders += 1; taken += 1
                pos_list.append({"ticker": e["ticker"], "shares": sh, "df": e["df"],
                                 "exit_date": e["exit_date"], "entry_price": e["entry_price"]})
            maxconc = max(maxconc, len(pos_list))
        eq = spy_sh * sp
        for p in pos_list:
            df = p["df"]
            if df.index[-1] < d: continue
            v = df["close"].asof(d); eq += p["shares"] * (float(v) if pd.notna(v) else p["entry_price"])
        curve.append((str(d.date()), round(eq, 4)))
        peak = max(peak, eq); maxdd = max(maxdd, (peak - eq) / peak if peak else 0)
    return {"final": round(curve[-1][1], 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "taken": taken,
            "skipped": skipped, "max_concurrent": maxconc, "curve": curve}

def spy_final(start, end):
    s = bars("SPY").loc[start:end]
    return round(100 * s["close"].iloc[-1] / s["close"].iloc[0], 2)

def monthly_stats(curve):
    pts = [(pd.Timestamp(d), v) for d, v in curve]
    months = {}
    for d, v in pts: months.setdefault((d.year, d.month), []).append(v)
    keys = sorted(months)
    rets = []
    prev = 100.0
    for k in keys:
        end_v = months[k][-1]
        rets.append(end_v / prev - 1); prev = end_v
    if not rets: return {}
    srt = sorted(rets)
    med = srt[len(srt)//2] if len(srt) % 2 else (srt[len(srt)//2-1] + srt[len(srt)//2]) / 2
    # longest losing streak (months <= 0 count as non-positive losing months for streak of negative months)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; streak = max(streak, cur)
    # longest stretch between new highs (months)
    peak = 100.0; since = 0; longest = 0
    monthly_ends = [months[k][-1] for k in keys]
    for v in monthly_ends:
        if v >= peak: peak = v; since = 0
        else: since += 1; longest = max(longest, since)
    return {"periods": len(rets), "positive": sum(1 for r in rets if r > 0),
            "share_positive_pct": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "median_pct": round(med * 100, 2), "mean_pct": round(sum(rets) / len(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_streak_mo": streak, "longest_between_highs_mo": longest}

def main():
    verified = json.load(open(os.path.join(V12, "data", "verified_events.json")))
    events_all = [e for e in verified if e.get("announced")]
    for e in events_all:
        df = bars(e["ticker"])
        if df is None: e["_entry"] = None; continue
        nxt = df.index[df.index > pd.Timestamp(e["announced"])]
        e["_entry"] = nxt[0] if len(nxt) else None
    events_all = [e for e in events_all if e["_entry"] is not None]
    print(f"verified events with entry: {len(events_all)}", flush=True)

    universe = json.load(open(os.path.join(V12, "data", "universe.json")))
    pool = [t for t in universe if bars(t) is not None and t != "SPY"]

    # event study (same method as v12): 1yr standalone excess vs SPY, net of pot costs not applied (gross price rel, as v12)
    s = bars("SPY"); rows = []
    for e in events_all:
        df = bars(e["ticker"]); idx = df.index
        pos = idx.searchsorted(e["_entry"]); xi = pos + 252
        r = {"ticker": e["ticker"], "announced": e["announced"], "ex_date": e["ex_date"], "factor": e["factor"]}
        if xi < len(idx):
            ret = float(df["close"].iloc[xi] / df["close"].iloc[pos] - 1)
            sr = float(s["close"].asof(idx[xi]) / s["close"].asof(idx[pos]) - 1)
            r["ret_1yr_pct"] = round(ret * 100, 2); r["excess_1yr_pp"] = round((ret - sr) * 100, 2)
        rows.append(r)
    ex = sorted(r["excess_1yr_pp"] for r in rows if "excess_1yr_pp" in r)
    med = ex[len(ex)//2] if len(ex) % 2 else (ex[len(ex)//2-1] + ex[len(ex)//2]) / 2
    ev_summary = {"n": len(ex), "mean_excess_pp": round(sum(ex)/len(ex), 2), "median_excess_pp": round(med, 2),
                  "beat_spy": sum(1 for x in ex if x > 0), "best_pp": ex[-1], "worst_pp": ex[0],
                  "all_excess_pp_sorted": ex}

    roads = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-01-04", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
    champions = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
    out = {"family": "gap-a7-split-drift", "program": "v13-best-rules",
           "event_study_1yr": ev_summary, "event_rows": rows, "roads": {}}
    for name, (st, en) in roads.items():
        st_t, en_t = pd.Timestamp(st), pd.Timestamp(en)
        evs = [{"ticker": e["ticker"], "entry_date": e["_entry"]} for e in events_all if st_t <= e["_entry"] <= en_t]
        res = run_pot(evs, st_t, en_t, 252)
        finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            pev = [{"ticker": rng.choice(pool), "entry_date": e["entry_date"]} for e in evs]
            pr = run_pot(pev, st_t, en_t, 252)
            finals.append(pr["final"] if pr else None)
        beaten = sum(1 for f in finals if f is not None and res and res["final"] > f)
        sev = []
        for e in evs:
            df = bars(e["ticker"]); idx = df.index
            p0 = idx.searchsorted(e["entry_date"]); p1 = min(p0 + 126, len(idx) - 1)
            sev.append({"ticker": e["ticker"], "entry_date": idx[p1]})
        sh = run_pot(sev, st_t, en_t, 252)
        road_events = [r for r in rows if "excess_1yr_pp" in r and
                       st_t <= pd.Timestamp(next(e["_entry"] for e in events_all if e["ticker"] == r["ticker"] and e["announced"] == r["announced"])) <= en_t]
        out["roads"][name] = {"window": [st, en], "n_events": len(evs), "pot": res,
                              "spy_final_gross": spy_final(st_t, en_t), "champion_vm": champions[name],
                              "placebo_finals": finals, "placebos_beaten": beaten,
                              "placebo_median": round(sorted(f for f in finals if f is not None)[10], 2) if finals else None,
                              "shifted_plus126td": sh,
                              "monthly": monthly_stats(res["curve"]) if res else {},
                              "road_event_excess_pp": sorted(r["excess_1yr_pp"] for r in road_events)}
        print(name, "events", len(evs), "final", res["final"], "dd", res["max_dd_pct"],
              "taken", res["taken"], "skipped", res["skipped"], "spy", out["roads"][name]["spy_final_gross"],
              "placebos beaten", beaten, "/20 shifted", sh["final"] if sh else None, flush=True)

    # Confirmation rule: split-half re-run for any road beating its champion
    conf = {}
    for name, (st, en) in roads.items():
        if out["roads"][name]["pot"]["final"] > champions[name]:
            st_t, en_t = pd.Timestamp(st), pd.Timestamp(en)
            mid = st_t + (en_t - st_t) / 2
            halves = {}
            for lab, (a, b) in {"first_half": (st_t, mid), "second_half": (mid, en_t)}.items():
                evs = [{"ticker": e["ticker"], "entry_date": e["_entry"]} for e in events_all if a <= e["_entry"] <= b]
                halves[lab] = {"window": [str(a.date()), str(b.date())], "n_events": len(evs),
                               "pot": run_pot(evs, a, b, 252), "spy_final_gross": spy_final(a, b)}
            conf[name] = halves
            print("CONFIRMATION", name, json.dumps(halves, default=str)[:600], flush=True)
    out["confirmation"] = conf
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
    print("saved results.json", flush=True)

if __name__ == "__main__":
    main()
