#!/usr/bin/env python3
"""Crypto Wing 1 Group C — CONSTRUCTED forms on crypto. Frozen in
CONSTRUCTION-SPEC.md. Form A: v12 candlestick construction per coin.
Form B: GEM dual momentum translated (BTC / PIT alt basket / cash).
Costs 0.60%/side. $100 pots. Simulation only."""
import bisect, csv, json, os, random, sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4D = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-basket-pit-data")
V4RES = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-basket-pit-results.json")
OHLC = os.path.join(HERE, "data_ohlc")
SHYCSV = os.path.expanduser("~/workspace/stock-app/backtests/v3/tournament2-data/SHY.csv")
COST = 0.006; START = 100.0; GRACE = 30
WINDOWS = {"FULL": ("2017-01-01", "2026-11-20"), "DESIGN": ("2017-01-01", "2022-12-31"),
           "VALIDATION": ("2023-01-01", "2026-11-20")}
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}
STABLE_SYMS = {"USDT", "USDC", "DAI", "BUSD", "UST", "TUSD", "USDE", "USD1"}

def d2o(s): return date.fromisoformat(s)
def o2d(o): return o.isoformat()

# ------------------------------------------------------------------ data --
def load_registry_oc():
    """cid -> {symbol, source, rows:[{d,o,c}]} from v4 cache (read-only) + HYPE."""
    reg = {}
    v4 = json.load(open(V4RES))["registry"]
    for cid_s, info in v4.items():
        cid = int(cid_s)
        if info["source"] == "excluded": continue
        kind, name = info["source"].split(":", 1)
        fn = {"yahoo": f"y_{name}.json", "binance": f"b_{name}.json", "kraken": f"k_{name}.json"}[kind]
        rows = json.load(open(os.path.join(V4D, fn)))
        if cid in CREDIBLE_START: rows = [r for r in rows if r["d"] >= CREDIBLE_START[cid]]
        reg[cid] = {"symbol": info["symbol"], "source": info["source"], "rows": rows}
    hp = os.path.join(OHLC, "32196.json")
    if os.path.exists(hp):
        rows = [{"d": r["d"], "o": r["o"], "c": r["c"]} for r in json.load(open(hp))]
        reg[32196] = {"symbol": "HYPE", "source": "hyperliquid:HYPE", "rows": rows}
    return reg

def load_ohlc(cid):
    p = os.path.join(OHLC, f"{cid}.json")
    if not os.path.exists(p): return None
    return json.load(open(p))

def period_stats(monthly):
    """monthly: [(yyyymm, end_equity)] starting from START before first month.
    Returns period-by-period record at monthly tempo."""
    rets = []; prev = START; peak = START; peak_i = -1; since_high = 0; max_gap = 0
    highs_gap = []
    last_high_idx = -1
    vals = [START] + [v for _, v in monthly]
    for i, (_, v) in enumerate(monthly):
        rets.append(v / prev - 1.0 if prev > 0 else 0.0); prev = v
    for i, v in enumerate(vals):
        if v >= max(vals[:i + 1]) and v > START or (i == 0):
            if last_high_idx >= 0: highs_gap.append(i - last_high_idx)
            last_high_idx = i
    if last_high_idx < len(vals) - 1: highs_gap.append(len(vals) - 1 - last_high_idx)
    streak = mx = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0; mx = max(mx, streak)
    srt = sorted(rets); n = len(rets)
    med = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    return {"n_periods": n,
            "pct_positive": round(100.0 * sum(1 for r in rets if r > 0) / n, 1) if n else None,
            "median_pct": round(med * 100, 2) if n else None,
            "best_pct": round(max(rets) * 100, 2) if n else None,
            "worst_pct": round(min(rets) * 100, 2) if n else None,
            "longest_losing_streak": mx,
            "longest_between_new_highs_months": max(highs_gap) if highs_gap else 0,
            "mean_pct_secondary": round(sum(rets) / n * 100, 2) if n else None}

def monthly_curve(daily):
    """daily: [(date, equity)] -> [(yyyymm, last equity of month)]"""
    out = {}
    for d, v in daily: out[d[:7]] = v
    return sorted(out.items())

def max_dd(curve_vals):
    peak = -1.0; mdd = 0.0
    for v in curve_vals:
        peak = max(peak, v); mdd = max(mdd, (peak - v) / peak if peak > 0 else 0)
    return round(mdd * 100, 2)

