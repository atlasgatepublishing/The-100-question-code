#!/usr/bin/env python3
"""V12 Crypto Wing 1, Group A — single-asset timer shelf x every PIT coin.
Frozen forms: see CONSTRUCTION-SPEC.md. Shared v4 data read-only.
Costs 0.60%/side. $100 per coin-run. Bar convention: UTC calendar days.
"""
import json, os, math, random, statistics
from datetime import date, timedelta

BASE = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-basket-pit-data")
TREND = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-trend-data")
OUT = os.path.dirname(os.path.abspath(__file__))
COST = 0.006
END_ORD = date(2026, 11, 21).toordinal()
RECENT_ORD = date(2023, 1, 1).toordinal()

FILEMAP = {"LUNA": "y_LUNC-USD.json", "UST": "y_USTC-USD.json",
           "MATIC": "b_MATICUSDT.json", "MIOTA": "b_IOTAUSDT.json",
           "PEPE": "b_PEPEUSDT.json", "POL": "b_POLUSDT.json",
           "SUI": "b_SUIUSDT.json", "UNI": "b_UNIUSDT.json",
           "USD1": "b_USD1USDT.json", "USDe": "b_USDEUSDT.json",
           "TON": "k_TONUSD.json"}
NO_DATA = ["BCC", "CC", "DGD", "FCT", "GAME", "GNT", "GRAM", "HYPE", "ICN",
           "M", "MAID", "STRAT", "VEN",
           "HC", "MIN", "PAY", "TAGZ5", "NANO", "SNGLS"]  # last 6: cache file exists but is empty (0 rows) or a 1-row stub

def load_universe():
    snap = json.load(open(os.path.join(BASE, "snapshots.json")))
    coins = set()
    for v in snap.values():
        for e in v["top20"]:
            coins.add(e["symbol"])
    return sorted(coins)

def load_series(sym):
    fn = FILEMAP.get(sym, f"y_{sym}-USD.json")
    p = os.path.join(BASE, fn)
    if not os.path.exists(p):
        return None
    raw = json.load(open(p))
    rows = []
    for r in raw:
        y, m, d = map(int, r["d"].split("-"))
        rows.append((date(y, m, d).toordinal(), float(r["o"]), float(r["c"])))
    rows.sort()
    # drop nonpositive / duplicate dates
    out, seen = [], set()
    for o_, op, cl in rows:
        if op > 0 and cl > 0 and o_ not in seen:
            seen.add(o_); out.append((o_, op, cl))
    if len(out) < 10:
        return None
    dord = [r[0] for r in out]; o = [r[1] for r in out]; c = [r[2] for r in out]
    h = [max(a, b) for a, b in zip(o, c)]   # OC-RANGE PROXY
    l = [min(a, b) for a, b in zip(o, c)]
    return {"d": dord, "o": o, "c": c, "h": h, "l": l, "proxy_hl": True}

def load_true_ohlc(sym):
    p = os.path.join(TREND, f"{sym}-USD.csv")
    if not os.path.exists(p):
        return None
    dord, o, h, l, c = [], [], [], [], []
    with open(p) as f:
        next(f)
        for line in f:
            parts = line.strip().split(",")
            if len(parts) < 5:
                continue
            y, m, dd = map(int, parts[0].split("-"))
            dord.append(date(y, m, dd).toordinal())
            o.append(float(parts[1])); h.append(float(parts[2]))
            l.append(float(parts[3])); c.append(float(parts[4]))
    return {"d": dord, "o": o, "c": c, "h": h, "l": l, "proxy_hl": False}

# ---------------- indicators / state builders (state[t] decided at close t) ----

def sma(arr, n):
    out = [None] * len(arr); s = 0.0
    for i, v in enumerate(arr):
        s += v
        if i >= n: s -= arr[i - n]
        if i >= n - 1: out[i] = s / n
    return out

def state_golden_cross(s):
    c = s["c"]; s50 = sma(c, 50); s200 = sma(c, 200)
    return [1 if (s50[i] is not None and s200[i] is not None and s50[i] > s200[i]) else 0
            for i in range(len(c))], 199

def _mid(h, l, i, n):
    return (max(h[i - n + 1:i + 1]) + min(l[i - n + 1:i + 1])) / 2.0

