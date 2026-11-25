#!/usr/bin/env python3
"""GMMA (Guppy Multiple Moving Average) — v12 Deep-Hunt RUN worker.
Implements SPEC-FROZEN.md EXACTLY. Two frozen forms:
  FORM A: long when EVERY short-group EMA (3,5,8,10,12,15) is above EVERY
          long-group EMA (30,35,40,45,50,60); exit to cash when every short
          is below every long; interleaved states hold current position.
  FORM B: GMMA + Count Back Line (Guppy's own documented combination).
          Entry: after a full-bear GMMA state ends (potential trend change),
          a close above the 3-bar CBL resistance line computed from the
          downtrend episode's highest-high anchor bar. Exit: close below the
          trailing CBL stop (3-bar count-back from the most recent highest
          high since entry; ratchets up only, never lowered).
CBL step rule (per SPEC-FROZEN (b), from Guppy's published notes): from the
anchor bar step down to its low, then move left to the next bar with a lower
low, then left again to a third bar with a lower low. Entry line = HIGH of
the third count-back bar; stop line = LOW of the third count-back bar.
(CONSTRUCTED disambiguation, logged in RESULTS.md.)
Execution: decide at close t, execute at next open. $100 pot, all-in.
Stocks: program costs 0.10%/side + $0.01 sell fee. Coins: 0.60%/side
(midpoint of the program's 0.40-0.80% crypto band).
House = v9 chassis (-15% episode floor, liquidate next open, 90 calendar
days cash, restart, second halt ends run). Native = no floor.
Dead coins: a series ending before 2026-01-01 (MATIC, delisted/migrated)
has any open terminal position written to ZERO (never carried at last
price); buy-hold likewise. Coin H/L = OC-range proxy (PIT cache holds
open/close only) — named convention, logged in RESULTS.md.
Simulation only. Shared inputs read-only."""
import json, os, math, random, statistics, time
import numpy as np
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
CBASE = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-basket-pit-data")
SHORT = [3, 5, 8, 10, 12, 15]
LONG = [30, 35, 40, 45, 50, 60]
START = 100.0
SCOST = 0.001; SFEE = 0.01
CCOST = 0.006
ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
END_ORD = date(2026, 11, 21).toordinal()
RECENT_ORD = date(2023, 1, 1).toordinal()
DEAD_CUTOFF = date(2026, 1, 1).toordinal()

