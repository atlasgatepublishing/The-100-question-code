#!/usr/bin/env python3
"""
V13 BEST-RULES RUN — BREAKOUT-VALIDATION (52-week-high breakout, validation-era form).

Spec frozen in BEST-RULES-SPEC.md before this run. One shot.

MY RULES: universe SPY QQQ NVDA TSLA AAPL MSFT AMZN META AMD AVGO (v2
tournament cache, unchanged); daily cadence; entry at next open after a
close above the prior 252-session high close, CONFIRMED by breakout-day
volume >= 1.5x the mean volume of the prior 50 sessions, and GATED to
days when SPY's close is above its 200-day average (entry-only gate);
max 2 positions at 50% of equity each; exit at next open after a close
below the 20-day average; -10% intraday stop (gaps fill at the open);
NO floor, NO ladder; costs 0.10%/side + $0.01/sell; $100 pots.

Engine: a numpy re-implementation of the v3 run_breakout semantics
(same order of operations, same Portfolio cost/floor formulas from
tournament.py) — the shared machine is heavily loaded and the pandas
engine is too slow under contention. FAITHFULNESS IS PROVEN, NOT
ASSUMED: the integrity block below must reproduce the v3 originals
(full $383.36; validation $124.82 with ladder halt 2026-08-14) to the
cent before any v13 number is taken; the script aborts otherwise.

Roads: DECADE 2016-11-21->2026-11-20, CONT 2019-01-02->2026-11-20,
VAL 2023-01-03->2026-11-20. LONG 2010 is a named closure (cache begins
2015-01-02; signal needs 252 prior sessions).

Placebos: 20 seeds/road, v3 fixed design (per-year filled-entry
matching, up to 60 top-up iterations), identical exits/stop/sizing/
costs, entries restricted to regime-gate-open days.

Confirmation (pre-registered in the spec): only if a champion road is
beaten (V+M DECADE $667.35 / CONT $544.47 / VAL $288.05).
"""
import json
import os
import sys
from datetime import date

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
V2_DIR = os.path.join(HERE, "..", "..", "v2")
sys.path.insert(0, V2_DIR)

import tournament as T  # data loading only (read-only); engine below