# ============================================================ FORM A ======
def candle_prepare(bars):
    n = len(bars)
    ema = [None] * n; e = bars[0]["c"]; a = 2.0 / 11.0
    for i in range(n):
        e = bars[i]["c"] if i == 0 else a * bars[i]["c"] + (1 - a) * e
        ema[i] = e
    bodies = [abs(b["c"] - b["o"]) for b in bars]
    meanbody = [None] * n
    for i in range(n):
        if i >= 10: meanbody[i] = sum(bodies[i - 10:i]) / 10.0
    pats = []
    def dt(s): return s >= 0 and bars[s]["c"] < ema[s]
    for t in range(n):
        b = bars[t]; body = bodies[t]; rng = b["h"] - b["l"]
        if rng > 0 and (min(b["o"], b["c"]) - b["l"]) >= 2 * max(body, 1e-9) \
           and (b["h"] - max(b["o"], b["c"])) <= 0.1 * rng and dt(t - 1):
            pats.append((t, t, b["h"], b["l"]))
        if t >= 1:
            p = bars[t - 1]
            if p["c"] < p["o"] and b["c"] > b["o"] and b["o"] <= p["c"] and b["c"] >= p["o"] and dt(t - 2):
                pats.append((t - 1, t, max(p["h"], b["h"]), min(p["l"], b["l"])))
            if p["c"] < p["o"] and b["c"] > b["o"] and b["o"] < p["c"] \
               and b["c"] > (p["o"] + p["c"]) / 2 and b["c"] < p["o"] and dt(t - 2):
                pats.append((t - 1, t, max(p["h"], b["h"]), min(p["l"], b["l"])))
        if t >= 2:
            x, m = bars[t - 2], bars[t - 1]
            hi3 = max(x["h"], m["h"], b["h"]); lo3 = min(x["l"], m["l"], b["l"])
            if x["c"] > x["o"] and m["c"] > m["o"] and b["c"] > b["o"] \
               and x["c"] < m["c"] < b["c"] and x["o"] <= m["o"] <= x["c"] \
               and m["o"] <= b["o"] <= m["c"] and dt(t - 3):
                pats.append((t - 2, t, hi3, lo3))
            if x["c"] < x["o"] and meanbody[t - 2] is not None and bodies[t - 2] > meanbody[t - 2] \
               and min(m["o"], m["c"]) >= x["c"] and max(m["o"], m["c"]) <= x["o"] \
               and b["c"] > b["o"] and b["c"] > x["o"] and dt(t - 3):
                pats.append((t - 2, t, hi3, lo3))
            if x["c"] < x["o"] and m["c"] > m["o"] and m["o"] <= x["c"] and m["c"] >= x["o"] \
               and b["c"] > b["o"] and b["c"] > m["c"] and dt(t - 3):
                pats.append((t - 2, t, hi3, lo3))
            if x["c"] < x["o"] and meanbody[t - 2] is not None and bodies[t - 2] > meanbody[t - 2] \
               and meanbody[t - 1] is not None and bodies[t - 1] < meanbody[t - 1] \
               and max(m["o"], m["c"]) <= x["c"] \
               and b["c"] > b["o"] and b["c"] > (x["o"] + x["c"]) / 2 and dt(t - 3):
                pats.append((t - 2, t, hi3, lo3))
    return pats

def candle_signals(bars, pats, start, end):
    by = {b["d"]: i for i, b in enumerate(bars)}
    out = {}; seen = set()
    for (f, e, hi, lo) in pats:
        if bars[f]["d"] < start or bars[e]["d"] > end: continue
        for k in range(e + 1, min(e + 1 + 3, len(bars))):
            if bars[k]["d"] > end: break
            if bars[k]["c"] > hi:
                if k + 1 < len(bars):
                    nd = bars[k + 1]["d"]
                    if nd <= end and (nd, round(lo, 6)) not in seen:
                        seen.add((nd, round(lo, 6)))
                        out.setdefault(nd, []).append((lo, hi + (hi - lo)))
                break
    return out