# ------------------------------------------------------------------ loaders
def load_stock(sym):
    p = os.path.join(PXDIR, f"pxfull_{sym}.json")
    if not os.path.exists(p):
        return None
    j = json.load(open(p))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    d, o, h, l, c = [], [], [], [], []
    for i, t in enumerate(ts):
        if None in (q["close"][i], adj[i], q["open"][i], q["high"][i], q["low"][i]):
            continue
        ratio = adj[i] / q["close"][i]
        dt = date.fromordinal(date(1970, 1, 1).toordinal() + t // 86400)
        d.append(dt.toordinal()); o.append(q["open"][i] * ratio)
        h.append(q["high"][i] * ratio); l.append(q["low"][i] * ratio); c.append(adj[i])
    if len(c) < 100:
        return None
    return {"d": d, "o": o, "h": h, "l": l, "c": c}

CFILEMAP = {"LUNA": "y_LUNC-USD.json", "UST": "y_USTC-USD.json",
            "MATIC": "b_MATICUSDT.json", "MIOTA": "b_IOTAUSDT.json",
            "PEPE": "b_PEPEUSDT.json", "POL": "b_POLUSDT.json",
            "SUI": "b_SUIUSDT.json", "UNI": "b_UNIUSDT.json",
            "USD1": "b_USD1USDT.json", "USDe": "b_USDEUSDT.json",
            "TON": "k_TONUSD.json"}
CNO_DATA = ["BCC", "CC", "DGD", "FCT", "GAME", "GNT", "GRAM", "HYPE", "ICN",
            "M", "MAID", "STRAT", "VEN", "HC", "MIN", "PAY", "TAGZ5", "NANO", "SNGLS"]

def load_coin(sym):
    fn = CFILEMAP.get(sym, f"y_{sym}-USD.json")
    p = os.path.join(CBASE, fn)
    if not os.path.exists(p):
        return None
    raw = json.load(open(p))
    rows, seen = [], set()
    for r in raw:
        y, m, dd = map(int, r["d"].split("-"))
        ordd = date(y, m, dd).toordinal()
        op, cl = float(r["o"]), float(r["c"])
        if op > 0 and cl > 0 and ordd not in seen:
            seen.add(ordd); rows.append((ordd, op, cl))
    rows.sort()
    if len(rows) < 100:
        return None
    d = [r[0] for r in rows]; o = [r[1] for r in rows]; c = [r[2] for r in rows]
    h = [max(a, b) for a, b in zip(o, c)]   # OC-RANGE PROXY
    l = [min(a, b) for a, b in zip(o, c)]
    return {"d": d, "o": o, "h": h, "l": l, "c": c, "proxy_hl": True}

def coin_universe():
    snap = json.load(open(os.path.join(CBASE, "snapshots.json")))
    coins = set()
    for v in snap.values():
        for e in v["top20"]:
            coins.add(e["symbol"])
    return sorted(coins)

# ------------------------------------------------------------------ GMMA
def ema(arr, n):
    out = [None] * len(arr); k = 2.0 / (n + 1)
    s = None
    for i, v in enumerate(arr):
        if i == n - 1:
            s = sum(arr[:n]) / n; out[i] = s
        elif i >= n:
            s = (v - s) * k + s; out[i] = s
    return out

def groups(c):
    es = {n: ema(c, n) for n in SHORT + LONG}
    n = len(c)
    mn_s = [None] * n; mx_s = [None] * n; mn_l = [None] * n; mx_l = [None] * n
    for i in range(n):
        if es[60][i] is None:
            continue
        sv = [es[p][i] for p in SHORT]; lv = [es[p][i] for p in LONG]
        mn_s[i] = min(sv); mx_s[i] = max(sv); mn_l[i] = min(lv); mx_l[i] = max(lv)
    return mn_s, mx_s, mn_l, mx_l

def form_a_state(c):
    mn_s, mx_s, mn_l, mx_l = groups(c)
    n = len(c); st = [0] * n; pos = 0
    for i in range(n):
        if mn_s[i] is None:
            st[i] = 0; continue
        if mn_s[i] > mx_l[i]:
            pos = 1
        elif mx_s[i] < mn_l[i]:
            pos = 0
        st[i] = pos
    return st

def cbl_from_anchor(h, l, anchor):
    """3-bar count-back from anchor bar. Returns (entry_line, stop_line):
    entry = high of 3rd count-back bar, stop = low of 3rd count-back bar."""
    level = l[anchor]; bar = anchor; steps = 1; i = anchor - 1
    while i >= 0 and steps < 3:
        if l[i] < level:
            level = l[i]; bar = i; steps += 1
        i -= 1
    return h[bar], l[bar]

def form_b_state(s):
    c, h, l = s["c"], s["h"], s["l"]
    mn_s, mx_s, mn_l, mx_l = groups(c)
    n = len(c); st = [0] * n; pos = 0
    in_bear = False; bear_anchor = None; bear_hi = None
    armed = False; entry_line = None
    hi_anchor = None; stop = None
    for i in range(n):
        if mn_s[i] is None:
            st[i] = 0; continue
        full_bull = mn_s[i] > mx_l[i]
        full_bear = mx_s[i] < mn_l[i]
        if pos == 0:
            if full_bear:
                if not in_bear:
                    in_bear = True; bear_anchor = i; bear_hi = h[i]
                elif h[i] > bear_hi:
                    bear_hi = h[i]; bear_anchor = i
                armed = False; entry_line = None
            else:
                if in_bear:
                    # potential trend change: arm the CBL from the episode anchor
                    entry_line, _ = cbl_from_anchor(h, l, bear_anchor)
                    armed = True; in_bear = False
                if armed and entry_line is not None and c[i] > entry_line:
                    pos = 1; hi_anchor = i; stop = None
                    armed = False; entry_line = None
                elif full_bull and not armed:
                    pass  # no CBL confirmation, no entry (frozen rule)
        else:
            if hi_anchor is None or h[i] > h[hi_anchor]:
                hi_anchor = i
                _, sl = cbl_from_anchor(h, l, hi_anchor)
                stop = sl if stop is None else max(stop, sl)
            if stop is not None and c[i] < stop:
                pos = 0; stop = None; hi_anchor = None
        st[i] = pos
    return st

# ------------------------------------------------------------------ engine
def simulate(s, tgt, i0, i1, chassis, cost, sell_fee, dead_zero=False):
    """Bars i0..i1 inclusive. Decide close t -> execute open t+1.
    At i1 an open position is liquidated at close (unless dead_zero)."""
    d, o, c = s["d"], s["o"], s["c"]
    cash = START; shares = 0.0; costs = 0.0; orders = 0; halts = 0
    ep_start = START; episodes = 1; in_halt = False; halt_until = -1
    pending_liq = False; ended = False
    curve = []; peak = START; maxdd = 0.0
    for t in range(i0, i1 + 1):
        if in_halt and d[t] >= halt_until:
            in_halt = False; ep_start = cash
        if pending_liq:
            if shares > 0:
                v = shares * o[t]; fee = v * cost + sell_fee
                cash = v - fee; costs += fee; shares = 0.0; orders += 1
            pending_liq = False
            if not ended:
                in_halt = True
        if not in_halt and not ended and t > i0:
            desired = tgt[t - 1]
            if desired == 1 and shares == 0 and cash > 0:
                bv = cash / (1 + cost); fee = bv * cost
                shares = bv / o[t]; cash = 0.0; costs += fee; orders += 1
            elif desired == 0 and shares > 0:
                v = shares * o[t]; fee = v * cost + sell_fee
                cash = v - fee; costs += fee; shares = 0.0; orders += 1
        eq = cash + shares * c[t]
        curve.append((d[t], eq))
        if eq > peak: peak = eq
        if peak > 0: maxdd = max(maxdd, (peak - eq) / peak)
        if chassis and not in_halt and not ended and eq <= 0.85 * ep_start:
            halts += 1; pending_liq = True
            if episodes == 1:
                episodes = 2; halt_until = d[t] + 90
            else:
                ended = True
    if shares > 0:
        if dead_zero:
            cash = 0.0
        else:
            v = shares * c[i1]; fee = v * cost + sell_fee
            cash = v - fee; costs += fee; orders += 1
        shares = 0.0
        curve[-1] = (d[i1], cash)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "orders": orders, "costs": round(costs, 2), "halts": halts, "curve": curve}

