#!/usr/bin/env python3
"""
V13 BEST-RULES - breakout-regime. Simulation only.
Spec frozen in BEST-RULES-SPEC.md BEFORE this run. One spec, run once.

MY RULES (summary; spec is binding):
  ENTRY: close at new 252-day high AND signal-day volume > mean volume of
         prior 20 sessions; fill next open. Slots RANKED by 126-day return.
  REGIME: breadth = share of the 10 names above their own 200-day average
         (signal day). Tiers cap concurrent positions: >=70% -> 5,
         40-69% -> 3, <40% -> 1. Tier NEVER forces a sale.
  SIZE: 20% of current equity per position.
  EXIT: next open after close below 50-day average; initial stop at
         entry - 2.5*ATR(14) (signal-day ATR, fixed), intraday, gaps at open.
  NO floor / ladder / sit-out. Costs 0.10%/side + $0.01/sell.

INTEGRITY: the frozen v12 gated form (2x50%, SPY 200d gate, 20-day exit,
-8% stop, v9 protections) is re-run in this folder's copied runner and
must reproduce DECADE $359.44 before v13 numbers are claimed.

Placebos: 20 seeds (777001+7919*i), random entries matched per-year in
filled count, same tier caps / exits / ATR stop shape / costs.
Roads: DECADE / CONT / VAL. LONG not run (named blocker, spec).
"""
import importlib.util
import json
import os
import sys
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
V2_DIR = os.path.join(ROOT, "v2")
V4_DIR = os.path.join(ROOT, "v4")
sys.path.insert(0, V2_DIR)

import tournament as T

spec = importlib.util.spec_from_file_location(
    "breakout_regime_v4", os.path.join(V4_DIR, "breakout-regime.py"))
V4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V4)

UNIVERSE = T.STOCK_UNIVERSE
COST_RATE = T.COST_RATE
SELL_FEE = T.SELL_FEE

ROADS = {
    "DECADE": (date(2016, 11, 21), date(2026, 11, 20)),
    "CONT": (date(2019, 1, 2), date(2026, 11, 20)),
    "VAL": (date(2023, 1, 3), date(2026, 11, 20)),
}
SPY_DIV_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
PUBLISHED = {"DECADE": 359.44, "CONT": 267.51, "VAL": 109.54}
PUBLISHED_DD = {"DECADE": 30.22, "CONT": 30.2, "VAL": 30.3}


# ----------------------------------------------------------------------------
# Data: v2 cache frames + my indicators (vol20-prior, ATR14, ret126, breadth)
# ----------------------------------------------------------------------------
class Data:
    def __init__(self, frames, mkt):
        self.dates = list(mkt.test_dates)
        self.pos_list = list(mkt.test_pos)
        self.n = len(self.dates)
        self.arr = {}
        for sym in UNIVERSE:
            df = frames[sym]
            a = {k: df[k].to_numpy(dtype=float)
                 for k in ("open", "high", "low", "close", "volume",
                           "sma50", "sma200", "prior252_high_close")}
            v = a["volume"]
            vol_prior = np.full(len(v), np.nan)
            cs = np.cumsum(np.insert(v, 0, 0.0))
            for i in range(20, len(v)):
                vol_prior[i] = (cs[i] - cs[i - 20]) / 20.0
            a["vol_prior20"] = vol_prior
            h, l, c = a["high"], a["low"], a["close"]
            tr = np.full(len(c), np.nan)
            tr[1:] = np.maximum(h[1:] - l[1:],
                                np.maximum(np.abs(h[1:] - c[:-1]),
                                           np.abs(l[1:] - c[:-1])))
            atr = np.full(len(c), np.nan)
            cs_tr = np.cumsum(np.insert(np.nan_to_num(tr), 0, 0.0))
            for i in range(14, len(c)):
                atr[i] = (cs_tr[i] - cs_tr[i - 14]) / 14.0
            a["atr14"] = atr
            ret = np.full(len(c), np.nan)
            ret[126:] = c[126:] / c[:-126] - 1.0
            a["ret126"] = ret
            self.arr[sym] = a
        # breadth: share of universe with close > own sma200, per frame pos
        nfr = len(frames["SPY"])
        above = np.zeros(nfr)
        valid = np.zeros(nfr)
        for sym in UNIVERSE:
            a = self.arr[sym]
            ok = ~np.isnan(a["sma200"])
            valid += ok
            above += ok & (a["close"] > a["sma200"])
        self.breadth = np.where(valid > 0, above / np.maximum(valid, 1), 0.0)

    def cap(self, p):
        b = self.breadth[p]
        return 5 if b >= 0.70 else (3 if b >= 0.40 else 1)

    def breakout(self, sym, p):
        if p < 253:
            return False
        a = self.arr[sym]
        ph = a["prior252_high_close"][p]
        if np.isnan(ph) or not (a["close"][p] > ph):
            return False
        vp = a["vol_prior20"][p]
        return not np.isnan(vp) and a["volume"][p] > vp


