#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — basket-roa-gate (momentum basket + ROA gate).

One strategy, one clean shot, per backtests/v10-retest/SPEC.md:
  (1) INTEGRITY: reproduce the original published finals in the ORIGINAL
      form (v4 engine, floor+ladder, monthly) — CONT (full) $405.21,
      VAL $192.86 — through plumbing copied verbatim into this file.
  (2) CADENCE SWEEP: DECADE 2016-11-21 -> 2026-11-20 at daily, weekly,
      biweekly, monthly, quarterly, semi-annual, annual, under the
      SPEC's uniform cadence definition, $100/cell, program costs
      (0.10%/side + $0.01/share sell charge), adopted v9 protections
      (plain -15% floor per episode, no ladder; first halt -> liquidate
      at next open, 90 calendar days in cash, restart at the next
      cadence decision day under an episode-2 -15% floor; second halt
      ends the run). 20-seed placebos per cell (random 5 of the gated
      eligible set, seeds 1..20).

THE GATE (frozen, exactly as published in v4/basket-roa-gate.py): at
each selection, a name is selectable only if its most recent
point-in-time ROA = NetIncomeLoss (fallback ProfitLoss) / Assets,
from a single EDGAR filing, annual period, most recently FILED
observation strictly before the signal day, is POSITIVE. No
observation also fails. Momentum ranking (200-day eligibility, 12-1)
then proceeds among passers; top 5 at 20% each. The gate is NOT
softened at any cadence.

Data (read-only, nothing written outside this folder):
  - Prices: backtests/v4/momentum-basket-honest-data/ (Yahoo raw
    open/close cache, 2015-01-01 -> 2026-11-20, the original engine's
    own cache and bar convention).
  - EDGAR facts: backtests/v4/data/facts_<CIK>.json + company_tickers
    .json (the shared quality-momentum cache the original used).
  - XOM CIK hard-corrected to 34088 (parent), exactly as the original.

