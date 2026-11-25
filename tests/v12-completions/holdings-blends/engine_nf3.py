#!/usr/bin/env python3
"""
COMBO V+M x N-F3 50/50 — THE GREAT RETEST (v10), cadence sweep.
Simulation only. Terry's AI stock app.

Strategy: ONE $100 pot, two 50/50 sleeves — $50 value+momentum (the
champion, exactly as promoted) + $50 N-F3 "Paying in Stock" (exactly
as frozen) — sleeve weights reset to 50/50 at every selection date,
one combined plain -15% floor. Original: backtests/v8/combo-vm-nf3/
(published CONT $532.39 / VAL $290.45, verdict: dilution). v9 folder:
backtests/v9-muse-rules/combo-vm-nf3/ (main windows identical under
v9 — floor never fired; folds re-run under v9).

THIS SCRIPT (v10):
  PHASE 1 — INTEGRITY: reproduce the ORIGINAL published finals in
  ORIGINAL form (quarterly, single plain floor, original engine code
  copied verbatim from the v8 script, original price cache): combo
  CONT/VAL, both parents standalone, 20-seed placebos, yearly folds
  under his rules and under v9.
  PHASE 2 — SWEEP: DECADE 2016-11-21 -> 2026-11-20, $100/cell,
  program costs, v9 protections, at 7 cadences. CADENCE TREATMENT
  (per SPEC uniform definition, stated for this combo): cadence
  governs BOTH legs uniformly — on each cadence date both sleeves
  re-rank their own signal, re-pick their top-5, rebalance, and the
  50/50 sleeve reset happens on that same date; execution at the
  next open, champion mechanics in both sleeves; the combined floor
  is still checked on every trading day's close. Native cadence =
  quarterly (both legs).
  Prices for the sweep: the champion cache (2017-06-01 onward,
  reused read-only, verbatim) spliced with Yahoo bars downloaded
  into THIS folder for 2014-01-01 -> 2017-05-31, same adjclose
  method as the champion engine; the pre-2017 segment of each
  ticker is scaled by one constant so its last pre-splice close
  equals the cached series' level (factor recorded in the run log;
  the post-2017 segment is the cached series untouched, so the
  quarterly CONT cross-check on the spliced book must — and does —
  reproduce the integrity numbers).

Speed-only changes (semantics identical, validated by Phase 1):
  - FastPriceBook: O(1) bar/close lookups via bisect (the original
    PriceBook scans the bar list linearly). Ranked CONT/VAL are run
    on BOTH books in Phase 1 and must agree to the cent.
  - pit_value results are memoized per (ticker, eligible-row-set):
    eligibility depends only on how many filed dates fall before
    the as-of date and before the 548-day freshness cutoff, so the
    cached value is exactly the original function's value.
  - N-F3 signal_at is memoized per (ticker, filing prefix): the
    signal depends on the as-of date only through the set of rows
    filed before it, which is a prefix of the filed-sorted rows of
    the SBC + revenue concepts; identical prefix -> identical signal.

One clean shot, no tuning. Writes only inside this folder.
"""
import bisect
import importlib.util
import json
import math
import os
import random
import sys
import time
import urllib.request
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
V8 = os.path.expanduser("~/workspace/stock-app/backtests/v8")
MYDATA = os.path.expanduser(
    "~/workspace/stock-app/backtests/v10-retest/combo-vm-nf3/data")
os.makedirs(MYDATA, exist_ok=True)
os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


champ = _load("champ", os.path.join(V4, "value-momentum-plainfloor.py"))
nf3 = _load("nf3", os.path.join(
    V8, "novel-f3-paying-in-stock", "novel-f3-paying-in-stock.py"))

UNIVERSE = champ.UNIVERSE
PLACEBO_SEEDS = list(range(1, 21))
START_CASH = 100.0
DECADE = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")


def log(*a):
    print(*a, flush=True)


