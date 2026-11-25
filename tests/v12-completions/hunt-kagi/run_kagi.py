#!/usr/bin/env python3
"""
KAGI — v12 FINAL DEEP-HUNT wing, family hunt-kagi. SIMULATION ONLY.
Ledger disposition: HUNT-FOUND (deep-hunt-nonus).

Frozen spec (SPEC-FROZEN.md, hunter 2026-11-22; source: Nison, Beyond
Candlesticks, 1994 / StockCharts ChartSchool):
  Kagi line on daily closes, reversal amount R = 3% (primary) and R = 5%
  (secondary) — the two documented settings, both frozen, no others.
  Buy on yang (line turns thick: rising line exceeds prior shoulder),
  sell on yin (falling line drops below prior waist).
  Entry/exit AT the close on which the thickness changes (spec mechanised
  literally). Sizing CONSTRUCTED (program standard): all-in, $100 pot.
  Native: no floor, drawdown printed. House: v9 protections
  (floor $85; ladder -> $100 at $125 close, -> $125 at $150 close;
  breach liquidates at next open, halt permanent).
Costs: stocks 0.10%/side + $0.01 sell fee. Coins 0.60%/side (stated rate,
  inside the program's measured retail range 0.40-0.80%/side).
Stocks: SPY + the program 30-name pond individually (GOOG file = GOOGL line),
  roads LONG/DECADE/CONT/VAL, SPY buy-hold beside every number.
Coins: PIT universe (97 coins incl. dead) per coin, full honest history,
  BTC buy-hold beside every number; a coin whose series ends before
  2025-06-01 with a position still open is written to ZERO (dead -> ZERO).
Placebos: 20-seed circular shifts of the in-window yang/yin state series.
Confirmation: any cell beating its bar (champion road figure for stocks,
  BTC hold for coins) is re-run on split halves + alternate windows.
Data READ-ONLY: v7 pxfull_* caches (stocks); v4 crypto-basket-pit registry
  + cached bars (coins).
"""
import json, os, random, statistics, sys, time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
CCACHE = os.path.join(V4, "crypto-basket-pit-data")
START = 100.0
STOCK_COST = 0.001; SELL_FEE = 0.01
COIN_COST = 0.006
REVERSALS = (0.03, 0.05)
ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
POND = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM", "JNJ", "PG",
        "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T", "DIS", "NFLX",
        "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA", "KO", "PEP", "WFC"]
FILEMAP = {"GOOGL": "GOOG"}
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}
DEAD_CUTOFF = "2025-06-01"

# ------------------------------------------------------------------ kagi ----
def kagi_yang(closes, R):
    """yang[i] = True if the Kagi line is thick (yang) after close i.
    Line extends on new extremes in its direction; reverses when price moves
    >= R (fraction) against the current tip. Rising line turns yang when it
    exceeds the prior shoulder; falling line turns yin below the prior waist."""
    n = len(closes)
    yang = [False] * n
    if n == 0:
        return yang
    direction = 0            # +1 up, -1 down, 0 not yet established
    tip = closes[0]          # extreme of current leg
    leg_start_ref = closes[0]
    prev_shoulder = None     # last completed peak before current up-leg
    prev_waist = None        # last completed trough before current down-leg
    is_yang = False
    for i, c in enumerate(closes):
        if direction == 0:
            if c >= leg_start_ref * (1 + R):
                direction = 1; tip = c
            elif c <= leg_start_ref * (1 - R):
                direction = -1; tip = c
        elif direction == 1:
            if c > tip:
                tip = c
            elif c <= tip * (1 - R):
                prev_shoulder = tip          # peak completed = shoulder
                direction = -1; tip = c
        else:
            if c < tip:
                tip = c
            elif c >= tip * (1 + R):
                prev_waist = tip             # trough completed = waist
                direction = 1; tip = c
        if direction == 1 and prev_shoulder is not None and c > prev_shoulder:
            is_yang = True
        elif direction == -1 and prev_waist is not None and c < prev_waist:
            is_yang = False
        yang[i] = is_yang
    return yang

