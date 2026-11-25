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
CACHE = os.path.join(HERE, "..", "..", "v6", "leveraged-trend", "data")  # V9: original cache, read-only
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
            label="", start_cash=START_CASH, floor_val=None):
    """One program pot. Returns a results dict including the daily curve."""
    days = [d for d in CAL if start <= d <= end]
    cash = start_cash
    shares = 0.0
    holding = False
    total_costs = 0.0
    trades = []            # (date, side, value, cost)
    switches = []          # (date, to_invested) executed AFTER initial entry
    curve = []             # (date, close equity)
    days_in_cash = 0
    halted = None
    halt_info = None
    fl = FLOOR if floor_val is None else floor_val

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
        if floor_on and v <= fl and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor": fl}
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



# ============================================================ V9 MODULE
# CLAUDE-RULES PROTECTION SPEC v9 — the ONLY change vs the original
# script above (copied verbatim except: CACHE repointed at the
# original test's data folder, read-only, and run_pot gained
# start_cash / floor_val parameters so the protection module can
# restart a halted pot — signal, trend, costs and execution are
# unchanged). Episode 1: plain -15% floor from the $100 start,
# identical to Terry's rule. On FIRST halt: liquidate exactly as the
# original engine does (next open; gap-through fills stay exactly as
# modeled), sit in cash 90 calendar days, then RESTART with the
# remaining cash at the strategy's next regular decision point (the
# next month-start trading day, when the monthly trend check is
# executed). Episode 2 floor: -15% from the RESTART balance. On
# SECOND halt: run ends permanently. Ranked pots only (the UPRO
# trend strategy); controls and no-floor diagnostics are not re-run.
# Windows judged here, as in the original: champion_2019_2026 as the
# continuous window and validation_2023_2026 as the validation
# window. The full_2017_2026 window never halted under his rules
# (worst close $88.19 vs the $85 floor) and is identical by
# construction; it is not re-run.