def buy_hold(s, i0, i1, cost, sell_fee, dead_zero=False):
    o, c = s["o"], s["c"]
    bv = START / (1 + cost); sh = bv / o[i0]
    curve = [(s["d"][t], sh * c[t]) for t in range(i0, i1 + 1)]
    if dead_zero:
        fin = 0.0
    else:
        v = sh * c[i1]; fin = v - (v * cost + sell_fee)
    peak = START; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0.0)
    return {"final": round(fin, 2), "max_dd_pct": round(maxdd * 100, 2), "curve": curve}

def period_stats(curve, tempo):
    if tempo == "M":
        vals = []; last_key = None
        for ordv, v in curve:
            dt = date.fromordinal(ordv); key = (dt.year, dt.month)
            if key != last_key:
                vals.append(v); last_key = key
            else:
                vals[-1] = v
        series = [START] + vals
    else:
        series = [v for _, v in curve]
    if len(series) < 2:
        return None
    rets = [(series[i] / series[i - 1] - 1.0) * 100.0 if series[i - 1] > 0 else 0.0
            for i in range(1, len(series))]
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        if r < 0: streak += 1; worst = max(worst, streak)
        else: streak = 0
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak:
            peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(series) - 1 - last_high)
    return {"periods": len(rets), "pct_positive": round(100.0 * pos / len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak": worst, "longest_between_highs": longest}

def placebo_pooled(items, cost, seeds=20):
    """items: (series, state, i0, i1). Circular-shift states; open-to-open
    replay, switch costs charged. Returns pooled mean finals per seed."""
    finals = []
    rng = random.Random(20261122)
    for _ in range(seeds):
        mults = []
        for s, st, i0, i1 in items:
            o = np.array(s["o"][i0:i1 + 1], dtype=float)
            seg = np.array(st[i0 - 1:i1 - 1], dtype=float) if i0 >= 1 else np.array(st[i0:i1], dtype=float)
            if len(seg) < 2 or len(o) < 2:
                continue
            m = min(len(seg), len(o) - 1)
            seg = seg[:m]
            shift = rng.randrange(1, len(seg))
            sh = np.roll(seg, shift)
            oo = o[1:m + 1] / o[:m]
            fac = np.where(sh > 0, oo, 1.0)
            prev = np.concatenate(([0.0], sh[:-1]))
            sw = (sh != prev).astype(float)
            fac = fac * (1.0 - cost) ** sw
            mults.append(float(np.prod(fac)) * START)
        if mults:
            finals.append(round(statistics.mean(mults), 2))
    return finals

def idx_range(s, start_s, end_s):
    so = date(*map(int, start_s.split("-"))).toordinal()
    eo = date(*map(int, end_s.split("-"))).toordinal()
    idx = [i for i, dv in enumerate(s["d"]) if so <= dv <= eo]
    if len(idx) < 30 or idx[0] < 60:
        return None
    return idx[0], idx[-1]

def curve_out(curve, step=1):
    return [[date.fromordinal(dv).isoformat(), round(v, 2)] for dv, v in curve[::step]]

# ------------------------------------------------------------------ stocks
def run_stocks(symbols):
    out = {}
    placebo_items = {"A": {}, "B": {}}
    for sym in symbols:
        s = load_stock(sym)
        if s is None:
            continue
        states = {"A": form_a_state(s["c"]), "B": form_b_state(s)}
        rec = {}
        for rname, (rs, re_) in ROADS.items():
            rng_ = idx_range(s, rs, re_)
            if rng_ is None:
                continue
            i0, i1 = rng_
            bh = buy_hold(s, i0, i1, SCOST, SFEE)
            cell = {"hold_final": bh["final"], "hold_max_dd_pct": bh["max_dd_pct"]}
            for form in ("A", "B"):
                for ruleset in ("native", "house"):
                    r = simulate(s, states[form], i0, i1, ruleset == "house", SCOST, SFEE)
                    cell[f"{form}_{ruleset}"] = {
                        "final": r["final"], "max_dd_pct": r["max_dd_pct"],
                        "orders": r["orders"], "costs": r["costs"], "halts": r["halts"],
                        "beat_hold": r["final"] > bh["final"],
                        "period_stats_monthly": period_stats(r["curve"], "M")}
                    if sym == "SPY":
                        cell[f"{form}_{ruleset}"]["curve"] = curve_out(r["curve"], 5)
                if rname == "LONG":
                    placebo_items[form].setdefault(rname, []).append((s, states[form], i0, i1))
            rec[rname] = cell
        out[sym] = rec
    plac = {}
    for form in ("A", "B"):
        items = placebo_items[form].get("LONG", [])
        if items:
            plac[form] = placebo_pooled(items, SCOST)
    return out, plac

# ------------------------------------------------------------------ coins
def run_coins():
    universe = coin_universe()
    out = {}; excluded = {}
    pitems = {"A": [], "B": []}
    for sym in universe:
        if sym in CNO_DATA:
            excluded[sym] = "NO_DATA: no usable free price file in the PIT cache (named closure, crypto-x-ledger class)"
            continue
        s = load_coin(sym)
        if s is None:
            excluded[sym] = "NO_DATA: cache file missing/empty or <100 bars"
            continue
        dead = s["d"][-1] < DEAD_CUTOFF
        states = {"A": form_a_state(s["c"]), "B": form_b_state(s)}
        i1 = len(s["c"]) - 1
        rec = {"dead_zero_applied": dead, "bars": len(s["c"]),
               "start": date.fromordinal(s["d"][0]).isoformat(),
               "end": date.fromordinal(s["d"][-1]).isoformat()}
        windows = {"FULL": 60}
        for i, dv in enumerate(s["d"]):
            if dv >= RECENT_ORD:
                windows["RECENT2023"] = max(i, 60); break
        for wname, i0 in windows.items():
            if i1 - i0 < 30:
                continue
            bh = buy_hold(s, i0, i1, CCOST, 0.0, dead_zero=dead)
            cell = {"hold_final": bh["final"], "hold_max_dd_pct": bh["max_dd_pct"]}
            for form in ("A", "B"):
                for ruleset in ("native", "house"):
                    r = simulate(s, states[form], i0, i1, ruleset == "house",
                                 CCOST, 0.0, dead_zero=dead)
                    cell[f"{form}_{ruleset}"] = {
                        "final": r["final"], "max_dd_pct": r["max_dd_pct"],
                        "orders": r["orders"], "costs": r["costs"], "halts": r["halts"],
                        "beat_hold": r["final"] > bh["final"],
                        "period_stats_monthly": period_stats(r["curve"], "M")}
                    if sym == "BTC":
                        cell[f"{form}_{ruleset}"]["curve"] = curve_out(r["curve"], 7)
                if wname == "FULL":
                    pitems[form].append((s, states[form], i0, i1))
            rec[wname] = cell
        out[sym] = rec
    plac = {f: placebo_pooled(pitems[f], CCOST) for f in ("A", "B") if pitems[f]}
    return out, plac, excluded

def main():
    t0 = time.time()
    symbols = sorted(fn[len("pxfull_"):-len(".json")] for fn in os.listdir(PXDIR)
                     if fn.startswith("pxfull_"))
    print(f"pond symbols: {len(symbols)}", flush=True)
    stocks, splac = run_stocks(symbols)
    print(f"stocks done {time.time()-t0:.0f}s; placebos A med "
          f"{statistics.median(splac.get('A', [0]))} B med {statistics.median(splac.get('B', [0]))}", flush=True)
    coins, cplac, cexcl = run_coins()
    print(f"coins done {time.time()-t0:.0f}s; ran {len(coins)}, excluded {len(cexcl)}", flush=True)
    res = {"family": "GMMA (Guppy Multiple Moving Average) — hunt-gmma",
           "disposition": "HUNT-FOUND (deep-hunt-nonus)",
           "forms": {"A": "12-EMA full-group-cross (published read, mechanised)",
                     "B": "GMMA + Count Back Line (Guppy's own combination)"},
           "stock_cost": "0.10%/side + $0.01 sell fee",
           "coin_cost": "0.60%/side",
           "champions": CHAMP, "spy_references": SPYREF,
           "stocks": stocks, "stock_placebos_LONG_pooled": splac,
           "coins": coins, "coin_placebos_FULL_pooled": cplac,
           "coin_excluded": cexcl}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(res, f)
    print("wrote results.json", flush=True)
    # headline summary to stdout
    spy = stocks.get("SPY", {})
    for rname in ROADS:
        if rname in spy:
            c = spy[rname]
            print(f"SPY {rname}: hold {c['hold_final']} | " +
                  " ".join(f"{f}{r}={c[f'{f}_{r}']['final']}" for f in 'AB' for r in ('native', 'house')), flush=True)
    btc = coins.get("BTC", {})
    for w in ("FULL", "RECENT2023"):
        if w in btc:
            c = btc[w]
            print(f"BTC {w}: hold {c['hold_final']} | " +
                  " ".join(f"{f}{r}={c[f'{f}_{r}']['final']}" for f in 'AB' for r in ('native', 'house')), flush=True)

if __name__ == "__main__":
    main()
