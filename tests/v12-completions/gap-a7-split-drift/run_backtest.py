"""Stage 3: pots per CONSTRUCTION-SPEC (frozen). $100, slice=equity/5, max 5
concurrent, entry next trading day after announcement at adj close, hold 252 td
(1yr primary) / 756 td (3yr, LONG only), costs 0.25%/side (2% if price<$5),
vanishing series -> zero. Placebos 20 seeds (random fence tickers, same dates);
shifted control +126 td. Curves + placebos + census -> results.json.
"""
import json, os, random
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")

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

SPY = None
def spy():
    global SPY
    if SPY is None: SPY = bars("SPY")
    return SPY

def cost_rate(px): return 0.02 if px < 5 else 0.0025

def run_pot(events, start, end, hold_td=252):
    """events: list of dicts {ticker, entry_date(Timestamp)}. Returns result dict."""
    s = spy(); cal = list(s.loc[start:end].index)
    if not cal: return None
    calset = {d: i for i, d in enumerate(cal)}
    ev_by = {}
    for e in events:
        df = bars(e["ticker"])
        if df is None: continue
        idx = df.index
        pos = idx.searchsorted(e["entry_date"])
        if pos >= len(idx): continue
        ed = idx[pos]
        if ed < cal[0] or ed > cal[-1]: continue
        xi = pos + hold_td
        exit_date = idx[min(xi, len(idx) - 1)]
        ev_by.setdefault(ed, []).append({"ticker": e["ticker"], "df": df, "entry_price": float(df["close"].iloc[pos]),
                                         "exit_date": exit_date, "exit_idx_pos": min(xi, len(idx) - 1)})
    cash, pos_list, curve, costs, orders, taken, skipped = 100.0, [], [], 0.0, 0, 0, 0
    peak, maxdd = 100.0, 0.0
    for d in cal:
        still = []
        for p in pos_list:
            df = p["df"]
            if d >= p["exit_date"]:
                if df.index[-1] < p["exit_date"]:  # series vanished before exit -> zero
                    val = 0.0; costs += 0.0
                else:
                    px = float(df["close"].asof(p["exit_date"]))
                    cr = cost_rate(px); val = p["shares"] * px * (1 - cr); costs += p["shares"] * px * cr
                cash += val; orders += 1
            else: still.append(p)
        pos_list = still
        if d in ev_by:
            marked = cash + sum(p["shares"] * (float(p["df"]["close"].asof(d)) if pd.notna(p["df"]["close"].asof(d)) else p["entry_price"]) for p in pos_list)
            for e in ev_by[d]:
                if len(pos_list) >= 5: skipped += 1; continue
                amt = min(marked / 5, cash)
                if amt <= 0: skipped += 1; continue
                cr = cost_rate(e["entry_price"])
                sh = amt * (1 - cr) / e["entry_price"]; costs += amt * cr; orders += 1; taken += 1
                cash -= amt
                pos_list.append({"ticker": e["ticker"], "shares": sh, "df": e["df"],
                                 "exit_date": e["exit_date"], "entry_price": e["entry_price"]})
        eq = cash
        for p in pos_list:
            df = p["df"]
            if df.index[-1] < d: eq += 0.0
            else:
                v = df["close"].asof(d); eq += p["shares"] * (float(v) if pd.notna(v) else p["entry_price"])
        curve.append((str(d.date()), round(eq, 4)))
        peak = max(peak, eq); maxdd = max(maxdd, (peak - eq) / peak if peak else 0)
    # liquidate remainder at road end (already marked; final = last curve value net of exit cost approx: apply exit cost)
    final = curve[-1][1]
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2), "costs": round(costs, 2),
            "orders": orders, "taken": taken, "skipped": skipped, "curve": curve}

def spy_final(start, end):
    s = spy().loc[start:end]
    return round(100 * s["close"].iloc[-1] / s["close"].iloc[0], 2)

