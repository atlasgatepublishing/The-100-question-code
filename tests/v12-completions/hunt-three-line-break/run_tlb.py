#!/usr/bin/env python3
"""Three-Line Break (Nison, Beyond Candlesticks 1994) — v12 Deep-Hunt run.
Implements SPEC-FROZEN.md EXACTLY:
- Lines built on closes only. Continuation line when close exceeds the last
  line's directional extreme. Reversal line when close breaks the combined
  high-low range of the last three lines of the current run (all lines of
  the run when the run is shorter than three — the only way alternating
  lines can print at all; declared mechanisation).
- Every line starts at the previous line's end price (standard TLB geometry:
  reversal lines overlap the run they reverse).
- BUY at the close completing a white reversal line after >=3 consecutive
  black lines. SELL at the close completing a black reversal line after
  >=3 consecutive white lines. Reversals after runs of 1-2 lines change
  nothing (alternation = do not trade, per the published rule).
- Execution AT THE SIGNAL CLOSE (the frozen form specifies it).
- Sizing: all-in $100 pot. Stocks: program costs 0.10%/side + $0.01 sell fee.
  Coins: 0.60%/side (midpoint of the program's measured 0.40-0.80% band), no
  fixed fee. Cash 0%.
- Rule sets: NATIVE = bare published rules, no floor. HOUSE (v9) = same
  signal + v9 chassis: plain -15% floor from episode start balance (close
  check, liquidate next open), 90-calendar-day sit-out, one restart under an
  episode-2 -15% floor from the restart balance; second halt ends the run.
- Placebos: 20-seed circular shifts of the desired-state series (preserves
  time-in-market and switch count, destroys alignment).
Simulation only. Shared inputs read-only.
"""
import json, os, time, random, statistics
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
CBASE = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-basket-pit-data")
START = 100.0
STK_COST = 0.001; STK_FEE = 0.01
COIN_COST = 0.006
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
COIN_END = "2026-11-21"

# ---------------- TLB signal construction ----------------

def tlb_desired(closes):
    """Return (desired[0/1 per bar], n_lines, n_buy_signals, n_sell_signals).
    desired[t] is the position the published rules dictate AFTER bar t's close."""
    n = len(closes)
    desired = [0] * n
    if n < 2:
        return desired, 0, 0, 0
    lines = []  # [dir(+1 white/-1 black), start, end]
    base = closes[0]
    cur = 0; buys = 0; sells = 0
    run_dir = 0; run_len = 0
    for t in range(1, n):
        c = closes[t]
        if not lines:
            if c > base:
                lines.append([1, base, c]); run_dir, run_len = 1, 1
            elif c < base:
                lines.append([-1, base, c]); run_dir, run_len = -1, 1
            desired[t] = cur
            continue
        last = lines[-1]
        top = max(last[1], last[2]); bot = min(last[1], last[2])
        new_line = 0
        if last[0] == 1:  # white run
            if c > top:
                new_line = 1
            elif c < min(min(l[1], l[2]) for l in lines[-run_len:][-3:]):
                new_line = -1
        else:  # black run
            if c < bot:
                new_line = -1
            elif c > max(max(l[1], l[2]) for l in lines[-run_len:][-3:]):
                new_line = 1
        if new_line:
            if new_line == run_dir:
                run_len += 1
            else:
                reversed_run = run_len
                if new_line == 1 and reversed_run >= 3 and run_dir == -1:
                    cur = 1; buys += 1
                elif new_line == -1 and reversed_run >= 3 and run_dir == 1:
                    cur = 0; sells += 1
                run_dir = new_line; run_len = 1
            lines.append([new_line, last[2], c])
        desired[t] = cur
    return desired, len(lines), buys, sells

# ---------------- simulation ----------------

