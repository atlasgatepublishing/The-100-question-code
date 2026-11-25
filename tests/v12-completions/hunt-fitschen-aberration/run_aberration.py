import json, os, time, random, statistics, math
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
"""hunt-fitschen-aberration — CONSTRUCTED form frozen in SPEC-FROZEN.md
(the original Aberration rule/parameter is a sold product, never
published; every number carries the CONSTRUCTED label). Documented
framework: Bollinger-Band trend system, one rule for all markets.
Frozen construction: SMA(20) +/- 2.0 x population SD(20); entry long at
close above upper band; exit at close back below SMA(20) center line;
no other stop; long-only translation (short signals = no-trade). Daily,
all-in, decide at close, execute next open. Native = no floor; house =
v9 chassis. Coins: OC-range H/L proxy except BTC/ETH true OHLC."""
HERE = os.path.dirname(os.path.abspath(__file__))
FAMILY = "hunt-fitschen-aberration (Fitschen Aberration — CONSTRUCTED)"
FORM_NOTE = ("CONSTRUCTED forever (original paywalled by design): SMA20 "
             "+/- 2.0 SD20 band-break entry, center-line exit, long-only; "
             "daily, all-in; native no floor, house v9 chassis")

def signal_fn(bars):
    n = len(bars)
    closes = [b["c"] for b in bars]
    targets = [False] * n
    pos = False
    for i in range(n):
        if i >= 19:
            win = closes[i - 19:i + 1]
            sma = sum(win) / 20.0
            var = sum((x - sma) ** 2 for x in win) / 20.0
            upper = sma + 2.0 * math.sqrt(var)
            if not pos and closes[i] > upper:
                pos = True
            elif pos and closes[i] < sma:
                pos = False
        targets[i] = pos
    return targets

# ---- generic per-asset timer driver (FAMILY / signal_fn set by family code above)
import glob

def main():
    out = {"family": FAMILY, "form": FORM_NOTE,
           "costs": "stocks 0.10%/side + $0.01 sell fee; crypto 0.60%/side",
           "holdings_sweep": "NOT-APPLICABLE — single-asset timer, no ranked selection",
           "stocks": {}, "coins": {}}
    spy = load_pxfull("SPY")
    tgt = signal_fn(spy)
    roads = run_timer_roads(spy, tgt, ROADS, STK_COST, STK_SELL_FEE,
                            "SPY buy-and-hold (same plumbing)", freq="monthly")
    for name in ROADS:
        roads[name]["champion_vm"] = CHAMP[name]
        roads[name]["spy_program_ref"] = SPYREF[name]
    out["stocks"]["SPY"] = {"data_range": f"{spy[0]['d']} -> {spy[-1]['d']}",
                            "roads": roads}
    print("SPY done")
    for name, rec in roads.items():
        print(f"SPY {name}: native ${rec['native']['final']} (DD {rec['native']['max_dd_pct']}%, "
              f"inv {rec['native']['invested_pct']}%, orders {rec['native']['orders']}, "
              f"placebos {rec['placebo_native']['beaten_of_20']}/20) | house ${rec['house_v9']['final']} "
              f"(halts {rec['house_v9']['halts']}) | hold ${rec['benchmark_hold']['final']}")
    # per-name pooled native run, LONG window, each name vs its own buy-hold
    pooled = {}
    for p in sorted(glob.glob(os.path.join(PXDIR, "pxfull_*.json"))):
        tick = os.path.basename(p)[7:-5]
        if tick == "SPY":
            continue
        try:
            bars = load_pxfull(tick)
        except Exception:
            continue
        if len(bars) < 300:
            continue
        t2 = signal_fn(bars)
        rn = simulate(bars, t2, ROADS["LONG"][0], ROADS["LONG"][1], STK_COST, STK_SELL_FEE)
        bh = buy_hold(bars, ROADS["LONG"][0], ROADS["LONG"][1], STK_COST, STK_SELL_FEE)
        if rn is None or bh is None:
            continue
        pooled[tick] = {"native_final": rn["final"], "hold_final": bh["final"],
                        "beat_hold": rn["final"] > bh["final"],
                        "max_dd_pct": rn["max_dd_pct"], "orders": rn["orders"]}
    if pooled:
        nat = [v["native_final"] for v in pooled.values()]
        hold = [v["hold_final"] for v in pooled.values()]
        out["stocks"]["per_name_LONG_native"] = {
            "names": len(pooled), "beat_hold_count": sum(1 for v in pooled.values() if v["beat_hold"]),
            "median_native": round(statistics.median(nat), 2),
            "median_hold": round(statistics.median(hold), 2),
            "mean_native_secondary_average_only": round(statistics.mean(nat), 2),
            "mean_hold_secondary_average_only": round(statistics.mean(hold), 2),
            "per_name": pooled}
        print(f"per-name: {len(pooled)} names, beat hold {out['stocks']['per_name_LONG_native']['beat_hold_count']}, "
              f"median native ${out['stocks']['per_name_LONG_native']['median_native']} vs hold ${out['stocks']['per_name_LONG_native']['median_hold']}")
    per, closures = run_coins(signal_fn)
    out["coins"]["per_coin"] = per
    out["coins"]["closures"] = closures
    out["coins"]["summary"] = coin_summary(per)
    for sym in ("BTC", "ETH"):
        if sym in per:
            print(sym, json.dumps(per[sym]["windows"]))
    print("coin summary:", json.dumps(out["coins"]["summary"]))
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")

if __name__ == "__main__":
    main()