def candle_sim(bars, entries, start, end, cal, v9=False):
    """Single-asset run on the BTC calendar (cal) for curve marking; trades
    only on the coin's own bar days. entries: {date: [(stop, target)]}."""
    pending.clear()
    by = {b["d"]: b for b in bars}
    dates = [b["d"] for b in bars]
    cash = START; pos = None; costs = 0.0; buys = 0; closed = 0; wins = 0
    curve = []; halts = 0; floor = 0.85 * START; sit_until = None; ended = False
    last_close = None; last_bar_d = None
    def mark(d):
        if pos is None: return cash
        if d in by: return cash + pos["shares"] * by[d]["c"]
        if last_close is not None and (d2o(d) - d2o(last_bar_d)).days <= GRACE:
            return cash + pos["shares"] * last_close
        return cash
    for d in [x for x in cal if start <= x <= end]:
        b = by.get(d)
        if b is not None: last_close, last_bar_d = b["c"], d
        # pending floor liquidation at today's open
        if v9 and sit_until == d and pos is not None and b is not None:
            val = pos["shares"] * b["o"]; fee = val * COST
            cash += val - fee; costs += fee; closed += 1
            if b["o"] > pos["entry"]: wins += 1
            pos = None
        if not ended and b is not None:
            # entries at open
            if pos is None and d in entries and b["o"] > 0 and not (v9 and sit_until and d < sit_until):
                eq_open = cash
                for (stop, target) in sorted(entries[d]):
                    val = 0.10 * eq_open
                    if cash < val * (1 + COST) or val < 1.0: continue
                    fee = val * COST; cash -= val + fee; costs += fee; buys += 1
                    pos = {"shares": val / b["o"], "entry": b["o"], "stop": stop,
                           "target": target, "held": 0}
                    break
            # exits
            if pos is not None:
                pos["held"] += 1
                fill = None
                if b["o"] <= pos["stop"]: fill = b["o"]
                elif b["o"] >= pos["target"]: fill = b["o"]
                elif b["l"] <= pos["stop"] and b["h"] >= pos["target"]: fill = pos["stop"]
                elif b["l"] <= pos["stop"]: fill = pos["stop"]
                elif b["h"] >= pos["target"]: fill = pos["target"]
                elif pos["held"] >= 10: fill = b["c"]
                if fill is not None:
                    val = pos["shares"] * fill; fee = val * COST
                    cash += val - fee; costs += fee; closed += 1
                    if fill > pos["entry"]: wins += 1
                    pos = None
        eq = mark(d)
        curve.append((d, round(eq, 4)))
        # v9 floor check at close
        if v9 and not ended and sit_until is None and eq <= floor and (pos is not None or halts == 0 and eq < START):
            if pos is not None:
                # liquidate at next bar's open: mark sit_until as next coin bar date
                nxt = None
                i = bisect.bisect_right(dates, d)
                if i < len(dates) and dates[i] <= end: nxt = dates[i]
                if nxt is None:  # liquidate at today's close
                    val = pos["shares"] * b["c"] if b else 0.0; fee = val * COST
                    cash += val - fee; costs += fee; closed += 1; pos = None
                    halts += 1
                    if halts >= 2: ended = True
                    else: floor = 0.85 * cash; sit_until = o2d(d2o(d) + timedelta(days=90))
                else:
                    sit_until = nxt  # liquidation executes at that open (handled above)
                    halts += 1
                    # after liquidation the sit runs 90d from nxt; encode via halt marker below
                    # store pending restart info in a side channel:
                    pending.append((nxt, halts))
            else:
                halts += 1
                if halts >= 2: ended = True
                else: floor = 0.85 * cash; sit_until = o2d(d2o(d) + timedelta(days=90))
        # resolve pending halt bookkeeping once liquidation day passed
        if v9 and pending and d >= pending[0][0]:
            _, h = pending.pop(0)
            if h >= 2: ended = True
            else: floor = 0.85 * cash; sit_until = o2d(d2o(d) + timedelta(days=90))
        if v9 and sit_until and not pending and d >= sit_until and halts < 2:
            pass  # sit simply expires by date comparison in entry gate
    # end of window liquidation
    if pos is not None:
        if last_bar_d and (d2o(end) - d2o(last_bar_d)).days <= GRACE:
            val = pos["shares"] * last_close; fee = val * COST
            cash += val - fee; costs += fee; closed += 1
            if last_close > pos["entry"]: wins += 1
        else:
            closed += 1  # written to zero under death rule
        pos = None
        if curve: curve[-1] = (curve[-1][0], round(cash, 4))
    return {"final": round(cash, 2), "max_dd_pct": max_dd([v for _, v in curve]),
            "costs": round(costs, 2), "buys": buys, "closed_trades": closed,
            "win_rate_pct": round(100 * wins / closed, 1) if closed else None,
            "halts": halts, "curve_daily": curve}
pending = []