def simulate(dates, opens, closes, desired, i0, i1, cost, fee, house, light=False):
    """Run over bars [i0, i1]. Trades at close on signal change; v9 floor
    liquidates at next open. light=True: final only (placebo replays)."""
    cash = START; shares = 0.0; costs = 0.0; orders = 0
    if light:
        class _Null(list):
            def append(self, x): pass
        curve = _Null(); trades = _Null()
    else:
        curve = []; trades = []
    ep_start_bal = START; episodes = 1; halts = 0
    sitout_until = None; dead = False; pending_halt = False
    for t in range(i0, i1 + 1):
        d = dates[t]; px = closes[t]
        if pending_halt:
            # liquidate at this bar's open (the open after the breach close)
            if shares > 0:
                val = shares * opens[t]; cf = val * cost + fee
                cash += val - cf; costs += cf; orders += 1
                trades.append([d, "HALT-SELL", round(opens[t], 4), round(cash, 2)])
                shares = 0.0
            pending_halt = False
            if halts == 1:
                hd = date(int(d[:4]), int(d[5:7]), int(d[8:10])) + timedelta(days=90)
                sitout_until = hd.isoformat(); episodes = 2
                ep_start_bal = cash
            else:
                dead = True
        if sitout_until is not None and d >= sitout_until and not dead:
            sitout_until = None  # restart: resume syncing at today's close
        halted_today = False
        if house and not dead and sitout_until is None and not pending_halt:
            eq_close = cash + shares * px
            if eq_close <= 0.85 * ep_start_bal:
                halts += 1; halted_today = True
                if t == i1:  # breach on last bar: liquidate at this close now
                    if shares > 0:
                        val = shares * px; cf = val * cost + fee
                        cash += val - cf; costs += cf; orders += 1; shares = 0.0
                    if halts == 1:
                        episodes = 2; ep_start_bal = cash
                    else:
                        dead = True
                else:
                    pending_halt = True
        if not halted_today and not dead and sitout_until is None:
            want = desired[t]
            if want == 1 and shares == 0.0 and cash > 0:
                bv = cash / (1 + cost); cf = bv * cost
                shares = bv / px; cash -= bv + cf; costs += cf; orders += 1
                trades.append([d, "BUY", round(px, 4), round(bv, 2)])
            elif want == 0 and shares > 0:
                val = shares * px; cf = val * cost + fee
                cash += val - cf; costs += cf; orders += 1; shares = 0.0
                trades.append([d, "SELL", round(px, 4), round(val, 2)])
        curve.append([d, round(cash + shares * px, 4)])
    # end of window: liquidate at last close
    if shares > 0:
        val = shares * closes[i1]; cf = val * cost + fee
        cash += val - cf; costs += cf; orders += 1
        trades.append([dates[i1], "SELL-END", round(closes[i1], 4), round(val, 2)])
        if not light: curve[-1] = [dates[i1], round(cash, 4)]
    peak = -1.0; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0: mdd = max(mdd, (peak - v) / peak)
    inv = sum(1 for t in range(i0, i1 + 1) if desired[t] == 1)
    return {"final": round(cash, 2), "max_dd_pct": round(mdd * 100, 2),
            "costs": round(costs, 2), "orders": orders, "halts": halts,
            "invested_pct": round(100.0 * inv / (i1 - i0 + 1), 1),
            "trades": trades, "equity_curve": curve}

def buyhold(dates, closes, i0, i1, cost, fee, dead_zero=False):
    sh = (START / (1 + cost)) / closes[i0]
    if dead_zero:
        return 0.0
    val = sh * closes[i1]
    return round(val - (val * cost + fee), 2)

def period_stats(curve):
    """Monthly period distribution from a daily equity curve."""
    months = {}
    order = []
    for d, v in curve:
        m = d[:7]
        if m not in months: order.append(m)
        months[m] = v
    vals = [months[m] for m in order]
    rets = []
    prev = START
    for v in vals:
        rets.append(v / prev - 1.0); prev = v
    if not rets:
        return None
    prof = sum(1 for r in rets if r > 0)
    longest_loss = 0; run = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        longest_loss = max(longest_loss, run)
    peak = -1.0; since_high = 0; longest_gap = 0
    for v in vals:
        if v > peak: peak = v; since_high = 0
        else:
            since_high += 1; longest_gap = max(longest_gap, since_high)
    return {"periods": len(rets), "pct_profitable": round(100.0 * prof / len(rets), 1),
            "median_pct": round(100.0 * statistics.median(rets), 2),
            "best_pct": round(100.0 * max(rets), 2), "worst_pct": round(100.0 * min(rets), 2),
            "longest_losing_run": longest_loss, "longest_between_highs_periods": longest_gap,
            "average_pct_secondary": round(100.0 * statistics.mean(rets), 2)}

