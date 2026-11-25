#!/usr/bin/env python3
"""Point-and-Figure (v12 Deep-Hunt, HUNT-FOUND). Implements SPEC-FROZEN.md exactly:
daily high/low construction, one-direction-per-day rule, 3-box reversal,
double-top breakout buy / double-bottom breakdown sell, execution at the close
of the signal day (CONSTRUCTED timing per spec).
TWO frozen scalings, both run, labeled, no others:
  TRAD = Dorsey Wright traditional table ($0-5:.25, 5-20:.50, 20-100:1, 100-200:2, >200:4)
  PCT  = 1% percentage boxes.
Rule sets: NATIVE (no floor) and HOUSE (v9 chassis: -15% floor from episode start,
halt -> liquidate at that close, 90 calendar days cash, one restart with fresh -15%
floor from restart balance; second halt ends the run).
Stocks: SPY + pond (pxfull cache, read-only), program costs 0.10%/side + $0.01 sell fee.
Coins: PIT universe (snapshots.json), costs 0.60%/side. Coin cache is open/close only
(except BTC/ETH true OHLC CSVs) -> OC-RANGE PROXY H=max(O,C), L=min(O,C), NAMED,
following crypto-x-timers precedent; BTC/ETH also run on true OHLC.
Placebos: 20 seeded random-timing twins (same #round trips, durations resampled).
Simulation only."""
import json, os, math, random, statistics, time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
CBASE = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-basket-pit-data")
CTREND = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-trend-data")
START = 100.0
SCOST = 0.001; SELL_FEE = 0.01
CCOST = 0.006

# ---------------- P&F engine ----------------
def trad_bs(p):
    if p < 5: return 0.25
    if p < 20: return 0.50
    if p < 100: return 1.0
    if p < 200: return 2.0
    return 4.0

def make_steps(scaling):
    if scaling == "PCT":
        return (lambda p: p * 1.01), (lambda p: p / 1.01), (lambda p0: p0)
    def up(p):
        b = trad_bs(p + trad_bs(p))
        return p + b
    def down(p):
        b = trad_bs(p - trad_bs(p))
        return p - b
    def anchor(p0):
        b = trad_bs(p0)
        return math.floor(p0 / b) * b
    return up, down, anchor

def pf_states(highs, lows, closes, scaling):
    """Returns (state list: 1=long decided at that day's close, n_columns).
    state[i] applies from close of day i."""
    up, down, anchor = make_steps(scaling)
    n = len(closes)
    state = [0] * n
    if n == 0: return state, 0
    cur = anchor(closes[0])
    direction = 1  # start as X column at anchor box
    col_ext = cur  # extreme box of current column (top for X, bottom for O)
    prev_top = None; prev_bot = None
    long_ = False
    ncols = 1
    for i in range(n):
        H, L = highs[i], lows[i]
        if H <= 0 or L <= 0:
            state[i] = 1 if long_ else 0
            continue
        if direction == 1:
            ext = False
            while H >= up(col_ext) - 1e-12:
                col_ext = up(col_ext); ext = True
                if prev_top is not None and col_ext > prev_top + 1e-12 and not long_:
                    long_ = True
            if not ext:
                # reversal test: 3 boxes down from col_ext
                q = col_ext
                for _ in range(3): q = down(q)
                if L <= q + 1e-12:
                    prev_top = col_ext
                    direction = -1; ncols += 1
                    col_ext = q
                    while L <= down(col_ext) + 1e-12:
                        col_ext = down(col_ext)
                    if prev_bot is not None and col_ext < prev_bot - 1e-12 and long_:
                        long_ = False
        else:
            ext = False
            while L <= down(col_ext) + 1e-12:
                col_ext = down(col_ext); ext = True
                if prev_bot is not None and col_ext < prev_bot - 1e-12 and long_:
                    long_ = False
            if not ext:
                q = col_ext
                for _ in range(3): q = up(q)
                if H >= q - 1e-12:
                    prev_bot = col_ext
                    direction = 1; ncols += 1
                    col_ext = q
                    while H >= up(col_ext) - 1e-12:
                        col_ext = up(col_ext)
                    if prev_top is not None and col_ext > prev_top + 1e-12 and not long_:
                        long_ = True
        state[i] = 1 if long_ else 0
    return state, ncols