def state_ichimoku(s, native):
    n = len(s["c"]); h, l, c = s["h"], s["l"], s["c"]
    ten = [None] * n; kij = [None] * n; sa = [None] * n; sb = [None] * n
    for i in range(n):
        if i >= 8: ten[i] = _mid(h, l, i, 9)
        if i >= 25: kij[i] = _mid(h, l, i, 26)
        if i >= 51: sb[i] = _mid(h, l, i, 52)
        if ten[i] is not None and kij[i] is not None: sa[i] = (ten[i] + kij[i]) / 2.0
    st = [0] * n
    for t in range(78, n):
        if sa[t - 26] is None or sb[t - 26] is None or ten[t] is None or kij[t] is None:
            continue
        cloud_hi = max(sa[t - 26], sb[t - 26])
        cond_house = c[t] > cloud_hi and ten[t] > kij[t]
        if native:
            ok = cond_house and c[t] > c[t - 26] and sa[t] is not None and sb[t] is not None and sa[t] > sb[t]
        else:
            ok = cond_house
        st[t] = 1 if ok else 0
    return st, 78

def _ha_series(s):
    n = len(s["c"]); o, h, l, c = s["o"], s["h"], s["l"], s["c"]
    hac = [(o[i] + h[i] + l[i] + c[i]) / 4.0 for i in range(n)]
    hao = [0.0] * n; hao[0] = (o[0] + c[0]) / 2.0
    for i in range(1, n):
        hao[i] = (hao[i - 1] + hac[i - 1]) / 2.0
    hah = [max(h[i], hao[i], hac[i]) for i in range(n)]
    hal = [min(l[i], hao[i], hac[i]) for i in range(n)]
    return hao, hah, hal, hac

def state_heikin_ashi(s, native):
    n = len(s["c"]); hao, hah, hal, hac = _ha_series(s)
    green = [hac[i] > hao[i] for i in range(n)]
    red = [hac[i] < hao[i] for i in range(n)]
    strong = [green[i] and hal[i] == hao[i] for i in range(n)]
    st = [0] * n; pos = 0
    for t in range(n):
        if native:
            if pos == 0 and t >= 1 and strong[t] and strong[t - 1]: pos = 1
            elif pos == 1 and not strong[t]: pos = 0
        else:
            if pos == 0 and green[t]: pos = 1
            elif pos == 1 and red[t]: pos = 0
        st[t] = pos
    return st, 2

def _dow_native_state(c):
    """Per-average bullish/bearish state (Rhea freeze: >=5% retracement confirms swing)."""
    n = len(c); state = [0] * n  # 1 bull, -1 bear, 0 unknown
    last_peak = None; last_trough = None
    mode = None; cand_hi = c[0]; cand_lo = c[0]; cur = 0
    for t in range(n):
        if mode is None:
            cand_hi = max(cand_hi, c[t]); cand_lo = min(cand_lo, c[t])
            if c[t] <= cand_hi * 0.95:
                last_peak = cand_hi; mode = "down"; cand_lo = c[t]
            elif c[t] >= cand_lo * 1.05:
                last_trough = cand_lo; mode = "up"; cand_hi = c[t]
        elif mode == "up":
            cand_hi = max(cand_hi, c[t])
            if c[t] <= cand_hi * 0.95:
                last_peak = cand_hi; mode = "down"; cand_lo = c[t]
        else:
            cand_lo = min(cand_lo, c[t])
            if c[t] >= cand_lo * 1.05:
                last_trough = cand_lo; mode = "up"; cand_hi = c[t]
        if last_peak is not None and c[t] > last_peak: cur = 1
        elif last_trough is not None and c[t] < last_trough: cur = -1
        state[t] = cur
    return state

def _dow_house_events(c):
    """Days printing a new 252-bar closing high / low."""
    n = len(c); hi_ev = [False] * n; lo_ev = [False] * n
    for t in range(252, n):
        w = c[t - 252:t]
        if c[t] > max(w): hi_ev[t] = True
        if c[t] < min(w): lo_ev[t] = True
    return hi_ev, lo_ev