def placebo_finals(dates, opens, closes, desired, i0, i1, cost, fee, house, seeds=20):
    seg = desired[i0:i1 + 1]
    out = []
    L = len(seg)
    for s in range(seeds):
        rng = random.Random(4200 + s)
        k = rng.randrange(1, L) if L > 1 else 0
        sh = seg[k:] + seg[:k]
        full = list(desired[:i0]) + sh + list(desired[i1 + 1:])
        r = simulate(dates, opens, closes, full, i0, i1, cost, fee, house, light=True)
        out.append(r["final"])
    return out

# ---------------- data ----------------

def load_stock(sym):
    p = os.path.join(PXDIR, f"pxfull_{sym}.json")
    if not os.path.exists(p): return None
    j = json.load(open(p)); r = j["chart"]["result"][0]
    ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    dates, opens, closes = [], [], []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None: continue
        ratio = adj[i] / q["close"][i]
        dates.append(time.strftime("%Y-%m-%d", time.gmtime(t)))
        opens.append(q["open"][i] * ratio); closes.append(adj[i])
    return dates, opens, closes

COIN_FILEMAP = {"LUNA": "y_LUNC-USD.json", "UST": "y_USTC-USD.json",
                "MATIC": "b_MATICUSDT.json", "MIOTA": "b_IOTAUSDT.json",
                "PEPE": "b_PEPEUSDT.json", "POL": "b_POLUSDT.json",
                "SUI": "b_SUIUSDT.json", "UNI": "b_UNIUSDT.json",
                "USD1": "b_USD1USDT.json", "USDe": "b_USDEUSDT.json",
                "TON": "k_TONUSD.json"}
COIN_NO_DATA = ["BCC", "CC", "DGD", "FCT", "GAME", "GNT", "GRAM", "HYPE", "ICN",
                "M", "MAID", "STRAT", "VEN", "HC", "MIN", "PAY", "TAGZ5", "NANO", "SNGLS"]

def load_coin(sym):
    fn = COIN_FILEMAP.get(sym, f"y_{sym}-USD.json")
    p = os.path.join(CBASE, fn)
    if not os.path.exists(p): return None
    raw = json.load(open(p))
    rows = []
    for r in raw:
        o, c = float(r["o"]), float(r["c"])
        if o > 0 and c > 0: rows.append((r["d"], o, c))
    rows.sort()
    out, seen = [], set()
    for d, o, c in rows:
        if d not in seen: seen.add(d); out.append((d, o, c))
    if len(out) < 30: return None
    return [x[0] for x in out], [x[1] for x in out], [x[2] for x in out]

def idx_range(dates, start, end):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    return (idx[0], idx[-1]) if idx else (None, None)

