#!/usr/bin/env python3
"""
PERMANENT PORTFOLIO (Harry Browne) — Terry's AI stock app. Simulation only.

The published static allocation, tested in the program's format:
  $100 pot split 25/25/25/25 across
    SPY  (stocks)
    TLT  (long-term Treasuries)
    GLD  (gold)
    SHY  (cash proxy — Browne's cash leg is T-bills; SHY is the program's
          tradable stand-in, stated here and in the report)
  Rebalance rule (as published): check the sleeves; if any sleeve has
  drifted outside the 15%-35% band, rebalance ALL sleeves back to 25%.
  Browne's rule is "check at least once a year." PROGRAM SIMPLIFICATION
  (documented): the band check happens once a year, on the first trading
  day of each calendar year, using the prior trading day's closing
  weights; any triggered rebalance executes at that day's open.

Program conventions, identical to the champion engine
(backtests/v4/value-momentum-plainfloor.py):
  - Prices: Yahoo Finance chart API, dividend/split-adjusted open & close
    (adjclose ratio applied to open), daily bars.
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Plain -15% floor at pot level: if the pot's closing value <= $85 on
    the $100 start, liquidate everything at the next open and stop.
  - End of window: liquidate at the final close (sell costs charged);
    the reported final is post-liquidation cash.
  - SPY benchmark: spy_net method from the champion engine (buy at first
    open net of buy cost, sell at final close net of sell cost).

Windows (chosen to match the champion's headline windows exactly):
  - Continuous: 2019-01-02 -> 2026-11-20   (champion V+M: $544.47,
    SPY net: $313.62)
  - Validation: 2023-01-01 -> 2026-11-20   (champion V+M: $288.05,
    SPY net: $187.77)
  - Yearly folds: fresh $100 pot each calendar year 2019-2026
    (2026 ends 2026-11-20), scored vs SPY net over the same window.

Controls instead of random-seed placebos: for a static allocation there
is no stock-picking to randomize, so the honest controls are other
static mixes run through identical machinery — 60/40 SPY/TLT (annual
rebalance to target) and 100% SPY. A never-rebalanced Permanent
Portfolio is also reported as a diagnostic.
"""
import calendar
import json
import os
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

SLEEVES = ["SPY", "TLT", "GLD", "SHY"]
TARGET = 0.25
BAND_LO, BAND_HI = 0.15, 0.35
START_CASH = 100.0
FLOOR0 = 85.0
BUY_COST = 0.001
SELL_COST = 0.001
SELL_FEE = 0.01

CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-01", "2026-11-20")