def state_dow(s, other, native):
    """Combine coin + second average by date. Returns (state, warmup_idx)."""
    n = len(s["c"])
    if native:
        a = _dow_native_state(s["c"]); bmap = {}
        bs = _dow_native_state(other["c"])
        for i, d in enumerate(other["d"]): bmap[d] = bs[i]
        st = [0] * n; pos = 0; bcur = 0
        for t in range(n):
            if s["d"][t] in bmap: bcur = bmap[s["d"][t]]
            if a[t] == 1 and bcur == 1: pos = 1
            elif a[t] == -1 and bcur == -1: pos = 0
            st[t] = pos
        return st, 120
    ha, la = _dow_house_events(s["c"]); hb, lb = _dow_house_events(other["c"])
    bmap = {}
    for i, d in enumerate(other["d"]): bmap[d] = (hb[i], lb[i])
    st = [0] * n; pos = 0
    last_ahi = -99; last_alow = -99; last_bhi = -99; last_blow = -99
    for t in range(n):
        if ha[t]: last_ahi = t
        if la[t]: last_alow = t
        if s["d"][t] in bmap:
            bh, bl = bmap[s["d"][t]]
            if bh: last_bhi = t
            if bl: last_blow = t
        bull_today = ha[t] or (s["d"][t] in bmap and bmap[s["d"][t]][0])
        if (bull_today and last_ahi >= 0 and last_bhi >= 0 and
                t - last_ahi <= 20 and t - last_bhi <= 20):
            pos = 1
        elif (last_alow >= 0 and last_blow >= 0 and t - last_alow <= 20 and t - last_blow <= 20 and
              (la[t] or (s["d"][t] in bmap and bmap[s["d"][t]][1]))):
            pos = 0
        st[t] = pos
    return st, 252

def state_pivots(s):
    n = len(s["c"]); d, h, l, c = s["d"], s["h"], s["l"], s["c"]
    # monthly aggregates
    months = {}
    for i in range(n):
        dt = date.fromordinal(d[i]); key = (dt.year, dt.month)
        months.setdefault(key, []).append(i)
    keys = sorted(months)
    pivot = {}
    for j in range(1, len(keys)):
        idxs = months[keys[j - 1]]
        P = (max(h[i] for i in idxs) + min(l[i] for i in idxs) + c[idxs[-1]]) / 3.0
        pivot[keys[j]] = P
    st = [0] * n; warm = n
    for i in range(n):
        dt = date.fromordinal(d[i]); key = (dt.year, dt.month)
        if key in pivot:
            if warm == n: warm = i
            st[i] = 1 if c[i] > pivot[key] else 0
    return st, warm

def state_presidential(s, form_b):
    st = []
    for ordv in s["d"]:
        dt = date.fromordinal(ordv); long_ = 0
        for Y in (2009, 2013, 2017, 2021, 2025):
            if form_b:
                start = date(Y + 1, 10, 1).toordinal(); end = date(Y + 2, 7, 31).toordinal()
                if start <= ordv <= end: long_ = 1
            else:
                if dt.year in (Y + 2, Y + 3): long_ = 1
        st.append(long_)
    return st, 0

NEWMOON_REF = date(2000, 1, 6).toordinal(); SYNODIC = 29.530588853

def state_lunar(s, half_window, full=False):
    st = []
    for ordv in s["d"]:
        k = (ordv - NEWMOON_REF) % SYNODIC
        if full: k = (k - SYNODIC / 2.0) % SYNODIC
        dist = min(k, SYNODIC - k)
        st.append(1 if dist <= half_window else 0)
    return st, 0

def state_fibonacci(s, house):
    """ZigZag 10% on closes; enter 61.8% retracement of completed up-swing."""
    c = s["c"]; n = len(c); st = [0] * n
    # zigzag pivots (confirmed)
    pivots = []  # (idx, price, kind) kind 'H'/'L'
    mode = None; ext_i = 0; ext_p = c[0]
    for t in range(1, n):
        if mode is None:
            if c[t] >= ext_p * 1.10:
                pivots.append((ext_i, ext_p, "L")); mode = "up"; ext_i, ext_p = t, c[t]
            elif c[t] <= ext_p * 0.90:
                pivots.append((ext_i, ext_p, "H")); mode = "down"; ext_i, ext_p = t, c[t]
            else:
                if c[t] > ext_p: ext_i, ext_p = t, c[t]
        elif mode == "up":
            if c[t] > ext_p: ext_i, ext_p = t, c[t]
            elif c[t] <= ext_p * 0.90:
                pivots.append((ext_i, ext_p, "H")); mode = "down"; ext_i, ext_p = t, c[t]
        else:
            if c[t] < ext_p: ext_i, ext_p = t, c[t]
            elif c[t] >= ext_p * 1.10:
                pivots.append((ext_i, ext_p, "L")); mode = "up"; ext_i, ext_p = t, c[t]
    # walk: watch completed L->H swings
    pos = 0; watch = None; entry_t = -1
    pv = list(pivots)
    pidx = 0
    for t in range(n):
        while pidx < len(pv) and pv[pidx][0] <= t:
            kind = pv[pidx][2]
            if kind == "H" and pidx >= 1 and pv[pidx - 1][2] == "L":
                L = pv[pidx - 1][1]; H = pv[pidx][1]
                if H >= 1.20 * L and pos == 0:
                    watch = (L, H)
            pidx += 1
        if pos == 1:
            L, H = watch
            if c[t] >= H or c[t] < L or (house and t - entry_t >= 252):
                pos = 0; watch = None
        elif watch is not None:
            L, H = watch
            R = H - 0.618 * (H - L)
            if c[t] < L:
                watch = None
            elif c[t] <= R:
                pos = 1; entry_t = t
        st[t] = pos
    return st, 120