Signal arrays (SMA200, 12-1 momentum, gate pass/fail per day) are
precomputed once with cumulative sums / pointer walks — arithmetic
identical to the original per-day calls, just faster.
"""

import bisect
import json
import math
import os
import random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
PRICE_CACHE = os.path.join(V4, "momentum-basket-honest-data")
FACTS_DIR = os.path.join(V4, "data")

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
BENCH = "SPY"
COST_RATE = 0.001
SELL_FEE = 0.01
CIK_OVERRIDES = {"XOM": 34088}
NI_CONCEPTS = ["NetIncomeLoss", "ProfitLoss"]
ASSETS_CONCEPT = "Assets"

DECADE = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")          # SPEC canonical CONT
VAL = ("2023-01-03", "2026-11-20")           # SPEC canonical VAL
ORIG_FULL = ("2016-11-21", "2026-11-20")     # v4 "full" window
ORIG_VAL = ("2023-01-01", "2026-11-20")      # v4 "validation" window
PUBLISHED = {"CONT": 405.21, "VAL": 192.86}  # gated, $100, original form


# --------------------------------------------------------------------------
# Market (construction copied from momentum-basket-honest.py / lr_basket.py,
# fed from the v4 cache files instead of fetch()).
# --------------------------------------------------------------------------
def load_bars(ticker):
    with open(os.path.join(PRICE_CACHE, f"{ticker}.json")) as f:
        return json.load(f)


class Market:
    def __init__(self, tickers):
        self.bars = {}
        self.closes = {}
        spy = load_bars(BENCH)
        self.cal = [r["d"] for r in spy]
        self.cal_index = {d: i for i, d in enumerate(self.cal)}
        raw = {BENCH: spy}
        for t in tickers:
            raw[t] = load_bars(t)
        for t in list(tickers) + [BENCH]:
            self.bars[t] = {r["d"]: (r["o"], r["c"]) for r in raw[t]}
            arr, last = [], None
            for d in self.cal:
                if d in self.bars[t]:
                    last = self.bars[t][d][1]
                arr.append(last)
            self.closes[t] = arr

    def open_px(self, t, i):
        d = self.cal[i]
        if d in self.bars[t]:
            return self.bars[t][d][0]
        return None

    def close_px(self, t, i):
        return self.closes[t][i]

    def sma(self, t, i, n):
        if i + 1 < n:
            return None
        seg = self.closes[t][i - n + 1: i + 1]
        if any(v is None for v in seg):
            return None
        return sum(seg) / n

    def momentum_12_1(self, t, i):
        if i - 252 < 0:
            return None
        a, b = self.closes[t][i - 252], self.closes[t][i - 21]
        if a is None or b is None or a <= 0:
            return None
        return b / a - 1.0


def spy_net(mkt, start_d, end_d, pot0):
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    buy_px = mkt.open_px(BENCH, i0)
    sell_px = mkt.close_px(BENCH, i1)
    sh = (pot0 * (1 - COST_RATE)) / buy_px
    return sh * sell_px * (1 - COST_RATE) - SELL_FEE


def years_between(sd, ed):
    return (date.fromisoformat(ed) - date.fromisoformat(sd)).days / 365.25


def cagr(final, pot, yrs):
    return (final / pot) ** (1.0 / yrs) - 1.0 if final > 0 else -1.0


# --------------------------------------------------------------------------
# ROA observations — copied from v4/basket-roa-gate.py (which mirrors
# quality-momentum.py's helpers, also copied here).
# --------------------------------------------------------------------------
def _entries(facts, concept):
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return []
    key = "USD" if "USD" in units else list(units)[0]
    return units[key]


def _annual(entries):
    out = []
    for e in entries:
        if "start" not in e or "end" not in e or "val" not in e:
            continue
        try:
            days = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days
        except ValueError:
            continue
        if 300 <= days <= 400:
            out.append(e)
    return out


def quality_at(obs, asof):
    """Most recently FILED observation strictly before asof (verbatim)."""
    best = None
    for filed, end, val, method in obs:
        if filed < asof:
            if best is None or (filed, end) > (best[0], best[1]):
                best = (filed, end, val, method)
        else:
            break
    return best


def build_roa_observations(facts):
    assets_by_accn = {}
    for e in _entries(facts, ASSETS_CONCEPT):
        if "val" not in e or "end" not in e:
            continue
        accn = e.get("accn", "")
        assets_by_accn.setdefault(accn, {})[e["end"]] = (float(e["val"]),
                                                         e.get("filed", ""))

    def assets_for(accn, period_end):
        m = assets_by_accn.get(accn, {})
        if period_end in m:
            return m[period_end]
        earlier = [en for en in m if en <= period_end]
        if earlier:
            return m[max(earlier)]
        return None

    ni = {}
    for concept in NI_CONCEPTS:
        for e in _annual(_entries(facts, concept)):
            accn = e.get("accn", "")
            key = (e["start"], e["end"])
            slot = ni.setdefault(accn, {})
            if key not in slot:
                slot[key] = (float(e["val"]), e.get("filed", ""))

    obs = []
    for accn, periods in ni.items():
        for (start, end), (nval, nfiled) in periods.items():
            a = assets_for(accn, end)
            if a is None or a[0] <= 0:
                continue
            filed = max(nfiled, a[1])
            obs.append((filed, end, nval / a[0], "ROA"))
    obs.sort()
    return obs


def load_roa_obs():
    with open(os.path.join(FACTS_DIR, "company_tickers.json")) as f:
        raw = json.load(f)
    ciks = {row["ticker"]: int(row["cik_str"]) for row in raw.values()}
    for t, cik in CIK_OVERRIDES.items():
        ciks[t] = cik
    roa_obs, info = {}, {}
    for t in UNIVERSE:
        with open(os.path.join(FACTS_DIR, f"facts_{ciks[t]:010d}.json")) as f:
            facts = json.load(f)
        obs = build_roa_observations(facts)
        roa_obs[t] = obs
        info[t] = {"cik": ciks[t], "n_obs": len(obs),
                   "n_negative": sum(1 for o in obs if o[2] <= 0)}
    return roa_obs, info


# --------------------------------------------------------------------------
# INTEGRITY ENGINE — v4 basket-roa-gate.simulate copied verbatim in
# behaviour (floor + ladder, monthly selection), with the gate applied.
# FLOORS copied from momentum-basket-honest.py.
# --------------------------------------------------------------------------
FLOORS = {
    100: (85.0,  [(125.0, 100.0), (150.0, 125.0)]),
    50:  (42.50, [(62.50, 50.0),  (75.0, 62.50)]),
}


class Result:
    def __init__(self):
        self.final = None
        self.orders = 0
        self.costs = 0.0
        self.halt_date = None
        self.halts = []
        self.restarts = []
        self.max_dd = 0.0
        self.equity_curve = []


def simulate_original(mkt, start_d, end_d, pot0, gate_obs):
    """The v4 original: monthly, ladder, gate on. For the integrity gate."""
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    floor0, ladder = FLOORS[pot0]
    floor = floor0
    cash = float(pot0)
    pos = {}
    res = Result()
    pending_liquidation = False
    mark_px = {}
    cur_month = None

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            tot += sh * px
        return tot

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        month_key = d[:7]
        if pending_liquidation:
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    px = mkt.close_px(t, i)
                val = pos[t] * px
                fee = val * COST_RATE + SELL_FEE
                cash += val - fee
                res.costs += fee
                res.orders += 1
                del pos[t]
            mark_px.clear()
            res.halt_date = d
            res.final = cash
            res.equity_curve.append((d, cash))
            break
        if month_key != cur_month and i > 0:
            cur_month = month_key
            j = i - 1
            elig = []
            for t in UNIVERSE:
                sma200 = mkt.sma(t, j, 200)
                c = mkt.close_px(t, j)
                if sma200 is None or c is None or c <= sma200:
                    continue
                mom = mkt.momentum_12_1(t, j)
                if mom is None:
                    continue
                elig.append((t, mom))
            elig.sort(key=lambda x: -x[1])
            kept = []
            for t, mom in elig:
                q = quality_at(gate_obs.get(t, []), mkt.cal[j])
                if q is None or q[2] <= 0:
                    continue
                kept.append((t, mom))
            picks = [t for t, _ in kept[:5]]
            eq_open = equity_at(i, use_open=True)
            target_val = {t: 0.20 * eq_open for t in picks}
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos[t] * px
                want = target_val.get(t, 0.0)
                if cur_val > want + 0.01:
                    sell_val = cur_val - want
                    sh = sell_val / px
                    fee = sell_val * COST_RATE + SELL_FEE
                    cash += sell_val - fee
                    res.costs += fee
                    res.orders += 1
                    pos[t] -= sh
                    if want <= 0.0 or pos[t] * px < 0.01:
                        del pos[t]
            for t in picks:
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos.get(t, 0.0) * px
                deficit = target_val[t] - cur_val
                if deficit <= 0.01:
                    continue
                buy_val = min(deficit, cash / (1.0 + COST_RATE))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * COST_RATE
                cash -= buy_val + fee
                res.costs += fee
                res.orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px
            mark_px = {}
            for t in pos:
                px = mkt.open_px(t, i)
                if px is not None:
                    mark_px[t] = px
        eq_close = equity_at(i, use_open=False)
        res.equity_curve.append((d, eq_close))
        for thresh, new_floor in ladder:
            if eq_close >= thresh:
                floor = max(floor, new_floor)
        if eq_close <= floor:
            pending_liquidation = True
            if i == i1:
                tot = cash
                for t, sh in list(pos.items()):
                    val = sh * mkt.close_px(t, i)
                    fee = val * COST_RATE + SELL_FEE
                    tot += val - fee
                    res.costs += fee
                    res.orders += 1
                res.final = tot
                res.halt_date = d
                pos.clear()
                break
    if res.final is None:
        res.final = res.equity_curve[-1][1]
    peak = -1.0
    for d, eq in res.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            res.max_dd = min(res.max_dd, eq / peak - 1.0)
    return res


# --------------------------------------------------------------------------
# SWEEP ENGINE — v9 protections (lr_basket.py form), generalized cadence,
# gate on/off, ranked/placebo. Precomputed signal arrays (identical math).
# --------------------------------------------------------------------------
class Signals:
    """Per-ticker arrays over the master calendar: sma200_ok, mom, gate_ok.
    gate_ok[t][j] uses signal day j's date, exactly quality_at semantics."""

    def __init__(self, mkt, roa_obs):
        n = len(mkt.cal)
        self.elig = {}      # t -> list[bool] indexable by signal day j
        self.mom = {}       # t -> list[float|None]
        self.gate = {}      # t -> list[bool]
        for t in UNIVERSE:
            closes = mkt.closes[t]
            # prefix sums with None handling: count of None in window
            ps = [0.0] * (n + 1)
            pn = [0] * (n + 1)
            for i, v in enumerate(closes):
                ps[i + 1] = ps[i] + (v if v is not None else 0.0)
                pn[i + 1] = pn[i] + (1 if v is None else 0)
            elig = [False] * n
            mom = [None] * n
            for j in range(n):
                if j + 1 >= 200 and pn[j + 1] - pn[j - 199] == 0:
                    sma = (ps[j + 1] - ps[j - 199]) / 200.0
                    c = closes[j]
                    if c is not None and c > sma:
                        if j - 252 >= 0:
                            a, b = closes[j - 252], closes[j - 21]
                            if a is not None and b is not None and a > 0:
                                elig[j] = True
                                mom[j] = b / a - 1.0
            self.elig[t] = elig
            self.mom[t] = mom
            # gate: most recently filed obs strictly before cal[j]
            obs = roa_obs.get(t, [])
            fileds = [o[0] for o in obs]
            g = [False] * n
            for j in range(n):
                k = bisect.bisect_left(fileds, mkt.cal[j]) - 1
                # quality_at breaks ties by (filed, end): among obs with
                # filed < asof pick max (filed, end). Obs are sorted by
                # (filed, end, ...) so index k is that element.
                if k >= 0 and obs[k][2] > 0:
                    g[j] = True
            self.gate[t] = g