def buyhold_oc(rows, start, end):
    idx = [r for r in rows if start <= r["d"] <= end]
    if not idx: return None
    px0 = idx[0]["o"] if idx[0]["o"] > 0 else idx[0]["c"]
    if px0 <= 0: return None
    sh = START / (px0 * (1 + COST))
    last = idx[-1]
    if (d2o(end) - d2o(last["d"])).days > GRACE: return 0.0
    val = sh * last["c"]
    return round(val - val * COST, 2)

def run_candle(reg, cal):
    out = {"form": "A_candlestick_constructed_per_coin", "coins": {}}
    btc_hold = {w: buyhold_oc(reg[1]["rows"], s, e) for w, (s, e) in WINDOWS.items()}
    out["btc_buyhold"] = btc_hold
    for cid, info in sorted(reg.items()):
        bars = load_ohlc(cid)
        if bars is None:
            out["coins"][str(cid)] = {"symbol": info["symbol"], "ohlc": "unavailable"}
            continue
        if cid in CREDIBLE_START: bars = [b for b in bars if b["d"] >= CREDIBLE_START[cid]]
        pats = candle_prepare(bars) if bars else []
        by = {b["d"]: b for b in bars}
        coin = {"symbol": info["symbol"], "source": info["source"], "windows": {}}
        for w, (s, e) in WINDOWS.items():
            nbars = sum(1 for b in bars if s <= b["d"] <= e)
            if nbars < 60:
                coin["windows"][w] = {"status": "insufficient-history", "bars_in_window": nbars}
                continue
            entries = candle_signals(bars, pats, s, e)
            rn = candle_sim(bars, entries, s, e, cal, v9=False)
            rv = candle_sim(bars, entries, s, e, cal, v9=True)
            twins = []
            if rn["buys"] > 0:
                draw_days = [b["d"] for b in bars if s <= b["d"] <= o2d(d2o(e) - timedelta(days=11))]
                dates = [b["d"] for b in bars]
                for seed in range(20):
                    rng = random.Random(12000 + seed)
                    pent = {}
                    for _ in range(rn["buys"]):
                        d0 = rng.choice(draw_days); bb = by[d0]
                        i = bisect.bisect_right(dates, d0)
                        if i >= len(dates) or dates[i] > e: continue
                        pent.setdefault(dates[i], []).append((bb["l"], bb["h"] + (bb["h"] - bb["l"])))
                    twins.append(candle_sim(bars, pent, s, e, cal, v9=False)["final"])
            mc = monthly_curve(rn["curve_daily"])
            res = {"coin_buyhold": buyhold_oc(reg[cid]["rows"], s, e),
                   "native": {k: rn[k] for k in ("final", "max_dd_pct", "costs", "buys", "closed_trades", "win_rate_pct")},
                   "v9": {k: rv[k] for k in ("final", "max_dd_pct", "costs", "buys", "closed_trades", "win_rate_pct", "halts")},
                   "placebo_finals": twins,
                   "placebo_beaten": sum(1 for t in twins if rn["final"] > t) if twins else None,
                   "monthly_curve_native": mc,
                   "period_stats_monthly_native": period_stats(mc),
                   "beats_btc_full_and_val": None}
            coin["windows"][w] = res
        out["coins"][str(cid)] = coin
        print("candle", cid, info["symbol"], "done", flush=True)
    return out

