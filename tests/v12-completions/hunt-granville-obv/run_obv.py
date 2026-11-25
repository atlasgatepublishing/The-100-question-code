#!/usr/bin/env python3
"""Granville On-Balance Volume (1963) — CONSTRUCTED standalone form per
SPEC-FROZEN.md. OBV exactly as published (add full volume on up-close,
subtract on down-close). CONSTRUCTED trend ruler: OBV vs its own
50-day SMA (accumulation above / distribution below). Entry: OBV state
flips to accumulation AND price above its 200-day average. Exit: OBV
flips to distribution OR price closes below 200-day average.
Forms: (i) SPY single-asset timer; (ii) pond per-name basket, equal
weight, max N names ranked by fewest days since entry signal
(CONSTRUCTED ranking); (iii) per-coin timers on BTC/ETH (Yahoo daily
volume; wash-trading caveat printed). Program costs on stocks
(0.10%/side + $0.01/sell); crypto 0.60%/side. NATIVE no floor; HOUSE
v9 (stocks: -15% floor/sit-out/restart chassis; coins: -15% floor,
run stops, per crypto wing standard). Placebos: 20-seed circular
state shifts (SPY timer; basket on LONG/VAL). Simulation only."""
import json, os, sys, glob, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chassis import load_bars, simulate, buy_hold, period_stats, ROADS, CHAMP, SPYREF
from crypto_chassis import simulate as csim, buy_hold as cbh, period_stats as cps, sma as csma

HERE = os.path.dirname(os.path.abspath(__file__))
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")

def obv_states(bars):
    """Per-bar desired state + days-since-entry for ranking."""
    n = len(bars); obv = [0.0] * n
    for i in range(1, n):
        if bars[i]["c"] > bars[i-1]["c"]: obv[i] = obv[i-1] + bars[i].get("v", 0)
        elif bars[i]["c"] < bars[i-1]["c"]: obv[i] = obv[i-1] - bars[i].get("v", 0)
        else: obv[i] = obv[i-1]
    def sma(xs, m):
        out = [None] * n; s = 0.0
        for i, x in enumerate(xs):
            s += x
            if i >= m: s -= xs[i - m]
            if i >= m - 1: out[i] = s / m
        return out
    o50 = sma(obv, 50); p200 = sma([b["c"] for b in bars], 200)
    st = [0] * n; since = [None] * n; pos = 0; entry_i = None
    for i in range(n):
        if o50[i] is None or p200[i] is None: continue
        accum = obv[i] > o50[i]
        if pos == 0 and accum and bars[i]["c"] > p200[i]:
            pos = 1; entry_i = i
        elif pos == 1 and ((not accum) or bars[i]["c"] < p200[i]):
            pos = 0; entry_i = None
        st[i] = pos
        if pos == 1: since[i] = i - entry_i
    return st, since

def basket_run(series, maxn, start, end, form="native", shift_seed=None):
    """series: {ticker: (bars, state, since)}; calendar from SPY bars.
    Daily equal-weight target among signaled names, freshest signals
    first, capped at maxn. Explicit cash accounting; program costs on
    traded notional (0.10%/side + $0.01 per sell order)."""
    cal = series["__cal__"]
    days = [b["d"] for b in cal if start <= b["d"] <= end]
    if len(days) < 2: return None
    # per-ticker date maps
    maps = {}
    for t in series:
        if t == "__cal__": continue
        bars_t, st_t, sn_t = series[t]
        maps[t] = ({b["d"]: b["c"] for b in bars_t},
                   {bars_t[i]["d"]: st_t[i] for i in range(len(bars_t))},
                   {bars_t[i]["d"]: sn_t[i] for i in range(len(bars_t))})
    rng = random.Random(shift_seed) if shift_seed is not None else None
    shifts = {t: rng.randint(30, 300) for t in maps} if rng else {}
    date_list = {t: sorted(maps[t][0]) for t in maps}
    _didx = {t: {d: i for i, d in enumerate(date_list[t])} for t in maps}
    cash = 100.0; held = {}; lastpx = {}
    curve = []; trades = 0; costs = 0.0
    anchor = 100.0; halts = 0; sitout = 0; ended = False
    for d in days:
        for t in list(held):
            c = maps[t][0].get(d, lastpx.get(t))
            if c is not None and lastpx.get(t):
                held[t] *= c / lastpx[t]
            if c is not None: lastpx[t] = c
        eq = cash + sum(held.values())
        force_cash = False
        if form == "house":
            if ended or sitout > 0:
                force_cash = True
                if sitout > 0:
                    sitout -= 1
                    if sitout == 0 and not ended: anchor = eq
            elif held and eq <= 0.85 * anchor:
                force_cash = True; halts += 1
                if halts >= 2: ended = True
                else: sitout = 63
        if force_cash:
            target = []
        else:
            cand = []
            for t in maps:
                stmap = maps[t][1]
                if d not in stmap: continue
                if rng:
                    dl = date_list[t]; j = maps[t][0] and _didx[t].get(d, -1)
                    jj = j - shifts[t]
                    s = stmap[dl[jj]] if 0 <= jj < len(dl) else 0
                    sn = maps[t][2][dl[jj]] if 0 <= jj < len(dl) else None
                else:
                    s = stmap[d]; sn = maps[t][2][d]
                if s == 1: cand.append((sn if sn is not None else 9999, t))
            cand.sort()
            target = [t for _, t in cand[:maxn]]
        tw = eq / len(target) if target else 0.0
        # sells first
        for t in list(held):
            want = tw if t in target else 0.0
            if held[t] > want + 0.01:
                dv = held[t] - want
                c = dv * 0.001 + 0.01; costs += c; trades += 1
                cash += dv - c; held[t] = want
                if held[t] <= 0.001: del held[t]
        for t in target:
            cur_v = held.get(t, 0.0)
            if tw > cur_v + 0.01:
                dv = min(tw - cur_v, cash)
                if dv <= 0.01: continue
                c = dv * 0.001; costs += c; trades += 1
                cash -= dv; held[t] = cur_v + dv - c
                if t not in lastpx and d in maps[t][0]: lastpx[t] = maps[t][0][d]
        eq = cash + sum(held.values())
        curve.append([d, round(eq, 4)])
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, 1 - v / peak)
    return {"final": round(eq, 2), "curve": curve, "trades": trades,
            "costs": round(costs, 2), "max_dd": round(maxdd, 4)}