def _v9_ord(dstr):
    from datetime import date as _d
    return _d(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()


def _month_start_days(start, end):
    out, seen = [], set()
    for d in CAL:
        if start <= d <= end and d[:7] not in seen:
            seen.add(d[:7])
            out.append(d)
    return out


def run_v9(start, end, start_cash=100.0):
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_pot(start, end, asset="UPRO", trend=True, floor_on=True,
                 label="V9 EP1", start_cash=start_cash, floor_val=floor1)
    out = {"final": r1["final"], "costs": r1["costs"],
           "curve": list(r1["curve"]), "halted": r1["halted"],
           "ep1_final": r1["final"], "ep1_halt_info": r1["halt_info"],
           "restarts": [], "second_halt": None}
    if r1["halted"] is None:
        return out
    liq = r1["halt_info"]["fill_date"]
    cash = r1["final"]
    day90 = _v9_ord(r1["halted"]) + 90
    restart = None
    for cand in _month_start_days(start, end):
        if _v9_ord(cand) >= day90:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in CAL:
        if liq < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": r1["halted"], "liquidation_date": liq,
        "halt_signal_close": r1["halt_info"]["signal_close"],
        "fill_value": r1["halt_info"]["fill_value"],
        "restart_date": restart, "restart_balance": round(cash, 2),
        "episode2_floor": floor2})
    r2 = run_pot(restart, end, asset="UPRO", trend=True, floor_on=True,
                 label="V9 EP2", start_cash=cash, floor_val=floor2)
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor"],
                              "fill_date": r2["halt_info"]["fill_date"],
                              "fill_value": r2["halt_info"]["fill_value"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out


def main_v9():
    import glob as _glob
    his = json.load(open(_glob.glob(os.path.join(
        HERE, "..", "..", "v6", "leveraged-trend", "*-results.json"))[0]))
    detail = {}

    def do_window(tag, wkey):
        rec = his["windows"][wkey]["strategy_upro_trend"]
        ws, we = his["windows"][wkey]["window"]
        if rec["halted"] is None:
            print(f"V9 {tag}: IDENTICAL — floor never fired (worst close ${rec['worst_close']})", flush=True)
            return {"final": rec["final"], "status": "identical — floor never fired",
                    "restarts": [], "second_halt": None,
                    "worst_close": rec["worst_close"]}
        r = run_v9(ws, we)
        assert round(r["ep1_final"], 2) == rec["final"], \
            f"EP1 replication mismatch {tag}: {r['ep1_final']} vs {rec['final']}"
        worst = min([v for _, v in r["curve"]] + [r["final"]])
        print(f"V9 {tag}: his=${rec['final']} v9=${r['final']:,.2f} restarts={r['restarts']} second_halt={r['second_halt']}", flush=True)
        return {"final": round(r["final"], 2),
                "status": "second halt — run ended" if r["second_halt"] else ("restarted once" if r["restarts"] else "halted, no in-window restart — ended in cash"),
                "restarts": r["restarts"], "second_halt": r["second_halt"],
                "worst_close": round(worst, 2),
                "ep1_halt_info": r["ep1_halt_info"]}

    detail["continuous"] = do_window("CONTINUOUS 2019-2026", "champion_2019_2026")
    detail["validation"] = do_window("VALIDATION 2023-2026", "validation_2023_2026")
    full_rec = his["windows"]["full_2017_2026"]["strategy_upro_trend"]
    print(f"V9 FULL 2017-2026: IDENTICAL — floor never fired (worst close ${full_rec['worst_close']})", flush=True)
    folds = []
    for hf in his["folds"]:
        y = hf["year"]
        fs, fe = hf["window"]
        if hf["halted"] is None:
            folds.append({"year": y, "his_final": hf["strategy_final"],
                          "v9_final": hf["strategy_final"], "halted_his": None,
                          "restarts": [], "second_halt": None})
            print(f"V9 FOLD {y}: IDENTICAL (no halt)", flush=True)
        else:
            r = run_v9(fs, fe)
            assert round(r["ep1_final"], 2) == hf["strategy_final"], \
                f"FOLD {y} EP1 mismatch {r['ep1_final']} vs {hf['strategy_final']}"
            folds.append({"year": y, "his_final": hf["strategy_final"],
                          "v9_final": round(r["final"], 2),
                          "halted_his": hf["halted"], "restarts": r["restarts"],
                          "second_halt": r["second_halt"],
                          "ep1_halt_info": r["ep1_halt_info"]})
            print(f"V9 FOLD {y}: his=${hf['strategy_final']} v9=${r['final']:,.2f} restarts={r['restarts']} second_halt={r['second_halt']}", flush=True)
    comp_his = 100.0
    comp_v9 = 100.0
    for f in folds:
        comp_his *= f["his_final"] / 100.0
        comp_v9 *= f["v9_final"] / 100.0
    n_his_halted = sum(1 for f in folds if f["halted_his"])
    worsts = [100.0 - detail["continuous"]["worst_close"],
              100.0 - detail["validation"]["worst_close"]]
    out = {"slug": "leveraged-trend", "name": "Leveraged-ETF Trend (Gayed UPRO)",
           "status": "rerun",
           "his": {"continuous_final": detail["continuous"]["final"] if False else his["windows"]["champion_2019_2026"]["strategy_upro_trend"]["final"],
                   "validation_final": his["windows"]["validation_2023_2026"]["strategy_upro_trend"]["final"]},
           "v9": {"continuous_final": detail["continuous"]["final"],
                  "validation_final": detail["validation"]["final"],
                  "continuous_status": detail["continuous"]["status"],
                  "validation_status": detail["validation"]["status"],
                  "restarts": detail["continuous"]["restarts"] + detail["validation"]["restarts"],
                  "folds_note": f"{n_his_halted} of 10 yearly fold pots halted under his rules; his fold-compounded ${round(comp_his,2)} -> v9 fold-compounded ${round(comp_v9,2)}; per-fold detail in detail.folds",
                  "worst_total_loss_pct": round(max(worsts), 2)},
           "notes": "Continuous window = the original's champion_2019_2026 window (halted 2019-08-05, final $82.18); validation window = validation_2023_2026 (halted 2023-03-10, final $81.65). The full_2017_2026 window never halted (worst close $88.19) and is identical. GAP-THROUGH: in the 2020 fold the floor signalled 2020-02-27 but the next-open fill came at $68.78 — a realized -31.22% loss from $100 under a '-15%' floor; the v9 episode-2 floor inherits exactly the same gap-through mechanics. Under v9 the 2020 fold restarts 2020-06-01 with the $68.78 remainder (episode-2 floor $58.46).",
           "detail": {"continuous": detail["continuous"], "validation": detail["validation"],
                      "full_2017_2026": {"final": full_rec["final"], "status": "identical — floor never fired",
                                         "worst_close": full_rec["worst_close"]},
                      "folds": folds, "fold_compounded_his": round(comp_his, 2),
                      "fold_compounded_v9": round(comp_v9, 2),
                      "gap_through_2020_fold": {"signal_date": "2020-02-27",
                                                 "fill_value": 68.78,
                                                 "realized_loss_pct_from_100": -31.22}}}
    with open(os.path.join(HERE, "v9-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE V9")


main_v9()
