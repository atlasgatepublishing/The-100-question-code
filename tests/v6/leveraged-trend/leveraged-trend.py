#!/usr/bin/env python3
"""
LEVERAGED-ETF TREND FOLLOWING (Gayed, "Leverage for the Long Run") —
Terry's AI stock app. Simulation only.

THE RULE (as published, task spec): hold UPRO (3x S&P 500 ETF) only while
SPY trades above its 200-day moving average; when SPY is below, hold cash
(0% return). Check monthly at month-end (last trading day, at close);
trade at the next trading day's open.

Program format, identical to the champion engines:
  - $100 pot, fractional shares, long only.
  - Prices: Yahoo Finance chart API, dividend+split adjusted (adjclose;
    opens scaled by adjclose/close) — total-return basis, same method as
    etf-trend-sleeve.py / value-momentum-plainfloor.py.
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Protection: plain -15% floor ($85 on the $100 pot), checked on the
    daily close; close at/below floor -> liquidate at next open, run ends.
  - End of window: liquidate at the final close (program convention).
  - Signal: SPY adjusted close at month-end vs the 200-trading-day simple
    moving average of SPY adjusted closes (including the check day).
    Close strictly above SMA -> invested; at/below -> cash.
  - Initial state of every run: the state dictated by the most recent
    month-end check BEFORE the window's first trading day (a fresh pot
    starting that year would have read the same signal on Dec 31).

Windows:
  FULL      2017-01-01 -> 2026-11-20 (UPRO exists since 2009; data allows)
  CHAMPION  2019-01-02 -> 2026-11-20 (value+momentum's continuous window,
            for an apples-to-apples with its $544.47)
  VALIDATION 2023-01-01 -> 2026-11-20 (matches the champion's $288.05)
  FOLDS     fresh $100 pot each calendar year 2017..2026 vs SPY buy-hold
            net over the identical window.

Controls (random seeds do not apply — the rule is a single deterministic
binary switch on one instrument, there is no stock selection to randomize):
  - SPY-TREND: the identical trend rule holding unleveraged SPY instead of
    UPRO. Isolates what the 3x leverage adds on top of the timing rule.
  - UPRO BUY-HOLD: UPRO bought at the window's first open and held.
    Isolates what the trend rule saves vs raw 3x exposure.
  Both controls run as program pots (same costs, same plain floor).
  No-floor diagnostic runs of the strategy and of UPRO buy-hold are also
  recorded so the report can state honestly how deep the instrument's
  closes actually go when the floor is not there to stop the run.
"""
import json, os, urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "data")
os.makedirs(CACHE, exist_ok=True)

COST_RATE = 0.0010          # 0.10% per side
SELL_FEE = 0.01             # $0.01 per sell order
START_CASH = 100.0
FLOOR = 85.0                # plain -15% floor on the $100 pot
FETCH_START = "2015-01-01"  # >200 trading days before the 2017 window
FETCH_END = "2026-11-21"


