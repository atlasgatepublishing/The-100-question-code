#!/usr/bin/env python3
"""
NOVEL N-F1 — "THE SLOW FILER" (filing-lag rank) — THE GREAT RETEST (v10).
Simulation only.

Strategy (frozen, verbatim from backtests/v8/novel-f1-slow-filer/ and its
v9 copy in backtests/v9-muse-rules/novel-f1-slow-filer/): rank the honest
top-30 pond (as of Nov 2016) by dLAG = LAG_now - LAG_ref, where LAG is the
acceptance-date minus period-of-report-date (days) of a firm's most recent
original 10-K/10-Q, and LAG_ref is the same form's filing whose period
date falls 320-410 days earlier (closest to 365). Rank ascending (largest
shortening first), hold top 5 equal weight. Hard exclusion: any NT 10-K /
NT 10-Q accepted in the trailing 365 days. Eligibility: both lags
computable and LAG_now accepted within 200 days before the selection
date. Costs 0.10%/side + $0.01 per sell order. INVENTED rule (2026):
candidate ceiling language applies — an invention can at best be a
CANDIDATE, and only a forward paper trial can promote it.

INTEGRITY (run first, in ORIGINAL form): the original v8/v9 engine
(imported verbatim from the v9 folder) on its original caches reproduces
CONT 2019-01-02->2026-11-20 = $332.79 and VAL 2023-01-03->2026-11-20 =
$189.47, SPY $313.62 / $187.77, and the original placebos (CONT median
$283.72, beat 13/20; VAL median $204.08, beat 8/20 — the eligible pool
did the work on VAL, not the rank).

CADENCE SWEEP (SPEC v10): DECADE 2016-11-21 -> 2026-11-20, $100/cell,
v9 protections (plain -15% floor; first halt -> liquidate, 90 calendar
days cash, restart at the next regular decision point under an episode-2
floor of -15% from the restart balance; second halt ends the run),
20-seed random-rank placebos per cell (same eligible pools, dates and
mechanics; median twin reported per cell).

SIGNAL TREATMENT UNDER CADENCE (stated per task): the filing-lag signal
is recomputed at EVERY cadence date from the freshest filings accepted
strictly before that date — i.e. the eligible pool and dLAG ranks update
as filings land, and faster cadences simply re-evaluate (re-rank and
rebalance) on that freshest filed data more often. Nothing else changes:
same dLAG definition, same NT exclusion, same 200-day staleness gate,
same top-5 equal-weight mechanics, execution at the next open.
NATIVE CADENCE = quarterly (first trading day of Jan/Apr/Jul/Oct).

Data (read-only shared caches; nothing written outside this folder):
  - Filings: EDGAR submissions history cached in
    backtests/v8/novel-f1-slow-filer/data/ (the original engine's own
    loader, read-only).
  - Sweep prices: full-range Yahoo payloads from
    backtests/v7/long-hold/data/pxfull_*.json (read-only, the program's
    verified cache); any ticker missing there is downloaded once into
    THIS folder's data/ and used from there.
  - Integrity prices: the original engine's v4 caches, via the original
    engine itself.
"""
import importlib.util
import json
import math
import os
import random
import sys
import time
import urllib.request
from bisect import bisect_right
from datetime import date, timedelta

HERE = "/home/hatch/workspace/stock-app/backtests/v10-retest/novel-f1-slow-filer"
BT = os.path.expanduser("~/workspace/stock-app/backtests")
sys.path.insert(0, os.path.join(BT, "long-run-2010"))
import lr_common as C  # noqa: E402  (FastPriceBook, bars_adj, champ.spy_net, run_v9, diagnostics)

# ------------------------------------------------ original engine, verbatim
_spec = importlib.util.spec_from_file_location(
    "nf1_v9", os.path.join(BT, "v9-muse-rules", "novel-f1-slow-filer",
                           "novel-f1-slow-filer-v9.py"))
nf1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nf1)

UNIVERSE = nf1.UNIVERSE
DEC = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
PLACEBO_SEEDS = list(range(1, 21))
MYDATA = os.path.join(HERE, "data")
LH_DATA = os.path.join(BT, "v7", "long-hold", "data")


# ------------------------------------------------------------ sweep prices
def payload_for(t):
    """Full-range Yahoo payload: v7 long-hold cache (read-only) first,
    else this folder's data/, else one fresh download into this folder."""
    lh = os.path.join(LH_DATA, f"pxfull_{t}.json")
    if os.path.exists(lh) and os.path.getsize(lh) > 100:
        with open(lh, "rb") as f:
            return json.loads(f.read())
    mine = os.path.join(MYDATA, f"pxfull_{t}.json")
    if os.path.exists(mine) and os.path.getsize(mine) > 100:
        with open(mine, "rb") as f:
            return json.loads(f.read())
    import calendar
    t1 = calendar.timegm(time.strptime("2008-01-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2026-11-22", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        blob = r.read()
    with open(mine, "wb") as f:
        f.write(blob)
    return json.loads(blob)


# ------------------------------------------------------- cadence calendar
def cadence_dates(pb, start, end, cad):
    """Uniform SPEC cadence: first trading day of each cadence period.
    Biweekly anchored on absolute week parity (Monday ordinal // 7),
    the W4 harness convention."""
    days = [d for d in pb.dates if start <= d <= end]
    if cad == "daily":
        return days
    out, seen = [], set()
    for d in days:
        dt = date.fromisoformat(d)
        if cad == "weekly":
            key = ("W", dt.isocalendar()[0], dt.isocalendar()[1])
        elif cad == "biweekly":
            monday = dt.toordinal() - dt.weekday()
            if (monday // 7) % 2 != 0:
                continue
            key = ("B", monday)
        elif cad == "monthly":
            key = ("M", d[:4], d[5:7])
        elif cad == "quarterly":
            if d[5:7] not in ("01", "04", "07", "10"):
                continue
            key = ("Q", d[:4], d[5:7])
        elif cad == "semiannual":
            if d[5:7] not in ("01", "07"):
                continue
            key = ("S", d[:4], d[5:7])
        elif cad == "annual":
            key = ("A", d[:4])
        else:
            raise ValueError(cad)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


# ------------------------------------------- engine: original mechanics,
# selection calendar parameterised (body copied from nf1.run_pot with
# only the sel_dates source changed; everything else identical).
def run_pot_cad(pb, pools, start, end, start_cash, floor0, sel_dates,
                placebo_rng=None, label="", record_pools=False, n_hold=5):
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    pools_log = []
    sel_dates = [d for d in sel_dates if start <= d <= end]
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None

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
            pending = None
        if d in sel_set:
            pool = pools.get(d, {})
            if len(pool) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(pool), min(n_hold, len(pool))) if n_hold else sorted(pool)
                else:
                    picks = sorted(pool, key=lambda t: (pool[t], t))[:n_hold] if n_hold else sorted(pool, key=lambda t: (pool[t], t))
                if record_pools:
                    pools_log.append((d, dict(pool), list(picks)))
                pv = portfolio_close(d)
                each = pv / len(picks)
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t],
                                   b["o"], val, c))
            positions = {}
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "pools": pools_log,
                    "curve": curve}
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
            "halt_info": None, "pools": pools_log, "curve": curve}


def median(vals):
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