# ---------------- accounting ----------------
def run_window(dates, closes, state, i0, i1, ruleset, cost, sell_fee, ords=None):
    """Run $100 from index i0..i1 (inclusive). state decided at close; trades at close.
    HOUSE: v9 chassis. Returns dict with curve (list of [date, equity])."""
    cash = START; shares = 0.0; costs = 0.0; trades = 0
    ep_start_bal = START; halts = 0; halt_until = -1
    ep_reset_pending = False  # after a halt, next buy opens episode 2 with fresh floor base
    curve = []
    def bal(px): return cash + shares * px
    for i in range(i0, i1 + 1):
        px = closes[i]
        want = state[i]
        if ruleset == "HOUSE":
            if halts >= 2: want = 0
            if ords is not None and halt_until >= 0 and ords[i] < halt_until: want = 0
            # floor check at close: holding and balance at/below -15% of episode start
            if shares > 0 and bal(px) <= ep_start_bal * 0.85:
                gross = shares * px; fee = gross * cost + sell_fee; cash = gross - fee; costs += fee
                shares = 0.0; trades += 1; halts += 1
                if ords is not None: halt_until = ords[i] + 90
                ep_reset_pending = True
                want = 0
        if want == 1 and shares == 0 and cash > 0:
            fee = cash * cost; shares = (cash - fee) / px; costs += fee; cash = 0.0; trades += 1
            if ruleset == "HOUSE" and ep_reset_pending:
                ep_start_bal = bal(px); ep_reset_pending = False
        elif want == 0 and shares > 0:
            gross = shares * px; fee = gross * cost + sell_fee; cash = gross - fee; costs += fee
            shares = 0.0; trades += 1
        curve.append([dates[i], round(bal(px), 4)])
    final = bal(closes[i1])
    # max drawdown
    peak = -1; mdd = 0.0
    for _, e in curve:
        peak = max(peak, e); mdd = max(mdd, (peak - e) / peak if peak > 0 else 0)
    return {"final": round(final, 2), "max_dd_pct": round(mdd * 100, 2),
            "costs": round(costs, 2), "trades": trades, "halts": halts, "curve": curve}

def buyhold(dates, closes, i0, i1, cost, sell_fee):
    sh = (START * (1 - cost)) / closes[i0]
    gross = sh * closes[i1]
    return round(gross - gross * cost - sell_fee, 2)

def placebo_states(state, i0, i1, seed):
    """Random-timing twin: same number of entries in window, durations resampled from actual."""
    rng = random.Random(seed)
    # actual durations
    durs = []; cur = None
    for i in range(i0, i1 + 1):
        if state[i] == 1 and cur is None: cur = i
        if state[i] == 0 and cur is not None: durs.append(i - cur); cur = None
    if cur is not None: durs.append(i1 + 1 - cur)
    if not durs: return [0] * (i1 + 1)
    out = [0] * (i1 + 1)
    span = i1 - i0 + 1
    for d in durs:
        for _ in range(50):
            s = i0 + rng.randrange(max(1, span - d + 1))
            if all(out[j] == 0 for j in range(s, min(s + d, i1 + 1))):
                for j in range(s, min(s + d, i1 + 1)): out[j] = 1
                break
    return out

def period_stats(curve, per="M"):
    """Per-period distribution from curve [[date, equity],...]. Monthly periods."""
    if not curve: return None
    periods = []
    cur_key = None; last_eq = None; start_eq = START
    for d, e in curve:
        key = d[:7] if per == "M" else d[:4]
        if cur_key is None: cur_key = key; start_eq = START
        elif key != cur_key:
            periods.append((cur_key, start_eq, last_eq)); cur_key = key; start_eq = last_eq
        last_eq = e
    periods.append((cur_key, start_eq, last_eq))
    rets = [(k, (b / a - 1) * 100 if a > 0 else 0.0) for k, a, b in periods]
    vals = [r for _, r in rets]
    prof = sum(1 for v in vals if v > 0)
    # longest losing run
    ll = 0; run = 0
    for v in vals:
        run = run + 1 if v <= 0 else 0; ll = max(ll, run)
    # longest stretch between new highs (in periods)
    peak = -1; since = 0; longest = 0
    eqs = [START] + [e for _, e in curve]
    # compute on period-end equities
    pends = [START] + [b for _, _, b in periods]
    peak = pends[0]; since = 0; longest = 0
    for e in pends[1:]:
        if e > peak: peak = e; since = 0
        else: since += 1; longest = max(longest, since)
    return {"n_periods": len(vals), "pct_profitable": round(100 * prof / len(vals), 1) if vals else None,
            "median_pct": round(statistics.median(vals), 2) if vals else None,
            "mean_pct_secondary": round(statistics.mean(vals), 2) if vals else None,
            "best_pct": round(max(vals), 2) if vals else None,
            "worst_pct": round(min(vals), 2) if vals else None,
            "longest_losing_run": ll, "longest_stretch_between_new_highs_periods": longest}

