import json, os, time, random, statistics
from datetime import date

START = 100.0
STK_COST = 0.001; STK_SELL_FEE = 0.01
CRY_COST = 0.006
ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
CBASE = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-basket-pit-data")
CTREND = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-trend-data")


def load_pxfull(ticker, path=None):
    p = path or os.path.join(PXDIR, f"pxfull_{ticker}.json")
    j = json.load(open(p))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "h": q["high"][i] * ratio,
                     "l": q["low"][i] * ratio, "c": adj[i],
                     "v": q["volume"][i] or 0})
    bars.sort(key=lambda b: b["d"])
    return bars


def load_coin_csv(sym):
    p = os.path.join(CTREND, f"{sym}-USD.csv")
    bars = []
    with open(p) as f:
        next(f)
        for line in f:
            pp = line.strip().split(",")
            if len(p) < 5:
                continue
            bars.append({"d": pp[0], "o": float(pp[1]), "h": float(pp[2]),
                         "l": float(pp[3]), "c": float(pp[4]), "v": 0})
    bars.sort(key=lambda b: b["d"])
    return bars


CFILEMAP = {"LUNA": "y_LUNC-USD.json", "UST": "y_USTC-USD.json",
            "MATIC": "b_MATICUSDT.json", "MIOTA": "b_IOTAUSDT.json",
            "PEPE": "b_PEPEUSDT.json", "POL": "b_POLUSDT.json",
            "SUI": "b_SUIUSDT.json", "UNI": "b_UNIUSDT.json",
            "USD1": "b_USD1USDT.json", "USDe": "b_USDEUSDT.json",
            "TON": "k_TONUSD.json"}
CNO_DATA = ["BCC", "CC", "DGD", "FCT", "GAME", "GNT", "GRAM", "HYPE", "ICN",
            "M", "MAID", "STRAT", "VEN", "HC", "MIN", "PAY", "TAGZ5", "NANO", "SNGLS"]


def coin_universe():
    snap = json.load(open(os.path.join(CBASE, "snapshots.json")))
    coins = set()
    for v in snap.values():
        for e in v["top20"]:
            coins.add(e["symbol"])
    return sorted(coins)


def load_coin(sym):
    """OC series with OC-range H/L proxy (program crypto-x-timers convention).
    BTC/ETH use the true-OHLC v4 trend CSVs instead."""
    if sym in ("BTC", "ETH"):
        return load_coin_csv(sym), False
    fn = CFILEMAP.get(sym, f"y_{sym}-USD.json")
    p = os.path.join(CBASE, fn)
    if not os.path.exists(p):
        return None, True
    raw = json.load(open(p))
    bars, seen = [], set()
    for r in raw:
        if r["d"] in seen:
            continue
        seen.add(r["d"])
        o, c = float(r["o"]), float(r["c"])
        if o <= 0 or c <= 0:
            continue
        bars.append({"d": r["d"], "o": o, "h": max(o, c), "l": min(o, c),
                     "c": c, "v": 0})
    bars.sort(key=lambda b: b["d"])
    if len(bars) < 10:
        return None, True
    return bars, True