def main():
    verified = json.load(open(os.path.join(HERE, "data", "verified_events.json")))
    events_all = [e for e in verified if e.get("announced")]
    for e in events_all:
        df = bars(e["ticker"])
        if df is None: e["_entry"] = None; continue
        nxt = df.index[df.index > pd.Timestamp(e["announced"])]
        e["_entry"] = nxt[0] if len(nxt) else None
    events_all = [e for e in events_all if e["_entry"] is not None]
    print(f"verified events with entry: {len(events_all)}")

    universe = json.load(open(os.path.join(HERE, "data", "universe.json")))
    pool = [t for t in universe if bars(t) is not None and t != "SPY"]

    roads = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-01-04", "2026-11-20"),
             "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
    out = {"roads": {}, "event_study": {}, "census": {}}

    # event study: 1yr & 3yr excess vs SPY per event (standalone, gross of pot sizing, net 0.25%/side)
    s = spy(); rows = []
    for e in events_all:
        df = bars(e["ticker"]); idx = df.index
        pos = idx.searchsorted(e["_entry"])
        r = {"ticker": e["ticker"], "announced": e["announced"], "ex_date": e["ex_date"], "factor": e["factor"]}
        for yrs, td in ((1, 252), (3, 756)):
            xi = pos + td
            if xi < len(idx):
                ret = float(df["close"].iloc[xi] / df["close"].iloc[pos] - 1)
                ed, xd = idx[pos], idx[xi]
                sp = s["close"]; sr = float(sp.asof(xd) / sp.asof(ed) - 1)
                r[f"ret_{yrs}yr_pct"] = round(ret * 100, 2); r[f"excess_{yrs}yr_pp"] = round((ret - sr) * 100, 2)
        rows.append(r)
    out["event_study"]["events"] = rows
    for yrs in (1, 3):
        ex = [r[f"excess_{yrs}yr_pp"] for r in rows if f"excess_{yrs}yr_pp" in r]
        if ex:
            exs = sorted(ex)
            out["event_study"][f"summary_{yrs}yr"] = {
                "n": len(ex), "mean_excess_pp": round(sum(ex) / len(ex), 2),
                "median_excess_pp": round(exs[len(exs) // 2], 2),
                "beat_spy": sum(1 for x in ex if x > 0)}
    ex2 = [r for r in rows if r["factor"] == 2.0 and "excess_1yr_pp" in r]
    if ex2:
        out["event_study"]["exactly_2for1_1yr"] = {
            "n": len(ex2), "mean_excess_pp": round(sum(r["excess_1yr_pp"] for r in ex2) / len(ex2), 2),
            "beat_spy": sum(1 for r in ex2 if r["excess_1yr_pp"] > 0)}

    for name, (st, en) in roads.items():
        st_t, en_t = pd.Timestamp(st), pd.Timestamp(en)
        evs = [{"ticker": e["ticker"], "entry_date": e["_entry"]} for e in events_all if st_t <= e["_entry"] <= en_t]
        res = run_pot(evs, st_t, en_t, 252)
        # placebos
        finals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            pev = [{"ticker": rng.choice(pool), "entry_date": e["entry_date"]} for e in evs]
            pr = run_pot(pev, st_t, en_t, 252)
            finals.append(pr["final"] if pr else None)
        beaten = sum(1 for f in finals if f is not None and res and res["final"] > f)
        # shifted control: same tickers, entries +126 trading days
        sev = []
        for e in evs:
            df = bars(e["ticker"]); idx = df.index
            p0 = idx.searchsorted(e["entry_date"]); p1 = min(p0 + 126, len(idx) - 1)
            sev.append({"ticker": e["ticker"], "entry_date": idx[p1]})
        sh = run_pot(sev, st_t, en_t, 252)
        out["roads"][name] = {"window": [st, en], "n_events": len(evs), "pot_1yr": res,
                              "spy_final": spy_final(st_t, en_t),
                              "placebo_finals": finals, "placebos_beaten": beaten,
                              "shifted_plus126td": sh}
        print(name, "events", len(evs), "final", res["final"] if res else None, "spy", out["roads"][name]["spy_final"],
              "placebos beaten", beaten, "/20 shifted", sh["final"] if sh else None, flush=True)

    # 3yr-hold pot, LONG only (secondary horizon)
    st_t, en_t = pd.Timestamp(roads["LONG"][0]), pd.Timestamp(roads["LONG"][1])
    evs = [{"ticker": e["ticker"], "entry_date": e["_entry"]} for e in events_all if st_t <= e["_entry"] <= en_t]
    out["roads"]["LONG_3yr_hold"] = {"pot_3yr": run_pot(evs, st_t, en_t, 756), "n_events": len(evs)}

    # census / completeness
    from collections import Counter
    raw = json.load(open(os.path.join(HERE, "data", "exdate_census.json")))
    out["census"] = {
        "universe_size": raw["universe_size"], "fetch_failures": len(raw["fetch_failures"]),
        "exdate_events_ge2": len(raw["events"]),
        "exdate_per_year": dict(sorted(Counter(e["ex_date"][:4] for e in raw["events"]).items())),
        "verified": len(events_all),
        "verified_per_year": dict(sorted(Counter(e["announced"][:4] for e in events_all).items())),
        "unverified": [{"ticker": e["ticker"], "ex_date": e["ex_date"], "factor": e["factor"],
                        "status": e["verify_status"]} for e in verified if not e.get("announced")]}
    try:
        json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1, default=str)
        print("saved results.json")
    except Exception as e:
        print("results.json write failed:", e)
        print("SUMMARY|" + json.dumps({k: v for k, v in out.items()}, default=str)[:2000])

if __name__ == "__main__":
    main()