# ------------------------------------------------------------ fast book
class FastPriceBook:
    """Same interface/semantics as champ.PriceBook, O(1) lookups."""

    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values()
                             for b in bl})
        self.idx = {t: {b["d"]: b for b in bl}
                    for t, bl in bars_by_ticker.items()}
        self._dl = {t: [b["d"] for b in bl]
                    for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return None
        i = bisect.bisect_right(dl, d) - 1
        if i < 0:
            return None
        return self.bars[t][i]["c"]

    def next_open(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return None, None
        i = bisect.bisect_right(dl, d)
        if i >= len(dl):
            return None, None
        b = self.bars[t][i]
        return b["d"], b["o"]


# ------------------------------------------------------------- scoring
def _ord(s):
    return _date(int(s[:4]), int(s[5:7]), int(s[8:10])).toordinal()


class Scorer:
    """Memoized per-date scores for both sleeves. vm() is the
    champion's scoring block verbatim except pit_value goes through
    an eligibility-key cache (identical values). nf3() calls the
    frozen module's signal_at, memoized per filing prefix."""

    def __init__(self, pb, equity_rows, shares_rows, facts_by_ticker):
        self.pb = pb
        self.equity_rows = equity_rows
        self.shares_rows = shares_rows
        self.facts = facts_by_ticker
        self.pos_idx = {t: {b["d"]: i for i, b in enumerate(pb.bars[t])}
                        for t in pb.bars}
        self._vm = {}
        self._nf3 = {}
        self._pit_cache = {}
        self._filed_ords = {}
        for t in UNIVERSE:
            for kind, rows in (("eq", equity_rows.get(t, [])),
                               ("sh", shares_rows.get(t, []))):
                self._filed_ords[(t, kind)] = sorted(r[0] for r in rows)
        # N-F3 filing prefixes: filed dates of SBC + revenue rows
        self._nf3_filed = {}
        self._nf3_cache = {}
        for t in UNIVERSE:
            fdates = []
            for concept in [nf3.SBC_CONCEPT] + list(nf3.REVENUE_CHAIN):
                for e in nf3.concept_rows(facts_by_ticker[t], concept):
                    fdates.append(e["filed"])
            self._nf3_filed[t] = sorted(fdates)

    def _pit(self, t, kind, rows, d):
        filed = self._filed_ords[(t, kind)]
        k1 = bisect.bisect_left(filed, d)          # rows filed < d
        cutoff = _date.fromordinal(_ord(d) - 548).isoformat()
        k2 = bisect.bisect_left(filed, cutoff)     # rows too old
        key = (t, kind, k1, k2)
        if key not in self._pit_cache:
            self._pit_cache[key] = champ.pit_value(rows, d)
        return self._pit_cache[key]

    def vm(self, d):
        if d in self._vm:
            return self._vm[d]
        pb = self.pb
        scores = {}
        for t in UNIVERSE:
            be = self._pit(t, "eq", self.equity_rows.get(t, []), d)
            so = self._pit(t, "sh", self.shares_rows.get(t, []), d)
            px = pb.close_on_or_before(t, d)
            if be is None or so is None or px is None or so[2] <= 0 \
                    or be[2] is None:
                continue
            mcap = so[2] * px
            if mcap <= 0:
                continue
            bm = be[2] / mcap
            bl = pb.bars.get(t, [])
            didx = self.pos_idx.get(t, {}).get(d)
            if didx is None or didx < 253:
                continue
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            scores[t] = (bm, mom)
        picks = []
        if len(scores) >= 5:
            vr = champ.percentile_ranks({t: v[0] for t, v in scores.items()})
            mr = champ.percentile_ranks({t: v[1] for t, v in scores.items()})
            combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
            picks = sorted(combined, key=lambda t: -combined[t])
        out = (scores, picks)
        self._vm[d] = out
        return out

    def _nf3_one(self, t, d):
        filed = self._nf3_filed[t]
        k = bisect.bisect_left(filed, d)
        key = (t, k)
        if key not in self._nf3_cache:
            stats = {"direct": 0, "derived": 0}
            self._nf3_cache[key] = nf3.signal_at(self.facts[t], d, stats)
        return self._nf3_cache[key]

    def nf3(self, d):
        if d in self._nf3:
            return self._nf3[d]
        scores = {}
        for t in UNIVERSE:
            a = self._nf3_one(t, d)
            if a is not None:
                scores[t] = a
        picks = []
        if len(scores) >= 5:
            picks = sorted(scores, key=lambda t: (scores[t], t))
        out = (scores, picks)
        self._nf3[d] = out
        return out


# ------------------------------------------------------------- sleeves
# (copied verbatim from the v8 combo script)
class Sleeve:
    def __init__(self, name, cash):
        self.name = name
        self.cash = cash
        self.positions = {}
        self.trades = []
        self.costs = 0.0
        self.pending = None
        self.curve = []

    def close_value(self, pb, d):
        v = self.cash
        for t, sh in self.positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def open_value(self, pb, d):
        v = self.cash
        for t, sh in self.positions.items():
            b = pb.bar(t, d)
            if b:
                v += sh * b["o"]
        return v


def sleeve_sells(pb, s, d, targets):
    opens = {}
    for t in set(list(s.positions) + list(targets)):
        b = pb.bar(t, d)
        if b:
            opens[t] = b["o"]
    for t in list(s.positions):
        if t not in opens:
            continue
        cur_val = s.positions[t] * opens[t]
        tgt = targets.get(t, 0.0)
        if cur_val > tgt + 0.005:
            sell_val = cur_val - tgt
            sh = sell_val / opens[t]
            c = sell_val * 0.001 + 0.01
            s.cash += sell_val - c
            s.costs += c
            s.positions[t] -= sh
            s.trades.append((d, s.name, "SELL", sh, opens[t], sell_val, c))
            if s.positions[t] < 1e-9:
                del s.positions[t]
    return opens


def sleeve_buys(pb, s, d, targets, opens):
    for t, tgt in targets.items():
        if t not in opens:
            continue
        cur_val = s.positions.get(t, 0.0) * opens[t]
        buy_val = tgt - cur_val
        if buy_val > 0.005:
            buy_val = min(buy_val, s.cash / 1.001)
            if buy_val <= 0.005:
                continue
            sh = buy_val / opens[t]
            c = buy_val * 0.001
            s.cash -= buy_val + c
            s.costs += c
            s.positions[t] = s.positions.get(t, 0.0) + sh
            s.trades.append((d, s.name, "BUY", sh, opens[t], buy_val, c))


# ------------------------------------------------------------- combo
def run_combo(pb, scorer, start, end, sel_dates, start_cash=100.0,
              floor0=85.0, placebo_rng=None, label="", n=5):
    """The v8 combo engine verbatim, except the selection-date list
    is passed in (quarterly in the original; cadence dates in v10)."""
    vm = Sleeve("VM", start_cash / 2.0)
    f3 = Sleeve("NF3", start_cash / 2.0)
    sleeves = [vm, f3]
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    curve = []
    pools = []
    transfers = []
    halted = None
    halt_info = None

    def combined_close(d):
        return vm.close_value(pb, d) + f3.close_value(pb, d)

    def liquidate(d, tag):
        for s in sleeves:
            for t in list(s.positions):
                if tag == "SELL-HALT":
                    b = pb.bar(t, d)
                    px = b["o"] if b else None
                else:
                    px = pb.close_on_or_before(t, d)
                if px:
                    val = s.positions[t] * px
                    c = val * 0.001 + 0.01
                    s.cash += val - c
                    s.costs += c
                    s.trades.append((d, s.name, tag, s.positions[t],
                                     px, val, c))
            s.positions = {}

    for di, d in enumerate(days):
        if vm.pending is not None or f3.pending is not None:
            opens_by_sleeve = {}
            budgets = {}
            for s in sleeves:
                if s.pending is not None:
                    targets, budget = s.pending
                    opens_by_sleeve[s.name] = sleeve_sells(pb, s, d, targets)
                    budgets[s.name] = budget
            vals = {s.name: s.open_value(pb, d) for s in sleeves}
            excess = {n: vals[n] - budgets.get(n, vals[n]) for n in vals}
            if excess["VM"] > 0.005 and excess["NF3"] < -0.005:
                amt = min(excess["VM"], -excess["NF3"], vm.cash)
                if amt > 0.005:
                    vm.cash -= amt
                    f3.cash += amt
                    transfers.append((d, "VM->NF3", round(amt, 2)))
            elif excess["NF3"] > 0.005 and excess["VM"] < -0.005:
                amt = min(excess["NF3"], -excess["VM"], f3.cash)
                if amt > 0.005:
                    f3.cash -= amt
                    vm.cash += amt
                    transfers.append((d, "NF3->VM", round(amt, 2)))
            for s in sleeves:
                if s.pending is not None:
                    targets, _ = s.pending
                    sleeve_buys(pb, s, d, targets,
                                opens_by_sleeve[s.name])
                    s.pending = None
        if d in sel_set:
            vm_pool, vm_picks = scorer.vm(d)
            f3_pool, f3_picks = scorer.nf3(d)
            kv = len(vm_pool) if n == "ALL" else min(n, len(vm_pool))
            kf = len(f3_pool) if n == "ALL" else min(n, len(f3_pool))
            if placebo_rng is not None:
                if len(vm_pool) >= 5:
                    vm_picks = placebo_rng.sample(sorted(vm_pool), kv)
                if len(f3_pool) >= 5:
                    f3_picks = placebo_rng.sample(sorted(f3_pool), kf)
            else:
                vm_picks = vm_picks[:kv]
                f3_picks = f3_picks[:kf]
            combined = combined_close(d)
            budget = combined / 2.0
            if len(vm_pool) >= 5 and vm_picks:
                vm.pending = ({t: budget / len(vm_picks)
                               for t in vm_picks}, budget)
            if len(f3_pool) >= 5 and f3_picks:
                f3.pending = ({t: budget / len(f3_picks)
                               for t in f3_picks}, budget)
            pools.append((d, len(vm_pool), list(vm_picks),
                          len(f3_pool), list(f3_picks),
                          round(combined, 2)))
        v = combined_close(d)
        curve.append((d, v))
        for s in sleeves:
            s.curve.append((d, s.close_value(pb, d)))
        if v <= floor0 and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor0}
            nd = days[di + 1]
            liquidate(nd, "SELL-HALT")
            final = vm.cash + f3.cash
            return {"label": label, "final": final,
                    "costs": vm.costs + f3.costs,
                    "trades": vm.trades + f3.trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "pools": pools, "curve": curve, "transfers": transfers,
                    "sleeve_finals": {"VM": vm.cash, "NF3": f3.cash}}
    last = days[-1]
    liquidate(last, "SELL-END")
    final = vm.cash + f3.cash
    return {"label": label, "final": final, "costs": vm.costs + f3.costs,
            "trades": vm.trades + f3.trades,
            "halted": None, "end": last, "halt_info": None,
            "pools": pools, "curve": curve, "transfers": transfers,
            "sleeve_finals": {"VM": vm.cash, "NF3": f3.cash}}


def run_combo_v9(pb, scorer, start, end, sel_dates, start_cash=100.0,
                 placebo_rng=None, label="", n=5):
    """v9 protection wrapper (generalized from the v9 combo script):
    ep-1 floor -15% from start; on first halt liquidate as the engine
    does, sit in cash 90 calendar days, restart at the next cadence
    selection date on/after day 90 with floor -15% from the restart
    balance; second halt ends the run."""
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_combo(pb, scorer, start, end, sel_dates, start_cash, floor1,
                   placebo_rng=placebo_rng, label=label + " EP1", n=n)
    out = {"final": r1["final"], "costs": r1["costs"],
           "trades": r1["trades"], "curve": list(r1["curve"]),
           "halted": r1["halted"], "restarts": [], "second_halt": None,
           "episodes": 1, "orders": len(r1["trades"])}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    day90 = _ord(liq_date) + 90
    restart = None
    for cand in sel_dates:
        if _ord(cand) >= day90:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq_date <= d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": r1["halted"], "liquidation_date": liq_date,
        "halt_signal_close": r1["halt_info"]["signal_close"],
        "restart_date": restart, "restart_balance": round(cash, 2),
        "episode2_floor": floor2})
    r2 = run_combo(pb, scorer, restart, end, sel_dates, cash, floor2,
                   placebo_rng=placebo_rng, label=label + " EP2", n=n)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["trades"] += r2["trades"]
    out["orders"] += len(r2["trades"])
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {
            "signal_date": r2["halted"],
            "signal_close": r2["halt_info"]["signal_close"],
            "floor_in_effect": r2["halt_info"]["floor_in_effect"],
            "liquidation_date": r2["end"],
            "final": round(r2["final"], 2)}
        for d in pb.dates:
            if r2["end"] <= d <= end:
                out["curve"].append((d, r2["final"]))
    out["curve"].sort(key=lambda kv: kv[0])
    return out