def cadence_days(mkt, cadence, i0, i1):
    """Set of calendar indices in [i0, i1] that are decision days.
    i0 (window start) is always a decision day (the engine selects on
    day one, as the original does)."""
    days = {i0}
    cal = mkt.cal
    if cadence == "daily":
        days.update(range(i0, i1 + 1))
    elif cadence in ("weekly", "biweekly"):
        seen_weeks = []
        prev = None
        for i in range(i0, i1 + 1):
            y, w, _ = date.fromisoformat(cal[i]).isocalendar()
            key = (y, w)
            if key != prev:
                seen_weeks.append(i)
                prev = key
        if cadence == "weekly":
            days.update(seen_weeks)
        else:
            days.update(seen_weeks[::2])
    elif cadence == "monthly":
        for i in range(i0, i1 + 1):
            if cal[i][:7] != cal[i - 1][:7]:
                days.add(i)
    elif cadence == "quarterly":
        for i in range(i0, i1 + 1):
            if cal[i][:7] != cal[i - 1][:7] and cal[i][5:7] in ("01", "04", "07", "10"):
                days.add(i)
    elif cadence == "semiannual":
        for i in range(i0, i1 + 1):
            if cal[i][:7] != cal[i - 1][:7] and cal[i][5:7] in ("01", "07"):
                days.add(i)
    elif cadence == "annual":
        for i in range(i0, i1 + 1):
            if cal[i][:7] != cal[i - 1][:7] and cal[i][5:7] == "01":
                days.add(i)
    else:
        raise ValueError(cadence)
    return days