# ------------------------------------------------------------------ data
def fetch(ticker):
    path = os.path.join(CACHE, f"{ticker}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path) as f:
            return json.load(f)
    p1 = int(datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp())
    p2 = int(datetime(2026, 11, 21, tzinfo=timezone.utc).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={p1}&period2={p2}&interval=1d&events=div,splits")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    with open(path, "w") as f:
        json.dump(data, f)
    return data


def load_series(ticker):
    """dict date -> (adj_open, adj_close), same construction as the
    program's ETF engines."""
    data = fetch(ticker)
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = None
    if "adjclose" in res["indicators"]:
        adj = res["indicators"]["adjclose"][0]["adjclose"]
    out = {}
    for i, t in enumerate(ts):
        d = datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d")
        c = q["close"][i]
        o = q["open"][i]
        if c is None or o is None:
            continue
        if adj is not None and adj[i]:
            ratio = adj[i] / c
            out[d] = (o * ratio, adj[i])
        else:
            out[d] = (o, c)
    return out


SERIES = {t: load_series(t) for t in ("SPY", "UPRO")}
CAL = sorted(SERIES["SPY"].keys())            # master calendar = SPY days
CAL_IDX = {d: i for i, d in enumerate(CAL)}
SPY_CLOSES = []
_last = None
for d in CAL:
    if d in SERIES["SPY"]:
        _last = SERIES["SPY"][d][1]
    SPY_CLOSES.append(_last)

# 200-day SMA of SPY adjusted closes, aligned to CAL (None until day 200)
SMA200 = []
for i in range(len(CAL)):
    if i >= 199:
        SMA200.append(sum(SPY_CLOSES[i - 199:i + 1]) / 200.0)
    else:
        SMA200.append(None)

MONTH_ENDS = set()
for i, d in enumerate(CAL):
    if i == len(CAL) - 1 or CAL[i + 1][:7] != d[:7]:
        MONTH_ENDS.add(d)


def close_on(ticker, date):
    s = SERIES[ticker]
    if date in s:
        return s[date][1]
    i = CAL_IDX[date]
    for j in range(i - 1, -1, -1):
        if CAL[j] in s:
            return s[CAL[j]][1]
    return None


def open_on(ticker, date):
    s = SERIES[ticker]
    if date in s:
        return s[date][0]
    return close_on(ticker, date)


def desired_invested(date):
    """Trend state from the check made on `date` (a month-end close)."""
    i = CAL_IDX[date]
    if SMA200[i] is None:
        return False
    return SPY_CLOSES[i] > SMA200[i]


def last_month_end_before(date):
    prev = None
    for d in CAL:
        if d >= date:
            break
        if d in MONTH_ENDS:
            prev = d
    return prev


# ------------------------------------------------------------------ engine
def run_pot(start, end, asset="UPRO", trend=True, floor_on=True,
            label=""):
    """One program pot. Returns a results dict including the daily curve."""
    days = [d for d in CAL if start <= d <= end]
    cash = START_CASH
    shares = 0.0
    holding = False
    total_costs = 0.0
    trades = []            # (date, side, value, cost)
    switches = []          # (date, to_invested) executed AFTER initial entry
    curve = []             # (date, close equity)
    days_in_cash = 0
    halted = None
    halt_info = None

    # initial state: most recent month-end check before the window
    if trend:
        me = last_month_end_before(days[0])
        want = desired_invested(me) if me else False
    else:
        want = True
    initial_state = want

    pending = None  # target state to execute at today's open
    if want:
        pending = True

    def buy_all(d):
        nonlocal cash, shares, holding, total_costs
        o = open_on(asset, d)
        sh = (cash / (1.0 + COST_RATE)) / o
        c = cash - sh * o
        total_costs += c
        trades.append((d, "BUY", round(sh * o, 2), round(c, 4)))
        cash = 0.0
        shares = sh
        holding = True

    def sell_all(d, at_open=True, tag="SELL"):
        nonlocal cash, shares, holding, total_costs
        px = open_on(asset, d) if at_open else close_on(asset, d)
        val = shares * px
        c = val * COST_RATE + SELL_FEE
        total_costs += c
        trades.append((d, tag, round(val, 2), round(c, 4)))
        cash = val - c
        shares = 0.0
        holding = False
        return cash

    for di, d in enumerate(days):
        # execute pending switch at today's open
        if pending is not None:
            if pending and not holding:
                buy_all(d)
                if di > 0:
                    switches.append((d, True))
            elif not pending and holding:
                sell_all(d)
                switches.append((d, False))
            pending = None
        # close equity
        v = cash + (shares * close_on(asset, d) if holding else 0.0)
        curve.append((d, v))
        if not holding:
            days_in_cash += 1
        # plain floor: close at/below floor -> liquidate at next open, end
        if floor_on and v <= FLOOR and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor": FLOOR}
            if holding:
                nd = days[di + 1]
                final = sell_all(nd, at_open=True, tag="SELL-HALT")
                halt_info["fill_date"] = nd
                halt_info["fill_value"] = round(final, 2)
            else:
                final = cash
                halt_info["fill_date"] = d
                halt_info["fill_value"] = round(final, 2)
            return finish(label, final, total_costs, trades, switches,
                          curve, days_in_cash, days, halted, halt_info,
                          initial_state)
        # month-end check (close): set pending switch for next open
        if trend and d in MONTH_ENDS:
            want = desired_invested(d)
            if want != holding:
                pending = want
    # end of window: liquidate at final close (program convention)
    if holding:
        final = sell_all(days[-1], at_open=False, tag="SELL-END")
    else:
        final = cash
    return finish(label, final, total_costs, trades, switches, curve,
                  days_in_cash, days, halted, halt_info, initial_state)


def finish(label, final, total_costs, trades, switches, curve,
           days_in_cash, days, halted, halt_info, initial_state):
    vals = [v for _, v in curve]
    peak, maxdd = -1.0, 0.0
    for v in vals:
        if v > peak:
            peak = v
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    worst_close = min(vals) if vals else START_CASH
    # calendar-month returns chained from the close curve
    month_last = {}
    for d, v in curve:
        month_last[d[:7]] = v
    months = sorted(month_last)
    mrets = []
    prev = START_CASH
    for m in months:
        mrets.append((m, month_last[m] / prev - 1.0))
        prev = month_last[m]
    worst_month = min(mrets, key=lambda x: x[1]) if mrets else (None, 0.0)
    # whipsaw legs: a position entered/exited and reversed within 62 days
    whipsaws = 0
    sw = [(datetime.strptime(d, "%Y-%m-%d").date(), s) for d, s in switches]
    for k in range(len(sw) - 1):
        if (sw[k + 1][0] - sw[k][0]).days <= 62:
            whipsaws += 1
    return {
        "label": label,
        "final": round(final, 2),
        "return_pct": round(final / START_CASH * 100 - 100, 2),
        "costs": round(total_costs, 2),
        "orders": len(trades),
        "trades": trades,
        "switches": len(switches),
        "switch_list": switches,
        "whipsaw_legs": whipsaws,
        "days": len(days),
        "days_in_cash": days_in_cash,
        "pct_time_in_cash": round(100.0 * days_in_cash / len(days), 1) if days else 0.0,
        "max_drawdown_pct": round(maxdd * 100, 2),
        "worst_close": round(worst_close, 2),
        "worst_month": {"month": worst_month[0],
                        "return_pct": round(worst_month[1] * 100, 2)},
        "halted": halted,
        "halt_info": halt_info,
        "initial_state_invested": initial_state,
        "curve": curve,
    }


def spy_net(start, end, start_cash=START_CASH):
    """SPY buy-hold net, program convention (spy_net in the champion
    engine): buy at first day's open, sell at last day's close."""
    days = [d for d in CAL if start <= d <= end]
    first, last = days[0], days[-1]
    o = open_on("SPY", first)
    sh = (start_cash / (1.0 + COST_RATE)) / o
    buy_cost = start_cash - sh * o
    val = sh * close_on("SPY", last)
    sell_cost = val * COST_RATE + SELL_FEE
    return round(val - sell_cost, 2), round(buy_cost + sell_cost, 2)


def slim(r):
    """Results-JSON view: everything except the daily curve."""
    out = {k: v for k, v in r.items() if k != "curve"}
    return out


# ------------------------------------------------------------------ runs
WINDOWS = {
    "full_2017_2026": ("2017-01-01", "2026-11-20"),
    "champion_2019_2026": ("2019-01-02", "2026-11-20"),
    "validation_2023_2026": ("2023-01-01", "2026-11-20"),
}

out = {
    "test": "Leveraged-ETF trend following (Gayed) — UPRO/SPY 200-day, "
            "monthly check, next-open execution",
    "pot": START_CASH, "floor": FLOOR,
    "costs": "0.10% per side + $0.01 per sell order",
    "data": {
        "source": "Yahoo Finance chart API, adjclose-adjusted (total return)",
        "spy_range": [CAL[0], CAL[-1]],
        "upro_range": [min(SERIES["UPRO"]), max(SERIES["UPRO"])],
    },
    "champion_reference": {"validation_vm": 288.05,
                           "continuous_vm_2019_2026": 544.47},
    "windows": {},
    "folds": [],
}

for name, (ws, we) in WINDOWS.items():
    strat = run_pot(ws, we, asset="UPRO", trend=True, floor_on=True,
                    label=f"UPRO-TREND {name}")
    strat_nf = run_pot(ws, we, asset="UPRO", trend=True, floor_on=False,
                       label=f"UPRO-TREND nofloor {name}")
    spy_tr = run_pot(ws, we, asset="SPY", trend=True, floor_on=True,
                     label=f"SPY-TREND {name}")
    upro_bh = run_pot(ws, we, asset="UPRO", trend=False, floor_on=True,
                      label=f"UPRO-BUYHOLD {name}")
    upro_bh_nf = run_pot(ws, we, asset="UPRO", trend=False, floor_on=False,
                         label=f"UPRO-BUYHOLD nofloor {name}")
    spy_final, spy_costs = spy_net(ws, we)
    out["windows"][name] = {
        "window": [ws, we],
        "strategy_upro_trend": slim(strat),
        "strategy_upro_trend_nofloor_diag": slim(strat_nf),
        "control_spy_trend": slim(spy_tr),
        "control_upro_buyhold": slim(upro_bh),
        "control_upro_buyhold_nofloor_diag": slim(upro_bh_nf),
        "spy_buyhold_net": {"final": spy_final, "costs": spy_costs},
    }
    print(f"[{name}] UPRO-trend ${strat['final']:,.2f} "
          f"(halted={strat['halted']}, worst close ${strat['worst_close']:,.2f}, "
          f"maxDD {strat['max_drawdown_pct']}%, switches {strat['switches']}, "
          f"cash {strat['pct_time_in_cash']}%) | SPY-trend "
          f"${spy_tr['final']:,.2f} | UPRO-BH ${upro_bh['final']:,.2f} "
          f"(halted={upro_bh['halted']}) | UPRO-BH nofloor "
          f"${upro_bh_nf['final']:,.2f} worst close "
          f"${upro_bh_nf['worst_close']:,.2f} | SPY ${spy_final:,.2f}",
          flush=True)

wins = 0
for y in range(2017, 2027):
    fs = f"{y}-01-01"
    fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
    r = run_pot(fs, fe, asset="UPRO", trend=True, floor_on=True,
                label=f"FOLD {y}")
    bh = run_pot(fs, fe, asset="UPRO", trend=False, floor_on=True,
                 label=f"FOLD {y} UPRO-BH")
    fspy, _ = spy_net(fs, fe)
    beat = r["final"] > fspy
    wins += 1 if beat else 0
    out["folds"].append({
        "year": y, "window": [fs, fe],
        "strategy_final": r["final"], "strategy_return_pct": r["return_pct"],
        "spy_net_final": fspy,
        "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
        "beat_spy": beat, "halted": r["halted"],
        "worst_close": r["worst_close"],
        "max_drawdown_pct": r["max_drawdown_pct"],
        "switches": r["switches"], "pct_time_in_cash": r["pct_time_in_cash"],
        "upro_buyhold_final": bh["final"], "upro_buyhold_halted": bh["halted"],
    })
    print(f"FOLD {y}: UPRO-trend ${r['final']:,.2f} ({r['return_pct']:+.2f}%) "
          f"vs SPY ${fspy:,.2f} beat={beat} halted={r['halted']} "
          f"worst close ${r['worst_close']:,.2f}", flush=True)
out["fold_record"] = f"{wins} wins, {len(out['folds']) - wins} losses vs SPY"

with open(os.path.join(HERE, "leveraged-trend-results.json"), "w") as f:
    json.dump(out, f, indent=1, default=str)
print("DONE — results written to leveraged-trend-results.json")