# ---------------------------------------------------------------- engine ----
def run_engine(bars, yang, cost, sell_fee, house, dead_zero=False):
    """bars: list of {d,o,c}; yang aligned. Trades at the close where the
    state changes (frozen spec). House floor breach liquidates next open."""
    cash, units = START, 0.0
    floor = 85.0; halted = False
    trades = 0; costs = 0.0; held = 0
    curve = []; dates = []
    pending_liq = False
    n = len(bars)
    for i in range(n):
        o, c = bars[i]["o"], bars[i]["c"]
        if pending_liq and not halted:
            if units > 0:
                v = units * o; fee = v * cost + sell_fee; costs += fee
                cash = v - fee; units = 0.0; trades += 1
            halted = True; pending_liq = False
        if not halted:
            want = yang[i]
            if want and units == 0 and cash > 0:
                units = cash * (1 - cost) / c; costs += cash * cost; cash = 0.0; trades += 1
            elif not want and units > 0:
                v = units * c; fee = v * cost + sell_fee; costs += fee
                cash = v - fee; units = 0.0; trades += 1
        eq = cash + units * c
        if units > 0: held += 1
        curve.append(round(eq, 4)); dates.append(bars[i]["d"])
        if house and not halted:
            if eq >= 150.0 and floor < 125.0: floor = 125.0
            elif eq >= 125.0 and floor < 100.0: floor = 100.0
            if eq <= floor: pending_liq = True
    if dead_zero and units > 0:
        # dead coin: open position written to ZERO at series end
        curve[-1] = round(cash, 4)
        final = cash
    else:
        final = cash + units * bars[-1]["c"] if n else START
    peak, maxdd = START, 0.0
    for eq in curve:
        peak = max(peak, eq); maxdd = min(maxdd, eq / peak - 1.0)
    return {"final": round(final, 2), "maxdd_pct": round(maxdd * 100, 1),
            "trades": trades, "costs": round(costs, 2),
            "exposure_pct": round(100.0 * held / max(n, 1), 1), "halted": halted,
            "curve": curve, "dates": dates}

def buy_hold(bars, cost, sell_fee):
    if len(bars) < 2: return None
    units = START * (1 - cost) / bars[0]["o"]
    curve = [round(units * b["c"], 4) for b in bars]
    peak, maxdd = START, 0.0
    for eq in curve:
        peak = max(peak, eq); maxdd = min(maxdd, eq / peak - 1.0)
    return {"final": round(units * bars[-1]["c"], 2), "maxdd_pct": round(maxdd * 100, 1),
            "curve": curve}

def period_stats(curve, dates, months=1):
    """Distribution of calendar-month period returns from an equity curve."""
    pts = {}
    for d, v in zip(dates, curve):
        pts[d[:7]] = v  # last equity of each month
    keys = sorted(pts)
    rets = []; ends = []; prev = START
    for k in keys:
        v = pts[k]
        rets.append(v / prev - 1.0 if prev > 0 else 0.0)
        ends.append(v); prev = v
    if not rets: return None
    longest_loss = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        longest_loss = max(longest_loss, cur)
    peak = START; since = 0; longest_between = 0
    for e in ends:
        if e > peak: peak = e; since = 0
        else:
            since += 1; longest_between = max(longest_between, since)
    return {"periods": len(rets),
            "pct_profitable": round(100.0 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 1), "worst_pct": round(min(rets) * 100, 1),
            "longest_losing_run": longest_loss,
            "longest_between_new_highs": longest_between,
            "average_pct_secondary": round(statistics.mean(rets) * 100, 2)}

def placebos(bars, yang, cost, sell_fee, seed_base):
    finals = []
    n = len(bars)
    if n < 30: return finals
    rng = random.Random(seed_base)
    for _ in range(20):
        shift = rng.randrange(1, n)
        shifted = yang[shift:] + yang[:shift]
        finals.append(run_engine(bars, shifted, cost, sell_fee, False)["final"])
    return finals

def pct_rank(vals, x):
    return round(100.0 * sum(1 for v in vals if v < x) / len(vals), 0) if vals else None

# ---------------------------------------------------------------- stocks ----
def load_stock_bars(sym):
    fn = FILEMAP.get(sym, sym)
    path = os.path.join(PXDIR, f"pxfull_{fn}.json")
    if not os.path.exists(path): return None
    j = json.loads(open(path, "rb").read())
    res = j["chart"]["result"][0]; ts = res["timestamp"]; q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if None in (o, c): continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": o * r, "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

def window_slice(bars, yang, start, end):
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    return [bars[i] for i in idx], [yang[i] for i in idx]