# ----------------------------------------------------------------------------
# My-rules runner
# ----------------------------------------------------------------------------
def run_mine(data, placebo_sched=None):
    A = data.arr
    cash = 100.0
    lots = {}  # sym -> [shares, entry_price, stop_price]
    curve = []
    orders = 0
    costs = 0.0
    entries_by_year = {}
    pending_exits = []
    pending_entries = []  # list of (sym, cap, atr_at_signal)

    def equity(field, p):
        return cash + sum(sh * A[s][field][p] for s, (sh, _, _) in lots.items())

    def do_buy(d, p, sym, atr_sig):
        nonlocal cash, orders, costs
        price = A[sym]["open"][p]
        if price <= 0:
            return False
        target = 0.20 * equity("open", p)
        value = min(target, cash / (1 + COST_RATE))
        if value < 1.0:
            return False
        atr = atr_sig if (atr_sig is not None and not np.isnan(atr_sig)) \
            else A[sym]["atr14"][p]
        stop = price - 2.5 * atr if (atr is not None and not np.isnan(atr)) \
            else price * 0.80
        cost = COST_RATE * value
        lots[sym] = [value / price, price, stop]
        cash -= value + cost
        costs += cost
        orders += 1
        entries_by_year[d.year] = entries_by_year.get(d.year, 0) + 1
        return True

    def do_sell(p, sym, price):
        nonlocal cash, orders, costs
        sh = lots.pop(sym)[0]
        value = sh * price
        cost = COST_RATE * value + SELL_FEE
        cash += value - cost
        costs += cost
        orders += 1

    for t in range(data.n):
        p = data.pos_list[t]
        d = data.dates[t]
        for sym in pending_exits:
            if sym in lots:
                do_sell(p, sym, A[sym]["open"][p])
        pending_exits = []
        cands, pending_entries = pending_entries, []
        for sym, cap, atr_sig in cands:
            if sym in lots or len(lots) >= cap:
                continue
            do_buy(d, p, sym, atr_sig)
        for sym in list(lots):
            _, _, stop = lots[sym]
            o, low = A[sym]["open"][p], A[sym]["low"][p]
            if o <= stop:
                do_sell(p, sym, o)
            elif low <= stop:
                do_sell(p, sym, stop)
        eq = equity("close", p)
        curve.append((d, eq))
        if t == data.n - 1:
            break
        for sym in list(lots):
            ma = A[sym]["sma50"][p]
            if not np.isnan(ma) and A[sym]["close"][p] < ma:
                pending_exits.append(sym)
        if placebo_sched is not None:
            pending_entries = [(s, data.cap(p), A[s]["atr14"][p])
                               for s in placebo_sched.get(d, [])]
        else:
            sigs = [s for s in UNIVERSE if s not in lots and data.breakout(s, p)]
            sigs.sort(key=lambda s: -(A[s]["ret126"][p]
                                      if not np.isnan(A[s]["ret126"][p]) else -9))
            cap = data.cap(p)
            pending_entries = [(s, cap, A[s]["atr14"][p]) for s in sigs]
    final = curve[-1][1] if curve else cash
    return finish(final, curve, costs, orders, entries_by_year)