def bollinger_arrays(s):
    c = s["c"]; n = len(c); mid = sma(c, 20)
    sd = [None] * n
    for i in range(19, n):
        m = mid[i]; sd[i] = math.sqrt(sum((x - m) ** 2 for x in c[i - 19:i + 1]) / 20.0)
    up = [None if sd[i] is None else mid[i] + 2 * sd[i] for i in range(n)]
    lo = [None if sd[i] is None else mid[i] - 2 * sd[i] for i in range(n)]
    bw = [None if sd[i] is None else (up[i] - lo[i]) / mid[i] for i in range(n)]
    return mid, up, lo, bw

def state_bollinger_house(s):
    """Signal scan for house form; exit needs entry price -> tracked in scan."""
    c, o = s["c"], s["o"]; n = len(c)
    mid, up, lo, bw = bollinger_arrays(s)
    st = [0] * n; pos = 0; entry_px = None
    for t in range(144, n):
        if pos == 1:
            if c[t] < mid[t] or c[t] <= entry_px * 0.92:
                pos = 0; entry_px = None
        else:
            win = bw[t - 125:t + 1]
            squeeze = any(bw[u] is not None and bw[u] == min(win) for u in range(max(19, t - 4), t + 1))
            if squeeze and c[t] > up[t]:
                pos = 1; entry_px = o[t + 1] if t + 1 < n else c[t]
        st[t] = pos
    return st, 144

def run_bollinger_native(s, start):
    """Dedicated engine: entry/exit AT the close, as frozen in v11."""
    c = s["c"]; n = len(c)
    mid, up, lo, bw = bollinger_arrays(s)
    cash = 100.0; shares = 0.0; costs = 0.0; orders = 0; pos = 0
    curve = []; peak = 100.0; maxdd = 0.0
    for t in range(start, n):
        if t >= 144:
            if pos == 1 and c[t] <= lo[t]:
                cash = shares * c[t] * (1 - COST); costs += shares * c[t] * COST
                shares = 0.0; pos = 0; orders += 1
            elif pos == 0:
                win = bw[t - 125:t + 1]
                squeeze = any(bw[u] is not None and bw[u] == min(win) for u in range(max(19, t - 4), t + 1))
                if squeeze and c[t] > up[t]:
                    shares = cash * (1 - COST) / c[t]; costs += cash * COST
                    cash = 0.0; pos = 1; orders += 1
        eq = cash + shares * c[t]
        curve.append((s["d"][t], eq))
        peak = max(peak, eq); maxdd = max(maxdd, (peak - eq) / peak if peak > 0 else 0.0)
    return {"final": curve[-1][1] if curve else 100.0, "max_dd_pct": round(maxdd * 100, 2),
            "orders": orders, "costs": round(costs, 2), "halts": 0, "curve": curve}

# ---------------- core simulator (state series, next-open execution) ----------

