#!/usr/bin/env python3
"""Donchian Weekly Rule (4-week, always-in) — frozen form (SPEC-FROZEN.md).
PUBLISHED signal: weekly evaluation; break of prior 4 full calendar weeks'
high -> long state; break of low -> short state; state persists.
Program form: CONSTRUCTED long-only adaptation (long when state long, cash
when state short; short leg NOT run — bias hurts, printed). SPY timer +
9-ETF basket (donchian-basket universe, equal weight across long-state
assets) + per-coin crypto port. Native no floor; house v9 pair.
Placebos: circular-shift state twins (20 shifts), SPY form."""
import json, os, random, statistics, sys
sys.path.insert(0, "/tmp/hs2")
from common import *
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ETFS = ["SPY","QQQ","IWM","IEFA","EEM","GLD","TLT","VNQ","DBC"]

def weekly_state(bars):
    """Returns daily state array: state[i] = position decided at close of day i.
    Weeks = ISO calendar weeks. At the last trading day of week w, compare
    week w's close vs high/low of weeks w-4..w-1 (full weeks only)."""
    weeks = {}
    for i, b in enumerate(bars):
        y, w, _ = date.fromisoformat(b["d"]).isocalendar()
        weeks.setdefault((y, w), []).append(i)
    wk = sorted(weeks)
    state = [0]*len(bars); cur = 0
    for wi, k in enumerate(wk):
        idxs = weeks[k]
        for i in idxs: state[i] = cur
        if wi >= 4:
            prev = [weeks[wk[j]] for j in range(wi-4, wi)]
            hi = max(bars[i]["h"] for g in prev for i in g)
            lo = min(bars[i]["l"] for g in prev for i in g)
            c = bars[idxs[-1]]["c"]
            if c > hi: cur = 1
            elif c < lo: cur = 0
            state[idxs[-1]] = cur
    return state

def basket_run(bars_by, start, end, floor=False):
    """Equal-weight across assets in long state; rebalance on state changes
    at closes (chassis approximation, stated). Daily equity."""
    dates = sorted({b["d"] for bl in bars_by.values() for b in bl if start <= b["d"] <= end})
    states = {t: weekly_state(bl) for t, bl in bars_by.items()}
    didx = {t: {b["d"]: i for i, b in enumerate(bl)} for t, bl in bars_by.items()}
    closes = {t: {b["d"]: b["c"] for b in bl} for t, bl in bars_by.items()}
    eq = 100.0; curve = []; held = {}; ep_start = 100.0; halts = 0; halt_until = None; dead = False; trades = 0
    prev_close = {}
    from datetime import timedelta
    for di, d in enumerate(dates):
        # accrue returns on held
        if held:
            tot = 0.0
            for t, sh in held.items():
                c = closes[t].get(d, prev_close.get(t))
                tot += sh * c; prev_close[t] = c
            eq = tot
        want = {t for t in bars_by if d in didx[t] and states[t][didx[t][d]] == 1}
        if dead or (halt_until and d < halt_until): want = set()
        if halt_until and d >= halt_until: halt_until = None; ep_start = eq
        if want != set(held):
            # sell all, buy equal weight
            cash = eq
            if held: cash *= (1 - STOCK_COST); cash -= SELL_FEE * len(held); trades += len(held)
            held = {}
            if want:
                cash *= (1 - STOCK_COST)
                for t in want:
                    c = closes[t].get(d)
                    if c: held[t] = (cash/len(want)) / c; prev_close[t] = c
            eq = cash if not held else sum(sh * prev_close[t] for t, sh in held.items())
        if floor and held and eq < 0.85 * ep_start:
            eq = eq * (1 - STOCK_COST) - SELL_FEE * len(held); trades += len(held); held = {}; halts += 1
            if halts == 1: halt_until = (date.fromisoformat(d) + timedelta(days=90)).isoformat()
            else: dead = True
        curve.append((d, round(eq, 4)))
    if held:
        eq = eq * (1 - STOCK_COST) - SELL_FEE * len(held)
        curve[-1] = (curve[-1][0], round(eq, 4))
    return {"final": round(eq, 2), "curve": curve, "trades": trades}

def main():
    res = {"family": "hunt-donchian-weekly-rule", "form": "long-only adaptation of always-in weekly rule"}
    spy, _ = load_bars("SPY"); st = weekly_state(spy)
    curves = {}
    for road, (s, e) in ROADS.items():
        nat = run_state_timer(spy, st, s, e, floor=False)
        hou = run_state_timer(spy, st, s, e, floor=True, restart=True)
        bh = buyhold(spy, s, e)
        res.setdefault("spy", {})[road] = {"native_final": nat["final"], "house_final": hou["final"],
            "buyhold_final": bh["final"], "trades": nat["trades"], "maxdd_pct": max_dd(nat["curve"]),
            "periods_weekly_native": period_stats(nat["curve"], "weekly")}
        curves[road] = {"native": nat["curve"], "house": hou["curve"]}
    res["spy_curves"] = curves
    # placebos: circular shifts of the state array
    pl = {}
    n = len(st)
    for road in ["DECADE", "VAL"]:
        s, e = ROADS[road]; finals = []
        for seed in range(1, 21):
            rng = random.Random(seed * 13 + len(road))
            sh = rng.randrange(50, n - 50)
            st2 = st[-sh:] + st[:-sh]
            finals.append(run_state_timer(spy, st2, s, e, floor=False)["final"])
        pl[road] = {"median": round(statistics.median(finals), 2),
                    "n_beaten_by_native": sum(1 for f in finals if res["spy"][road]["native_final"] > f), "finals": finals}
    res["placebos_spy"] = pl
    # ETF basket
    bars_by = {}
    for t in ETFS:
        b, _ = load_bars(t); bars_by[t] = b
    bk = {}
    for road, (s, e) in ROADS.items():
        nat = basket_run(bars_by, s, e, floor=False); hou = basket_run(bars_by, s, e, floor=True)
        bk[road] = {"native_final": nat["final"], "house_final": hou["final"], "trades": nat["trades"],
                    "maxdd_pct": max_dd(nat["curve"]), "periods_weekly_native": period_stats(nat["curve"], "weekly"),
                    "curve_native": nat["curve"]}
    res["etf_basket"] = bk
    # crypto per-coin
    coins = load_crypto(); cres = {}
    for sym, cd in coins.items():
        bars = crypto_bars(cd["rows"])
        if len(bars) < 300: continue
        cst = weekly_state(bars)
        nat = run_state_timer(bars, cst, "2017-01-01", END, cost=CRYPTO_COST, sell_fee=0.0, floor=False)
        val = run_state_timer(bars, cst, "2023-01-03", END, cost=CRYPTO_COST, sell_fee=0.0, floor=False)
        bh = buyhold(bars, "2017-01-01", END, cost=CRYPTO_COST, sell_fee=0.0)
        bhv = buyhold(bars, "2023-01-03", END, cost=CRYPTO_COST, sell_fee=0.0)
        if nat and bh: cres[sym] = {"full_native": nat["final"], "full_buyhold": bh["final"],
                                    "val_native": val["final"] if val else None, "val_buyhold": bhv["final"] if bhv else None,
                                    "trades": nat["trades"], "first": bars[0]["d"]}
    res["crypto"] = cres
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print({r: res["spy"][r] for r in ROADS}); print("basket:", {r: bk[r]["native_final"] for r in ROADS})
    print("placebos:", pl); print("crypto coins:", len(cres))

if __name__ == "__main__": main()