def main():
    out = {"family": "hunt-granville-obv", "constructed": True, "roads": {}}
    spy = load_bars(os.path.join(PXDIR, "pxfull_SPY.json"))
    sst, _ = obv_states(spy)
    for road, (s, e) in ROADS.items():
        ent = {}
        for form in ("native", "house"):
            r = simulate(spy, sst, s, e, form)
            ent["spy_timer_" + form] = {k: v for k, v in r.items() if k != "curve"}
            ent["spy_timer_" + form]["period_stats_monthly"] = period_stats(r["curve"], "M")
            if form == "native": ent["spy_timer_curve_native"] = r["curve"]
        ent["spy_buy_hold"] = buy_hold(spy, s, e)
        ent["champion_vm"] = CHAMP[road]; ent["spy_reference_program"] = SPYREF[road]
        out["roads"][road] = ent
        print("SPY timer", road, ent["spy_timer_native"]["final"], ent["spy_timer_house"]["final"])
    finals = []
    for seed in range(1, 21):
        rng = random.Random(seed); sh = rng.randint(30, 300)
        pst = sst[sh:] + sst[:sh]
        finals.append(simulate(spy, pst, *ROADS["LONG"], "native")["final"])
    sysf = out["roads"]["LONG"]["spy_timer_native"]["final"]
    out["spy_timer_placebos_LONG"] = {"finals": finals, "median": round(statistics.median(finals), 2),
                                      "system_native_final": sysf,
                                      "beats": sum(1 for f in finals if sysf > f)}
    print("SPY placebos", out["spy_timer_placebos_LONG"])
    # pond basket lives in run_basket.py (split for speed); merge if present
    bp = os.path.join(HERE, "basket_results.json")
    if os.path.exists(bp):
        bj = json.load(open(bp))
        out["basket_grid"] = bj["basket_grid"]; out["basket_placebos"] = bj["basket_placebos"]
    out["basket_grid_note"] = ("Frozen construction caps the basket at 10 names; "
                               "grid counts 15/20/30/ALL exceed the frozen cap and are NOT RUN "
                               "(named here as capped-by-spec, not gaps in the data).")
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    # crypto per-coin
    crypto = {}
    for sym in ("BTC-USD", "ETH-USD"):
        bars = load_bars(os.path.join(HERE, "data", sym + ".json"))
        stt, _ = obv_states(bars)
        days = [{"d": b["d"], "c": b["c"]} for b in bars]
        ent = {}
        for form in ("native", "house"):
            r = csim(days, stt, bars[0]["d"], "2026-11-20", form)
            ent[form] = {k: v for k, v in r.items() if k != "curve"}
            ent[form]["period_stats_monthly"] = cps(r["curve"], "M")
            if form == "native": ent["curve_native"] = r["curve"]
        ent["buy_hold_bar"] = cbh(days, bars[0]["d"], "2026-11-20")
        ent["window"] = [bars[0]["d"], "2026-11-20"]
        crypto[sym] = ent
        print(sym, "native", ent["native"]["final"], "house", ent["house"]["final"], "bar", ent["buy_hold_bar"])
    out["crypto"] = crypto
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