def simulate(s, tgt, start, chassis):
    d, o, c = s["d"], s["o"], s["c"]; n = len(c)
    cash = 100.0; shares = 0.0; costs = 0.0; orders = 0; halts = 0
    ep_start = 100.0; episodes = 1; in_halt = False; halt_until = -1
    pending_liq = False; ended = False
    curve = []; peak = 100.0; maxdd = 0.0
    for t in range(start, n):
        if in_halt and d[t] >= halt_until:
            in_halt = False; ep_start = cash
        if pending_liq:
            if shares > 0:
                v = shares * o[t]; cash = v * (1 - COST); costs += v * COST
                shares = 0.0; orders += 1
            pending_liq = False
            if not ended: in_halt = True
        if not in_halt and not ended:
            desired = tgt[t - 1] if t - 1 >= 0 else 0
            if desired == 1 and shares == 0 and cash > 0:
                shares = cash * (1 - COST) / o[t]; costs += cash * COST; cash = 0.0; orders += 1
            elif desired == 0 and shares > 0:
                v = shares * o[t]; cash = v * (1 - COST); costs += v * COST
                shares = 0.0; orders += 1
        eq = cash + shares * c[t]
        curve.append((d[t], eq))
        if eq > peak: peak = eq
        if peak > 0 and (peak - eq) / peak > maxdd: maxdd = (peak - eq) / peak
        if chassis and not in_halt and not ended and eq <= 0.85 * ep_start:
            halts += 1; pending_liq = True
            if episodes == 1:
                episodes = 2; halt_until = d[t] + 90
            else:
                ended = True
    return {"final": round(curve[-1][1], 2) if curve else 100.0,
            "max_dd_pct": round(maxdd * 100, 2), "orders": orders,
            "costs": round(costs, 2), "halts": halts, "curve": curve}

def buy_hold(s, start):
    o, c = s["o"], s["c"]
    sh = 100.0 * (1 - COST) / o[start]
    curve = [(s["d"][t], sh * c[t]) for t in range(start, len(c))]
    peak = 100.0; maxdd = 0.0
    for _, v in curve:
        peak = max(peak, v); maxdd = max(maxdd, (peak - v) / peak if peak > 0 else 0.0)
    return {"final": round(curve[-1][1], 2), "max_dd_pct": round(maxdd * 100, 2), "curve": curve}

def gate(state, start, k):
    """Cadence gating: state re-read only every k bars from start."""
    if k == 1: return state
    out = [0] * len(state); cur = 0
    for t in range(len(state)):
        if t >= start and (t - start) % k == 0: cur = state[t]
        out[t] = cur if t >= start else 0
    return out

# ---------------- period statistics (coordinator update 2026-11-22) -----------