def stock_part(out):
    symbols = ["SPY"] + POND
    spy_hold = {}
    all_bars = {}
    for sym in symbols:
        bars = load_stock_bars(sym)
        if bars: all_bars[sym] = bars
    for road, (s, e) in ROADS.items():
        wb, _ = window_slice(all_bars["SPY"], [False] * len(all_bars["SPY"]), s, e)
        spy_hold[road] = buy_hold(wb, STOCK_COST, SELL_FEE)
    out["spy_buy_hold"] = {r: {"final": v["final"], "maxdd_pct": v["maxdd_pct"]} for r, v in spy_hold.items()}
    out["stocks"] = {}
    for sym in symbols:
        bars = all_bars.get(sym)
        if not bars:
            out["stocks"][sym] = {"closure": "NO-CACHE-FILE"}; continue
        entry = {"first": bars[0]["d"], "last": bars[-1]["d"], "bars": len(bars), "R": {}}
        for R in REVERSALS:
            yang = kagi_yang([b["c"] for b in bars], R)
            rentry = {}
            for road, (s, e) in ROADS.items():
                wb, wy = window_slice(bars, yang, s, e)
                if len(wb) < 30:
                    rentry[road] = {"closure": "INSUFFICIENT-BARS"}; continue
                nat = run_engine(wb, wy, STOCK_COST, SELL_FEE, False)
                hou = run_engine(wb, wy, STOCK_COST, SELL_FEE, True)
                hold = buy_hold(wb, STOCK_COST, SELL_FEE)
                cell = {
                    "native": {k: nat[k] for k in ("final", "maxdd_pct", "trades", "costs", "exposure_pct", "halted")},
                    "v9_house": {k: hou[k] for k in ("final", "maxdd_pct", "trades", "costs", "exposure_pct", "halted")},
                    "own_hold": {"final": hold["final"], "maxdd_pct": hold["maxdd_pct"]},
                    "spy_hold_same_road": out["spy_buy_hold"][road],
                    "native_curve": nat["curve"], "house_curve": hou["curve"],
                    "curve_dates": nat["dates"],
                    "period_stats_monthly_native": period_stats(nat["curve"], nat["dates"]),
                    "period_stats_monthly_house": period_stats(hou["curve"], hou["dates"]),
                }
                if sym == "SPY" or road == "LONG":
                    tw = placebos(wb, wy, STOCK_COST, SELL_FEE, 777)
                    cell["placebo_median"] = round(statistics.median(tw), 2) if tw else None
                    cell["placebo_pct_rank_native"] = pct_rank(tw, nat["final"])
                    cell["placebo_beats"] = f"{sum(1 for v in tw if nat['final'] > v)}/20" if tw else None
                # confirmation: native beats champion road figure
                if nat["final"] > CHAMPION[road]:
                    mid = len(wb) // 2
                    h1 = run_engine(wb[:mid], wy[:mid], STOCK_COST, SELL_FEE, False)
                    h2 = run_engine(wb[mid:], wy[mid:], STOCK_COST, SELL_FEE, False)
                    cell["confirmation_split_half"] = {"half1": h1["final"], "half2": h2["final"]}
                rentry[road] = cell
            entry["R"][f"{int(R*100)}pct"] = rentry
        out["stocks"][sym] = entry
        print("stock", sym, "done", flush=True)

# ----------------------------------------------------------------- coins ----
def load_registry():
    with open(os.path.join(V4, "crypto-basket-pit-results.json")) as f:
        reg = json.load(f)["registry"]
    out = {}
    for cid_s, v in reg.items():
        cid = int(cid_s); rows = []
        if v["bars"] > 0:
            src = v["source"]; path = None
            if src.startswith("yahoo:"): path = os.path.join(CCACHE, f"y_{src[6:]}.json")
            elif src.startswith("binance:"): path = os.path.join(CCACHE, f"b_{src[8:]}.json")
            elif src.startswith("kraken:"): path = os.path.join(CCACHE, f"k_{src[7:]}.json")
            if path and os.path.exists(path):
                with open(path) as f: rows = json.load(f)
            if cid in CREDIBLE_START:
                rows = [r for r in rows if r["d"] >= CREDIBLE_START[cid]]
            rows = [r for r in rows if r.get("o", 0) > 0 and r.get("c", 0) > 0]
        out[cid] = {**v, "rows": rows}
    return out