# ------------------------------------------------------------------ prices
def fetch_prices(ticker, p1="2018-01-01", p2="2026-11-21"):
    """Same fetch/parse method as the champion engine's get_prices."""
    path = os.path.join(DATA, f"px_{ticker}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            blob = f.read()
    else:
        t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d"))
        t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            blob = r.read()
        with open(path, "wb") as f:
            f.write(blob)
    j = json.loads(blob)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


class PriceBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        dates = set()
        for bl in bars_by_ticker.values():
            dates.update(b["d"] for b in bl)
        self.dates = sorted(dates)
        self._idx = {t: {b["d"]: b for b in bl}
                     for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self._idx[t].get(d)

    def close_on_or_before(self, t, d):
        bl = self.bars[t]
        best = None
        for b in bl:
            if b["d"] <= d:
                best = b["c"]
            else:
                break
        return best

    def open_on(self, t, d):
        b = self.bar(t, d)
        if b:
            return b["o"]
        # fall back to close on or before if the ticker has no bar that day
        return self.close_on_or_before(t, d)


# ------------------------------------------------------------------ engine
def run_alloc(pb, start, end, weights, band=None, annual_to_target=False,
              start_cash=START_CASH, floor=FLOOR0, label=""):
    """Static-allocation engine.
    weights: {ticker: target weight}. band=(lo,hi) -> annual band check
    (Permanent Portfolio). annual_to_target=True -> rebalance to target
    every year regardless of band (60/40 control). band=None and not
    annual_to_target -> never rebalance (diagnostic).
    """
    days = [d for d in pb.dates if start <= d <= end]
    cash = start_cash
    positions = {}   # ticker -> shares
    trades = []
    total_costs = 0.0
    curve = []
    rebalances = []

    def equity_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def equity_open(d):
        v = cash
        for t, sh in positions.items():
            o = pb.open_on(t, d)
            if o:
                v += sh * o
        return v

    def rebalance_to(d, targets, reason):
        nonlocal cash, total_costs
        eq = equity_open(d)
        # sells first
        for t in sorted(targets):
            o = pb.open_on(t, d)
            if not o:
                continue
            cur = positions.get(t, 0.0) * o
            tgt = targets[t] * eq
            if cur > tgt + 1e-9:
                sell_val = cur - tgt
                sh = sell_val / o
                c = sell_val * SELL_COST + SELL_FEE
                positions[t] -= sh
                if positions[t] <= 1e-12:
                    del positions[t]
                cash += sell_val - c
                total_costs += c
                trades.append((d, t, "SELL", round(sh, 6), o,
                               round(sell_val, 2), round(c, 4)))
        # then buys
        for t in sorted(targets):
            o = pb.open_on(t, d)
            if not o:
                continue
            cur = positions.get(t, 0.0) * o
            tgt = targets[t] * eq
            if tgt > cur + 1e-9:
                buy_val = min(tgt - cur, cash / (1.0 + BUY_COST))
                if buy_val <= 0:
                    continue
                sh = buy_val / o
                c = buy_val * BUY_COST
                positions[t] = positions.get(t, 0.0) + sh
                cash -= buy_val + c
                total_costs += c
                trades.append((d, t, "BUY", round(sh, 6), o,
                               round(buy_val, 2), round(c, 4)))
        rebalances.append({"date": d, "reason": reason,
                           "equity_open": round(eq, 2)})

    # initial allocation at first day's open
    first = days[0]
    rebalance_to(first, weights, "initial allocation")

    years_seen = {first[:4]}
    halted = None
    halt_info = None
    for di, d in enumerate(days):
        # annual check: first trading day of a new calendar year
        if d[:4] not in years_seen:
            years_seen.add(d[:4])
            prev = days[di - 1]
            eq_prev = equity_close(prev)
            if eq_prev > 0:
                ws = {}
                for t in weights:
                    c = pb.close_on_or_before(t, prev)
                    ws[t] = (positions.get(t, 0.0) * c / eq_prev) if c else 0.0
                ws["CASH"] = cash / eq_prev
                if annual_to_target:
                    rebalance_to(d, weights,
                                 f"annual rebalance to target (prev weights "
                                 f"{ {k: round(v,3) for k,v in ws.items()} })")
                elif band is not None:
                    lo, hi = band
                    drifted = {t: round(w, 4) for t, w in ws.items()
                               if t in weights and (w < lo or w > hi)}
                    if drifted:
                        rebalance_to(d, weights,
                                     f"band breach {drifted} "
                                     f"(prev weights "
                                     f"{ {k: round(v,3) for k,v in ws.items()} })")
        v = equity_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            nd = days[di + 1]
            for t in list(positions):
                o = pb.open_on(t, nd)
                if o:
                    val = positions[t] * o
                    c = val * SELL_COST + SELL_FEE
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", round(positions[t], 6),
                                   o, round(val, 2), round(c, 4)))
            positions = {}
            return {"label": label, "final": round(cash, 2),
                    "costs": round(total_costs, 2), "trades": trades,
                    "halted": halted, "halt_info": halt_info, "curve": curve,
                    "rebalances": rebalances}
    # end of window: liquidate at final close
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * SELL_COST + SELL_FEE
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", round(positions[t], 6), c_,
                           round(val, 2), round(cst, 4)))
    return {"label": label, "final": round(cash, 2),
            "costs": round(total_costs, 2), "trades": trades,
            "halted": None, "halt_info": None, "curve": curve,
            "rebalances": rebalances}


def spy_net(pb, start, end, start_cash=START_CASH):
    """Champion engine's benchmark method."""
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * SELL_COST + SELL_FEE
    return round(val - sell_cost, 2), round(buy_cost + sell_cost, 2)


def curve_stats(r, start_cash=START_CASH):
    curve = r["curve"]
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    min_close, min_close_d = 1e18, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
        if v < min_close:
            min_close, min_close_d = v, d
    yrs = (len(curve) / 252.0)
    cagr = (r["final"] / start_cash) ** (1.0 / yrs) - 1.0 if yrs > 0 else 0.0
    return {"final": r["final"],
            "return_pct": round(r["final"] / start_cash * 100 - 100, 2),
            "cagr_pct": round(cagr * 100, 2),
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "worst_close": round(min_close, 2),
            "worst_close_date": min_close_d,
            "min_distance_to_floor": round(min_close - FLOOR0, 2),
            "costs": r["costs"], "orders": len(r["trades"]),
            "halted": r["halted"],
            "rebalances": len(r.get("rebalances", []))}


