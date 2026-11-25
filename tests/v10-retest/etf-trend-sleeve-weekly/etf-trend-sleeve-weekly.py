#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — etf-trend-sleeve-weekly
The WEEKLY variant of the multi-asset ETF trend sleeve (v3, etf-trend-sleeve.py).

STRATEGY (unchanged from the original published form):
  Universe: SPY, QQQ, TLT, IEF, GLD, DBC, UUP (Yahoo daily bars, dividend+split
  adjusted; opens scaled by adjclose/close — same basis as the original).
  Trend score per asset = signs of trailing 3-mo (63d), 6-mo (126d), 12-mo (252d)
  returns on adjusted closes. Hold only assets with >=2 of 3 signals positive.
  Weights proportional to 1 / trailing-20-day realized vol (pstdev of daily
  returns), capped at 40% per asset (excess redistributed; remainder is cash).
  No-trade band: an existing position is adjusted only if its target weight
  moved >20% relative; entries and exits (signal flips) always trade.
  Costs: 0.10% of trade value per side + $0.01 per sell order. Long only,
  fractional shares. $100 start.

THIS SCRIPT DOES TWO THINGS:
  1) INTEGRITY — re-runs the ORIGINAL engine form (weekly evaluation at the
     last trading day of each ISO week close, trades at next open, Terry's
     ladder floor) on the original windows A / B-design / B-validation and
     compares against the published finals ($189.75 / $148.75 / $127.14).
  2) THE CADENCE SWEEP — DECADE 2016-11-21 -> 2026-11-20 at all 7 cadences
     under the v10 SPEC's uniform cadence definition: signal evaluation,
     selection and trading happen ONLY on cadence dates (daily = every trading
     day; weekly = first trading day of each week; biweekly = first trading
     day of every second week; monthly = first trading day of each month;
     quarterly = first trading day of each calendar quarter; semi-annual =
     first trading day of each half-year; annual = first trading day of each
     year). Signals are computed from adjusted closes through the PRIOR
     trading day (point-in-time) and trades execute at the cadence date's
     open. v9 protections: plain -15% floor from the episode's starting
     balance, checked at every close; on halt, liquidate at next open, sit in
     cash 90 calendar days, restart at the next regular cadence date under an
     episode-2 floor of -15% from the restart balance; second halt ends run.
  Placebos (20 seeds per cell): at each cadence date, count k = number of
  assets passing the trend filter; the twin holds a uniformly random k-subset
  of the 7-asset universe, weighted by the SAME capped inverse-vol scheme on
  those assets' own vols, with the same band, costs and v9 floor. This tests
  whether the trend signal itself adds anything over random selection of the
  same breadth on the same universe.