# ------------------------------------------------------------- cadences
def cadence_dates(pb, start, end, cadence):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    out, seen = [], set()
    if cadence == "biweekly":
        weeks, wseen = [], set()
        for d in days:
            iso = _date(int(d[:4]), int(d[5:7]), int(d[8:10])).isocalendar()
            key = (iso[0], iso[1])
            if key not in wseen:
                wseen.add(key)
                weeks.append((key, d))
        return [d for i, (k, d) in enumerate(weeks) if i % 2 == 0]
    for d in days:
        y, m = d[:4], d[5:7]
        if cadence == "weekly":
            iso = _date(int(y), int(m), int(d[8:10])).isocalendar()
            key = (iso[0], iso[1])
        elif cadence == "monthly":
            key = (y, m)
        elif cadence == "quarterly":
            if m not in ("01", "04", "07", "10"):
                continue
            key = (y, m)
        elif cadence == "semiannual":
            if m not in ("01", "07"):
                continue
            key = (y, m)
        elif cadence == "annual":
            if m != "01":
                continue
            key = (y,)
        else:
            raise ValueError(cadence)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


# ------------------------------------------------------------- helpers
def diagnostics(curve):
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d}


def cagr_pct(final, start_cash, start, end):
    yrs = (_ord(end) - _ord(start)) / 365.25
    if final <= 0 or yrs <= 0:
        return None
    return round(((final / start_cash) ** (1.0 / yrs) - 1.0) * 100, 2)


