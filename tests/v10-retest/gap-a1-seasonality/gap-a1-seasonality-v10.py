#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — GAP A-1 SAME-MONTH SEASONALITY (Heston & Sadka 2008)
Terry's AI stock app. Simulation only. No broker orders were placed.

Original: backtests/v7/gap-a1-seasonality/ (engine below is that engine,
verbatim except: (a) decision dates are generated per CADENCE instead of
always monthly, (b) data is read read-only from the v7 cache). The v9
episode wrapper follows backtests/v9-muse-rules/gap-a1-seasonality/
exactly (plain -15% floor; first halt -> liquidate next open, sit out 90
calendar days, restart at the next regular decision point under an
episode-2 floor of -15% from the restart balance; second halt ends run).

CADENCE TREATMENT (stated before any run — the frozen reading for v10):
  The signal is INHERENTLY monthly: at any decision date falling in
  calendar month (Y, m), the ranking is the Heston-Sadka signal for
  month m = mean of that name's month-m returns over years Y-10..Y-1
  (annual lags only, >= 6 observations). Cadence governs ONLY when that
  ranking is evaluated and the top-5 rotated in / re-equalized:
    daily      = every trading day is a decision date
    weekly     = first trading day of each week
    biweekly   = first trading day of every second week (anchored on the
                 first weekly date of the window)
    monthly    = first trading day of each month  (NATIVE — original form)
    quarterly  = first trading day of each calendar quarter
    semi-annual= first trading day of each half-year
    annual     = first trading day of each year
  Within one calendar month the ranking cannot change (its inputs are
  completed months only), so sub-monthly cadences only re-equalize
  weights more often. Super-monthly cadences only ever sample the
  rankings of their decision months (quarterly: Jan/Apr/Jul/Oct;
  semi-annual: Jan/Jul; annual: January only) and hold those picks past
  their strong month — mechanically expressible, so they are run, with
  that degradation documented. No cadence is N/A for this strategy.
  Targets execute at the NEXT session's open (original R3), at every
  cadence. Costs 0.10%/side + $0.01/share on sells, unchanged.
  Placebos: 5 names drawn uniformly at random (seeds 1..20) from the
  same eligible pool at each decision date, same engine/costs/floor;
  one Random(seed) object flows through both v9 episodes (original R6).

INTEGRITY: before the sweep, the ORIGINAL form (monthly decisions,
plain $85 floor, NO restart — the v7 engine as published) is re-run on
CONT 2019-01-02->2026-11-20 and VAL 2023-01-03->2026-11-20 and must
reproduce CONT $406.91 (costs $39.79, 840 orders, placebos beaten 19/20)
and VAL $278.12 (costs $18.25, 417 orders, placebos beaten 18/20).