def main():
    out = {"family": "hunt-three-line-break", "disposition": "HUNT-FOUND (deep-hunt-nonus)",
           "form": "Three-Line Break, Nison 1994 published rules frozen literally; at-close execution; sizing CONSTRUCTED program standard",
           "stock_costs": "0.10%/side + $0.01 sell fee", "coin_costs": "0.60%/side (stated rate; band 0.40-0.80)",
           "champions": CHAMP, "spy_reference": SPYREF, "stocks": {}, "coins": {}}

    # ---------- STOCKS: SPY ----------
    dates, opens, closes = load_stock("SPY")
    desired, nlines, nb, ns = tlb_desired(closes)
    spy = {"n_lines_full_series": nlines, "buy_signals": nb, "sell_signals": ns, "roads": {}}
    for road, (s, e) in ROADS.items():
        i0, i1 = idx_range(dates, s, e)
        ent = {}
        for rules, house in (("native", False), ("v9", True)):
            r = simulate(dates, opens, closes, desired, i0, i1, STK_COST, STK_FEE, house)
            pl = placebo_finals(dates, opens, closes, desired, i0, i1, STK_COST, STK_FEE, house)
            ent[rules] = {**{k: r[k] for k in ("final", "max_dd_pct", "costs", "orders", "halts", "invested_pct")},
                          "placebo_finals": pl,
                          "placebos_beaten": sum(1 for x in pl if r["final"] > x),
                          "period_stats_monthly": period_stats(r["equity_curve"]),
                          "equity_curve": r["equity_curve"], "trades": r["trades"]}
        ent["buyhold_own_plumbing"] = buyhold(dates, closes, i0, i1, STK_COST, STK_FEE)
        ent["spy_reference_program"] = SPYREF[road]
        ent["champion_vm"] = CHAMP[road]
        spy["roads"][road] = ent
    # SPY calendar-year folds (native + v9), confirmation evidence
    folds = {}
    for y in range(2010, 2027):
        i0, i1 = idx_range(dates, f"{y}-01-01", f"{y}-12-31")
        if i0 is None: continue
        folds[str(y)] = {rules: simulate(dates, opens, closes, desired, i0, i1, STK_COST, STK_FEE, house)["final"]
                         for rules, house in (("native", False), ("v9", True))}
        folds[str(y)]["buyhold"] = buyhold(dates, closes, i0, i1, STK_COST, STK_FEE)
    spy["year_folds"] = folds
    out["stocks"]["SPY"] = spy
    print("SPY done", flush=True)

    # ---------- STOCKS: pond names ----------
    pond_syms = sorted(fn[len("pxfull_"):-len(".json")] for fn in os.listdir(PXDIR)
                       if fn.startswith("pxfull_") and fn != "pxfull_SPY.json")
    pond = {}; pond_cache = {}
    for sym in pond_syms:
        ld = load_stock(sym)
        if ld is None: continue
        d2, o2, c2 = ld
        des2, nl2, nb2, ns2 = tlb_desired(c2)
        pond_cache[sym] = (d2, o2, c2, des2)
        ent = {"n_lines": nl2, "buy_signals": nb2, "sell_signals": ns2, "roads": {}}
        for road, (s, e) in ROADS.items():
            i0, i1 = idx_range(d2, s, e)
            if i0 is None: continue
            ent["roads"][road] = {
                rules: simulate(d2, o2, c2, des2, i0, i1, STK_COST, STK_FEE, house)["final"]
                for rules, house in (("native", False), ("v9", True))}
            ent["roads"][road]["buyhold"] = buyhold(d2, c2, i0, i1, STK_COST, STK_FEE)
        pond[sym] = ent
    out["stocks"]["pond"] = pond
    # pond pooled placebos (native + v9, LONG + VAL): shift each name's state
    pooled_pl = {}
    for road in ("LONG", "VAL"):
        s, e = ROADS[road]
        for rules, house in (("native", False), ("v9", True)):
            reals, pls = [], []
            seed_finals = [[] for _ in range(20)]
            for sym in pond_syms:
                if sym not in pond_cache: continue
                d2, o2, c2, des2 = pond_cache[sym]
                i0, i1 = idx_range(d2, s, e)
                if i0 is None: continue
                reals.append(pond[sym]["roads"][road]["native" if not house else "v9"])
                seg = des2[i0:i1 + 1]; L = len(seg)
                for sd in range(20):
                    rng = random.Random(7700 + sd)
                    k = rng.randrange(1, L) if L > 1 else 0
                    full = list(des2[:i0]) + seg[k:] + seg[:k] + list(des2[i1 + 1:])
                    seed_finals[sd].append(simulate(d2, o2, c2, full, i0, i1, STK_COST, STK_FEE, house, light=True)["final"])
            pooled_pl[f"{road}_{rules}"] = {
                "real_mean": round(statistics.mean(reals), 2) if reals else None,
                "placebo_means": [round(statistics.mean(x), 2) for x in seed_finals],
                "n_names": len(reals)}
    out["stocks"]["pond_pooled_placebos"] = pooled_pl
    print("pond done", flush=True)

    # ---------- COINS ----------
    snap = json.load(open(os.path.join(CBASE, "snapshots.json")))
    universe = set()
    for v in snap.values():
        for en in v["top20"]: universe.add(en["symbol"])
    universe = sorted(universe)
    coins = {}; excluded = {}; coin_cache = {}
    for sym in universe:
        if sym in COIN_NO_DATA:
            excluded[sym] = "NO-FREE-SERIES (v4 registry: no usable free daily series)"
            continue
        ld = load_coin(sym)
        if ld is None:
            excluded[sym] = "NO-FREE-SERIES (cache missing or <30 usable bars)"
            continue
        d2, o2, c2 = ld
        des2, nl2, nb2, ns2 = tlb_desired(c2)
        coin_cache[sym] = (d2, o2, c2, des2)
        dead = d2[-1] < "2026-05-24"  # series ended >180d before universe end -> dead/abandoned
        ent = {"first": d2[0], "last": d2[-1], "bars": len(d2), "n_lines": nl2,
               "buy_signals": nb2, "sell_signals": ns2, "dead_series": dead, "windows": {}}
        for wname, (s, e) in (("FULL", ("2015-01-01", COIN_END)), ("RECENT", ("2023-01-01", COIN_END))):
            i0, i1 = idx_range(d2, s, e)
            if i0 is None or i1 - i0 < 30:
                ent["windows"][wname] = None; continue
            w = {}
            for rules, house in (("native", False), ("v9", True)):
                r = simulate(d2, o2, c2, des2, i0, i1, COIN_COST, 0.0, house)
                w[rules] = {k: r[k] for k in ("final", "max_dd_pct", "costs", "orders", "halts", "invested_pct")}
                w[rules]["trades"] = r["trades"]
                if sym in ("BTC", "ETH"):
                    w[rules]["equity_curve"] = r["equity_curve"]
                    w[rules]["period_stats_monthly"] = period_stats(r["equity_curve"])
            # dead->ZERO: if series dead and the run ended still holding (SELL-END at a
            # price that no longer exists), the position is worth zero: recompute as
            # cash-only final by checking whether last trade was the forced end sale.
            if dead:
                for rules in ("native", "v9"):
                    tr = w[rules]["trades"]
                    if tr and tr[-1][1] == "SELL-END":
                        # position value at end sale removed: final becomes cash before sale
                        # cash_before = final - net sale proceeds; net proceeds = gross - fee
                        gross = tr[-1][3]
                        net = gross - (gross * COIN_COST)
                        w[rules]["final"] = round(w[rules]["final"] - net, 2)
                        w[rules]["dead_zero_applied"] = True
            w["buyhold"] = 0.0 if dead else buyhold(d2, c2, i0, i1, COIN_COST, 0.0)
            ent["windows"][wname] = w
        coins[sym] = ent
    out["coins"]["universe_size"] = len(universe)
    out["coins"]["ran"] = coins
    out["coins"]["excluded"] = excluded
    # BTC hold beside every coin number: BTC buy-hold over FULL and RECENT
    btc = coins.get("BTC", {}).get("windows", {})
    out["coins"]["btc_hold"] = {w: (btc[w]["buyhold"] if btc.get(w) else None) for w in ("FULL", "RECENT")}
    # coin pooled placebos (FULL + RECENT, native + v9): per-coin state shifts
    cpl = {}
    for wname, (s, e) in (("FULL", ("2015-01-01", COIN_END)), ("RECENT", ("2023-01-01", COIN_END))):
        for rules, house in (("native", False), ("v9", True)):
            reals = []; seed_lists = [[] for _ in range(20)]
            for sym, ent in coins.items():
                if not ent["windows"].get(wname): continue
                d2, o2, c2, des2 = coin_cache[sym]
                i0, i1 = idx_range(d2, s, e)
                reals.append(ent["windows"][wname][rules]["final"])
                seg = des2[i0:i1 + 1]; L = len(seg)
                for sd in range(20):
                    rng = random.Random(9900 + sd)
                    k = rng.randrange(1, L) if L > 1 else 0
                    full = list(des2[:i0]) + seg[k:] + seg[:k] + list(des2[i1 + 1:])
                    seed_lists[sd].append(simulate(d2, o2, c2, full, i0, i1, COIN_COST, 0.0, house, light=True)["final"])
            cpl[f"{wname}_{rules}"] = {
                "real_mean": round(statistics.mean(reals), 2) if reals else None,
                "real_median": round(statistics.median(reals), 2) if reals else None,
                "placebo_means": [round(statistics.mean(x), 2) for x in seed_lists],
                "n_coins": len(reals)}
    out["coins"]["pooled_placebos"] = cpl
    print("coins done", flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f)
    print("done. SPY:", {r: spy["roads"][r]["native"]["final"] for r in ROADS},
          "| v9:", {r: spy["roads"][r]["v9"]["final"] for r in ROADS})
    print("coins ran:", len(coins), "excluded:", len(excluded))

if __name__ == "__main__":
    main()