def finish(final, curve, costs, orders, entries_by_year):
    start_d = curve[0][0] if curve else None
    end_d = curve[-1][0] if curve else None
    years = max((end_d - start_d).days, 1) / 365.25 if start_d else 1
    cagr = (final / 100.0) ** (1 / years) - 1 if final > 0 else -1.0
    peak, max_dd = 100.0, 0.0
    for _, e in [(start_d, 100.0)] + curve:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak)
    return {
        "final": final, "cagr_pct": cagr * 100, "max_dd_pct": max_dd * 100,
        "costs": costs, "orders": orders,
        "entries": sum(entries_by_year.values()),
        "entries_by_year": {str(k): v for k, v in sorted(entries_by_year.items())},
        "equity_curve": [[d.isoformat(), round(e, 4)] for d, e in curve],
    }


# ----------------------------------------------------------------------------
# Frozen v12 form runner (copied logic from v12 run_breakout_regime_v12.py)
# ----------------------------------------------------------------------------
class FrozenData:
    def __init__(self, frames, mkt):
        self.dates = list(mkt.test_dates)
        self.pos_list = list(mkt.test_pos)
        self.n = len(self.dates)
        self.arr = {}
        for sym in UNIVERSE:
            df = frames[sym]
            self.arr[sym] = {k: df[k].to_numpy(dtype=float)
                             for k in ("open", "high", "low", "close", "sma20",
                                       "sma200", "prior252_high_close")}
        spy = self.arr["SPY"]
        self.regime = np.zeros(len(frames["SPY"]), dtype=bool)
        c, m = spy["close"], spy["sma200"]
        valid = ~np.isnan(m)
        self.regime[valid] = c[valid] > m[valid]
        self.regime[:200] = False

    def breakout(self, sym, p):
        if p < 253:
            return False
        ph = self.arr[sym]["prior252_high_close"][p]
        return not np.isnan(ph) and self.arr[sym]["close"][p] > ph


def run_frozen(data, floor_mode="v9"):
    A = data.arr
    cash = 100.0
    lots = {}
    curve = []
    orders = 0
    costs = 0.0
    entries_by_year = {}
    pending_entries, pending_exits = [], []
    halts = []
    episode = 1
    floor = 85.0
    halt_pending = False
    active = True
    restart_on_or_after = None
    n = data.n

    def equity(field, p):
        return cash + sum(sh * A[s][field][p] for s, (sh, _) in lots.items())

    def do_buy(d, p, sym):
        nonlocal cash, orders, costs
        price = A[sym]["open"][p]
        target = 0.5 * equity("open", p)
        value = min(target, cash / (1 + COST_RATE))
        if price <= 0 or value < 1.0:
            return False
        cost = COST_RATE * value
        lots[sym] = [value / price, price]
        cash -= value + cost
        costs += cost
        orders += 1
        entries_by_year[d.year] = entries_by_year.get(d.year, 0) + 1
        return True

    def do_sell(p, sym, price):
        nonlocal cash, orders, costs
        sh = lots.pop(sym)[0]
        value = sh * price
        cost = COST_RATE * value + SELL_FEE
        cash += value - cost
        costs += cost
        orders += 1

    for t in range(n):
        p = data.pos_list[t]
        d = data.dates[t]
        if halt_pending:
            for sym in list(lots):
                do_sell(p, sym, A[sym]["open"][p])
            curve.append((d, cash))
            halts[-1]["liquidation_date"] = d.isoformat()
            halt_pending = False
            if floor_mode == "original" or episode == 2:
                break
            active = False
            restart_on_or_after = d + timedelta(days=90)
            continue
        if not active:
            if d >= restart_on_or_after:
                episode = 2
                floor = 0.85 * cash
                active = True
            else:
                curve.append((d, cash))
                continue
        for sym in pending_exits:
            if sym in lots:
                do_sell(p, sym, A[sym]["open"][p])
        pending_exits = []
        cands, pending_entries = pending_entries, []
        for sym in cands:
            if sym in lots or len(lots) >= 2:
                continue
            do_buy(d, p, sym)
        for sym in list(lots):
            entry = lots[sym][1]
            o, low = A[sym]["open"][p], A[sym]["low"][p]
            stop_px = entry * (1 - 0.08)
            if o <= stop_px:
                do_sell(p, sym, o)
            elif low <= stop_px:
                do_sell(p, sym, stop_px)
        eq = equity("close", p)
        curve.append((d, eq))
        if eq <= floor:
            halts.append({"episode": episode, "trigger_date": d.isoformat(),
                          "floor_level": round(floor, 4),
                          "trigger_equity": round(eq, 4)})
            pending_entries, pending_exits = [], []
            if t == n - 1:
                break
            halt_pending = True
            continue
        if t == n - 1:
            break
        for sym in list(lots):
            ma = A[sym]["sma20"][p]
            if not np.isnan(ma) and A[sym]["close"][p] < ma:
                pending_exits.append(sym)
        if data.regime[p]:
            for sym in UNIVERSE:
                if sym not in lots and data.breakout(sym, p):
                    pending_entries.append(sym)
    res = finish(curve[-1][1] if curve else cash, curve, costs, orders,
                 entries_by_year)
    res["halts"] = halts
    return res