def simulate(bars, targets, start, end, cost, sell_fee, chassis=False,
             shift_seed=None):
    """Daily engine: targets[i] = desired long state AFTER close of bars[i];
    changes execute at the NEXT bar's open. House chassis (v9): floor checked
    on daily closes vs episode start, -15%: first breach liquidates at next
    open and halts 90 days, second breach ends the run (Coppock convention)."""
    idx = [i for i, b in enumerate(bars)
           if (start is None or b["d"] >= start) and b["d"] <= end]
    if not idx:
        return None
    tgt = list(targets)
    if shift_seed is not None:
        rng = random.Random(shift_seed)
        seg = [tgt[i] for i in idx]
        if len(seg) > 1:
            k = rng.randrange(1, len(seg))
            seg = seg[k:] + seg[:k]
            for j, i in enumerate(idx):
                tgt[i] = seg[j]
    desired = False
    for i in range(idx[0]):
        desired = tgt[i]
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    pending = desired if desired else None
    ep_start, halts, halt_until, ended = START, 0, None, False
    days_invested = 0
    for pos, i in enumerate(idx):
        b = bars[i]
        if halt_until is not None and b["d"] >= halt_until:
            halt_until = None; ep_start = cash + shares * b["o"]
        if pending is not None and halt_until is None and not ended:
            if pending and shares == 0.0 and cash > 0:
                bv = cash / (1 + cost); cfee = bv * cost
                shares = bv / b["o"]; cash -= bv + cfee; costs += cfee
                trades.append([b["d"], "BUY", round(b["o"], 6), round(bv, 2), round(cfee, 2)])
            elif not pending and shares > 0:
                val = shares * b["o"]; cfee = val * cost + sell_fee
                cash += val - cfee; costs += cfee; shares = 0.0
                trades.append([b["d"], "SELL", round(b["o"], 6), round(val, 2), round(cfee, 2)])
            pending = None
        if tgt[i] != (shares > 0) and halt_until is None and not ended:
            pending = tgt[i]
        eq = cash + shares * b["c"]
        if shares > 0:
            days_invested += 1
        curve.append([b["d"], round(eq, 4)])
        if chassis and not ended and halt_until is None and eq <= 0.85 * ep_start:
            halts += 1
            if pos + 1 < len(idx):
                nb = bars[idx[pos + 1]]
                if shares > 0:
                    val = shares * nb["o"]; cfee = val * cost + sell_fee
                    cash += val - cfee; costs += cfee; shares = 0.0
                    trades.append([nb["d"], "SELL-FLOOR", round(nb["o"], 6),
                                   round(val, 2), round(cfee, 2)])
                    pending = None
            if halts == 1:
                halt_until = date.fromordinal(
                    date.fromisoformat(b["d"]).toordinal() + 90).isoformat()
            else:
                ended = True
    if shares > 0:
        last = bars[idx[-1]]; val = shares * last["c"]
        cfee = val * cost + sell_fee
        cash += val - cfee; costs += cfee; shares = 0.0
        trades.append([last["d"], "SELL-END", round(last["c"], 6), round(val, 2), round(cfee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0 * days_invested / len(idx), 1) if idx else 0.0,
            "halts": halts, "equity_curve": curve}


def buy_hold(bars, start, end, cost, sell_fee):
    days = [b for b in bars if (start is None or b["d"] >= start) and b["d"] <= end]
    if not days:
        return None
    o = days[0]["o"]; sh = (START / (1 + cost)) / o
    curve = [[b["d"], round(sh * b["c"], 4)] for b in days]
    val = sh * days[-1]["c"]
    final = val - (val * cost + sell_fee)
    curve[-1] = [days[-1]["d"], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "equity_curve": curve}


def period_stats(curve, freq="monthly"):
    """Reporting standard at the family tempo. freq: weekly|monthly|annual."""
    if not curve:
        return None
    def key(d):
        if freq == "monthly":
            return d[:7]
        if freq == "annual":
            return d[:4]
        y, m, dd = map(int, d.split("-"))
        iso = date(y, m, dd).isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    vals, last = [], None
    for d, v in curve:
        k = key(d)
        if k != last:
            vals.append(v); last = k
        else:
            vals[-1] = v
    series = [START] + vals
    if len(series) < 2:
        return None
    rets = [(series[i] / series[i - 1] - 1.0) * 100.0 if series[i - 1] > 0 else 0.0
            for i in range(1, len(series))]
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        if r < 0:
            streak += 1; worst = max(worst, streak)
        else:
            streak = 0
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak:
            peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(series) - 1 - last_high)
    return {"periods": len(rets), "pct_positive": round(100.0 * pos / len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary_average_only": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak": worst, "longest_between_highs": longest}


def run_timer_roads(bars, targets, roads, cost, sell_fee, bench_name, freq="monthly",
                    placebos=True):
    out = {}
    for name, (s, e) in roads.items():
        rec = {}
        for form, chassis in (("native", False), ("house_v9", True)):
            r = simulate(bars, targets, s, e, cost, sell_fee, chassis=chassis)
            rec[form] = {**r, "period_stats": period_stats(r["equity_curve"], freq)}
        bh = buy_hold(bars, s, e, cost, sell_fee)
        rec["benchmark_hold"] = {"name": bench_name, "final": bh["final"],
                                 "max_dd_pct": bh["max_dd_pct"],
                                 "period_stats": period_stats(bh["equity_curve"], freq)}
        if placebos:
            finals = []
            for seed in range(1, 21):
                pr = simulate(bars, targets, s, e, cost, sell_fee,
                              chassis=False, shift_seed=seed)
                finals.append(pr["final"])
            rec["placebo_native"] = {
                "seed_finals": finals,
                "beaten_of_20": sum(1 for p in finals if rec["native"]["final"] > p),
                "design": "circular shift of the daily in/out state series within the road (20 seeds); preserves invested-day fraction and episode lengths"}
        out[name] = rec
    return out


def run_coins(signal_fn, min_bars=120):
    """Per-coin native+house on FULL history and RECENT (2023+) windows.
    signal_fn(bars) -> targets list. Returns (per_coin dict, closures list)."""
    per, closures = {}, []
    for sym in coin_universe():
        if sym in CNO_DATA:
            closures.append([sym, "named data closure: no usable free series in the program PIT cache (crypto-x-timers HUNT-LOG class)"])
            continue
        bars, proxy = load_coin(sym)
        if bars is None:
            closures.append([sym, "no usable series in cache"])
            continue
        if len(bars) < min_bars:
            closures.append([sym, f"only {len(bars)} bars — too short for the frozen form's warmup"])
            continue
        targets = signal_fn(bars)
        rec = {"proxy_hl": proxy, "first": bars[0]["d"], "last": bars[-1]["d"], "windows": {}}
        for wname, (s, e) in (("FULL", (None, "2026-11-21")),
                              ("RECENT", ("2023-01-01", "2026-11-21"))):
            rn = simulate(bars, targets, s, e, CRY_COST, 0.0, chassis=False)
            rh = simulate(bars, targets, s, e, CRY_COST, 0.0, chassis=True)
            bh = buy_hold(bars, s, e, CRY_COST, 0.0)
            if rn is None or bh is None:
                continue
            rec["windows"][wname] = {
                "native_final": rn["final"], "native_dd": rn["max_dd_pct"],
                "house_final": rh["final"], "house_halts": rh["halts"],
                "hold_final": bh["final"], "beat_hold_native": rn["final"] > bh["final"]}
        if rec["windows"]:
            per[sym] = rec
    return per, closures


def coin_summary(per):
    out = {}
    for wname in ("FULL", "RECENT"):
        rows = [(s, r["windows"][wname]) for s, r in per.items() if wname in r["windows"]]
        if not rows:
            continue
        nat = [w["native_final"] for _, w in rows]
        hold = [w["hold_final"] for _, w in rows]
        out[wname] = {
            "coins": len(rows),
            "beat_hold_count": sum(1 for _, w in rows if w["beat_hold_native"]),
            "median_native": round(statistics.median(nat), 2),
            "median_hold": round(statistics.median(hold), 2),
            "mean_native_secondary_average_only": round(statistics.mean(nat), 2),
            "mean_hold_secondary_average_only": round(statistics.mean(hold), 2)}
    return out

#!/usr/bin/env python3
"""hunt-fosback-seasonality-timing — SPEC-FROZEN form EXACTLY. Fosback's
Market Logic Seasonality Timing System (Stock Market Logic, 1976;
Hulbert's verbatim reprint, MarketWatch 2003):
1) Turn of month: buy at the close of the 3rd-to-last trading day of the
   month; sell at the close of the 5th trading session of the next month.
2) Pre-holiday: buy at the close of the 3rd-to-last trading day before an
   exchange holiday; sell at the close of the last trading day before it.
3) Exceptions: (i) holiday on a Thursday -> sell at Friday's close
   instead; (ii) if the last day before a holiday is the first trading
   day of the week -> sell the day after the holiday; (iii) never sell
   on the first trading day after options expire (third Friday) -> wait
   one extra day. Applied to all sells (the reprint lists (iii) as a
   general STS rule; the reading is printed here).
Windows combine into one continuous program (overlaps merge, no double
position). Trades execute AT THE CLOSES named in the rules (frozen in
spec — a stated deviation from the program's next-open convention, with
program costs still charged per side). Calendar: exchange holidays are
read off the SPY trading calendar itself (a weekday with no SPY bar is
an exchange closure — point-in-time, no look-ahead; this also captures
special closures such as Sandy 2012 and national-mourning days).
Instrument SPY (CONSTRUCTED proxy per spec). Native = no floor; house =
v9 chassis on the daily equity curve (spec note). Placebos: the same
windows shifted by random day-offsets, 20 seeds (spec). Coins:
NOT-APPLICABLE per spec (no exchange holidays / options expiries in a
24/7 market)."""
HERE = os.path.dirname(os.path.abspath(__file__))
FAMILY = "hunt-fosback-seasonality-timing (Fosback Market Logic STS, 1976)"
FORM_NOTE = ("FROZEN: turn-of-month + pre-holiday windows with the three "
             "published exceptions; close execution per spec; SPY; native "
             "no floor, house v9 chassis; calendar placebos 20 seeds")


def build_windows(bars):
    """Returns (invested_after_close boolean list, event list). invested[i]
    = True means a position bought at/before close i is held over the
    (i -> i+1) interval; a buy at close i sets invested[i]=True; a sell at
    close j means invested[j]=False and the (j-1 -> j) interval was held."""
    n = len(bars)
    dates = [b["d"] for b in bars]
    dobj = [date.fromisoformat(d) for d in dates]
    idx_of = {d: i for i, d in enumerate(dates)}
    buys, sells = set(), set()
    # --- turn of month ---
    months = {}
    for i, d in enumerate(dates):
        months.setdefault(d[:7], []).append(i)
    mkeys = sorted(months)
    for mi, mk in enumerate(mkeys):
        days = months[mk]
        if len(days) < 3 or mi + 1 >= len(mkeys):
            continue
        buy_i = days[-3]
        ndays = months[mkeys[mi + 1]]
        if len(ndays) < 5:
            continue
        sell_i = ndays[4]
        buys.add(buy_i); sells.add(sell_i)
    # --- holiday gaps: weekdays with no bar ---
    trading = set(dobj)
    holidays = []  # (holiday_date, last_td_before_idx, first_td_after_idx)
    d0, d1 = dobj[0], dobj[-1]
    cur = d0
    gap = []
    while cur <= d1:
        if cur.weekday() < 5 and cur not in trading:
            gap.append(cur)
        else:
            if gap:
                holidays.append(list(gap)); gap = []
        cur = date.fromordinal(cur.toordinal() + 1)
    if gap:
        holidays.append(gap)
    for gap in holidays:
        first_hol = gap[0]
        # last trading day before the gap
        prev = date.fromordinal(first_hol.toordinal() - 1)
        while prev not in trading and prev >= d0:
            prev = date.fromordinal(prev.toordinal() - 1)
        if prev < d0:
            continue
        last_before = idx_of[prev.isoformat()]
        if last_before < 2:
            continue
        buy_i = last_before - 2  # 3rd-to-last trading day before the holiday
        sell_i = last_before
        # exception (i): any holiday in the gap on a Thursday -> sell at
        # the close of the first trading day after the gap (Friday)
        if any(h.weekday() == 3 for h in gap):
            nxt = date.fromordinal(gap[-1].toordinal() + 1)
            while nxt not in trading and nxt <= d1:
                nxt = date.fromordinal(nxt.toordinal() + 1)
            if nxt <= d1:
                sell_i = idx_of[nxt.isoformat()]
        # exception (ii): last day before holiday is the first trading day
        # of its week -> sell the day after the holiday
        wk_start = date.fromordinal(prev.toordinal() - prev.weekday())
        first_td_week = wk_start
        while first_td_week not in trading and first_td_week <= prev:
            first_td_week = date.fromordinal(first_td_week.toordinal() + 1)
        if first_td_week == prev and sell_i == last_before:
            nxt = date.fromordinal(gap[-1].toordinal() + 1)
            while nxt not in trading and nxt <= d1:
                nxt = date.fromordinal(nxt.toordinal() + 1)
            if nxt <= d1:
                sell_i = idx_of[nxt.isoformat()]
        buys.add(buy_i); sells.add(sell_i)
    # exception (iii): a sell on the first trading day after the third
    # Friday (options expiry) waits one extra day
    third_fridays = set()
    for mk in mkeys:
        y, m = map(int, mk.split("-"))
        d = date(y, m, 1)
        fridays = []
        while d.month == m:
            if d.weekday() == 4:
                fridays.append(d)
            d = date.fromordinal(d.toordinal() + 1)
        if len(fridays) >= 3:
            third_fridays.add(fridays[2])
    def is_first_td_after_expiry(i):
        # previous calendar day(s): was the most recent Friday the 3rd Friday
        # and is bars[i] the first trading day strictly after it?
        dd = dobj[i]
        # find the Friday of the week containing dd or the prior Friday
        back = dd
        for _ in range(7):
            back = date.fromordinal(back.toordinal() - 1)
            if back.weekday() == 4:
                break
        if back not in third_fridays:
            return False
        # first trading day after that Friday?
        nxt = date.fromordinal(back.toordinal() + 1)
        while nxt not in trading and nxt <= d1:
            nxt = date.fromordinal(nxt.toordinal() + 1)
        return nxt == dd
    sells2 = set()
    for s in sells:
        if is_first_td_after_expiry(s) and s + 1 < n:
            sells2.add(s + 1)
        else:
            sells2.add(s)
    sells = sells2
    # merge into invested-after-close array
    invested = [False] * n
    pos = False
    events = []
    for i in range(n):
        if i in buys and not pos:
            pos = True; events.append([dates[i], "BUY-CLOSE"])
        if pos:
            invested[i] = True
        if i in sells and pos:
            pos = False; events.append([dates[i], "SELL-CLOSE"])
            invested[i] = True  # held over (i-1 -> i); exposure ends at close i
            # mark: after close i we are flat; handled by state flag below
            invested[i] = True
            # use a separate 'held into close' semantics in the simulator:
            # simulator treats invested[i] as exposure over (i-1 -> i) when
            # invested[i-1] or a buy happened at i-1... see sts_sim.
    return invested, buys, sells, events


def sts_sim(bars, buys, sells, start, end, chassis=False, shift=0, seed=None):
    """Close-execution simulator. Exposure over interval (i-1 -> i) is held
    iff a buy occurred at some close <= i-1 and no sell occurred at a close
    < i... implemented via an event state machine on closes."""
    n = len(bars)
    idx = [i for i, b in enumerate(bars) if b["d"] >= start and b["d"] <= end]
    if not idx:
        return None
    bset, sset = set(buys), set(sells)
    if shift:
        rng = random.Random(seed)
        k = rng.randrange(-15, 16) or 5
        seg_lo, seg_hi = idx[0], idx[-1]
        bset = {min(seg_hi, max(seg_lo, i + k)) for i in buys if seg_lo <= i <= seg_hi}
        sset = {min(seg_hi, max(seg_lo, i + k)) for i in sells if seg_lo <= i <= seg_hi}
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    ep_start, halts, halt_until, ended = START, 0, None, False
    days_invested = 0
    # state before the road: replay events before idx[0]
    pos = False
    for i in range(idx[0]):
        if i in bset:
            pos = True
        if i in sset:
            pos = False
    for posn, i in enumerate(idx):
        b = bars[i]
        if halt_until is not None and b["d"] >= halt_until:
            halt_until = None; ep_start = cash + shares * b["c"]
        if pos and shares == 0.0 and halt_until is None and not ended and cash > 0:
            bv = cash / (1 + STK_COST); cfee = bv * STK_COST
            shares = bv / b["c"]; cash -= bv + cfee; costs += cfee
            trades.append([b["d"], "BUY-CLOSE", round(b["c"], 4), round(bv, 2), round(cfee, 2)])
        eq = cash + shares * b["c"]
        if shares > 0:
            days_invested += 1
        curve.append([b["d"], round(eq, 4)])
        # events at this close
        if i in bset:
            pos = True
            if shares == 0.0 and halt_until is None and not ended and cash > 0:
                bv = cash / (1 + STK_COST); cfee = bv * STK_COST
                shares = bv / b["c"]; cash -= bv + cfee; costs += cfee
                trades.append([b["d"], "BUY-CLOSE", round(b["c"], 4), round(bv, 2), round(cfee, 2)])
                curve[-1] = [b["d"], round(cash + shares * b["c"], 4)]
        if i in sset and shares > 0:
            val = shares * b["c"]; cfee = val * STK_COST + STK_SELL_FEE
            cash += val - cfee; costs += cfee; shares = 0.0
            trades.append([b["d"], "SELL-CLOSE", round(b["c"], 4), round(val, 2), round(cfee, 2)])
            curve[-1] = [b["d"], round(cash, 4)]
            pos = False
        elif i in sset:
            pos = False
        if chassis and not ended and halt_until is None:
            eq_now = curve[-1][1]
            if eq_now <= 0.85 * ep_start:
                halts += 1
                if shares > 0:
                    val = shares * b["c"]; cfee = val * STK_COST + STK_SELL_FEE
                    cash += val - cfee; costs += cfee; shares = 0.0
                    trades.append([b["d"], "SELL-FLOOR", round(b["c"], 4), round(val, 2), round(cfee, 2)])
                    curve[-1] = [b["d"], round(cash, 4)]
                pos = False
                if halts == 1:
                    halt_until = date.fromordinal(date.fromisoformat(b["d"]).toordinal() + 90).isoformat()
                else:
                    ended = True
    if shares > 0:
        last = bars[idx[-1]]; val = shares * last["c"]
        cfee = val * STK_COST + STK_SELL_FEE
        cash += val - cfee; costs += cfee; shares = 0.0
        trades.append([last["d"], "SELL-END", round(last["c"], 4), round(val, 2), round(cfee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0 * days_invested / len(idx), 1) if idx else 0.0,
            "halts": halts, "equity_curve": curve}


def main():
    out = {"family": FAMILY, "form": FORM_NOTE,
           "costs": "stocks 0.10%/side + $0.01 sell fee, charged at the rule-named closes",
           "holdings_sweep": "NOT-APPLICABLE — calendar timer, no ranked selection",
           "coins": {"status": "NOT-APPLICABLE per spec: defined on exchange holidays and options-expiration days; a 24/7 market has neither"},
           "stocks": {}}
    spy = load_pxfull("SPY")
    invested, buys, sells, events = build_windows(spy)
    out["windows"] = {"buys": len(buys), "sells": len(sells),
                      "invested_day_share_pct": round(100.0 * sum(invested) / len(invested), 1)}
    print("windows:", out["windows"])
    roads = {}
    for name, (s, e) in ROADS.items():
        rec = {}
        for form, chassis in (("native", False), ("house_v9", True)):
            r = sts_sim(spy, buys, sells, s, e, chassis=chassis)
            rec[form] = {**r, "period_stats": period_stats(r["equity_curve"], "monthly")}
        bh = buy_hold(spy, s, e, STK_COST, STK_SELL_FEE)
        rec["benchmark_hold"] = {"name": "SPY buy-and-hold (same plumbing)",
                                 "final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                 "period_stats": period_stats(bh["equity_curve"], "monthly")}
        finals = []
        for seed in range(1, 21):
            pr = sts_sim(spy, buys, sells, s, e, chassis=False, shift=1, seed=seed)
            finals.append(pr["final"])
        rec["placebo_native"] = {"seed_finals": finals,
                                 "beaten_of_20": sum(1 for p in finals if rec["native"]["final"] > p),
                                 "design": "same windows shifted by a random day-offset within the road (20 seeds) — the spec's calendar placebo"}
        rec["champion_vm"] = CHAMP[name]; rec["spy_program_ref"] = SPYREF[name]
        roads[name] = rec
        print(f"SPY {name}: native ${rec['native']['final']} (DD {rec['native']['max_dd_pct']}%, inv {rec['native']['invested_pct']}%, orders {rec['native']['orders']}, placebos {rec['placebo_native']['beaten_of_20']}/20) | house ${rec['house_v9']['final']} (halts {rec['house_v9']['halts']}) | hold ${rec['benchmark_hold']['final']}")
    out["stocks"]["SPY"] = {"data_range": f"{spy[0]['d']} -> {spy[-1]['d']}", "roads": roads}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