UNIVERSE = list(T.STOCK_UNIVERSE)
ROADS = {
    "DECADE": (date(2016, 11, 21), date(2026, 11, 20)),
    "CONT": (date(2019, 1, 2), date(2026, 11, 20)),
    "VAL": (date(2023, 1, 3), date(2026, 11, 20)),
}
DESIGN = (date(2016, 11, 21), date(2022, 12, 31))
HALF1 = (date(2016, 11, 21), date(2021, 6, 30))
HALF2 = (date(2021, 7, 1), date(2026, 11, 20))
CHAMPION_VM = {"DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
VOL_MULT = 1.5
STOP_MINE = 0.10
STOP_ORIG = 0.08
COST = T.COST_RATE
FEE = T.SELL_FEE
START = 100.0

# ---------------------------------------------------------------- data
_raw = {sym: T.load_symbol(sym) for sym in T.ALL_SYMBOLS}
_frames = T.align_frames(_raw)
for _sym, _df in _frames.items():
    _v = _df["volume"].astype(float)
    _df["vol50_prior"] = _v.shift(1).rolling(50).mean()

DATES = list(_frames["SPY"]["date"])
NPOS = len(DATES)
A = {}
for s, df in _frames.items():
    A[s] = {k: df[k].to_numpy(dtype=float)
            for k in ("open", "high", "low", "close", "volume",
                      "sma20", "sma200", "prior252_high_close",
                      "vol50_prior")}


def window_idx(window):
    a, b = window
    idx = [i for i, d in enumerate(DATES) if a <= d <= b]
    return idx


def gate_open(pos):
    ma = A["SPY"]["sma200"][pos]
    return not np.isnan(ma) and A["SPY"]["close"][pos] > ma


def breakout(pos, sym, confirmed):
    if pos < 253:
        return False
    hi = A[sym]["prior252_high_close"][pos]
    if np.isnan(hi) or not (A[sym]["close"][pos] > hi):
        return False
    if confirmed:
        base = A[sym]["vol50_prior"][pos]
        if np.isnan(base) or base <= 0:
            return False
        if not (A[sym]["volume"][pos] >= VOL_MULT * base):
            return False
    return True


# ---------------------------------------------------------------- engine
class FastPF:
    """Replicates tournament.Portfolio economics for this strategy's
    trade shapes (single lot per symbol, full sells only)."""

    def __init__(self, use_floor):
        self.cash = START
        self.lots = {}          # sym -> [shares, entry_price, buy_cost]
        self.costs = 0.0
        self.orders = 0
        self.entries = 0
        self.round_trips = []   # pnl per closed position
        self.curve = []         # (date, equity_close)
        self.floor = 85.0
        self.use_floor = use_floor
        self.halt_pending = False
        self.halted = False
        self.halt_date = None

    def equity(self, field, pos):
        tot = self.cash
        for s, (sh, _, _) in self.lots.items():
            tot += sh * A[s][field][pos]
        return tot

    def buy(self, pos, sym, price, target):
        if price is None or price <= 0 or target <= 0:
            return False
        value = min(target, self.cash / (1 + COST))
        if value < 1.0:
            return False
        cost = COST * value
        self.cash -= value + cost
        self.costs += cost
        self.lots[sym] = [value / price, price, cost]
        self.orders += 1
        self.entries += 1
        return True

    def sell(self, pos, sym, price):
        lot = self.lots.pop(sym, None)
        if lot is None or price is None or price <= 0:
            if lot is not None:
                self.lots[sym] = lot
            return False
        sh, entry, buy_cost = lot
        value = sh * price
        cost = COST * value + FEE
        proceeds = value - cost
        self.cash += proceeds
        self.costs += cost
        self.orders += 1
        self.round_trips.append(proceeds - (sh * entry + buy_cost))
        return True

    def floor_check(self, eq_close):
        if not self.use_floor:
            return False
        if eq_close >= 150.0:
            self.floor = max(self.floor, 125.0)
        elif eq_close >= 125.0:
            self.floor = max(self.floor, 100.0)
        if eq_close <= self.floor:
            self.halt_pending = True
            return True
        return False


def run_strategy(idxs, confirmed=False, gated=False, stop_pct=STOP_ORIG,
                 use_floor=False, placebo_schedule=None):
    """v3 run_breakout order of operations, exactly."""
    pf = FastPF(use_floor)
    pending_entries, pending_exits = [], []
    last_t = len(idxs) - 1
    for t, pos in enumerate(idxs):
        d = DATES[pos]
        if pf.halt_pending:
            for sym in list(pf.lots):
                pf.sell(pos, sym, A[sym]["open"][pos])
            pf.halted = True
            pf.halt_date = d
            pf.curve.append((d, pf.equity("close", pos)))
            break
        for sym in pending_exits:
            if sym in pf.lots:
                pf.sell(pos, sym, A[sym]["open"][pos])
        pending_exits = []
        if placebo_schedule is not None:
            candidates = list(placebo_schedule.get(d, []))
        else:
            candidates = list(pending_entries)
        pending_entries = []
        for sym in candidates:
            if sym in pf.lots or len(pf.lots) >= 2:
                continue
            eq_open = pf.equity("open", pos)
            pf.buy(pos, sym, A[sym]["open"][pos], 0.5 * eq_open)
        if stop_pct is not None:
            for sym in list(pf.lots):
                entry = pf.lots[sym][1]
                o, low = A[sym]["open"][pos], A[sym]["low"][pos]
                stop_px = entry * (1 - stop_pct)
                fill = None
                if o <= stop_px:
                    fill = o
                elif low <= stop_px:
                    fill = stop_px
                if fill is not None:
                    pf.sell(pos, sym, fill)
        eq_close = pf.equity("close", pos)
        pf.curve.append((d, eq_close))
        touched = pf.floor_check(eq_close)
        if touched and t == last_t:
            pf.halted = True
            pf.halt_date = d
            break
        if t == last_t:
            break
        for sym in list(pf.lots):
            ma = A[sym]["sma20"][pos]
            if not np.isnan(ma) and A[sym]["close"][pos] < ma:
                pending_exits.append(sym)
        if placebo_schedule is None:
            if (not gated) or gate_open(pos):
                for sym in UNIVERSE:
                    if sym in pf.lots:
                        continue
                    if breakout(pos, sym, confirmed):
                        pending_entries.append(sym)
    return pf


def summarize(pf):
    curve = [(None, START)] + pf.curve
    final = curve[-1][1]
    peak, max_dd = START, 0.0
    for _, e in curve:
        peak = max(peak, e)
        if peak > 0:
            max_dd = max(max_dd, (peak - e) / peak)
    wins = [p for p in pf.round_trips if p > 0]
    return {"final": round(final, 2),
            "total_pct": round((final / START - 1) * 100, 2),
            "max_dd_pct": round(max_dd * 100, 2),
            "costs": round(pf.costs, 2), "orders": pf.orders,
            "entries": pf.entries, "closed_trades": len(pf.round_trips),
            "win_rate_pct": (round(100 * len(wins) / len(pf.round_trips), 1)
                             if pf.round_trips else None),
            "halt_date": (pf.halt_date.isoformat() if pf.halted else None)}


def spy_net(idxs):
    o = A["SPY"]["open"][idxs[0]]
    c = A["SPY"]["close"][idxs[-1]]
    buy_value = START / (1 + COST)
    sell_value = (buy_value / o) * c
    return round(sell_value - (COST * sell_value + FEE), 2)


def entries_by_year(pf, idxs):
    # entries counted from curve-independent log: recompute via trades is
    # not kept; use entries per year tracked during run -> stored on pf
    return pf.entries_by_year


def run_placebo_matched(idxs, target_by_year, seed):
    """v3 fixed placebo; attempts only on gate-open fill days (gate read
    from the prior test day's close, as the real signal saw it)."""
    rng = np.random.default_rng(seed)
    date_of = {DATES[p]: i for i, p in enumerate(idxs)}
    days_by_year = {}
    for t in range(1, len(idxs) - 1):
        if gate_open(idxs[t - 1]):
            d = DATES[idxs[t]]
            days_by_year.setdefault(d.year, []).append(d)
    schedule = {}

    def add_attempts(year, n):
        days = days_by_year.get(year, [])
        if not days:
            return
        for _ in range(n):
            d = days[rng.integers(0, len(days))]
            i = date_of[d]
            while len(schedule.get(d, [])) >= 2 and i < len(idxs) - 1:
                i += 1
                d = DATES[idxs[i]]
            sym = UNIVERSE[rng.integers(0, len(UNIVERSE))]
            schedule.setdefault(d, []).append(sym)

    for year, target in sorted(target_by_year.items()):
        add_attempts(year, target)
    pf, actual = None, {}
    for _ in range(60):
        pf = run_strategy(idxs, stop_pct=STOP_MINE,
                          placebo_schedule=schedule)
        actual = pf.entries_by_year
        missing = {y: target_by_year.get(y, 0) - actual.get(y, 0)
                   for y in target_by_year}
        if all(v <= 0 for v in missing.values()):
            break
        for year, miss in missing.items():
            if miss > 0:
                add_attempts(year, miss)
    return pf, {"seed": int(seed),
                "attempts": int(sum(len(v) for v in schedule.values())),
                "target_by_year": {str(k): v for k, v in target_by_year.items()},
                "actual_by_year": {str(k): v for k, v in actual.items()}}


# track entries by year inside FastPF.buy via a hook on date: simpler —
# patch: wrap run_strategy to record entry years from lots creation.
_orig_buy = FastPF.buy


def _buy_tracked(self, pos, sym, price, target):
    ok = _orig_buy(self, pos, sym, price, target)
    if ok:
        y = DATES[pos].year
        self.entries_by_year[y] = self.entries_by_year.get(y, 0) + 1
    return ok


FastPF.buy = _buy_tracked
_orig_init = FastPF.__init__


def _init_tracked(self, use_floor):
    _orig_init(self, use_floor)
    self.entries_by_year = {}


FastPF.__init__ = _init_tracked


def monthly_stats(curve):
    pts = list(curve)
    by_month = {}
    for d, e in pts:
        by_month[(d.year, d.month)] = e
    months = sorted(by_month)
    rets, prev = [], START
    for k in months:
        e = by_month[k]
        rets.append(e / prev - 1.0)
        prev = e
    rets = np.array(rets)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0
        streak = max(streak, cur)
    peak, peak_i, longest = -1.0, 0, 0
    for i, (_, e) in enumerate(pts):
        if e >= peak:
            peak, peak_i = e, i
        else:
            longest = max(longest, i - peak_i)
    return {"n_months": int(len(rets)),
            "median_month_pct": round(float(np.median(rets)) * 100, 2),
            "share_months_positive_pct": round(float((rets > 0).mean()) * 100, 1),
            "best_month_pct": round(float(rets.max()) * 100, 2),
            "worst_month_pct": round(float(rets.min()) * 100, 2),
            "longest_losing_streak_months": int(streak),
            "longest_stretch_between_new_highs_days": int(longest),
            "mean_month_pct_secondary": round(float(rets.mean()) * 100, 2)}


def main():
    print("data loaded", flush=True)
    out = {"family": "breakout-validation",
           "spec": "v13 best rules: 252-high entry + volume>=1.5x prior-50d mean + SPY>200d entry gate; max2@50%; SMA20 exit; -10% stop; no floor",
           "roads": {}}

    # ---------- integrity: original form must reproduce v3 ----------
    idx_full = window_idx(ROADS["DECADE"])
    pf = run_strategy(idx_full, stop_pct=STOP_ORIG, use_floor=True)
    r = summarize(pf)
    idx_val = window_idx(ROADS["VAL"])
    pfv = run_strategy(idx_val, stop_pct=STOP_ORIG, use_floor=True)
    rv = summarize(pfv)
    integ = {"full_final": r["final"], "full_expected": 383.36,
             "val_final": rv["final"], "val_expected": 124.82,
             "val_halt": rv["halt_date"], "val_halt_expected": "2026-08-14"}
    integ["ok"] = (r["final"] == 383.36 and rv["final"] == 124.82
                   and rv["halt_date"] == "2026-08-14")
    out["integrity"] = integ
    print("INTEGRITY:", integ, flush=True)
    if not integ["ok"]:
        print("INTEGRITY FAILED — aborting before any v13 number.", flush=True)
        with open(os.path.join(HERE, "results.json"), "w") as fh:
            json.dump(out, fh, indent=2, default=str)
        sys.exit(1)

    # ---------- my rules on the three roads ----------
    for name, window in ROADS.items():
        idxs = window_idx(window)
        pf = run_strategy(idxs, confirmed=True, gated=True,
                          stop_pct=STOP_MINE)
        r = summarize(pf)
        target = pf.entries_by_year
        twins, metas = [], []
        for k in range(20):
            ppf, meta = run_placebo_matched(idxs, target, seed=3100 + k)
            twins.append(summarize(ppf)["final"])
            metas.append(meta)
            print(f"  {name} placebo {k+1}/20 done", flush=True)
        beaten = sum(1 for x in twins if r["final"] > x)
        year_end = {}
        for d, e in pf.curve:
            year_end[str(d.year)] = round(e, 2)
        rec = {"window": [window[0].isoformat(), window[1].isoformat()],
               "result": r, "spy_net_price_basis": spy_net(idxs),
               "placebo_beaten": f"{beaten}/20", "placebo_finals": twins,
               "placebo_median": round(float(np.median(twins)), 2),
               "placebo_meta_first": metas[0],
               "year_end_equity": year_end,
               "curve": [[d.isoformat(), round(e, 4)]
                         for d, e in [(DATES[idxs[0]], START)] + pf.curve]}
        if name == "DECADE":
            rec["monthly_distribution"] = monthly_stats(
                [(DATES[idxs[0]], START)] + list(pf.curve))
        out["roads"][name] = rec
        print(f"{name}: mine ${r['final']} DD {r['max_dd_pct']}% costs "
              f"${r['costs']} trades {r['closed_trades']} win "
              f"{r['win_rate_pct']}% | SPYnet ${spy_net(idxs)} | placebo "
              f"{beaten}/20", flush=True)

    # ---------- per-year fresh-pot folds (my rules) ----------
    folds = {}
    for y in range(2017, 2027):
        w = (date(y, 1, 1), date(y, 12, 31)) if y < 2026 else \
            (date(2026, 1, 1), date(2026, 11, 20))
        idxs = window_idx(w)
        pf = run_strategy(idxs, confirmed=True, gated=True,
                          stop_pct=STOP_MINE)
        r = summarize(pf)
        folds[str(y)] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"],
                         "spy_net_price_basis": spy_net(idxs),
                         "closed_trades": r["closed_trades"],
                         "entries": r["entries"]}
        print(f"FOLD {y}: mine ${r['final']} vs SPYnet ${spy_net(idxs)}",
              flush=True)
    out["year_folds_mine"] = folds

    # ---------- confirmation, only if a champion road fell ----------
    triggered = [n for n in ROADS
                 if out["roads"][n]["result"]["final"] > CHAMPION_VM[n]]
    out["confirmation_triggered_on"] = triggered
    if triggered:
        conf = {}
        for label, w in (("DESIGN", DESIGN), ("HALF1", HALF1),
                         ("HALF2", HALF2)):
            idxs = window_idx(w)
            pf = run_strategy(idxs, confirmed=True, gated=True,
                              stop_pct=STOP_MINE)
            r = summarize(pf)
            conf[label] = {"final": r["final"],
                           "spy_net_price_basis": spy_net(idxs),
                           "beat_spy": bool(r["final"] > spy_net(idxs))}
        out["confirmation"] = conf
        print("CONFIRMATION:", conf, flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(out, fh, indent=2, default=str)
    print("saved results.json", flush=True)


if __name__ == "__main__":
    main()