DATA: read-only shared cache ~/workspace/stock-app/backtests/v3/data_etf/
(Yahoo chart JSON fetched by the original v3 run, 2007-01-01 -> 2026-11-20).
Nothing is written outside this folder.
"""
import json, math, os, random, statistics
from datetime import datetime, timedelta

ASSETS = ["SPY", "QQQ", "TLT", "IEF", "GLD", "DBC", "UUP"]
HERE = os.path.dirname(os.path.abspath(__file__))
SRC_CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v3/data_etf")
COST_RATE = 0.0010
SELL_FEE = 0.01
START_CASH = 100.0
DEC_START, DEC_END = "2016-11-21", "2026-11-20"

# ---------------------------------------------------------------- data layer
def _load_raw(ticker):
    with open(os.path.join(SRC_CACHE, f"{ticker}.json")) as f:
        data = json.load(f)
    res = data["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = None
    if "adjclose" in res["indicators"]:
        adj = res["indicators"]["adjclose"][0]["adjclose"]
    out = {}
    for i, t in enumerate(ts):
        d = datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        c, o = q["close"][i], q["open"][i]
        if c is None or o is None:
            continue
        if adj is not None and adj[i]:
            ratio = adj[i] / c
            out[d] = (o * ratio, adj[i])
        else:
            out[d] = (o, c)
    return out

RAW = {t: _load_raw(t) for t in ASSETS}
CAL = sorted(RAW["SPY"].keys())              # master calendar = SPY trading days
CIDX = {d: i for i, d in enumerate(CAL)}
N = len(CAL)

# forward-filled adjusted close and open_on arrays, identical semantics to the
# original engine's close_on()/open_on()
CLOSE = {}   # ticker -> list over CAL (None before first bar)
OPENP = {}
for t in ASSETS:
    s = RAW[t]
    closes, opens = [], []
    last = None
    for d in CAL:
        if d in s:
            last = s[d][1]
            closes.append(last)
            opens.append(s[d][0])
        else:
            closes.append(last)
            opens.append(last)   # open_on falls back to close_on
    CLOSE[t] = closes
    OPENP[t] = opens

# precomputed trend signals + 20d vol per asset per calendar index
# (values at index i use closes up to and including CAL[i], exactly like the
# original closes_window/trend_and_vol on the master calendar)
NPOS = {}    # ticker -> list of int or None
VOL = {}
for t in ASSETS:
    cl = CLOSE[t]
    npos = [None] * N
    vol = [None] * N
    for i in range(N):
        if i < 252 or cl[i] is None or cl[i - 252] is None:
            continue
        last = cl[i]
        cnt = 0
        for lag in (63, 126, 252):
            r = last / cl[i - lag] - 1.0
            if r > 0:
                cnt += 1
        rets = [cl[j] / cl[j - 1] - 1.0 for j in range(i - 19, i + 1)]
        npos[i] = cnt
        vol[i] = statistics.pstdev(rets)
    NPOS[t] = npos
    VOL[t] = vol

def capped_inv_vol_weights(vols):
    inv = {t: 1.0 / v for t, v in vols.items() if v and v > 0}
    if not inv:
        return {}
    weights, remaining, budget = {}, dict(inv), 1.0
    while remaining:
        tot = sum(remaining.values())
        over = [t for t in remaining if budget * remaining[t] / tot > 0.40]
        if not over:
            for t in remaining:
                weights[t] = budget * remaining[t] / tot
            break
        for t in over:
            weights[t] = 0.40
            budget -= 0.40
            del remaining[t]
        if budget <= 0:
            break
    return weights

def targets_at(sig_i, placebo_rng=None):
    """Target weights from signals at calendar index sig_i.
    Real: assets with >=2 positive trend signs. Placebo: random subset of the
    same size k, same capped inv-vol weighting on the chosen assets' vols."""
    vols, passing = {}, []
    for t in ASSETS:
        if NPOS[t][sig_i] is not None and NPOS[t][sig_i] >= 2 and VOL[t][sig_i]:
            passing.append(t)
            vols[t] = VOL[t][sig_i]
    if placebo_rng is None:
        return capped_inv_vol_weights(vols)
    if not passing:
        return {}
    chosen = placebo_rng.sample(ASSETS, len(passing))
    return capped_inv_vol_weights({t: VOL[t][sig_i] for t in chosen
                                     if VOL[t][sig_i]})