# ============================================================ FORM B ======
def run_gem(reg, cal):
    snaps = json.load(open(os.path.join(V4D, "snapshots.json")))
    snap_keys = sorted(snaps.keys())
    ci = {d: i for i, d in enumerate(cal)}
    def universe(d):
        k = bisect.bisect_right(snap_keys, d) - 1
        return [c["cmc_id"] for c in snaps[snap_keys[k]]["top20"]] if k >= 0 else []
    closes, opens = {}, {}
    for cid, info in reg.items():
        closes[cid] = {r["d"]: r["c"] for r in info["rows"]}
        opens[cid] = {r["d"]: r["o"] for r in info["rows"]}
    # precomputed per-coin arrays over cal: fwd value w/ death rule; last-bar close
    ffarr, lbarr = {}, {}
    for cid, cm in closes.items():
        ffv, lbv = [], []
        last = None; lastd = None
        for d in cal:
            if d in cm: last, lastd = cm[d], d
            if last is None: ffv.append(None)
            elif (d2o(d) - d2o(lastd)).days <= GRACE: ffv.append(last)
            else: ffv.append(0.0)
            lbv.append(last)
        ffarr[cid], lbarr[cid] = ffv, lbv
    def ret365_close(cid, t):
        i = ci.get(t)
        if i is None: return None
        j = bisect.bisect_right(cal, o2d(d2o(t) - timedelta(days=365))) - 1
        if j < 0: return None
        if (d2o(t) - d2o(cal[j])).days > 7 + 365 and False: return None
        # leg dates: close at last bar <= t and <= t-365, each within 7d of its target
        def leg(idx, target):
            if idx < 0: return None
            # walk back to a real bar
            cm = closes[cid]; k = idx
            while k >= 0 and cal[k] not in cm: k -= 1
            if k < 0 or (d2o(target) - d2o(cal[k])).days > 7: return None
            return cm[cal[k]]
        a = leg(j, o2d(d2o(t) - timedelta(days=365))); b = leg(i, t)
        if a is None or b is None or a <= 0: return None
        return b / a - 1.0
    shy = {}
    with open(SHYCSV) as f:
        for r in csv.DictReader(f): shy[r["date"]] = float(r["close"])
    shy_dates = sorted(shy)
    def shy_ret(t):
        def leg(target):
            i = bisect.bisect_right(shy_dates, target) - 1
            if i < 0: return None
            return shy[shy_dates[i]] if (d2o(target) - d2o(shy_dates[i])).days <= 10 else None
        a, b = leg(o2d(d2o(t) - timedelta(days=365))), leg(t)
        if a is None or b is None or a <= 0: return 0.0
        return b / a - 1.0
    def month_members(ym):
        return [c for c in universe(ym + "-01")
                if c != 1 and c in reg and reg[c]["symbol"] not in STABLE_SYMS
                and reg[c]["symbol"] != "WBTC"]
    # basket index chained over cal
    idx_val = {}; level = 100.0; prev_ym = None; prev_sums = None
    for i, d in enumerate(cal):
        if d < "2016-01-01": continue
        ym = d[:7]; mem = month_members(ym)
        s = sum(ffarr[m][i] for m in mem if ffarr[m][i] is not None)
        if prev_ym is not None:
            if ym != prev_ym:
                base = sum(ffarr[m][i - 1] for m in mem if ffarr[m][i - 1] is not None)
                if base > 0: level *= s / base
            elif prev_sums and prev_sums > 0:
                level *= s / prev_sums
        idx_val[d] = level; prev_sums = s; prev_ym = ym
    def basket_ret365(t):
        i = ci.get(t)
        if i is None: return None
        j = bisect.bisect_right(cal, o2d(d2o(t) - timedelta(days=365))) - 1
        if j < 0 or cal[j] not in idx_val or t not in idx_val: return None
        a = idx_val[cal[j]]
        return idx_val[t] / a - 1.0 if a > 0 else None
    def month_ends(start, end):
        out = []
        for d in cal:
            if start <= d <= end:
                nxt = cal[ci[d] + 1] if ci[d] + 1 < len(cal) else None
                if nxt is None or nxt[:7] != d[:7]: out.append(d)
        return out
    def gem_sim(start, end, v9=False, seed=None, force=None):
        rng = random.Random(seed) if seed is not None else None
        cash = START; held = "cash"; shares = {}
        costs = 0.0; curve = []; halts = 0; floor = 0.85 * START
        sit_until = None; ended = False; decisions = []
        me_set = set(month_ends(start, end))
        def open_px(cid, d):
            o = opens.get(cid, {}).get(d)
            if o: return o
            v = ffarr[cid][ci[d]] if cid in ffarr else None
            return v
        def value(d):
            v = cash; i = ci[d]
            for cid, sh in shares.items():
                fv = ffarr[cid][i]
                if fv: v += sh * fv
            return v
        def set_target(target, d):
            nonlocal cash, shares, costs, held
            i = ci[d]
            eq = cash + sum(sh * (open_px(cid, d) or 0.0) for cid, sh in shares.items())
            want = {}
            if target == "btc":
                px = open_px(1, d)
                if px: want = {1: eq / px}
            elif target == "basket":
                mem = [m for m in month_members(d[:7]) if open_px(m, d)]
                if mem:
                    each = eq / len(mem)
                    want = {m: each / open_px(m, d) for m in mem}
            # sells first
            for cid in list(shares):
                px = open_px(cid, d) or 0.0
                cur = shares[cid]; tgt = want.get(cid, 0.0)
                if cur > tgt:
                    val = (cur - tgt) * px; fee = val * COST
                    cash += val - fee; costs += fee
                    if tgt > 0: shares[cid] = tgt
                    else: del shares[cid]
            for cid, tgt in want.items():
                px = open_px(cid, d)
                cur = shares.get(cid, 0.0)
                if tgt > cur:
                    val = (tgt - cur) * px; fee = val * COST
                    spend = val + fee
                    if spend > cash:  # scale to available cash
                        val = cash / (1 + COST); fee = val * COST; spend = val + fee
                        tgt = cur + val / px
                    cash -= spend; costs += fee; shares[cid] = tgt
            held = target if want or target == "cash" else "cash"
            if not shares: held = "cash"
        days = [d for d in cal if start <= d <= end]
        pending_exec = None
        for d in days:
            if pending_exec and pending_exec[1] == d and not ended:
                set_target(pending_exec[0], d); pending_exec = None
            eq = value(d); curve.append((d, round(eq, 4)))
            if v9 and not ended and sit_until is None and eq <= floor and shares:
                halts += 1
                i = ci[d] + 1
                if i < len(cal) and cal[i] <= end: set_target("cash", cal[i])
                else: set_target("cash", d)
                if halts >= 2: ended = True
                else: floor = 0.85 * cash; sit_until = o2d(d2o(d) + timedelta(days=90))
            if d in me_set and not ended:
                if v9 and sit_until and d < sit_until: continue
                if force: pick = force
                elif rng: pick = rng.choice(["btc", "basket", "cash"])
                else:
                    rb = ret365_close(1, d); rk = basket_ret365(d); rs = shy_ret(d)
                    if rb is None or rb <= rs: pick = "cash"
                    elif rk is None: pick = "btc"
                    else: pick = "btc" if rb >= rk else "basket"
                decisions.append((d, pick))
                i = ci[d] + 1
                if i < len(cal) and cal[i] <= end:
                    if pick == held and pick != "basket": pass
                    else: pending_exec = (pick, cal[i])
        if shares:
            set_target("cash", end)
            if curve: curve[-1] = (curve[-1][0], round(cash, 4))
        mc = monthly_curve(curve)
        return {"final": round(curve[-1][1], 2) if curve else START,
                "max_dd_pct": max_dd([v for _, v in curve]), "costs": round(costs, 2),
                "halts": halts, "decisions": decisions, "curve_daily": curve,
                "monthly_curve": mc, "period_stats_monthly": period_stats(mc)}
    out = {"form": "B_gem_dual_momentum_translated", "windows": {}}
    for w, (s, e) in WINDOWS.items():
        rn = gem_sim(s, e, v9=False); rv = gem_sim(s, e, v9=True)
        ab = gem_sim(s, e, force="basket")
        twins = [gem_sim(s, e, seed=31000 + k)["final"] for k in range(20)]
        res = {"btc_buyhold": buyhold_oc(reg[1]["rows"], s, e),
               "native": {k: rn[k] for k in ("final", "max_dd_pct", "costs", "halts")},
               "native_decisions": rn["decisions"],
               "v9": {k: rv[k] for k in ("final", "max_dd_pct", "costs", "halts")},
               "always_basket": {k: ab[k] for k in ("final", "max_dd_pct", "costs")},
               "placebo_finals": twins,
               "placebo_beaten": sum(1 for t in twins if rn["final"] > t),
               "monthly_curve_native": rn["monthly_curve"],
               "period_stats_monthly_native": rn["period_stats_monthly"],
               "curve_daily_native": rn["curve_daily"]}
        out["windows"][w] = res
        print("gem", w, res["native"], "btc", res["btc_buyhold"], flush=True)
    return out

def main():
    part = sys.argv[1] if len(sys.argv) > 1 else "all"
    reg = load_registry_oc()
    cal = [r["d"] for r in reg[1]["rows"]]
    result = {"cost_rate_per_side": COST, "windows": WINDOWS}
    if part in ("all", "candle"):
        result["formA"] = run_candle(reg, cal)
        with open(os.path.join(HERE, "results_candle.json"), "w") as f: json.dump(result["formA"], f, indent=1)
    if part in ("all", "gem"):
        result["formB"] = run_gem(reg, cal)
        with open(os.path.join(HERE, "results_gem.json"), "w") as f: json.dump(result["formB"], f, indent=1)
    with open(os.path.join(HERE, "results.json"), "w") as f: json.dump(result, f, indent=1)
    print("wrote results")

if __name__ == "__main__":
    main()