def period_stats(curve, tempo):
    """curve: [(ord, value)]. tempo 'D' daily periods, 'M' monthly periods."""
    if tempo == "M":
        vals = []
        last_key = None
        for ordv, v in curve:
            dt = date.fromordinal(ordv); key = (dt.year, dt.month)
            if key != last_key:
                vals.append(v); last_key = key
            else:
                vals[-1] = v
        series = [100.0] + vals
    else:
        series = [v for _, v in curve]
    if len(series) < 2:
        return None
    rets = []
    for i in range(1, len(series)):
        prev = series[i - 1]
        rets.append((series[i] / prev - 1.0) * 100.0 if prev > 0 else 0.0)
    pos = sum(1 for r in rets if r > 0)
    # longest losing streak
    streak = 0; worst_streak = 0
    for r in rets:
        if r < 0: streak += 1; worst_streak = max(worst_streak, streak)
        else: streak = 0
    # longest stretch between new highs (in periods)
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak:
            peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(series) - 1 - last_high)
    return {"periods": len(rets), "pct_positive": round(100.0 * pos / len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak": worst_streak,
            "longest_between_highs": longest}

# ---------------- pooled placebo (state forms, native cadence) ----------------

def placebo_pooled(items, seeds=20):
    """items: list of (series, state, start). Circular-shift states per coin.
    Open-to-open replay, switch costs charged. Returns list of pooled mean finals."""
    import numpy as np
    finals = []
    rng = random.Random(20261122)
    for _ in range(seeds):
        mults = []
        for s, st, start in items:
            o = np.array(s["o"], dtype=float)
            sta = np.array(st, dtype=float)
            seg = sta[start - 1:-2] if start >= 1 else sta[:-2]
            if len(seg) < 2:
                continue
            shift = rng.randrange(1, len(seg))
            sh = np.roll(seg, shift)
            oo = o[start + 1:start + 1 + len(seg)] / o[start:start + len(seg)]
            fac = np.where(sh > 0, oo, 1.0)
            prev = np.concatenate(([0.0], sh[:-1]))
            sw = (sh != prev).astype(float)
            fac = fac * (1.0 - COST) ** sw
            mults.append(float(np.prod(fac)) * 100.0)
        if mults:
            finals.append(round(statistics.mean(mults), 2))
    return finals

# ---------------- driver -------------------------------------------------------

CAD_K = {"daily": 1, "weekly": 5, "monthly": 21, "calendar": 1, "monthly-form": 1}

def recent_start(s):
    for i, dv in enumerate(s["d"]):
        if dv >= RECENT_ORD:
            return i if i >= 1 else None
    return None

def run_cell(coins_data, builder, ruleset, cadence, min_bars, tempo, btc, eth):
    """builder(series, other, ruleset) -> (state, warm)."""
    chassis = (ruleset == "house")
    full = {}; recent = {}; excluded = []; pitems = []
    for sym, s in coins_data.items():
        other = eth if sym == "BTC" else btc
        st, warm = builder(s, other, ruleset)
        start = warm
        if len(s["c"]) - start < 30 or len(s["c"]) < min_bars:
            excluded.append(sym); continue
        gst = gate(st, start, CAD_K.get(cadence, 1))
        r = simulate(s, gst, start, chassis)
        bh = buy_hold(s, start)
        rec = {"final": r["final"], "hold_final": bh["final"],
               "beat_hold": r["final"] > bh["final"],
               "max_dd_pct": r["max_dd_pct"], "hold_max_dd_pct": bh["max_dd_pct"],
               "orders": r["orders"], "costs": r["costs"], "halts": r["halts"],
               "start": date.fromordinal(s["d"][start]).isoformat(),
               "period_stats": period_stats(r["curve"], tempo)}
        if sym in ("BTC", "ETH"):
            rec["curve"] = [[date.fromordinal(dv).isoformat(), round(v, 2)]
                            for dv, v in r["curve"][::7]]
            rec["hold_curve"] = [[date.fromordinal(dv).isoformat(), round(v, 2)]
                                 for dv, v in bh["curve"][::7]]
        full[sym] = rec
        pitems.append((s, gst, start))
        rs = recent_start(s)
        if rs is not None and rs > start and len(s["c"]) - rs >= 30:
            r2 = simulate(s, gst, rs, chassis)
            bh2 = buy_hold(s, rs)
            recent[sym] = {"final": r2["final"], "hold_final": bh2["final"],
                           "beat_hold": r2["final"] > bh2["final"],
                           "max_dd_pct": r2["max_dd_pct"], "orders": r2["orders"],
                           "costs": r2["costs"], "halts": r2["halts"],
                           "period_stats": period_stats(r2["curve"], tempo)}
    return full, recent, excluded, pitems

def pooled(cell):
    if not cell: return None
    finals = [v["final"] for v in cell.values()]
    holds = [v["hold_final"] for v in cell.values()]
    return {"coins": len(cell), "mean_final": round(statistics.mean(finals), 2),
            "median_final": round(statistics.median(finals), 2),
            "mean_hold": round(statistics.mean(holds), 2),
            "median_hold": round(statistics.median(holds), 2),
            "coins_beating_hold": sum(1 for v in cell.values() if v["beat_hold"]),
            "total_costs": round(sum(v["costs"] for v in cell.values()), 2),
            "total_orders": sum(v["orders"] for v in cell.values()),
            "total_halts": sum(v["halts"] for v in cell.values())}

def make_cell(builder, ruleset, cad, min_bars, tempo, data, btc, eth, with_placebo=False):
    full, recent, excl, pitems = run_cell(data, builder, ruleset, cad, min_bars, tempo, btc, eth)
    cell = {"ruleset": ruleset, "cadence": cad,
            "FULL": {"per_coin": full, "pooled": pooled(full)},
            "RECENT_2023": {"per_coin": recent, "pooled": pooled(recent)},
            "excluded": excl}
    if with_placebo:
        pf = placebo_pooled(pitems)
        rm = cell["FULL"]["pooled"]["mean_final"] if cell["FULL"]["pooled"] else None
        cell["placebo"] = {"seed_finals_pooled_mean": pf,
                           "seeds_beaten": (sum(1 for x in pf if rm > x) if rm is not None else None),
                           "of": len(pf),
                           "design": "20-seed pooled circular shift of each coin's state series; open-to-open replay, switch costs charged"}
    return cell

def main():
    universe = load_universe()
    data = {}
    for sym in universe:
        s = load_series(sym)
        if s is not None:
            data[sym] = s
    btc, eth = data["BTC"], data["ETH"]
    results = {"meta": {
        "group": "crypto-x-timers (Wing 1, Group A — single-asset timer shelf)",
        "universe_pit_symbols": len(universe), "coins_with_series": len(data),
        "no_data_closure": NO_DATA, "cost_per_side": COST,
        "bar_convention": "UTC calendar days, v4 cache daily bars (open/close)",
        "hl_convention": "OC-RANGE PROXY H=max(O,C), L=min(O,C) except BTC/ETH true-OHLC check cells",
        "start_pot": 100.0, "data_end": "2026-11-21",
        "champions_reference": {"champion_vm_long": 1415.62, "spy_long": 822.94,
                                "bar": "each coin's own buy-and-hold on the identical window"}},
        "forms": {}, "not_applicable": [
            {"form": "Fed model (folklore-f3)", "reason": "S&P 500 earnings yield vs US 10Y Treasury gauge; no per-coin mechanical form."},
            {"form": "CAPE timing", "reason": "S&P 500 cyclically-adjusted earnings multiple; coins have no earnings series."},
            {"form": "Floor-trader pivots — NATIVE", "reason": "No published native system exists (v11 verdict UNBUILDABLE-NATIVE); house monthly form run instead."}]}
    F = results["forms"]

    F["f8_golden_cross"] = {"label": "Golden cross SMA50/200 (folklore-f8)", "cells": {
        f"{rs}_{cad}": make_cell(lambda s, o, r: state_golden_cross(s), rs, cad, 230, "D",
                                 data, btc, eth, with_placebo=(rs == "native" and cad == "daily"))
        for rs in ("native", "house") for cad in ("daily", "weekly", "monthly")}}

    F["f5_ichimoku"] = {"label": "Ichimoku (folklore-f5) — native: full 4-condition alignment; house: cloud+Tenkan/Kijun only", "cells": {
        f"{rs}_{cad}": make_cell(lambda s, o, r: state_ichimoku(s, r == "native"), rs, cad, 108, "D",
                                 data, btc, eth, with_placebo=(rs == "native" and cad == "daily"))
        for rs in ("native", "house") for cad in ("daily", "weekly", "monthly")}}

    F["f6_heikin_ashi"] = {"label": "Heikin-Ashi (folklore-f6) — native: strong-trend candles; house: first green/red", "cells": {
        f"{rs}_{cad}": make_cell(lambda s, o, r: state_heikin_ashi(s, r == "native"), rs, cad, 40, "D",
                                 data, btc, eth, with_placebo=(rs == "native" and cad == "daily"))
        for rs in ("native", "house") for cad in ("daily", "weekly", "monthly")}}

    F["f4_dow_theory"] = {"label": "Dow Theory (folklore-f4) — two-average confirmation, coin + BTC (ETH stands in for BTC)", "cells": {
        f"{rs}_{cad}": make_cell(lambda s, o, r: state_dow(s, o, r == "native"), rs, cad,
                                 282 if rs == "house" else 150, "D",
                                 data, btc, eth, with_placebo=(rs == "native" and cad == "daily"))
        for rs in ("native", "house") for cad in ("daily", "weekly", "monthly")}}

    piv = make_cell(lambda s, o, r: state_pivots(s), "house", "monthly-form", 62, "M",
                    data, btc, eth, with_placebo=True)
    F["f7_pivots_house"] = {"label": "Floor-trader pivots, monthly house form only (folklore-f7; no native system exists)",
                            "cells": {"house_monthly": piv}}

    F["f1_fibonacci"] = {"label": "Fibonacci 61.8% retracement timer (folklore-f1) — house adds 252-day time exit + chassis", "cells": {
        rs + "_daily": dict(make_cell(lambda s, o, r: state_fibonacci(s, r == "house"), rs, "daily", 150, "D",
                                      data, btc, eth),
                            placebo={"note": "n/a — event/trade form; state-shift placebo cannot represent retracement entries (CONSTRUCTION-SPEC)"})
        for rs in ("native", "house")}}

    # Bollinger house via state scan
    bh_cell = make_cell(lambda s, o, r: state_bollinger_house(s), "house", "daily", 174, "D",
                        data, btc, eth)
    bh_cell["placebo"] = {"note": "n/a — event form (CONSTRUCTION-SPEC)"}
    # Bollinger native via dedicated close-execution engine
    nfull = {}; nrecent = {}; nexcl = []
    for sym, s in data.items():
        if len(s["c"]) < 174:
            nexcl.append(sym); continue
        r = run_bollinger_native(s, 144); bh = buy_hold(s, 144)
        rec = {"final": r["final"], "hold_final": bh["final"],
               "beat_hold": r["final"] > bh["final"], "max_dd_pct": r["max_dd_pct"],
               "hold_max_dd_pct": bh["max_dd_pct"], "orders": r["orders"],
               "costs": r["costs"], "halts": 0,
               "start": date.fromordinal(s["d"][144]).isoformat(),
               "period_stats": period_stats(r["curve"], "D")}
        if sym in ("BTC", "ETH"):
            rec["curve"] = [[date.fromordinal(dv).isoformat(), round(v, 2)] for dv, v in r["curve"][::7]]
            rec["hold_curve"] = [[date.fromordinal(dv).isoformat(), round(v, 2)] for dv, v in bh["curve"][::7]]
        nfull[sym] = rec
        rs_i = recent_start(s)
        if rs_i is not None and rs_i > 144 and len(s["c"]) - rs_i >= 30:
            r2 = run_bollinger_native(s, rs_i); bh2 = buy_hold(s, rs_i)
            nrecent[sym] = {"final": r2["final"], "hold_final": bh2["final"],
                            "beat_hold": r2["final"] > bh2["final"],
                            "max_dd_pct": r2["max_dd_pct"], "orders": r2["orders"],
                            "costs": r2["costs"], "halts": 0,
                            "period_stats": period_stats(r2["curve"], "D")}
    nat_cell = {"ruleset": "native", "cadence": "daily",
                "FULL": {"per_coin": nfull, "pooled": pooled(nfull)},
                "RECENT_2023": {"per_coin": nrecent, "pooled": pooled(nrecent)},
                "excluded": nexcl,
                "placebo": {"note": "n/a — event form (CONSTRUCTION-SPEC)"}}
    F["bollinger"] = {"label": "Bollinger squeeze breakout (bollinger-squeeze) — native Method I opposite-band exit; house MA20 exit + -8% stop + chassis",
                      "cells": {"native_daily": nat_cell, "house_daily": bh_cell}}

    for form_b, key, label in ((False, "f9_presidential_A", "Presidential cycle Form A — long term years 3-4 (folklore-f9)"),
                               (True, "f9_presidential_B", "Presidential cycle Form B — sweet spot Oct midterm to Jul pre-election (folklore-f9)")):
        F[key] = {"label": label, "cells": {
            rs + "_calendar": make_cell(lambda s, o, r, fb=form_b: state_presidential(s, fb),
                                        rs, "calendar", 365, "M", data, btc, eth,
                                        with_placebo=(rs == "native"))
            for rs in ("native", "house")}}

    for hw, key, label, fullmoon in ((7, "f2_lunar_15d", "Lunar new-moon 15-day window (folklore-f2)", False),
                                     (3, "f2_lunar_7d", "Lunar new-moon 7-day window (folklore-f2)", False),
                                     (7, "f2_lunar_fullmoon_control", "Lunar FULL-moon 15-day window — the papers' own control (folklore-f2)", True)):
        rulesets = ("native",) if fullmoon else ("native", "house")
        F[key] = {"label": label, "cells": {
            rs + "_calendar": make_cell(lambda s, o, r, hw=hw, fm=fullmoon: state_lunar(s, hw, fm),
                                        rs, "calendar", 60, "M", data, btc, eth,
                                        with_placebo=(rs == "native" and not fullmoon))
            for rs in rulesets}}

    # BTC/ETH true-OHLC check cells for the H/L forms
    checks = {}
    for sym in ("BTC", "ETH"):
        ts = load_true_ohlc(sym)
        if ts is None: continue
        entry = {}
        for name, builder, chassis in (
                ("ichimoku_native", lambda s: state_ichimoku(s, True), False),
                ("ichimoku_house", lambda s: state_ichimoku(s, False), True),
                ("heikin_ashi_native", lambda s: state_heikin_ashi(s, True), False),
                ("heikin_ashi_house", lambda s: state_heikin_ashi(s, False), True),
                ("pivots_house", lambda s: state_pivots(s), True)):
            st, w = builder(ts)
            r = simulate(ts, st, w, chassis)
            bh = buy_hold(ts, w)
            entry[name] = {"final": r["final"], "hold_final": bh["final"],
                           "beat_hold": r["final"] > bh["final"],
                           "max_dd_pct": r["max_dd_pct"], "orders": r["orders"],
                           "costs": r["costs"], "halts": r["halts"],
                           "start": date.fromordinal(ts["d"][w]).isoformat()}
        checks[sym] = entry
    results["true_ohlc_check"] = checks

    with open(os.path.join(OUT, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("coins:", len(data), "| forms:", list(F.keys()))

if __name__ == "__main__":
    main()