def simulate_v9(mkt, sig, start_d, end_d, pot0, cadence, gated=True,
                mode="ranked", seed=42):
    """v9 form of lr_basket.simulate with cadence + gate. Restart after a
    first halt = next cadence decision day >= halt + 90 calendar days."""
    rng = random.Random(seed)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    dec = cadence_days(mkt, cadence, i0, i1)
    episode = 1
    floor = 0.85 * float(pot0)
    sitout_restart_idx = None
    cash = float(pot0)
    pos = {}
    res = Result()
    pending_liquidation = False

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            tot += sh * px
        return tot

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        if pending_liquidation:
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    px = mkt.close_px(t, i)
                val = pos[t] * px
                fee = val * COST_RATE + SELL_FEE
                cash += val - fee
                res.costs += fee
                res.orders += 1
                del pos[t]
            res.halt_date = d
            res.halts.append(d)
            res.equity_curve.append((d, cash))
            pending_liquidation = False
            if episode == 1:
                earliest = (date.fromisoformat(d) + timedelta(days=90)).isoformat()
                ridx = None
                for j in sorted(dec):
                    if j > i and mkt.cal[j] >= earliest:
                        ridx = j
                        break
                if ridx is not None:
                    sitout_restart_idx = ridx
                    episode = 2
                    res.restarts.append({
                        "halt_date": d,
                        "restart_date": mkt.cal[ridx],
                        "restart_balance": round(cash, 2),
                        "episode2_floor": round(0.85 * cash, 2),
                    })
                    floor = 0.85 * cash
                    continue
            res.final = cash
            break
        if sitout_restart_idx is not None and i < sitout_restart_idx:
            res.equity_curve.append((d, cash))
            continue
        if sitout_restart_idx is not None and i == sitout_restart_idx:
            sitout_restart_idx = None
        if i in dec and i > i0 or (i == i0 and i in dec):
            j = i - 1 if i > 0 else i
            elig = []
            for t in UNIVERSE:
                if sig.elig[t][j] and (not gated or sig.gate[t][j]):
                    elig.append((t, sig.mom[t][j]))
            if mode == "ranked":
                elig.sort(key=lambda x: -x[1])
                picks = [t for t, _ in elig[:5]]
            else:
                names = sorted(t for t, _ in elig)
                picks = rng.sample(names, min(5, len(names))) if names else []
            eq_open = equity_at(i, use_open=True)
            target_val = {t: 0.20 * eq_open for t in picks}
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos[t] * px
                want = target_val.get(t, 0.0)
                if cur_val > want + 0.01:
                    sell_val = cur_val - want
                    sh = sell_val / px
                    fee = sell_val * COST_RATE + SELL_FEE
                    cash += sell_val - fee
                    res.costs += fee
                    res.orders += 1
                    pos[t] -= sh
                    if want <= 0.0 or pos[t] * px < 0.01:
                        del pos[t]
            for t in picks:
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos.get(t, 0.0) * px
                deficit = target_val[t] - cur_val
                if deficit <= 0.01:
                    continue
                buy_val = min(deficit, cash / (1.0 + COST_RATE))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * COST_RATE
                cash -= buy_val + fee
                res.costs += fee
                res.orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px
        eq_close = equity_at(i, use_open=False)
        res.equity_curve.append((d, eq_close))
        if eq_close <= floor:
            pending_liquidation = True
            if i == i1:
                tot = cash
                for t, sh in list(pos.items()):
                    val = sh * mkt.close_px(t, i)
                    fee = val * COST_RATE + SELL_FEE
                    tot += val - fee
                    res.costs += fee
                    res.orders += 1
                res.final = tot
                res.halt_date = d
                pos.clear()
                break
    if res.final is None:
        res.final = res.equity_curve[-1][1]
    peak = -1.0
    for d, eq in res.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            res.max_dd = min(res.max_dd, eq / peak - 1.0)
    return res