def main():
    bars = {t: fetch_prices(t) for t in SLEEVES}
    pb = PriceBook(bars)
    out = {"strategy": "Permanent Portfolio (Browne): 25/25/25/25 "
                       "SPY/TLT/GLD/SHY, 15-35% band, annual check",
           "cash_proxy": "SHY (T-bill ETF) stands in for Browne's cash leg",
           "costs": "0.10%/side + $0.01/sell order (program schedule)",
           "floor": "plain -15% ($85 on $100), daily close check",
           "windows": {}}

    pp_weights = {t: TARGET for t in SLEEVES}
    mix6040 = {"SPY": 0.60, "TLT": 0.40}

    for wname, (ws, we) in [("continuous", CONT), ("validation", VAL)]:
        pp = run_alloc(pb, ws, we, pp_weights, band=(BAND_LO, BAND_HI),
                       label=f"PP {wname}")
        pp_nr = run_alloc(pb, ws, we, pp_weights, band=None,
                          label=f"PP no-rebalance {wname}")
        m6040 = run_alloc(pb, ws, we, mix6040, annual_to_target=True,
                          label=f"60/40 {wname}")
        spy, spy_costs = spy_net(pb, ws, we)
        block = {"window": [ws, we],
                 "permanent_portfolio": curve_stats(pp),
                 "pp_rebalance_events": pp["rebalances"],
                 "pp_no_rebalance_diagnostic": curve_stats(pp_nr),
                 "control_60_40": curve_stats(m6040),
                 "control_spy_100": {"final": spy,
                                     "return_pct": round(spy / 100 * 100 - 100, 2),
                                     "costs": spy_costs}}
        out["windows"][wname] = block
        print(f"== {wname} {ws}->{we}")
        print(f"  PP        final=${pp['final']:,.2f} "
              f"({block['permanent_portfolio']['return_pct']:+.2f}%) "
              f"maxDD={block['permanent_portfolio']['max_drawdown_pct']}% "
              f"worstClose=${block['permanent_portfolio']['worst_close']:,.2f} "
              f"({block['permanent_portfolio']['worst_close_date']}) "
              f"costs=${pp['costs']} orders={len(pp['trades'])} "
              f"rebalances={len(pp['rebalances'])} halted={pp['halted']}")
        print(f"  PP no-reb final=${pp_nr['final']:,.2f} "
              f"maxDD={block['pp_no_rebalance_diagnostic']['max_drawdown_pct']}%")
        print(f"  60/40     final=${m6040['final']:,.2f} "
              f"maxDD={block['control_60_40']['max_drawdown_pct']}% "
              f"costs=${m6040['costs']}")
        print(f"  SPY 100%  final=${spy:,.2f} costs=${spy_costs}")

    # yearly folds: fresh $100 each calendar year
    folds = []
    for y in range(2019, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_alloc(pb, fs, fe, pp_weights, band=(BAND_LO, BAND_HI),
                       label=f"PP FOLD {y}")
        fspy, _ = spy_net(pb, fs, fe)
        fst = curve_stats(fr)
        row = {"year": y, "window": [fs, fe], "pp_final": fst["final"],
               "pp_return_pct": fst["return_pct"],
               "spy_final": fspy,
               "spy_return_pct": round(fspy / 100 * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "pp_max_drawdown_pct": fst["max_drawdown_pct"],
               "pp_worst_close": fst["worst_close"],
               "pp_min_distance_to_floor": fst["min_distance_to_floor"],
               "halted": fr["halted"], "costs": fr["costs"]}
        folds.append(row)
        print(f"FOLD {y}: PP ${fr['final']:,.2f} ({row['pp_return_pct']:+.2f}%) "
              f"vs SPY ${fspy:,.2f} ({row['spy_return_pct']:+.2f}%) "
              f"beat={row['beat_spy']} maxDD={row['pp_max_drawdown_pct']}% "
              f"worstClose=${row['pp_worst_close']:,.2f} halted={row['halted']}",
              flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"

    # sleeve buy-and-hold diagnostics over the continuous window
    sleeves_bh = {}
    for t in SLEEVES:
        r = run_alloc(pb, CONT[0], CONT[1], {t: 1.0}, band=None,
                      label=f"{t} alone")
        sleeves_bh[t] = curve_stats(r)
        print(f"SLEEVE {t} alone {CONT[0]}->{CONT[1]}: ${r['final']:,.2f} "
              f"maxDD={sleeves_bh[t]['max_drawdown_pct']}%")
    out["sleeve_buy_hold_continuous"] = sleeves_bh

    with open(os.path.join(HERE, "permanent-portfolio-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