def coin_part(out):
    reg = load_registry()
    btc_rows = reg[1]["rows"]
    out["coins"] = {}; out["coin_closures"] = []
    btc_cache = {}
    def btc_hold_for(first_d, last_d):
        key = (first_d, last_d)
        if key not in btc_cache:
            sub = [r for r in btc_rows if first_d <= r["d"] <= last_d]
            btc_cache[key] = buy_hold(sub, COIN_COST, 0.0) if len(sub) >= 2 else None
        return btc_cache[key]
    for cid in sorted(reg):
        v = reg[cid]; sym = v["symbol"]; rows = v["rows"]
        if not rows:
            out["coin_closures"].append({"cmc_id": cid, "symbol": sym, "closure": "NO-FREE-SERIES",
                                         "reason": v.get("reason")})
            continue
        if len(rows) < 100:
            out["coin_closures"].append({"cmc_id": cid, "symbol": sym, "closure": "INSUFFICIENT-HISTORY",
                                         "reason": f"only {len(rows)} bars", "first": rows[0]["d"], "last": rows[-1]["d"]})
            continue
        dead = rows[-1]["d"] < DEAD_CUTOFF
        closes = [r["c"] for r in rows]
        coin = {"cmc_id": cid, "symbol": sym, "source": v["source"], "first": rows[0]["d"],
                "last": rows[-1]["d"], "bars": len(rows), "dead_series_ends_early": dead, "R": {}}
        bh = btc_hold_for(rows[0]["d"], rows[-1]["d"])
        hold = buy_hold(rows, COIN_COST, 0.0)
        if dead and hold:
            # coin hold under dead->ZERO: a holder's position is written to zero
            hold = {**hold, "final_dead_zero": 0.0}
        for R in REVERSALS:
            yang = kagi_yang(closes, R)
            nat = run_engine(rows, yang, COIN_COST, 0.0, False, dead_zero=dead)
            hou = run_engine(rows, yang, COIN_COST, 0.0, True, dead_zero=dead)
            tw = placebos(rows, yang, COIN_COST, 0.0, 4242 + cid)
            cell = {
                "native": {k: nat[k] for k in ("final", "maxdd_pct", "trades", "costs", "exposure_pct", "halted")},
                "v9_house": {k: hou[k] for k in ("final", "maxdd_pct", "trades", "costs", "exposure_pct", "halted")},
                "coin_hold": {"final": hold["final"], "maxdd_pct": hold["maxdd_pct"]} if hold else None,
                "btc_hold_same_window": {"final": bh["final"], "maxdd_pct": bh["maxdd_pct"]} if bh else None,
                "placebo_median": round(statistics.median(tw), 2) if tw else None,
                "placebo_pct_rank_native": pct_rank(tw, nat["final"]),
                "placebo_beats": f"{sum(1 for x in tw if nat['final'] > x)}/20" if tw else None,
                "native_curve": nat["curve"], "house_curve": hou["curve"], "curve_dates": nat["dates"],
                "period_stats_monthly_native": period_stats(nat["curve"], nat["dates"]),
                "period_stats_monthly_house": period_stats(hou["curve"], hou["dates"]),
            }
            if bh and nat["final"] > bh["final"]:
                mid = len(rows) // 2
                h1 = run_engine(rows[:mid], yang[:mid], COIN_COST, 0.0, False, dead_zero=False)
                h2 = run_engine(rows[mid:], yang[mid:], COIN_COST, 0.0, False, dead_zero=dead)
                bh1 = buy_hold([r for r in btc_rows if rows[0]["d"] <= r["d"] <= rows[mid-1]["d"]], COIN_COST, 0.0)
                bh2 = buy_hold([r for r in btc_rows if rows[mid]["d"] <= r["d"] <= rows[-1]["d"]], COIN_COST, 0.0)
                cell["confirmation_split_half"] = {
                    "half1_strategy": h1["final"], "half1_btc_hold": bh1["final"] if bh1 else None,
                    "half2_strategy": h2["final"], "half2_btc_hold": bh2["final"] if bh2 else None,
                    "both_halves_beat_btc": bool(bh1 and bh2 and h1["final"] > bh1["final"] and h2["final"] > bh2["final"])}
            coin["R"][f"{int(R*100)}pct"] = cell
        out["coins"][sym] = coin
        print("coin", sym, "done", flush=True)

def main():
    out = {"family": "hunt-kagi", "ledger_disposition": "HUNT-FOUND (deep-hunt-nonus)",
           "source": "Nison, Beyond Candlesticks (1994); StockCharts ChartSchool",
           "reversals_run": ["3pct (primary)", "5pct (secondary)"],
           "stock_costs": "0.10%/side + $0.01 sell fee", "coin_cost_per_side": COIN_COST,
           "coin_cost_note": "0.60%/side, inside program measured retail range 0.40-0.80%/side",
           "execution": "at the close on which yang/yin state changes (frozen spec); house floor breach liquidates next open",
           "champion_reference": CHAMPION}
    stock_part(out)
    coin_part(out)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f)
    print("WROTE results.json")

if __name__ == "__main__":
    main()