# ----------------------------------------------------------------------------
# Placebos for my rules: random entries, per-year filled-count matched,
# same tier caps / exits / stop shape / costs (v12 design adapted).
# ----------------------------------------------------------------------------
def run_placebo_cell(data, target_by_year, seed):
    rng = np.random.default_rng(seed)
    eval_dates = list(data.dates)
    elig_by_year = {}
    for d in eval_dates:
        elig_by_year.setdefault(d.year, []).append(d)
    elig = list(eval_dates)
    elig_pos = {d: i for i, d in enumerate(elig)}
    schedule = {}

    def add_attempts(year, n_add):
        days = elig_by_year.get(year, [])
        if not days:
            return
        for _ in range(n_add):
            d = days[int(rng.integers(0, len(days)))]
            j = elig_pos[d]
            while len(schedule.get(d, [])) >= 5 and j < len(elig) - 1:
                j += 1
                d = elig[j]
            sym = UNIVERSE[int(rng.integers(0, len(UNIVERSE)))]
            schedule.setdefault(d, []).append(sym)

    for year, target in sorted(target_by_year.items()):
        add_attempts(year, target)
    res, actual = None, {}
    for _ in range(25):
        res = run_mine(data, placebo_sched=schedule)
        actual = {int(k): v for k, v in res["entries_by_year"].items()}
        missing = {y: target_by_year.get(y, 0) - actual.get(y, 0)
                   for y in target_by_year}
        if all(v <= 0 for v in missing.values()):
            break
        for year, miss in missing.items():
            if miss > 0:
                add_attempts(year, miss)
    return res, {"seed": seed,
                 "attempts": sum(len(v) for v in schedule.values()),
                 "target_by_year": {str(k): v for k, v in target_by_year.items()},
                 "actual_by_year": {str(k): v for k, v in sorted(actual.items())}}


# ----------------------------------------------------------------------------
# Per-period distribution (monthly) + SPY buy-hold in this plumbing
# ----------------------------------------------------------------------------
def monthly_stats(curve):
    pts = [(date.fromisoformat(d), e) for d, e in curve]
    months = []
    prev_e, prev_key = 100.0, None
    last_e = None
    for d, e in pts:
        key = (d.year, d.month)
        if prev_key is not None and key != prev_key:
            months.append(last_e / prev_e - 1.0)
            prev_e = last_e
        prev_key, last_e = key, e
    if last_e is not None and prev_e:
        months.append(last_e / prev_e - 1.0)
    if not months:
        return {}
    arr = np.array(months)
    streak = cur = 0
    for r in months:
        cur = cur + 1 if r <= 0 else 0
        streak = max(streak, cur)
    peak, peak_i, worst_gap, last_peak_i = pts[0][1], 0, 0, 0
    runmax = 100.0
    last_high_t = 0
    gap = 0
    for i, (_, e) in enumerate(pts):
        if e >= runmax:
            runmax = e
            last_high_t = i
        gap = max(gap, i - last_high_t)
    return {
        "periods": len(months),
        "median_pct": round(float(np.median(arr)) * 100, 2),
        "pct_positive": round(float(np.mean(arr > 0)) * 100, 1),
        "best_pct": round(float(arr.max()) * 100, 2),
        "worst_pct": round(float(arr.min()) * 100, 2),
        "mean_pct_secondary": round(float(arr.mean()) * 100, 2),
        "longest_losing_streak_months": streak,
        "longest_stretch_between_new_highs_days": gap,
    }