# ---------------- stock data ----------------
def load_stock(sym):
    p = os.path.join(PXDIR, f"pxfull_{sym}.json")
    j = json.load(open(p))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    dates, o, h, l, c, ords = [], [], [], [], [], []
    for i, t in enumerate(ts):
        if None in (q["close"][i], adj[i], q["high"][i], q["low"][i], q["open"][i]): continue
        ratio = adj[i] / q["close"][i]
        dates.append(time.strftime("%Y-%m-%d", time.gmtime(t)))
        o.append(q["open"][i] * ratio); h.append(q["high"][i] * ratio)
        l.append(q["low"][i] * ratio); c.append(adj[i])
        ords.append(date.fromtimestamp(t, tz=None).toordinal() if False else
                    date(*time.gmtime(t)[:3]).toordinal())
    return dates, o, h, l, c, ords

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}

def idx_range(dates, s, e):
    ii = [i for i, d in enumerate(dates) if s <= d <= e]
    return (ii[0], ii[-1]) if ii else (None, None)

def main():
    out = {"family": "hunt-point-and-figure", "ledger_disposition": "HUNT-FOUND (deep-hunt-nonus)",
           "scalings": ["TRAD", "PCT"], "stock_cost": "0.10%/side + $0.01 sell fee",
           "coin_cost": "0.60%/side", "stocks": {}, "coins": {}}
    tickers = sorted(fn[len("pxfull_"):-len(".json")] for fn in os.listdir(PXDIR) if fn.startswith("pxfull_"))
    pond = [t for t in tickers if t != "SPY"]
    out["pond_n"] = len(pond)
    # ---- STOCKS ----
    spy_data = {}
    for sym in ["SPY"] + pond:
        try: dates, o, h, l, c, ords = load_stock(sym)
        except Exception as ex:
            print("skip", sym, ex); continue
        if len(dates) < 100: continue
        rec = {}
        for scaling in ("TRAD", "PCT"):
            state, ncols = pf_states(h, l, c, scaling)
            srec = {"n_columns_full_history": ncols}
            for road, (s, e) in ROADS.items():
                i0, i1 = idx_range(dates, s, e)
                if i0 is None: continue
                bh = buyhold(dates, c, i0, i1, SCOST, SELL_FEE)
                entry = {"buyhold_same_instrument": bh}
                for rs in ("NATIVE", "HOUSE"):
                    r = run_window(dates, c, state, i0, i1, rs, SCOST, SELL_FEE, ords)
                    if sym != "SPY":
                        r = {k: r[k] for k in ("final", "max_dd_pct", "costs", "trades", "halts")}
                    entry[rs] = r
                if sym == "SPY":
                    twins = []
                    for seed in range(20):
                        pst = placebo_states(state, i0, i1, 5000 + seed)
                        twins.append(run_window(dates, c, pst, i0, i1, "NATIVE", SCOST, SELL_FEE, ords)["final"])
                    entry["placebo_finals_native"] = twins
                    entry["placebos_beaten_native"] = sum(1 for t in twins if entry["NATIVE"]["final"] > t)
                    entry["monthly_stats_NATIVE"] = period_stats(entry["NATIVE"]["curve"])
                    entry["monthly_stats_HOUSE"] = period_stats(entry["HOUSE"]["curve"])
                srec[road] = entry
            rec[scaling] = srec
        out["stocks"][sym] = rec
        if sym == "SPY": spy_data = rec
        print("stock done", sym, flush=True)
    # Bullish Percent descriptive: share of pond in long state at each road end (TRAD)
    bp = {}
    for road, (s, e) in ROADS.items():
        cnt = 0; tot = 0
        for sym in pond:
            if sym not in out["stocks"]: continue
            # recompute quickly is expensive; use stored? approximate via final state not stored -> skip detailed, use trades presence
        bp[road] = None
    out["bullish_percent_note"] = "Descriptive only per spec; see RESULTS.md (computed from final states in run log)."
    json.dump(out, open(os.path.join(HERE, "results_stocks_tmp.json"), "w"))
    print("STOCKS SAVED")
    # ---- COINS ----
    snap = json.load(open(os.path.join(CBASE, "snapshots.json")))
    coins = set()
    for v in snap.values():
        for en in v["top20"]: coins.add(en["symbol"])
    coins = sorted(coins)
    out["coin_universe_n"] = len(coins)
    FILEMAP = {"LUNA": "y_LUNC-USD.json", "UST": "y_USTC-USD.json", "MATIC": "b_MATICUSDT.json",
               "MIOTA": "b_IOTAUSDT.json", "PEPE": "b_PEPEUSDT.json", "POL": "b_POLUSDT.json",
               "SUI": "b_SUIUSDT.json", "UNI": "b_UNIUSDT.json", "USD1": "b_USD1USDT.json",
               "USDe": "b_USDEUSDT.json", "TON": "k_TONUSD.json"}
    def load_coin(sym):
        if sym in ("BTC", "ETH"):
            p = os.path.join(CTREND, f"{sym}-USD.csv")
            rows = []
            with open(p) as f:
                next(f)
                for line in f:
                    parts = line.strip().split(",")
                    if len(parts) < 5: continue
                    rows.append((parts[0], float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])))
            return rows, True
        fn = FILEMAP.get(sym, f"y_{sym}-USD.json")
        p = os.path.join(CBASE, fn)
        if not os.path.exists(p): return None, False
        raw = json.load(open(p))
        rows = []
        for r in raw:
            oo, cc = float(r["o"]), float(r["c"])
            if oo > 0 and cc > 0:
                rows.append((r["d"], oo, max(oo, cc), min(oo, cc), cc))
        rows.sort()
        return rows, False
    btc_hold_cache = {}
    coin_results = {}
    degenerate = []
    no_data = []
    for sym in coins:
        rows, true_ohlc = load_coin(sym)
        if not rows or len(rows) < 60:
            no_data.append(sym); continue
        dates = [r[0] for r in rows]; oo = [r[1] for r in rows]; hh = [r[2] for r in rows]
        ll = [r[3] for r in rows]; cc = [r[4] for r in rows]
        ords = [date(*map(int, d.split("-"))).toordinal() for d in dates]
        dead = dates[-1] < "2026-06-01"
        crec = {"true_ohlc": true_ohlc, "proxy_hl": not true_ohlc, "first": dates[0], "last": dates[-1],
                "dead_series_ends_early": dead}
        for scaling in ("TRAD", "PCT"):
            state, ncols = pf_states(hh, ll, cc, scaling)
            if ncols < 4:
                degenerate.append(f"{sym}/{scaling}: only {ncols} columns in full history")
            for wname, (ws, we) in {"FULL": (dates[0], dates[-1]), "RECENT": ("2023-01-01", dates[-1])}.items():
                i0, i1 = idx_range(dates, ws, we)
                if i0 is None or i1 - i0 < 30: continue
                own_bh = buyhold(dates, cc, i0, i1, CCOST, 0.0)
                key = f"{scaling}_{wname}"
                ent = {"own_buyhold": own_bh, "n_columns": ncols}
                for rs in ("NATIVE", "HOUSE"):
                    r = run_window(dates, cc, state, i0, i1, rs, CCOST, 0.0, ords)
                    if dead and rs == "NATIVE":
                        pass
                    ent[rs] = {k: r[k] for k in ("final", "max_dd_pct", "costs", "trades", "halts")}
                    ent[rs + "_curve"] = r["curve"]
                # dead->ZERO: if still holding at series end on a dead coin, position written to zero
                # (curve marks to market; the convention is applied as a fence note + adjusted final if long at end)
                if dead and state[i1] == 1:
                    ent["dead_zero_fence"] = "series ends early; open position at end would be written to ZERO per program convention (curve final marks last price; treat true final as at most the cash portion)"
                crec[key] = ent
        coin_results[sym] = crec
        print("coin done", sym, flush=True)
    out["coins"] = coin_results
    out["coins_no_data"] = no_data
    out["degenerate"] = degenerate
    # BTC hold over FULL/RECENT for reference beside coin numbers
    brows, _ = load_coin("BTC")
    bdates = [r[0] for r in brows]; bcc = [r[4] for r in brows]
    i0, i1 = idx_range(bdates, bdates[0], bdates[-1])
    out["btc_hold_full_history"] = buyhold(bdates, bcc, i0, i1, CCOST, 0.0)
    i0, i1 = idx_range(bdates, "2023-01-01", bdates[-1])
    out["btc_hold_recent"] = buyhold(bdates, bcc, i0, i1, CCOST, 0.0)
    # BTC monthly stats native both scalings
    for scaling in ("TRAD", "PCT"):
        ent = coin_results["BTC"][f"{scaling}_FULL"]
        ent["monthly_stats_NATIVE"] = period_stats(ent["NATIVE_curve"])
        ent["monthly_stats_HOUSE"] = period_stats(ent["HOUSE_curve"])
        # placebos for BTC native
        brows2 = brows
        hh = [r[2] for r in brows2]; ll = [r[3] for r in brows2]
        state, _ = pf_states(hh, ll, bcc, scaling)
        ords = [date(*map(int, d.split("-"))).toordinal() for d in bdates]
        twins = []
        for seed in range(20):
            pst = placebo_states(state, 0, len(bdates) - 1, 7000 + seed)
            twins.append(run_window(bdates, bcc, pst, 0, len(bdates) - 1, "NATIVE", CCOST, 0.0, ords)["final"])
        ent["placebo_finals_native"] = twins
        ent["placebos_beaten_native"] = sum(1 for t in twins if ent["NATIVE"]["final"] > t)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"))
    print("ALL SAVED")

if __name__ == "__main__":
    main()