def halts_of(r):
    n = 0
    if r.get("halted"):
        n += 1
    if r.get("second_halt"):
        n += 1
    return n


# ------------------------------------------------------------- data
def load_facts():
    ciks = champ.get_ciks()
    overrides = {"XOM": 34088}
    facts_by_ticker, equity_rows, shares_rows = {}, {}, {}
    for t in UNIVERSE:
        cik = overrides.get(t, ciks[t][0])
        facts = champ.get_companyfacts(cik)
        facts_by_ticker[t] = facts
        equity_rows[t] = (
            champ.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            champ.pit_series(facts, "us-gaap",
                             "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                             prio=1))
        shares_rows[t] = (
            champ.pit_series(facts, "dei",
                             "EntityCommonStockSharesOutstanding", prio=3) +
            champ.pit_series(facts, "us-gaap",
                             "CommonStockSharesOutstanding", prio=2) +
            champ.pit_series(facts, "us-gaap",
                             "WeightedAverageNumberOfSharesOutstandingBasic",
                             prio=1))
    return facts_by_ticker, equity_rows, shares_rows


def yahoo_bars_early(ticker):
    """Download (once, cached in MY data/) Yahoo daily bars
    2014-01-01 -> 2017-05-31, adjusted exactly like champ.get_prices."""
    path = os.path.join(MYDATA, f"pxearly_{ticker}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            blob = f.read()
    else:
        import calendar
        t1 = calendar.timegm(time.strptime("2014-01-01", "%Y-%m-%d"))
        t2 = calendar.timegm(time.strptime("2017-06-01", "%Y-%m-%d"))
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
    for i, tt in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(tt))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


def spliced_bars():
    """Cached champion bars (2017-06-01+) verbatim + scaled early
    bars before them. Returns (bars_by_ticker, splice_factors)."""
    out, factors = {}, {}
    for t in UNIVERSE + ["SPY"]:
        cached = champ.get_prices(t)
        first = cached[0]["d"]
        early = [b for b in yahoo_bars_early(t) if b["d"] < first]
        factor = 1.0
        if early:
            dl = {b["d"]: b for b in yahoo_bars_early(t)}
            ref = dl.get(first)
            if ref and ref["c"]:
                factor = cached[0]["c"] / ref["c"]
            early = [{"d": b["d"], "o": b["o"] * factor,
                      "c": b["c"] * factor} for b in early]
        factors[t] = round(factor, 6)
        out[t] = early + cached
    return out, factors


# ------------------------------------------------------------- phases
def phase_integrity(pb_orig, pb_fast, scorer_fast, scorer_orig):
    """Reproduce the original published finals in original form."""
    res = {}
    q_cont = champ.quarter_selection_dates(pb_fast, CONT[0], CONT[1])
    q_val = champ.quarter_selection_dates(pb_fast, VAL[0], VAL[1])
    # cross-check: original PriceBook vs FastPriceBook, ranked quarterly
    for name, pb, sc, win, q in (("orig-book", pb_orig, scorer_orig, CONT, q_cont),
                                 ("fast-book", pb_fast, scorer_fast, CONT, q_cont)):
        r = run_combo(pb, sc, win[0], win[1], q, 100.0, 85.0,
                      label=f"INTEGRITY CONT {name}")
        res[f"cont_{name}"] = round(r["final"], 2)
        log(f"INTEGRITY CONT [{name}] final=${r['final']:,.2f} "
            f"costs=${r['costs']:,.2f} orders={len(r['trades'])}")
    # ranked CONT + VAL on the fast book (original form)
    for wname, win, q in (("CONT", CONT, q_cont), ("VAL", VAL, q_val)):
        r = run_combo(pb_fast, scorer_fast, win[0], win[1], q, 100.0, 85.0,
                      label=f"INTEGRITY {wname}")
        spy, _ = champ.spy_net(pb_fast, win[0], win[1], 100.0)
        placebo_finals, beaten = [], 0
        for seed in PLACEBO_SEEDS:
            pr = run_combo(pb_fast, scorer_fast, win[0], win[1], q,
                           100.0, 85.0, placebo_rng=random.Random(seed),
                           label=f"INTEGRITY {wname} PLACEBO {seed}")
            placebo_finals.append(round(pr["final"], 2))
            beaten += 1 if r["final"] > pr["final"] else 0
        res[wname] = {"final": round(r["final"], 2),
                      "costs": round(r["costs"], 2),
                      "orders": len(r["trades"]), "halted": r["halted"],
                      "spy_net": round(spy, 2),
                      "placebo_finals": placebo_finals,
                      "placebo_beaten": beaten}
        log(f"INTEGRITY {wname}: final=${r['final']:,.2f} SPY=${spy:,.2f} "
            f"placebo beaten={beaten}/20")
    # parents standalone (champion + N-F3 engines verbatim, quarterly)
    parents = {}
    for wname, win in (("CONT", CONT), ("VAL", VAL)):
        vm = champ.run_pot(pb_fast, scorer_fast.equity_rows,
                           scorer_fast.shares_rows, win[0], win[1],
                           100.0, 85.0, [], label=f"{wname} VM", quiet=True)
        st = {"direct": 0, "derived": 0}
        f3 = nf3.run_pot(pb_fast, scorer_fast.facts, win[0], win[1],
                         100.0, 85.0, label=f"{wname} NF3", stats=st)
        parents[wname] = {"VM": round(vm["final"], 2),
                          "NF3": round(f3["final"], 2)}
        log(f"INTEGRITY PARENTS {wname}: VM=${vm['final']:,.2f} "
            f"NF3=${f3['final']:,.2f}")
    res["parents"] = parents
    # yearly folds: his rules + v9 (quarterly, original windows)
    folds = {}
    for yr in range(2020, 2027):
        fs = f"{yr}-01-01"
        fe = "2026-11-20" if yr == 2026 else f"{yr}-12-31"
        q = champ.quarter_selection_dates(pb_fast, fs, fe)
        rh = run_combo(pb_fast, scorer_fast, fs, fe, q, 100.0, 85.0,
                       label=f"HIS FOLD {yr}")
        rv = run_combo_v9(pb_fast, scorer_fast, fs, fe, q, 100.0,
                          label=f"V9 FOLD {yr}")
        spy, _ = champ.spy_net(pb_fast, fs, fe, 100.0)
        folds[str(yr)] = {
            "his_final": round(rh["final"], 2), "his_halted": rh["halted"],
            "v9_final": round(rv["final"], 2),
            "v9_restarts": rv["restarts"],
            "v9_second_halt": rv["second_halt"],
            "spy_final": round(spy, 2)}
        log(f"FOLD {yr}: his=${rh['final']:,.2f} halted={rh['halted']} | "
            f"v9=${rv['final']:,.2f} restarts={len(rv['restarts'])} "
            f"2nd={bool(rv['second_halt'])}")
    prod_h = prod_v = 1.0
    for yr in folds:
        prod_h *= folds[yr]["his_final"] / 100.0
        prod_v *= folds[yr]["v9_final"] / 100.0
    res["folds"] = folds
    res["folds_his_compounded"] = round(100.0 * prod_h, 2)
    res["folds_v9_compounded"] = round(100.0 * prod_v, 2)
    return res


def phase_sweep(pb, scorer):
    start, end = DECADE
    spy, _ = champ.spy_net(pb, start, end, 100.0)
    log(f"DECADE SPY (spliced book) = ${spy:,.2f}")
    cells = {}
    # priority: native (quarterly) first, then the rest; daily last
    # (it fills the scorer cache for every date)
    order = ["quarterly", "monthly", "semiannual", "annual",
             "weekly", "biweekly", "daily"]
    for cad in order:
        t0 = time.time()
        sel = cadence_dates(pb, start, end, cad)
        r = run_combo_v9(pb, scorer, start, end, sel, START_CASH,
                         label=f"DECADE {cad}")
        diag = diagnostics(r["curve"])
        placebo_finals, placebo_beaten = [], 0
        for seed in PLACEBO_SEEDS:
            pr = run_combo_v9(pb, scorer, start, end, sel, START_CASH,
                              placebo_rng=random.Random(seed),
                              label=f"DECADE {cad} PLACEBO {seed}")
            placebo_finals.append(round(pr["final"], 2))
            placebo_beaten += 1 if r["final"] > pr["final"] else 0
        sf = sorted(placebo_finals)
        cell = {
            "final": round(r["final"], 2),
            "cagr_pct": cagr_pct(r["final"], START_CASH, start, end),
            "max_dd_pct": diag["max_drawdown_pct"],
            "max_dd_date": diag["max_drawdown_date"],
            "worst_close": diag["worst_close"],
            "worst_close_date": diag["worst_close_date"],
            "costs": round(r["costs"], 2),
            "orders": r["orders"],
            "halts": halts_of(r),
            "halted_first": r["halted"],
            "restarts": r["restarts"],
            "restart": bool(r["restarts"]),
            "second_halt": bool(r["second_halt"]),
            "second_halt_detail": r["second_halt"],
            "n_selection_dates": len(sel),
            "first_selection_date": sel[0] if sel else None,
            "placebo_beaten": placebo_beaten,
            "placebo_median": round((sf[9] + sf[10]) / 2.0, 2),
            "placebo_finals": placebo_finals,
            "equity_curve": [[d, round(v, 2)] for d, v in r["curve"]],
        }
        cells[cad] = cell
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump({"slug": "combo-vm-nf3", "cadence": cad,
                       "window": {"start": start, "end": end},
                       "start_cash": START_CASH,
                       "decade_spy_final": round(spy, 2), **cell}, f,
                      indent=1)
        log(f"CELL {cad}: final=${r['final']:,.2f} CAGR={cell['cagr_pct']} "
            f"maxDD={cell['max_dd_pct']}% costs=${cell['costs']:,.2f} "
            f"orders={cell['orders']} halts={cell['halts']} "
            f"placebo beaten={placebo_beaten}/20 "
            f"({time.time()-t0:.0f}s)")
    return cells, round(spy, 2)


def main():
    t00 = time.time()
    facts, eq, sh = load_facts()
    log(f"facts loaded ({time.time()-t00:.0f}s)")
    bars_cached = {t: champ.get_prices(t) for t in UNIVERSE + ["SPY"]}
    pb_orig = champ.PriceBook(bars_cached)
    pb_fast_c = FastPriceBook(bars_cached)
    scorer_orig = Scorer(pb_orig, eq, sh, facts)
    scorer_fast_c = Scorer(pb_fast_c, eq, sh, facts)
    integrity = phase_integrity(pb_orig, pb_fast_c, scorer_fast_c,
                                scorer_orig)
    with open(os.path.join(HERE, "integrity.json"), "w") as f:
        json.dump(integrity, f, indent=1, default=str)
    log(f"integrity done ({time.time()-t00:.0f}s)")
    bars_spliced, factors = spliced_bars()
    log(f"splice factors: min={min(factors.values())} "
        f"max={max(factors.values())}")
    pb_s = FastPriceBook(bars_spliced)
    scorer_s = Scorer(pb_s, eq, sh, facts)
    # cross-check: quarterly CONT on the spliced book (original form)
    q_cont = champ.quarter_selection_dates(pb_s, CONT[0], CONT[1])
    rx = run_combo(pb_s, scorer_s, CONT[0], CONT[1], q_cont, 100.0, 85.0,
                   label="XCHECK CONT spliced")
    log(f"XCHECK spliced-book CONT quarterly (original form) = "
        f"${rx['final']:,.2f} (integrity target $532.39)")
    cells, spy_decade = phase_sweep(pb_s, scorer_s)
    out = {"integrity": integrity, "splice_factors": factors,
           "xcheck_spliced_cont": round(rx["final"], 2),
           "decade_spy_final": spy_decade, "cells": cells,
           "elapsed_s": round(time.time() - t00, 1)}
    with open(os.path.join(HERE, "sweep_raw.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    log(f"ALL DONE ({time.time()-t00:.0f}s)")


if __name__ == "__main__":
    main()