def spy_buyhold(data):
    A = data.arr["SPY"]
    p0, p1 = data.pos_list[0], data.pos_list[-1]
    buy = A["open"][p0]
    value = 100.0 / (1 + COST_RATE)
    sh = value / buy
    sell_val = sh * A["close"][p1]
    net = sell_val - (COST_RATE * sell_val + SELL_FEE)
    gross = 100.0 * A["close"][p1] / A["close"][p0]
    return round(net, 2)


def main():
    print("Loading data (v2 tournament cache, read-only)...", flush=True)
    frames = V4.build_frames()

    # ---------- Integrity: frozen form must reproduce DECADE $359.44 ----------
    mkt_dec = V4.make_market(frames, ROADS["DECADE"])
    fdata = FrozenData(frames, mkt_dec)
    fres = run_frozen(fdata, "v9")
    integ_ok = abs(round(fres["final"], 2) - 359.44) < 0.02
    print(f"INTEGRITY frozen DECADE: ${fres['final']:,.2f} expected $359.44 "
          f"match={integ_ok}", flush=True)
    assert integ_ok, "integrity failed - no v13 numbers claimed"

    results = {
        "program": "v13-best-rules", "family": "breakout-regime",
        "spec": "BEST-RULES-SPEC.md (frozen before run)",
        "my_rules": {
            "entry": "new 252d high close + volume > prior-20d mean volume; next-open fill; slots ranked by 126d return",
            "regime": "breadth (share of 10 names above own 200dma): >=70% cap 5, 40-69% cap 3, <40% cap 1; never forces a sale",
            "size": "20% of equity per position", "exit": "close below 50dma -> next open",
            "stop": "entry - 2.5*ATR14(signal day), fixed, intraday, gaps at open",
            "floor": None, "costs": "0.10%/side + $0.01 per sell order",
            "start_cash": 100.0},
        "published_form": {"rules": "house gated form (v12): SPY 200d gate, 2x50% first-come, 20dma exit, -8% stop, v9 floor",
                           "finals": PUBLISHED, "max_dd_pct": PUBLISHED_DD},
        "champion_vm": CHAMPION, "spy_div_ref": SPY_DIV_REF,
        "integrity": {"frozen_decade_expected": 359.44,
                      "frozen_decade_reproduced": round(fres["final"], 2),
                      "match": integ_ok},
        "long_road": "NOT RUN - named blocker: v2 cache begins 2015-01-02 (v3 cache 2015-06-01); spec needs 252 prior-high + 200 average sessions before first signal; no 2010-start series exists in program caches.",
        "roads": {}, "confirmation": None,
    }

    beat_champion = []
    for name, window in ROADS.items():
        mkt = V4.make_market(frames, window)
        data = Data(frames, mkt)
        res = run_mine(data)
        # diagnostics
        raw_sig = qual_sig = 0
        tier_days = {"strong": 0, "mid": 0, "weak": 0}
        for t in range(data.n):
            p = data.pos_list[t]
            b = data.breadth[p]
            tier_days["strong" if b >= 0.70 else ("mid" if b >= 0.40 else "weak")] += 1
            for sym in UNIVERSE:
                a = data.arr[sym]
                ph = a["prior252_high_close"][p]
                if p >= 253 and not np.isnan(ph) and a["close"][p] > ph:
                    raw_sig += 1
                    if data.breakout(sym, p):
                        qual_sig += 1
        target = {int(k): v for k, v in res["entries_by_year"].items()}
        twin_finals, twin_meta = [], []
        for i in range(20):
            seed = 777001 + 7919 * i
            pres, pmeta = run_placebo_cell(data, target, seed)
            twin_finals.append(round(pres["final"], 4))
            twin_meta.append(pmeta)
        beaten = sum(1 for f in twin_finals if res["final"] > f)
        if res["final"] > CHAMPION[name]:
            beat_champion.append(name)
        results["roads"][name] = {
            "window": [window[0].isoformat(), window[1].isoformat()],
            "final": round(res["final"], 2), "cagr_pct": round(res["cagr_pct"], 2),
            "max_dd_pct": round(res["max_dd_pct"], 2),
            "costs": round(res["costs"], 2), "orders": res["orders"],
            "entries": res["entries"], "entries_by_year": res["entries_by_year"],
            "published_best": PUBLISHED[name], "published_dd_pct": PUBLISHED_DD[name],
            "champion_vm": CHAMPION[name], "spy_div_ref": SPY_DIV_REF[name],
            "spy_price_only_net_this_plumbing": spy_buyhold(data),
            "placebo_beaten": f"{beaten}/20", "placebo_finals": twin_finals,
            "placebo_median": round(float(np.median(twin_finals)), 2),
            "placebo_meta": twin_meta,
            "raw_breakout_signals": raw_sig, "volume_qualified_signals": qual_sig,
            "tier_days": tier_days,
            "monthly_distribution": monthly_stats(res["equity_curve"]),
            "equity_curve": res["equity_curve"],
        }
        print(f"[{name}] mine ${res['final']:,.2f} DD {res['max_dd_pct']:.1f}% "
              f"costs ${res['costs']:,.2f} orders {res['orders']} entries "
              f"{res['entries']} placebo {beaten}/20 raw {raw_sig} qual "
              f"{qual_sig} tiers {tier_days}", flush=True)

    # ---------- Confirmation (pre-registered; only if a champion fell) ------
    if beat_champion:
        print(f"CONFIRMATION TRIGGERED on {beat_champion} - running folds",
              flush=True)
        folds = {}
        for yr in range(2017, 2027):
            w = (date(yr, 1, 1), date(yr, 12, 31))
            if yr == 2026:
                w = (date(2026, 1, 1), date(2026, 11, 20))
            mkt = V4.make_market(frames, w)
            d_mine = Data(frames, mkt)
            r_mine = run_mine(d_mine)
            fd = FrozenData(frames, mkt)
            r_froz = run_frozen(fd, "v9")
            folds[str(yr)] = {
                "mine": round(r_mine["final"], 2),
                "frozen_gated": round(r_froz["final"], 2),
                "spy_net": spy_buyhold(d_mine),
                "mine_beats_frozen": r_mine["final"] > r_froz["final"],
                "mine_beats_spy": r_mine["final"] > spy_buyhold(d_mine),
            }
            print(f" fold {yr}: mine ${r_mine['final']:,.2f} frozen "
                  f"${r_froz['final']:,.2f} SPY ${spy_buyhold(d_mine):,.2f}",
                  flush=True)
        nb_f = sum(1 for v in folds.values() if v["mine_beats_frozen"])
        nb_s = sum(1 for v in folds.values() if v["mine_beats_spy"])
        results["confirmation"] = {
            "triggered_on": beat_champion, "folds": folds,
            "beats_frozen_folds": f"{nb_f}/10", "beats_spy_folds": f"{nb_s}/10",
            "confirmed": nb_f >= 6 and nb_s >= 6}
    else:
        print("No champion beaten - confirmation not triggered.", flush=True)

    def _clean(o):
        if isinstance(o, dict):
            return {k: _clean(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_clean(v) for v in o]
        if isinstance(o, (np.bool_,)):
            return bool(o)
        if isinstance(o, (np.integer,)):
            return int(o)
        if isinstance(o, (np.floating,)):
            return float(o)
        return o

    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(_clean(results), fh, indent=2)
    print("Wrote results.json", flush=True)


if __name__ == "__main__":
    main()