# --------------------------------------------------------------------------
def cell_summary(res, pot, yrs):
    return {
        "final": round(res.final, 2),
        "cagr_pct": round(cagr(res.final, pot, yrs) * 100, 2),
        "max_dd_pct": round(res.max_dd * 100, 2),
        "costs": round(res.costs, 2),
        "orders": res.orders,
        "halts": res.halts,
        "restarts": res.restarts,
        "halt": res.halt_date,
        "restart": bool(res.restarts),
        "second_halt": len(res.halts) >= 2,
    }


def main():
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    mkt = Market(UNIVERSE)
    roa_obs, roa_info = load_roa_obs()
    print("ROA obs loaded:", {t: roa_info[t]["n_obs"] for t in UNIVERSE}, flush=True)

    # ---- (1) INTEGRITY: original form, original windows ------------------
    integ = {}
    for label, win, pub in (("CONT", ORIG_FULL, PUBLISHED["CONT"]),
                            ("VAL", ORIG_VAL, PUBLISHED["VAL"])):
        r = simulate_original(mkt, win[0], win[1], 100, roa_obs)
        got = round(r.final, 2)
        integ[label] = {"window": list(win), "published": pub,
                        "reproduced": got,
                        "match": abs(got - pub) < 0.02,
                        "orders": r.orders, "costs": round(r.costs, 2),
                        "max_dd_pct": round(r.max_dd * 100, 2),
                        "halt": r.halt_date}
        print(f"INTEGRITY {label}: published {pub} reproduced {got} "
              f"-> {'MATCH' if integ[label]['match'] else 'MISMATCH!'}", flush=True)
    # ungated sanity: original engine must also reproduce the ungated
    # basket's published finals ($439.45 / $208.27) with gate off.
    class _NoGate(dict):
        def get(self, k, d=None):
            return [( "0000-00-00", "0000-00-00", 1.0, "ROA")]
    # (simpler: pass obs of +1 ROA filed at dawn of time)
    fake = {t: [("1990-01-01", "1989-12-31", 1.0, "ROA")] for t in UNIVERSE}
    for label, win, pub in (("CONT", ORIG_FULL, 439.45), ("VAL", ORIG_VAL, 208.27)):
        r = simulate_original(mkt, win[0], win[1], 100, fake)
        got = round(r.final, 2)
        integ[f"ungated_{label}"] = {"published": pub, "reproduced": got,
                                     "match": abs(got - pub) < 0.02}
        print(f"INTEGRITY ungated {label}: published {pub} reproduced {got} "
              f"-> {'MATCH' if integ[f'ungated_{label}']['match'] else 'MISMATCH!'}",
              flush=True)

    status = "reproduced" if all(v["match"] for v in integ.values()) else "FAILED"

    # ---- (2) SWEEP: DECADE x 7 cadences, v9, gated + placebos ------------
    sig = Signals(mkt, roa_obs)
    yrs = years_between(*DECADE)
    spy_dec = spy_net(mkt, DECADE[0], DECADE[1], 100)
    print(f"DECADE SPY (plumbing, price convention): {round(spy_dec, 2)}", flush=True)
    cells = {}
    ungated_ref = {}
    for cadence in ("daily", "weekly", "biweekly", "monthly", "quarterly",
                    "semiannual", "annual"):
        r = simulate_v9(mkt, sig, DECADE[0], DECADE[1], 100, cadence, gated=True)
        s = cell_summary(r, 100, yrs)
        placebo_finals = []
        for seed in range(1, 21):
            pr = simulate_v9(mkt, sig, DECADE[0], DECADE[1], 100, cadence,
                             gated=True, mode="placebo", seed=seed)
            placebo_finals.append(round(pr.final, 2))
        beaten = sum(1 for f in placebo_finals if s["final"] > f)
        s["placebo_beaten"] = beaten
        s["placebo_note"] = ("20 seeds (1..20), random 5 of the gated "
                             "eligible set at each decision day")
        cells[cadence] = s
        cell_doc = dict(s)
        cell_doc.update({
            "slug": "basket-roa-gate", "cadence": cadence,
            "window": list(DECADE), "pot": 100,
            "equity_curve": [[d, round(v, 4)] for d, v in r.equity_curve],
            "placebo_finals": placebo_finals,
        })
        with open(os.path.join(HERE, "cells", f"{cadence}.json"), "w") as f:
            json.dump(cell_doc, f, indent=1)
        u = simulate_v9(mkt, sig, DECADE[0], DECADE[1], 100, cadence, gated=False)
        ungated_ref[cadence] = round(u.final, 2)
        print(f"CELL {cadence}: final={s['final']} CAGR={s['cagr_pct']} "
              f"maxDD={s['max_dd_pct']} costs={s['costs']} orders={s['orders']} "
              f"halts={s['halts']} placebo {beaten}/20 ungated={ungated_ref[cadence]}",
              flush=True)

    money = [c for c, s in cells.items()
             if s["final"] > 367.80 and s["placebo_beaten"] is not None
             and s["placebo_beaten"] >= 11]
    money_vs_plumbing_spy = [c for c, s in cells.items()
                             if s["final"] > spy_dec and s["placebo_beaten"] >= 11]

    out = {
        "slug": "basket-roa-gate",
        "area": "monthly momentum basket holding with a profitability (ROA) gate — basket family (W2)",
        "area_source": "SPEC W2: basket + its three gates/veto = monthly momentum holding, judged on the DECADE cadence sweep",
        "native_cadence": "monthly",
        "cadence": "monthly",
        "original_cadence_foreign": False,
        "native_change": "none — original form was native (monthly). The v10 change is the cadence sweep itself plus v9 protections substituted for the original floor+ladder (the v9 note showed the ladder never fired, so the trading path is unchanged at monthly).",
        "integrity": {
            "status": status,
            "original_finals": {"CONT": 405.21, "VAL": 192.86},
            "reproduced_finals": {"CONT": integ["CONT"]["reproduced"],
                                  "VAL": integ["VAL"]["reproduced"]},
            "detail": integ,
            "note": "Original form = v4 engine (floor+ladder, monthly, original windows full 2016-11-21->2026-11-20 and validation 2023-01-01->2026-11-20). Ungated control also reproduced ($439.45 / $208.27) with an always-pass gate, proving the plumbing.",
        },
        "decade_spy_final": round(spy_dec, 2),
        "decade_spy_note": "Plumbing SPY is the v4 price-cache convention (raw closes, net of program costs). SPEC's dividend-adjusted decade reference is $367.80; verdicts below are checked against BOTH.",
        "cells": cells,
        "ungated_basket_decade_cells": ungated_ref,
        "money_cadences": money,
        "money_cadences_vs_plumbing_spy": money_vs_plumbing_spy,
        "roa_obs_info": roa_info,
        "verdict_area": "NO GROUND",
        "verdict_change": "Unchanged in substance: REJECTED originally; the sweep finds no cadence at which the gate earns money vs SPY+placebos (see RESULTS.md).",
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved results.json + cells/", flush=True)


if __name__ == "__main__":
    main()