SWEEP ROAD: DECADE 2016-11-21 -> 2026-11-20, $100 start, v9 protection.
Data: read-only shared cache backtests/v7/gap-a1-seasonality/data/
(Yahoo adjclose daily bars 2008->2026 for the 30-name pond + SPY).
Only the 31 cached payloads this strategy needs are loaded.
"""
import json, math, os, random, time
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
ORIG_DATA = os.path.expanduser(
    "~/workspace/stock-app/backtests/v7/gap-a1-seasonality/data")

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
PLACEBO_SEEDS = list(range(1, 21))
START_CASH = 100.0
FLOOR0 = 85.0
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ------------------------------------------------------------- data (v7 cache)
def get_prices(ticker):
    path = os.path.join(ORIG_DATA, f"px_{ticker}.json")
    with open(path, "rb") as f:
        blob = f.read()
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
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}
        # per-ticker sorted date lists for bisect lookups (speed only; the
        # v7 engine's linear scan returns exactly the same bar)
        import bisect as _bisect
        self._bisect = _bisect
        self._dlists = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self._dlists.get(t)
        if not dl:
            return None
        i = self._bisect.bisect_right(dl, d) - 1
        if i < 0:
            return None
        return self.bars[t][i]["c"]

# ------------------------------------------------------------- seasonal signal
def month_end_closes(bars):
    out = {}
    for b in bars:
        out[(int(b["d"][:4]), int(b["d"][5:7]))] = b["c"]
    return out

def monthly_returns(bars):
    me = month_end_closes(bars)
    out = {}
    for (y, m), c in sorted(me.items()):
        py, pm = (y - 1, 12) if m == 1 else (y, m - 1)
        prev = me.get((py, pm))
        if prev:
            out[(y, m)] = c / prev - 1.0
    return out

def seasonal_signal(mrets, year, month):
    vals = [mrets[(y, month)] for y in range(year - 10, year)
            if (y, month) in mrets]
    if len(vals) < 6:
        return None, len(vals)
    return sum(vals) / len(vals), len(vals)

# ------------------------------------------------------------- cadence dates
def decision_dates(pb, start, end, cadence):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    out, seen = [], set()
    if cadence in ("weekly", "biweekly"):
        weekly = []
        for d in days:
            iso = dt.date.fromisoformat(d).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                weekly.append(d)
        if cadence == "weekly":
            return weekly
        return weekly[::2]
    for d in days:
        y, m = d[:4], d[5:7]
        if cadence == "monthly":
            key = (y, m)
        elif cadence == "quarterly":
            key = (y, (int(m) - 1) // 3)
        elif cadence == "semiannual":
            key = (y, (int(m) - 1) // 6)
        elif cadence == "annual":
            key = (y,)
        else:
            raise ValueError(cadence)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out

# ------------------------------------------------------------------ engine
# run_pot is the v7 engine verbatim except sel_dates come from the cadence.
def run_pot(pb, mrets_by, start, end, sel_dates, placebo_rng=None, label="",
            quiet=True, collect_spread=False):
    cash = START_CASH
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    picks_log = []
    spread_months = []
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None
    pending_meta = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        for t in list(positions):
            if t not in opens:
                continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c
                cost += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9:
                    del positions[t]
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c
                cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
        total_costs += cost
        return cost

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            if collect_spread and pending_meta is not None:
                spread_months.append((pending_meta[0], pending_meta[1],
                                      pending_meta[2], d))
            pending = None
            pending_meta = None
        if d in sel_set:
            y, m = int(d[:4]), int(d[5:7])
            signals = {}
            for t in UNIVERSE:
                s, _n = seasonal_signal(mrets_by[t], y, m)
                if s is not None:
                    signals[t] = s
            if len(signals) >= 5:
                ranked = sorted(signals, key=lambda t: (-signals[t], t))
                top5 = ranked[:5]
                bot5 = ranked[-5:]
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(signals), 5)
                else:
                    picks = top5
                picks_log.append({"date": d, "pool": len(signals),
                                  "picks": list(picks),
                                  "signals": {t: round(signals[t], 6) for t in picks}})
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                pending_meta = (d, top5, bot5)
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= FLOOR0 and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": FLOOR0}
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "curve": curve,
                    "picks_log": picks_log, "spread_months": spread_months}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "curve": curve,
            "picks_log": picks_log, "spread_months": spread_months}

def spy_net(pb, start, end, start_cash=100.0):
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost

# ------------------------------------------------------------- v9 wrapper
def run_pot_v9(pb, mrets_by, start, end, cadence, placebo_rng=None, label=""):
    global START_CASH, FLOOR0
    sel_dates = decision_dates(pb, start, end, cadence)
    START_CASH, FLOOR0 = 100.0, 85.0
    ep1 = run_pot(pb, mrets_by, start, end, sel_dates,
                  placebo_rng=placebo_rng, label=label + " EP1")
    base = {"label": label, "episodes": 1,
            "ep1_halted": ep1["halted"], "ep1_end": ep1["end"],
            "ep1_final": round(ep1["final"], 2),
            "costs": ep1["costs"], "orders": len(ep1["trades"]),
            "curve": list(ep1["curve"]),
            "restart": None, "ep2_halted": None, "halts": 0,
            "halt_dates": []}
    if not ep1["halted"]:
        base.update({"final": ep1["final"], "status": "no_halt"})
        return base
    base["halts"] = 1
    base["halt_dates"].append(ep1["halted"])
    liq_date = ep1["end"]
    cash1 = ep1["final"]
    base["curve"].append((liq_date, cash1))
    eligible = (dt.date.fromisoformat(liq_date) + dt.timedelta(days=90)).isoformat()
    restart = next((d for d in sel_dates if d >= eligible), None)
    if restart is None:
        base.update({"final": cash1, "status": "halted_ep1_no_restart_in_window"})
        return base
    floor2 = 0.85 * cash1
    START_CASH, FLOOR0 = cash1, floor2
    try:
        ep2 = run_pot(pb, mrets_by, restart, end, sel_dates,
                      placebo_rng=placebo_rng, label=label + " EP2")
    finally:
        START_CASH, FLOOR0 = 100.0, 85.0
    base["curve"].extend(ep2["curve"])
    if ep2["halted"]:
        base["halts"] = 2
        base["halt_dates"].append(ep2["halted"])
        base["curve"].append((ep2["end"], ep2["final"]))
    base.update({"episodes": 2, "final": ep2["final"],
                 "costs": ep1["costs"] + ep2["costs"],
                 "orders": len(ep1["trades"]) + len(ep2["trades"]),
                 "ep2_halted": ep2["halted"],
                 "status": "halted_ep2_run_ends" if ep2["halted"] else "restarted_completed",
                 "restart": {"liquidation_date": liq_date,
                             "cash_at_halt": round(cash1, 2),
                             "eligible_from": eligible,
                             "restart_decision_date": restart,
                             "restart_balance": round(cash1, 2),
                             "episode2_floor": round(floor2, 2)}})
    return base

# ------------------------------------------------------------- stats helpers
def max_dd(curve):
    peak, mdd = -1.0, 0.0
    for _d, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return round(mdd * 100, 2)

def cagr(final, start, end):
    days = (dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days
    years = days / 365.25
    if final <= 0 or years <= 0:
        return None
    return round(((final / 100.0) ** (1.0 / years) - 1.0) * 100, 2)

# --------------------------------------------------------------------- main
DEC_START, DEC_END = "2016-11-21", "2026-11-20"

def main():
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = get_prices(t)
    pb = PriceBook(bars)
    mrets_by = {t: monthly_returns(bars[t]) for t in UNIVERSE}
    print(f"loaded {len(bars)} tickers; dates {pb.dates[0]}..{pb.dates[-1]}",
          flush=True)

    # ---------------- INTEGRITY: original form (monthly, plain floor, no restart)
    integrity = {"original_finals": {"CONT": 406.91, "VAL": 278.12,
                                     "CONT_costs": 39.79, "VAL_costs": 18.25,
                                     "CONT_orders": 840, "VAL_orders": 417,
                                     "CONT_placebo_beaten": 19,
                                     "VAL_placebo_beaten": 18},
                 "reproduced_finals": {}}
    for wname, ws, we in [("CONT", "2019-01-02", "2026-11-20"),
                          ("VAL", "2023-01-03", "2026-11-20")]:
        sel = decision_dates(pb, ws, we, "monthly")
        r = run_pot(pb, mrets_by, ws, we, sel, label=wname + " INTEGRITY")
        finals = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            pr = run_pot(pb, mrets_by, ws, we, sel, placebo_rng=rng,
                         label=f"{wname} INTEGRITY PLACEBO {seed}")
            finals.append(round(pr["final"], 2))
        beats = sum(1 for v in finals if r["final"] > v)
        integrity["reproduced_finals"][wname] = round(r["final"], 2)
        integrity["reproduced_finals"][wname + "_costs"] = round(r["costs"], 2)
        integrity["reproduced_finals"][wname + "_orders"] = len(r["trades"])
        integrity["reproduced_finals"][wname + "_placebo_beaten"] = beats
        integrity["reproduced_finals"][wname + "_placebo_finals"] = finals
        print(f"INTEGRITY {wname}: final=${r['final']:.2f} costs=${r['costs']:.2f} "
              f"orders={len(r['trades'])} beats={beats}/20", flush=True)
    ok = (integrity["reproduced_finals"]["CONT"] == 406.91 and
          integrity["reproduced_finals"]["VAL"] == 278.12 and
          integrity["reproduced_finals"]["CONT_costs"] == 39.79 and
          integrity["reproduced_finals"]["VAL_costs"] == 18.25 and
          integrity["reproduced_finals"]["CONT_orders"] == 840 and
          integrity["reproduced_finals"]["VAL_orders"] == 417 and
          integrity["reproduced_finals"]["CONT_placebo_beaten"] == 19 and
          integrity["reproduced_finals"]["VAL_placebo_beaten"] == 18)
    integrity["status"] = "reproduced" if ok else "FAILED"
    print(f"INTEGRITY STATUS: {integrity['status']}", flush=True)

    # ---------------- SPY on the decade road (this plumbing)
    spy_dec, spy_dec_costs = spy_net(pb, DEC_START, DEC_END)
    print(f"SPY DECADE (plumbing): ${spy_dec:.2f} costs ${spy_dec_costs:.2f} "
          f"(SPEC reference $367.80)", flush=True)

    # ---------------- SWEEP
    cells = {}
    for cadence in CADENCES:
        r = run_pot_v9(pb, mrets_by, DEC_START, DEC_END, cadence,
                       label=f"DECADE {cadence} RANKED")
        finals = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            pr = run_pot_v9(pb, mrets_by, DEC_START, DEC_END, cadence,
                            placebo_rng=rng,
                            label=f"DECADE {cadence} PLACEBO {seed}")
            finals.append(round(pr["final"], 2))
        beats = sum(1 for v in finals if r["final"] > v)
        cell = {"final": round(r["final"], 2),
                "cagr_pct": cagr(r["final"], DEC_START, DEC_END),
                "max_dd_pct": max_dd(r["curve"]),
                "halts": r["halts"],
                "restart": bool(r["restart"]),
                "second_halt": bool(r["ep2_halted"]),
                "costs": round(r["costs"], 2),
                "orders": r["orders"],
                "placebo_beaten": beats,
                "placebo_note": "20 random-rank twins (seeds 1..20), v9-wrapped, "
                                "same cadence; full twin finals in cells/<cadence>.json"}
        cells[cadence] = cell
        cell_doc = {"slug": "gap-a1-seasonality", "cadence": cadence,
                    "window": [DEC_START, DEC_END],
                    "start_cash": 100.0,
                    "protection": "v9: plain -15% floor; first halt -> 90-day "
                                  "sit-out, restart at next cadence decision "
                                  "date, ep2 floor -15% from restart balance; "
                                  "second halt ends run",
                    "final": cell["final"], "cagr_pct": cell["cagr_pct"],
                    "max_dd_pct": cell["max_dd_pct"], "costs": cell["costs"],
                    "orders": cell["orders"], "halts": cell["halts"],
                    "halt_dates": r["halt_dates"],
                    "restart": r["restart"],
                    "second_halt": cell["second_halt"],
                    "status": r["status"],
                    "spy_final_plumbing": round(spy_dec, 2),
                    "spy_reference_spec": 367.80,
                    "placebo_beaten": beats,
                    "placebo_finals": finals,
                    "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]]}
        with open(os.path.join(HERE, "cells", f"{cadence}.json"), "w") as f:
            json.dump(cell_doc, f, indent=1)
        print(f"CELL {cadence}: final=${r['final']:.2f} CAGR={cell['cagr_pct']} "
              f"maxDD={cell['max_dd_pct']} costs=${r['costs']:.2f} "
              f"orders={r['orders']} halts={r['halts']} status={r['status']} "
              f"placebo beats={beats}/20", flush=True)

    money = [c for c in CADENCES
             if cells[c]["final"] > 367.80 and cells[c]["placebo_beaten"] >= 11]
    out = {"slug": "gap-a1-seasonality",
           "area": "monthly same-calendar-month seasonality ranking on the "
                   "honest 30-name pond (Heston & Sadka 2008) — judged in "
                   "this sweep on the DECADE road at every cadence",
           "area_source": "SPEC W4 + CADENCE GRID (gap-a1 — monthly); "
                          "THE CADENCE SWEEP (Terry 2026-11-21 ~22:09)",
           "native_cadence": "monthly",
           "cadence": "monthly",
           "original_cadence_foreign": False,
           "original_cadence_note": "Not foreign. The original v7 test and "
                                    "the v9 re-run both used monthly "
                                    "decisions — the strategy's native tempo.",
           "cadence_treatment": "Signal at any decision date = Heston-Sadka "
                                "signal for the calendar month containing "
                                "that date (mean same-month return, prior "
                                "10y annual lags, >=6 obs). Cadence governs "
                                "only when the ranking is evaluated and the "
                                "top-5 rotated/re-equalized. Sub-monthly "
                                "cadences cannot change the ranking inside a "
                                "month; super-monthly cadences sample only "
                                "their decision months' rankings (quarterly "
                                "Jan/Apr/Jul/Oct, semiannual Jan/Jul, annual "
                                "January only) and hold picks past their "
                                "strong month. No cadence is N/A: every "
                                "cadence date falls in a month whose signal "
                                "exists.",
           "integrity": integrity,
           "decade_spy_final": 367.80,
           "decade_spy_note": "SPEC dividend-adjusted reference $367.80 used "
                              "as the money hurdle; this plumbing's own SPY "
                              f"net on the same book = ${round(spy_dec, 2)} "
                              "(saved per cell as spy_final_plumbing).",
           "champion_decade": {"final": 65.89,
                               "note": "Value+Momentum decade final after two "
                                       "halts (lazy-quarterly test); its crown "
                                       "rests on the 2010 and 2019 roads — "
                                       "caveat per SPEC."},
           "cells": cells,
           "money_cadences": money,
           "data_note": "Read-only shared cache: backtests/v7/gap-a1-seasonality/"
                        "data/ (31 Yahoo adjclose payloads, 2008->2026, pond + "
                        "SPY). No new downloads; nothing written to shared folders.",
           "verdict_area": "PENDING — set in RESULTS.md after the sweep",
           "verdict_change": "PENDING"}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE SWEEP; money cadences:", money, flush=True)

if __name__ == "__main__":
    main()