# ---------------------------------------------------------------- execution
def execute(cash, shares, trade_set, targets, i):
    """Execute at CAL[i] open: sells first, then buys scaled to cash.
    Returns (cash, orders, costs, trades). Mirrors the original engine."""
    orders, costs, trades = 0, 0.0, []
    eq_open = cash + sum(shares[t] * OPENP[t][i] for t in ASSETS if shares[t] > 0)
    for t in sorted(trade_set):
        tgt_val = targets.get(t, 0.0) * eq_open
        cur_val = shares[t] * OPENP[t][i]
        diff = cur_val - tgt_val
        if diff > 0.01 and shares[t] > 0:
            sell_val = min(diff, cur_val)
            cost = sell_val * COST_RATE + SELL_FEE
            cash += sell_val - cost
            shares[t] -= sell_val / OPENP[t][i]
            if shares[t] < 1e-9:
                shares[t] = 0.0
            orders += 1
            costs += cost
            trades.append((CAL[i], "SELL", t, round(sell_val, 2)))
    buy_list = []
    for t in sorted(trade_set):
        tgt_val = targets.get(t, 0.0) * eq_open
        diff = tgt_val - shares[t] * OPENP[t][i]
        if diff > 0.01:
            buy_list.append((t, diff))
    tot_buy = sum(v for _, v in buy_list)
    if tot_buy > 0:
        scale = min(1.0, cash / (tot_buy * (1 + COST_RATE)))
        for t, diff in buy_list:
            buy_val = diff * scale
            if buy_val < 0.01:
                continue
            cost = buy_val * COST_RATE
            cash -= buy_val + cost
            shares[t] += buy_val / OPENP[t][i]
            orders += 1
            costs += cost
            trades.append((CAL[i], "BUY", t, round(buy_val, 2)))
    return cash, orders, costs, trades

def trade_set_for(cash, shares, targets, i):
    eq_c = cash + sum(shares[t] * CLOSE[t][i] for t in ASSETS if shares[t] > 0)
    ts = set()
    for t in ASSETS:
        cur_w = (shares[t] * CLOSE[t][i] / eq_c) if eq_c > 0 else 0.0
        tgt_w = targets.get(t, 0.0)
        held = shares[t] > 0
        if held and tgt_w == 0.0:
            ts.add(t)
        elif not held and tgt_w > 0.0:
            ts.add(t)
        elif held and tgt_w > 0.0 and abs(tgt_w - cur_w) / tgt_w > 0.20:
            ts.add(t)
    return ts

def equity(cash, shares, i, price):
    return cash + sum(shares[t] * price[t][i] for t in ASSETS if shares[t] > 0)

# ------------------------------------------------------- original-form engine
def simulate_original(start, end, start_cash=START_CASH, floor0=85.0,
                      ladder=((125.0, 100.0), (150.0, 125.0))):
    """Faithful port of v3/etf-trend-sleeve.py simulate(): weekly eval at the
    last trading day of each ISO week (close), trades at next open, ladder."""
    days = [d for d in CAL if start <= d <= end]
    cash, shares = start_cash, {t: 0.0 for t in ASSETS}
    floor, orders, total_costs, curve = floor0, 0, 0.0, []
    pending, halted, liq_next = None, None, False
    by_week = {}
    for d in days:
        dt = datetime.strptime(d, "%Y-%m-%d")
        by_week.setdefault(dt.isocalendar()[:2], []).append(d)
    eval_days = {max(ds) for ds in by_week.values()}
    for di, d in enumerate(days):
        i = CIDX[d]
        if liq_next or pending is not None:
            if liq_next:
                ts, tg = {t for t in ASSETS if shares[t] > 0}, {}
            else:
                ts, tg = pending
            cash, o, c, _ = execute(cash, shares, ts, tg, i)
            orders += o; total_costs += c
            pending = None
            if liq_next:
                halted = d
                liq_next = False
                curve.append((d, equity(cash, shares, i, CLOSE)))
                break
        eq_close = equity(cash, shares, i, CLOSE)
        curve.append((d, eq_close))
        for trigger, new_floor in sorted(ladder, reverse=True):
            if eq_close >= trigger:
                floor = max(floor, new_floor)
                break
        if eq_close <= floor:
            if di + 1 < len(days):
                liq_next = True
                continue
            halted = d
            break
        if d in eval_days and di + 1 < len(days):
            targets = targets_at(i)
            ts = trade_set_for(cash, shares, targets, i)
            if ts:
                pending = (ts, targets)
    return {"final": curve[-1][1] if curve else start_cash, "curve": curve,
            "orders": orders, "costs": total_costs, "halted": halted,
            "days": days, "start_cash": start_cash}

# ------------------------------------------------------------- cadence dates
def cadence_dates(start, end, cadence):
    days = [d for d in CAL if start <= d <= end]
    if cadence == "daily":
        return set(days)
    groups, order = {}, []
    for d in days:
        dt = datetime.strptime(d, "%Y-%m-%d")
        if cadence == "weekly":
            key = dt.isocalendar()[:2]
        elif cadence == "biweekly":
            key = dt.isocalendar()[:2]
        elif cadence == "monthly":
            key = (dt.year, dt.month)
        elif cadence == "quarterly":
            key = (dt.year, (dt.month - 1) // 3)
        elif cadence == "semiannual":
            key = (dt.year, (dt.month - 1) // 6)
        elif cadence == "annual":
            key = (dt.year,)
        else:
            raise ValueError(cadence)
        if key not in groups:
            groups[key] = d
            order.append(key)
    if cadence == "biweekly":
        return {groups[k] for j, k in enumerate(order) if j % 2 == 0}
    return set(groups.values())

# ------------------------------------------------------------- sweep engine
def simulate_sweep(start, end, cadence, placebo_seed=None):
    """Uniform-cadence run under v9 protections (see module docstring)."""
    days = [d for d in CAL if start <= d <= end]
    cad = cadence_dates(start, end, cadence)
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cash, shares = START_CASH, {t: 0.0 for t in ASSETS}
    episode, floor = 1, 0.85 * START_CASH
    orders, total_costs = 0, 0.0
    curve, halts, restarts = [], [], []
    state = "active"           # active | sitting | dead
    restart_on_or_after = None
    liq_next = False
    for di, d in enumerate(days):
        i = CIDX[d]
        # --- pending liquidation at today's open ---
        if liq_next:
            ts = {t for t in ASSETS if shares[t] > 0}
            cash, o, c, _ = execute(cash, shares, ts, {}, i)
            orders += o; total_costs += c
            liq_next = False
            halts[-1]["liquidation_date"] = d
            if episode == 1:
                state = "sitting"
                restart_on_or_after = (datetime.strptime(d, "%Y-%m-%d")
                                       + timedelta(days=90)).strftime("%Y-%m-%d")
            else:
                state = "dead"
            curve.append((d, cash))
            continue
        # --- restart at the first cadence date on/after the 90-day sit ---
        if state == "sitting" and d in cad and d >= restart_on_or_after:
            state = "active"
            episode = 2
            floor = 0.85 * cash
            restarts.append({"date": d, "balance": round(cash, 2),
                             "episode2_floor": round(floor, 2)})
        # --- cadence-date evaluation + trading at today's open ---
        if state == "active" and d in cad and i >= 1:
            targets = targets_at(i - 1, placebo_rng=rng)
            ts = trade_set_for_open(cash, shares, targets, i)
            if ts:
                cash, o, c, _ = execute(cash, shares, ts, targets, i)
                orders += o; total_costs += c
        # --- mark to close; floor check (protection runs daily) ---
        eq_close = equity(cash, shares, i, CLOSE)
        curve.append((d, eq_close))
        if state == "active" and eq_close <= floor:
            halts.append({"breach_close_date": d, "episode": episode})
            if di + 1 < len(days):
                liq_next = True
            else:
                halts[-1]["liquidation_date"] = None
                state = "dead"
    # if the run ended mid-liquidation bookkeeping, final = last curve value
    final = curve[-1][1] if curve else START_CASH
    return {"final": final, "curve": curve, "orders": orders,
            "costs": total_costs, "halts": halts, "restarts": restarts,
            "days": days}

def trade_set_for_open(cash, shares, targets, i):
    """Band test for sweep trades: current weights measured at the prior
    close (the same information the signal used), trades at today's open."""
    j = i - 1
    eq_c = cash + sum(shares[t] * CLOSE[t][j] for t in ASSETS if shares[t] > 0)
    ts = set()
    for t in ASSETS:
        cur_w = (shares[t] * CLOSE[t][j] / eq_c) if eq_c > 0 else 0.0
        tgt_w = targets.get(t, 0.0)
        held = shares[t] > 0
        if held and tgt_w == 0.0:
            ts.add(t)
        elif not held and tgt_w > 0.0:
            ts.add(t)
        elif held and tgt_w > 0.0 and abs(tgt_w - cur_w) / tgt_w > 0.20:
            ts.add(t)
    return ts

# ------------------------------------------------------------------ metrics
def metrics(final, curve, days):
    yrs = (datetime.strptime(days[-1], "%Y-%m-%d")
           - datetime.strptime(days[0], "%Y-%m-%d")).days / 365.25
    cagr = (final / START_CASH) ** (1 / yrs) - 1 if yrs > 0 and final > 0 else -1.0
    peak, maxdd = -1e18, 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        if peak > 0:
            maxdd = min(maxdd, eq / peak - 1.0)
    return cagr * 100, maxdd * 100

def year_return(curve, year):
    """Calendar-year return from a (date, equity) curve spanning the year."""
    this = [eq for d, eq in curve if d[:4] == str(year)]
    prev = [eq for d, eq in curve if d[:4] == str(year - 1)]
    if not this or not prev:
        return None
    return (this[-1] / prev[-1] - 1.0) * 100

def spy_buy_hold(start, end):
    days = [d for d in CAL if start <= d <= end]
    i0, i1 = CIDX[days[0]], CIDX[days[-1]]
    amt = START_CASH
    sh = (amt - amt * COST_RATE) / OPENP["SPY"][i0]
    val = sh * CLOSE["SPY"][i1]
    return val - (val * COST_RATE + SELL_FEE)

def spy_curve(start, end):
    days = [d for d in CAL if start <= d <= end]
    i0 = CIDX[days[0]]
    sh = (START_CASH - START_CASH * COST_RATE) / OPENP["SPY"][i0]
    return [(d, sh * CLOSE["SPY"][CIDX[d]]) for d in days]

def spy_year_return(year):
    days = [d for d in CAL if d[:4] == str(year)]
    prev = [d for d in CAL if d[:4] == str(year - 1)]
    if not days or not prev:
        return None
    return (CLOSE["SPY"][CIDX[days[-1]]] / CLOSE["SPY"][CIDX[prev[-1]]] - 1.0) * 100

# ---------------------------------------------------------------------- main
def main():
    report = {}
    # ---- 1) INTEGRITY: original form, original windows ----
    pub = {"A": (189.75, 896, 17.44), "B_design": (148.75, 495, 8.83),
           "B_validation": (127.14, 396, 6.34)}
    wins = {"A": (DEC_START, DEC_END), "B_design": (DEC_START, "2022-12-31"),
            "B_validation": ("2023-01-01", DEC_END)}
    integ = {}
    for name, (s, e) in wins.items():
        r = simulate_original(s, e)
        pf, po, pc = pub[name]
        ok = (round(r["final"], 2) == pf and r["orders"] == po
              and round(r["costs"], 2) == pc)
        integ[name] = {"published_final": pf, "reproduced_final": round(r["final"], 2),
                       "published_orders": po, "reproduced_orders": r["orders"],
                       "published_costs": pc, "reproduced_costs": round(r["costs"], 2),
                       "halted": r["halted"], "match": ok}
        print(f"INTEGRITY {name}: published ${pf} -> reproduced ${r['final']:.2f} "
              f"orders {r['orders']} costs ${r['costs']:.2f} match={ok}")
        if name == "A":
            integ["A_year_returns"] = {y: round(year_return(r["curve"], int(y)), 2)
                                       for y in ("2020", "2022")}
            integ["A_max_dd_pct"] = round(metrics(r["final"], r["curve"], r["days"])[1], 2)
    report["integrity_detail"] = integ

    # ---- SPY decade reference ----
    spy_fin = spy_buy_hold(DEC_START, DEC_END)
    sc = spy_curve(DEC_START, DEC_END)
    spy_dd = metrics(spy_fin, sc, [d for d, _ in sc])[1]
    spy_ref = {"final": round(spy_fin, 2), "max_dd_pct": round(spy_dd, 2),
               "ret_2020_pct": round(spy_year_return(2020), 2),
               "ret_2022_pct": round(spy_year_return(2022), 2)}
    report["decade_spy"] = spy_ref
    print(f"SPY decade: ${spy_fin:.2f} maxDD {spy_dd:.2f}% "
          f"2020 {spy_ref['ret_2020_pct']:+.2f}% 2022 {spy_ref['ret_2022_pct']:+.2f}%")

    # ---- 2) CADENCE SWEEP on the DECADE ----
    cells_dir = os.path.join(HERE, "cells")
    os.makedirs(cells_dir, exist_ok=True)
    cells = {}
    for cad in ("daily", "weekly", "biweekly", "monthly", "quarterly",
                "semiannual", "annual"):
        r = simulate_sweep(DEC_START, DEC_END, cad)
        cagr, dd = metrics(r["final"], r["curve"], r["days"])
        twins = []
        for seed in range(20):
            pr = simulate_sweep(DEC_START, DEC_END, cad, placebo_seed=seed)
            twins.append(round(pr["final"], 2))
        beaten = sum(1 for x in twins if r["final"] > x)
        cell = {"final": round(r["final"], 2), "cagr_pct": round(cagr, 2),
                "max_dd_pct": round(dd, 2),
                "costs": round(r["costs"], 2), "orders": r["orders"],
                "halts": r["halts"], "restarts": r["restarts"],
                "ret_2020_pct": round(year_return(r["curve"], 2020), 2),
                "ret_2022_pct": round(year_return(r["curve"], 2022), 2),
                "placebo_twin_finals": twins, "placebo_beaten": beaten,
                "placebo_note": ("20 random-selection twins: same universe, same "
                                 "k (number of trend-passing assets) each cadence "
                                 "date, same capped inv-vol weights/costs/band/v9 "
                                 "floor; only the selection is random.")}
        with open(os.path.join(cells_dir, f"{cad}.json"), "w") as f:
            json.dump({"slug": "etf-trend-sleeve-weekly", "cadence": cad,
                       "window": [DEC_START, DEC_END], "start_cash": START_CASH,
                       **cell,
                       "spy": spy_ref,
                       "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]]},
                      f, indent=1)
        cells[cad] = cell
        print(f"CELL {cad}: final ${r['final']:.2f} CAGR {cagr:+.2f}% "
              f"maxDD {dd:.2f}% costs ${r['costs']:.2f} orders {r['orders']} "
              f"2020 {cell['ret_2020_pct']:+.2f}% 2022 {cell['ret_2022_pct']:+.2f}% "
              f"placebo beaten {beaten}/20 halts {len(r['halts'])}")
    report["cells"] = cells

    # ---- native-cadence (weekly) champion-window context, v9 rules ----
    extra = {}
    for wname, (s, e) in {"CONT": ("2019-01-02", DEC_END),
                          "VAL": ("2023-01-03", DEC_END)}.items():
        r = simulate_sweep(s, e, "weekly")
        cagr, dd = metrics(r["final"], r["curve"], r["days"])
        extra[wname] = {"start": s, "end": e, "final": round(r["final"], 2),
                        "cagr_pct": round(cagr, 2), "max_dd_pct": round(dd, 2),
                        "costs": round(r["costs"], 2), "orders": r["orders"],
                        "halts": r["halts"], "restarts": r["restarts"],
                        "spy_final": round(spy_buy_hold(s, e), 2)}
        print(f"WEEKLY {wname}: final ${r['final']:.2f} (SPY ${extra[wname]['spy_final']:.2f})")
    report["native_weekly_extra_windows"] = extra

    with open(os.path.join(HERE, "run-output.json"), "w") as f:
        json.dump(report, f, indent=2)
    print("wrote cells/*.json and run-output.json")

if __name__ == "__main__":
    main()
