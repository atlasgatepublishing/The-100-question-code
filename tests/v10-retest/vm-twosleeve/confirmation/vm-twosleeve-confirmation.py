#!/usr/bin/env python3
"""
TWO-SLEEVE VALUE / MOMENTUM BLEND — Terry's AI stock app. Simulation only.

ONE pre-published restructure of the promoted value+momentum strategy,
run once, no tuning: Asness, Moskowitz & Pedersen (2013, JF) — keep the
value and momentum legs as SEPARATE sleeves instead of one combined
rank, because in their evidence the two legs' returns correlate ~ -0.60.
(Research basis: ~/workspace/stock-app/research/v5/crash-protection.md,
candidate #4. This is NOT the failed winners' blend — that mixed two
momentum-loaded sleeves, correlation +0.79.)

Construction (frozen before the run):
  - $100 pot split $50 / $50.
  - Sleeve A (VALUE): ranks the honest point-in-time top-30 universe
    (as of Nov 2016) by book-to-market ALONE, top-5, quarterly, equal
    weight within the sleeve.
  - Sleeve B (MOMENTUM): same universe, ranked by 12-1 momentum ALONE,
    top-5, quarterly, equal weight within the sleeve.
  - Everything else inherited verbatim from the promoted engine
    (value-momentum-plainfloor.py, imported read-only): EDGAR
    point-in-time facts (filed strictly before selection day, ~18-month
    freshness gate, XOM CIK override 34088, same shares-outstanding
    fallback chain), Yahoo adjusted prices from the same caches,
    quarterly selection on the first trading day of Jan/Apr/Jul/Oct with
    execution at the next open, costs 0.10% of trade value per side +
    $0.01 per sell order.
  - Plain -15% floor at the WHOLE-POT level only ($85 on the $100 pot):
    total pot close at/below floor -> liquidate BOTH sleeves at next
    open, run ends. No ladder, no per-sleeve floor.
  - Annual January 50/50 sleeve rebalancing: at each January quarterly
    selection, both sleeves' targets are set to half the total pot
    value (selection-day close); execution at the next open sells each
    sleeve toward its targets, transfers cash from the richer sleeve to
    the poorer so both hold equal value, then buys. All trades charged
    at the engine cost schedule. (Same January-rebalance convention as
    the winners'-blend test.)
  - Placebo: 20 seeds (1..20), random 5-name picks in BOTH sleeves from
    the same scored pool, identical mechanics (quarterly rebalance,
    January 50/50 reset, whole-pot floor).
  - Windows: CONTINUOUS 2019-01-02 -> 2026-11-20, VALIDATION
    2023-01-03 -> 2026-11-20, plus walk-forward folds (fresh $100 pot
    per calendar year 2020-2026, Jan 1 -> Dec 31; 2026 -> Nov 20),
    scored against SPY net over the same window (E.spy_net).

Baseline to judge against (promoted combined-rank V+M, plain floor):
  validation $288.05 | continuous $544.47 | placebo beaten 18/20
  validation, 19/20 continuous | folds 4 wins / 7 vs SPY (2020 fold
  halted 2020-03-09, final $83.62; 2021 +18.43% vs SPY +27.97%;
  2023 +18.47% vs SPY +25.28%).

Also reported: the realized correlation between the two sleeves' daily
(and monthly) returns in our data, continuous + validation runs.
"""
import bisect
import importlib.util
import json
import math
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

START_CASH = 100.0
FLOOR0 = 85.0                      # plain -15% floor on the whole $100 pot
PLACEBO_SEEDS = list(range(1, 21))
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")


# ------------------------------------------------------------ fast prices
class FastBook:
    """Same semantics as E.PriceBook (bars sorted by date), bisect lookups."""
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.by_date = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}
        self.dlist = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}
        self.didx = {t: {b["d"]: i for i, b in enumerate(bl)}
                     for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.by_date.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self.dlist.get(t, [])
        i = bisect.bisect_right(dl, d) - 1
        return self.bars[t][i]["c"] if i >= 0 else None


# ---------------------------------------------------------------- scoring
def score_pool(pb, equity_rows, shares_rows, d):
    """Identical point-in-time scoring to the promoted engine.
    Returns dict ticker -> (bm, mom) for every name that can be scored."""
    scores = {}
    for t in E.UNIVERSE:
        be = E.pit_value(equity_rows.get(t, []), d)
        so = E.pit_value(shares_rows.get(t, []), d)
        px = pb.close_on_or_before(t, d)
        if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
            continue
        mcap = so[2] * px
        if mcap <= 0:
            continue
        bm = be[2] / mcap
        bl = pb.bars.get(t, [])
        didx = pb.didx.get(t, {}).get(d)
        if didx is None or didx < 253:
            continue
        mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
        scores[t] = (bm, mom)
    return scores


# ---------------------------------------------------------------- sleeves
class Sleeve:
    def __init__(self, name, cash):
        self.name = name
        self.cash = cash
        self.positions = {}      # ticker -> shares
        self.trades = []
        self.costs = 0.0

    def close_value(self, pb, d):
        v = self.cash
        for t, sh in self.positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v


def sleeve_sells(pb, sl, d, targets):
    """Sell sl down toward targets at day d's open (baseline mechanics)."""
    opens = {}
    for t in set(list(sl.positions) + list(targets)):
        b = pb.bar(t, d)
        if b:
            opens[t] = b["o"]
    for t in list(sl.positions):
        if t not in opens:
            continue
        cur_val = sl.positions[t] * opens[t]
        tgt = targets.get(t, 0.0)
        if cur_val > tgt + 0.005:
            sell_val = cur_val - tgt
            sh = sell_val / opens[t]
            c = sell_val * 0.001 + 0.01
            sl.cash += sell_val - c
            sl.costs += c
            sl.positions[t] -= sh
            sl.trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
            if sl.positions[t] < 1e-9:
                del sl.positions[t]
    return opens


def sleeve_buys(pb, sl, d, targets, opens):
    for t, tgt in targets.items():
        if t not in opens:
            continue
        cur_val = sl.positions.get(t, 0.0) * opens[t]
        buy_val = tgt - cur_val
        if buy_val > 0.005:
            buy_val = min(buy_val, sl.cash / 1.001)
            if buy_val <= 0.005:
                continue
            sh = buy_val / opens[t]
            c = buy_val * 0.001
            sl.cash -= buy_val + c
            sl.costs += c
            sl.positions[t] = sl.positions.get(t, 0.0) + sh
            sl.trades.append((d, t, "BUY", sh, opens[t], buy_val, c))


def execute_rebalance(pb, sA, sB, d, targetsA, targetsB, january_reset):
    """Sells first (both sleeves), optional January cash transfer to
    equalize sleeve values, then buys. Returns transfer amount."""
    opensA = sleeve_sells(pb, sA, d, targetsA)
    opensB = sleeve_sells(pb, sB, d, targetsB)
    transfer = 0.0
    if january_reset:
        def open_value(sl):
            v = sl.cash
            for t, sh in sl.positions.items():
                b = pb.bar(t, d)
                if b:
                    v += sh * b["o"]
            return v
        va, vb = open_value(sA), open_value(sB)
        diff = (va - vb) / 2.0
        if diff > 0.005:
            amt = min(diff, sA.cash)
            sA.cash -= amt
            sB.cash += amt
            transfer = amt
        elif diff < -0.005:
            amt = min(-diff, sB.cash)
            sB.cash -= amt
            sA.cash += amt
            transfer = -amt
    sleeve_buys(pb, sA, d, targetsA, opensA)
    sleeve_buys(pb, sB, d, targetsB, opensB)
    return transfer


# ------------------------------------------------------------------- run
def run_two_sleeve(pb, equity_rows, shares_rows, start, end,
                   start_cash=START_CASH, floor0=FLOOR0,
                   placebo_rng=None, label="", quiet=False):
    sA = Sleeve("A-value", start_cash / 2.0)
    sB = Sleeve("B-momentum", start_cash / 2.0)
    sel_dates = E.quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None          # (targetsA, targetsB, january_reset)
    halted = None
    halt_info = None
    curve = []              # (date, total, vA, vB)
    picks_log = []
    transfers = []

    for di, d in enumerate(days):
        if pending is not None:
            tA, tB, jan = pending
            amt = execute_rebalance(pb, sA, sB, d, tA, tB, jan)
            if jan and abs(amt) > 0.005:
                transfers.append((d, round(amt, 2)))
            pending = None
        if d in sel_set:
            scores = score_pool(pb, equity_rows, shares_rows, d)
            if len(scores) >= 5:
                vr = E.percentile_ranks({t: v[0] for t, v in scores.items()})
                mr = E.percentile_ranks({t: v[1] for t, v in scores.items()})
                if placebo_rng is not None:
                    picksA = placebo_rng.sample(sorted(scores), 5)
                    picksB = placebo_rng.sample(sorted(scores), 5)
                else:
                    picksA = sorted(scores, key=lambda t: -vr[t])[:5]
                    picksB = sorted(scores, key=lambda t: -mr[t])[:5]
                vA = sA.close_value(pb, d)
                vB = sB.close_value(pb, d)
                total = vA + vB
                january = d[5:7] == "01"
                if january:
                    eachA = (total / 2.0) / 5.0
                    eachB = (total / 2.0) / 5.0
                else:
                    eachA = vA / 5.0
                    eachB = vB / 5.0
                pending = ({t: eachA for t in picksA},
                           {t: eachB for t in picksB}, january)
                picks_log.append((d, list(picksA), list(picksB)))
                if not quiet:
                    print(f"  [{label}] {d} pool={len(scores)} A={picksA} "
                          f"B={picksB} pot=${total:,.2f} jan={january}", flush=True)
        vA = sA.close_value(pb, d)
        vB = sB.close_value(pb, d)
        v = vA + vB
        curve.append((d, v, vA, vB))
        if v <= floor0 and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor0}
            nd = days[di + 1]
            for sl in (sA, sB):
                for t in list(sl.positions):
                    b = pb.bar(t, nd)
                    if b:
                        val = sl.positions[t] * b["o"]
                        c = val * 0.001 + 0.01
                        sl.cash += val - c
                        sl.costs += c
                        sl.trades.append((nd, t, "SELL-HALT",
                                          sl.positions[t], b["o"], val, c))
                sl.positions = {}
            return {"label": label, "final": sA.cash + sB.cash,
                    "costs": sA.costs + sB.costs,
                    "orders": len(sA.trades) + len(sB.trades),
                    "halted": halted, "halt_info": halt_info,
                    "curve": curve, "picks": picks_log,
                    "transfers": transfers,
                    "sleeve_finals": (sA.cash, sB.cash)}
    last = days[-1]
    for sl in (sA, sB):
        for t in list(sl.positions):
            c_ = pb.close_on_or_before(t, last)
            if c_:
                val = sl.positions[t] * c_
                cst = val * 0.001 + 0.01
                sl.cash += val - cst
                sl.costs += cst
                sl.trades.append((last, t, "SELL-END",
                                  sl.positions[t], c_, val, cst))
        sl.positions = {}
    return {"label": label, "final": sA.cash + sB.cash,
            "costs": sA.costs + sB.costs,
            "orders": len(sA.trades) + len(sB.trades),
            "halted": None, "halt_info": None,
            "curve": curve, "picks": picks_log, "transfers": transfers,
            "sleeve_finals": (sA.cash, sB.cash)}


# ------------------------------------------------------------- diagnostics
def diagnostics(r, floor0):
    curve = r["curve"]
    worst_d, worst_v = None, None
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    year_end = {}
    for d, v, va, vb in curve:
        if worst_v is None or v < worst_v:
            worst_d, worst_v = d, v
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
        year_end[d[:4]] = (d, v)
    covid = [(d, v) for d, v, _, _ in curve if "2020-02-01" <= d <= "2020-04-30"]
    covid_worst = min(covid, key=lambda kv: kv[1]) if covid else None
    # calendar-year returns of the total pot from the curve
    yr_ret = {}
    prev = None
    for y in sorted(year_end):
        close = year_end[y][1]
        if prev is not None:
            yr_ret[y] = round(close / prev * 100 - 100, 2)
        prev = close
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "floor": floor0,
            "worst_close_above_floor": round(worst_v - floor0, 2),
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "covid_worst_close": round(covid_worst[1], 2) if covid_worst else None,
            "covid_worst_date": covid_worst[0] if covid_worst else None,
            "year_end_closes": {y: {"date": d, "close": round(v, 2)}
                                for y, (d, v) in sorted(year_end.items())},
            "calendar_year_returns_pct": yr_ret}


def _pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def sleeve_correlations(r):
    """Correlation between sleeve A and sleeve B returns from the daily
    sleeve curves recorded inside the run (daily + calendar-monthly)."""
    curve = r["curve"]
    ra, rb = [], []
    for i in range(1, len(curve)):
        pa, pbv = curve[i - 1][2], curve[i - 1][3]
        ca, cb = curve[i][2], curve[i][3]
        if pa > 0 and pbv > 0:
            ra.append(ca / pa - 1.0)
            rb.append(cb / pbv - 1.0)
    daily = _pearson(ra, rb)
    month_end = {}
    for d, v, va, vb in curve:
        month_end[d[:7]] = (va, vb)
    keys = sorted(month_end)
    ma, mb = [], []
    for i in range(1, len(keys)):
        pa, pbv = month_end[keys[i - 1]]
        ca, cb = month_end[keys[i]]
        if pa > 0 and pbv > 0:
            ma.append(ca / pa - 1.0)
            mb.append(cb / pbv - 1.0)
    monthly = _pearson(ma, mb)
    return {"daily_corr": round(daily, 3) if daily is not None else None,
            "daily_obs": len(ra),
            "monthly_corr": round(monthly, 3) if monthly is not None else None,
            "monthly_obs": len(ma)}


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def placebo_block(pb, equity_rows, shares_rows, window, ranked_final, label):
    ws, we = window
    rows = []
    finals = []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        pr = run_two_sleeve(pb, equity_rows, shares_rows, ws, we,
                            placebo_rng=rng, label=f"{label} PLACEBO {seed}",
                            quiet=True)
        finals.append(pr["final"])
        rows.append({"seed": seed, "final": round(pr["final"], 2),
                     "halted": pr["halted"], "costs": round(pr["costs"], 2),
                     "orders": pr["orders"]})
        print(f"  {label} placebo seed {seed}: ${pr['final']:,.2f} "
              f"halted={pr['halted']}", flush=True)
    srt = sorted(finals)
    beaten = sum(1 for f in finals if ranked_final > f)
    dist = {"n": len(finals), "median": round(_pct(srt, 0.5), 2),
            "q1": round(_pct(srt, 0.25), 2), "q3": round(_pct(srt, 0.75), 2),
            "best": round(srt[-1], 2), "worst": round(srt[0], 2),
            "halts": sum(1 for r in rows if r["halted"]),
            "ranked_final": round(ranked_final, 2),
            "ranked_beats_seeds": beaten,
            "ranked_percentile": round(beaten / len(finals) * 100, 1),
            "ranked_minus_median": round(ranked_final - _pct(srt, 0.5), 2),
            "rows": rows}
    return dist


# ------------------------------------------------------------------ main
def build_inputs():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in E.UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        time.sleep(0.05)
    bars = {}
    for t in E.UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return FastBook(bars), equity_rows, shares_rows


# ============================================================ V9 MODULE
# "CLAUDE-RULES PROTECTION SPEC v9" - this copy only. The ONLY change vs
# the original v5 script is the protection module (the *_v9 wrapper
# below, which calls the original engine unchanged for each episode):
#   - Episode 1: plain -15% floor from the $100 start ($85.00), identical
#     to Terry's rule. On FIRST halt: liquidate exactly as the original
#     engine does, sit in cash 90 calendar days (counted from the
#     liquidation date), then RESTART with the remaining cash at the
#     strategy's next regular decision point after day 90.
#   - Episode 2: floor = -15% from the RESTART balance. On SECOND halt:
#     the run ends permanently.
#   - If halt + 90 days runs past the window/fold end (no regular
#     decision point remains in-window), the run ends in cash.
# Everything else is byte-identical: universe, signals, parameters
# (vol-scaling / trend-gate parameters are SIGNAL, not protection -
# untouched), costs 0.10%/side + $0.01/sell, windows, $100 start.
# Scope (per spec): ranked pots only, no placebos. Windows/folds where
# the original recorded run never fired the floor are NOT re-run - they
# are identical under v9 by construction and are logged from the
# original results JSON. This script writes ONLY v9-results.json next
# to itself. Simulation only.
# ============================================================

def run_two_sleeve_v9(pb, equity_rows, shares_rows, start, end,
                      start_cash=START_CASH, label=""):
    """One window under v9, wrapping the original run_two_sleeve.
    Liquidation date = the trading day after the halt signal (the day
    the original engine liquidates at the open)."""
    from datetime import date as _date
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_two_sleeve(pb, equity_rows, shares_rows, start, end,
                        start_cash=start_cash, floor0=floor1,
                        label=label + " EP1", quiet=True)
    curve = [(d, v) for d, v, _, _ in r1["curve"]]
    out = {"final": r1["final"], "costs": r1["costs"],
           "orders": r1["orders"], "curve": curve,
           "halted": r1["halted"], "halt_info": r1["halt_info"],
           "restarts": [], "second_halt": None, "episodes": 1,
           "ep1_final": r1["final"], "ep1_liq": None}
    if r1["halted"] is None:
        return out
    liq_date = next(d for d in pb.dates if r1["halted"] < d <= end)
    out["ep1_liq"] = liq_date
    cash = r1["final"]
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _date(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in E.quarter_selection_dates(pb, start, end):
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _date(cy, cm, cd).toordinal() >= day90:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": r1["halted"],
        "liquidation_date": liq_date,
        "halt_signal_close": r1["halt_info"]["signal_close"],
        "restart_date": restart,
        "restart_balance": round(cash, 2),
        "episode2_floor": floor2})
    r2 = run_two_sleeve(pb, equity_rows, shares_rows, restart, end,
                        start_cash=cash, floor0=floor2,
                        label=label + " EP2", quiet=True)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["orders"] += r2["orders"]
    out["curve"] += [(d, v) for d, v, _, _ in r2["curve"]]
    if r2["halted"] is not None:
        liq2 = next((d for d in pb.dates if r2["halted"] < d <= end), end)
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": liq2,
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out


HIS_FOLDS = [
    {"year": 2020, "final": 86.36, "spy_net": 117.47, "halted": "2020-03-09"},
    {"year": 2021, "final": 126.56, "spy_net": 127.97, "halted": None},
    {"year": 2022, "final": 84.37, "spy_net": 81.42, "halted": "2022-04-29"},
    {"year": 2023, "final": 118.87, "spy_net": 125.28, "halted": None},
    {"year": 2024, "final": 141.28, "spy_net": 125.46, "halted": None},
    {"year": 2025, "final": 127.69, "spy_net": 116.81, "halted": None},
    {"year": 2026, "final": 118.71, "spy_net": 101.17, "halted": None},
]




# ============================================================ V10 MODULE
# THE GREAT RETEST (v10) — vm-twosleeve cadence sweep. Everything above
# this marker is the v9 script copied byte-for-byte (engine + v9
# protection wrapper); the v9 main() was removed. What follows adds:
#   - a full-history price book (pxfull_* Yahoo payloads, 2008->2026,
#     read-only from backtests/v7/long-hold/data, GOOGL from
#     backtests/long-run-2010/data) so the DECADE road 2016-11-21 ->
#     2026-11-20 is fully covered (the v4 price cache starts 2017-06-01
#     and cannot score 12-1 momentum until mid-2018);
#   - a cadence-generalized twin of run_two_sleeve: identical sleeve
#     mechanics, costs and floor logic, except (a) selection dates come
#     from the cadence grid and (b) scoring is memoized per (book, date)
#     — score_pool is a pure function of the date, so memoization
#     changes nothing numerically;
#   - CADENCE TREATMENT (stated, applied uniformly): cadence governs
#     each sleeve's re-pick rhythm. The January 50/50 sleeve reset
#     stays ANNUAL as published: it fires at the FIRST selection date
#     in each January under every cadence (for quarterly that is
#     exactly the published January quarterly selection). The reset is
#     part of the strategy's published form (AMP two-sleeve with
#     January reset), not part of the re-pick rhythm, so it does not
#     follow cadence.
#   - a cadence-generalized v9 wrapper: plain -15% floor; first halt ->
#     liquidate next open, cash 90 calendar days, restart at the next
#     CADENCE selection date on/after day 90 under an episode-2 floor
#     of -15% from the restart balance; second halt ends the run.
# Integrity runs use the ORIGINAL run_two_sleeve (above) on the
# ORIGINAL v4 price caches. Simulation only.
# ============================================================
import datetime as _dt

LH_DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
LR_DATA = os.path.expanduser("~/workspace/stock-app/backtests/long-run-2010/data")
DECADE = ("2016-11-21", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def _load_pxfull(t):
    for base in (LH_DATA, LR_DATA):
        p = os.path.join(base, f"pxfull_{t}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            with open(p, "rb") as f:
                return json.loads(f.read())
    raise FileNotFoundError(f"pxfull_{t}.json not in read-only caches")


def _bars_adj(payload):
    """Identical bar construction to E.get_prices / lr_common.bars_adj:
    open scaled by adjclose/close, close = adjclose."""
    res = payload["chart"]["result"][0]
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


def build_facts():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in E.UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        time.sleep(0.05)
    return equity_rows, shares_rows


# ------------------------------------------------------- memoized scoring
_SCORE_CACHE = {}


def score_cached(pb, equity_rows, shares_rows, d):
    key = (id(pb), d)
    hit = _SCORE_CACHE.get(key)
    if hit is None:
        scores = score_pool(pb, equity_rows, shares_rows, d)
        vr = E.percentile_ranks({t: v[0] for t, v in scores.items()})
        mr = E.percentile_ranks({t: v[1] for t, v in scores.items()})
        hit = (scores, vr, mr, sorted(scores))
        _SCORE_CACHE[key] = hit
    return hit


# ------------------------------------------------------ cadence calendar
def cadence_dates(pb, start, end, cadence):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        sels = list(days)
    elif cadence in ("weekly", "biweekly"):
        seen, wk = set(), []
        for d in days:
            iso = _dt.date(int(d[:4]), int(d[5:7]), int(d[8:10])).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                wk.append(d)
        sels = wk if cadence == "weekly" else wk[0::2]
    elif cadence == "monthly":
        seen, sels = set(), []
        for d in days:
            if d[:7] not in seen:
                seen.add(d[:7])
                sels.append(d)
    elif cadence == "quarterly":
        sels = E.quarter_selection_dates(pb, start, end)
    elif cadence == "semiannual":
        seen, sels = set(), []
        for d in days:
            if d[5:7] in ("01", "07") and (d[:4], d[5:7]) not in seen:
                seen.add((d[:4], d[5:7]))
                sels.append(d)
    elif cadence == "annual":
        seen, sels = set(), []
        for d in days:
            if d[:4] not in seen:
                seen.add(d[:4])
                sels.append(d)
    else:
        raise ValueError(cadence)
    jan_reset, seen_y = set(), set()
    for d in sels:
        if d[5:7] == "01" and d[:4] not in seen_y:
            seen_y.add(d[:4])
            jan_reset.add(d)
    return sels, jan_reset


# ------------------------------------------- cadence-generalized engine
def run_two_sleeve_cad(pb, equity_rows, shares_rows, start, end,
                       sel_dates, jan_reset, start_cash=START_CASH,
                       floor0=FLOOR0, placebo_rng=None, label=""):
    """run_two_sleeve with the selection calendar and January-reset set
    passed in; sleeve mechanics copied from the original."""
    sA = Sleeve("A-value", start_cash / 2.0)
    sB = Sleeve("B-momentum", start_cash / 2.0)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None
    halted = None
    halt_info = None
    curve = []
    picks_log = []
    transfers = []

    for di, d in enumerate(days):
        if pending is not None:
            tA, tB, jan = pending
            amt = execute_rebalance(pb, sA, sB, d, tA, tB, jan)
            if jan and abs(amt) > 0.005:
                transfers.append((d, round(amt, 2)))
            pending = None
        if d in sel_set:
            scores, vr, mr, pool_sorted = score_cached(
                pb, equity_rows, shares_rows, d)
            if len(scores) >= 5:
                if placebo_rng is not None:
                    picksA = placebo_rng.sample(pool_sorted, 5)
                    picksB = placebo_rng.sample(pool_sorted, 5)
                else:
                    picksA = sorted(scores, key=lambda t: -vr[t])[:5]
                    picksB = sorted(scores, key=lambda t: -mr[t])[:5]
                vA = sA.close_value(pb, d)
                vB = sB.close_value(pb, d)
                total = vA + vB
                january = d in jan_reset
                if january:
                    eachA = (total / 2.0) / 5.0
                    eachB = (total / 2.0) / 5.0
                else:
                    eachA = vA / 5.0
                    eachB = vB / 5.0
                pending = ({t: eachA for t in picksA},
                           {t: eachB for t in picksB}, january)
                picks_log.append((d, list(picksA), list(picksB)))
        vA = sA.close_value(pb, d)
        vB = sB.close_value(pb, d)
        v = vA + vB
        curve.append((d, v, vA, vB))
        if v <= floor0 and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor0}
            nd = days[di + 1]
            for sl in (sA, sB):
                for t in list(sl.positions):
                    b = pb.bar(t, nd)
                    if b:
                        val = sl.positions[t] * b["o"]
                        c = val * 0.001 + 0.01
                        sl.cash += val - c
                        sl.costs += c
                        sl.trades.append((nd, t, "SELL-HALT",
                                          sl.positions[t], b["o"], val, c))
                sl.positions = {}
            return {"label": label, "final": sA.cash + sB.cash,
                    "costs": sA.costs + sB.costs,
                    "orders": len(sA.trades) + len(sB.trades),
                    "halted": halted, "halt_info": halt_info,
                    "curve": curve, "picks": picks_log,
                    "transfers": transfers,
                    "sleeve_finals": (sA.cash, sB.cash)}
    last = days[-1]
    for sl in (sA, sB):
        for t in list(sl.positions):
            c_ = pb.close_on_or_before(t, last)
            if c_:
                val = sl.positions[t] * c_
                cst = val * 0.001 + 0.01
                sl.cash += val - cst
                sl.costs += cst
                sl.trades.append((last, t, "SELL-END",
                                  sl.positions[t], c_, val, cst))
        sl.positions = {}
    return {"label": label, "final": sA.cash + sB.cash,
            "costs": sA.costs + sB.costs,
            "orders": len(sA.trades) + len(sB.trades),
            "halted": None, "halt_info": None,
            "curve": curve, "picks": picks_log, "transfers": transfers,
            "sleeve_finals": (sA.cash, sB.cash)}


# ------------------------------------------- cadence-generalized v9 wrap
def run_v10(pb, equity_rows, shares_rows, start, end, sel_dates, jan_reset,
            start_cash=START_CASH, placebo_seed=None, label=""):
    """v9 protections on the cadence engine: episode-1 plain -15% floor;
    first halt -> liquidate next open, 90 calendar days in cash, restart
    at the next cadence selection date on/after day 90; episode-2 floor
    -15% from the restart balance; second halt ends the run. A placebo
    twin keeps ONE random stream across both episodes."""
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_two_sleeve_cad(pb, equity_rows, shares_rows, start, end,
                            sel_dates, jan_reset, start_cash=start_cash,
                            floor0=floor1, placebo_rng=rng,
                            label=label + " EP1")
    curve = [(d, v) for d, v, _, _ in r1["curve"]]
    out = {"final": r1["final"], "costs": r1["costs"],
           "orders": r1["orders"], "curve": curve,
           "halt_events": [], "restarts": [], "second_halt": None,
           "episodes": 1}
    if r1["halted"] is None:
        return out
    liq_date = next(d for d in pb.dates if r1["halted"] < d <= end)
    out["halt_events"].append({
        "episode": 1, "signal_date": r1["halted"],
        "signal_close": r1["halt_info"]["signal_close"],
        "floor_in_effect": r1["halt_info"]["floor_in_effect"],
        "liquidation_date": liq_date,
        "liquidation_value": round(r1["final"], 2)})
    cash = r1["final"]
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _dt.date(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in sel_dates:
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _dt.date(cy, cm, cd).toordinal() >= day90 and start <= cand <= end:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({
        "halt_signal_date": r1["halted"],
        "liquidation_date": liq_date,
        "halt_signal_close": r1["halt_info"]["signal_close"],
        "restart_date": restart,
        "restart_balance": round(cash, 2),
        "episode2_floor": floor2})
    r2 = run_two_sleeve_cad(pb, equity_rows, shares_rows, restart, end,
                            sel_dates, jan_reset, start_cash=cash,
                            floor0=floor2, placebo_rng=rng,
                            label=label + " EP2")
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["orders"] += r2["orders"]
    out["curve"] += [(d, v) for d, v, _, _ in r2["curve"]]
    if r2["halted"] is not None:
        liq2 = next((d for d in pb.dates if r2["halted"] < d <= end), end)
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": liq2,
                              "final": round(r2["final"], 2)}
        out["halt_events"].append({
            "episode": 2, "signal_date": r2["halted"],
            "signal_close": r2["halt_info"]["signal_close"],
            "floor_in_effect": r2["halt_info"]["floor_in_effect"],
            "liquidation_date": liq2,
            "liquidation_value": round(r2["final"], 2)})
    out["curve"].sort(key=lambda kv: kv[0])
    return out


# ---------------------------------------------------------------- metrics
def _ord(d):
    return _dt.date(int(d[:4]), int(d[5:7]), int(d[8:10])).toordinal()


def metrics(final, curve, start, end, start_cash=START_CASH):
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    years = (_ord(end) - _ord(start)) / 365.25
    cagr = (final / start_cash) ** (1.0 / years) - 1.0 if final > 0 else -1.0
    return {"final": round(final, 2), "cagr_pct": round(cagr * 100, 2),
            "max_dd_pct": round(maxdd * 100, 2)}


# ------------------------------------------------------------------- main
def main():
    t0 = time.time()
    equity_rows, shares_rows = build_facts()
    print("facts built", flush=True)

    # ---- INTEGRITY: original engine, original v4 price caches --------
    bars_orig = {t: E.get_prices(t) for t in E.UNIVERSE + ["SPY"]}
    pb_orig = FastBook(bars_orig)
    integ = {}
    for name, win in (("CONT", CONT), ("VAL", VAL)):
        r = run_two_sleeve(pb_orig, equity_rows, shares_rows, win[0], win[1],
                           label=f"INTEGRITY {name}", quiet=True)
        integ[name] = {"final": round(r["final"], 2), "costs": round(r["costs"], 2),
                       "orders": r["orders"], "halted": r["halted"]}
        print(f"INTEGRITY {name}: final=${r['final']:.2f} halted={r['halted']}",
              flush=True)
    spy_orig = {name: round(E.spy_net(pb_orig, w[0], w[1], 100.0)[0], 2)
                for name, w in (("CONT", CONT), ("VAL", VAL))}
    print(f"SPY orig plumbing: {spy_orig}", flush=True)

    # ---- full-history book for the decade sweep -----------------------
    bars_full = {t: _bars_adj(_load_pxfull(t)) for t in E.UNIVERSE + ["SPY"]}
    pb = FastBook(bars_full)
    spy_dec, _ = E.spy_net(pb, DECADE[0], DECADE[1], 100.0)
    print(f"SPY DECADE (full book): ${spy_dec:.2f}", flush=True)

    # cross-check: generalized quarterly engine on the full book must
    # land on the same CONT/VAL finals (validates the cadence twin and
    # the pxfull bar construction against the originals)
    xcheck = {}
    for name, win in (("CONT", CONT), ("VAL", VAL)):
        sels, janr = cadence_dates(pb, win[0], win[1], "quarterly")
        r = run_v10(pb, equity_rows, shares_rows, win[0], win[1], sels, janr,
                    label=f"XCHECK {name}")
        xcheck[name] = round(r["final"], 2)
        print(f"XCHECK {name} (cadence engine, full book): ${r['final']:.2f}",
              flush=True)

    # ---- SWEEP ---------------------------------------------------------
    cells = {}
    for cad in CADENCES:
        sels, janr = cadence_dates(pb, DECADE[0], DECADE[1], cad)
        r = run_v10(pb, equity_rows, shares_rows, DECADE[0], DECADE[1],
                    sels, janr, label=f"DECADE {cad}")
        m = metrics(r["final"], r["curve"], DECADE[0], DECADE[1])
        print(f"[{cad}] ranked final=${r['final']:.2f} halts={len(r['halt_events'])} "
              f"restarts={len(r['restarts'])} costs=${r['costs']:.2f} "
              f"orders={r['orders']} ({time.time()-t0:.0f}s)", flush=True)
        twins = []
        for seed in PLACEBO_SEEDS:
            pr = run_v10(pb, equity_rows, shares_rows, DECADE[0], DECADE[1],
                         sels, janr, placebo_seed=seed,
                         label=f"DECADE {cad} PL{seed}")
            twins.append({"seed": seed, "final": round(pr["final"], 2),
                          "halts": len(pr["halt_events"]),
                          "restart": bool(pr["restarts"]),
                          "second_halt": pr["second_halt"] is not None})
            print(f"[{cad}] placebo {seed}: ${pr['final']:.2f}", flush=True)
        beaten = sum(1 for t in twins if r["final"] > t["final"])
        cell = {"slug": "vm-twosleeve", "cadence": cad,
                "window": {"start": DECADE[0], "end": DECADE[1]},
                "start_cash": START_CASH,
                **m,
                "costs": round(r["costs"], 2), "orders": r["orders"],
                "halts": len(r["halt_events"]), "halt_events": r["halt_events"],
                "restarts": r["restarts"], "second_halt": r["second_halt"],
                "episodes": r["episodes"],
                "selection_dates_count": len(sels),
                "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
                "placebo_beaten": beaten,
                "placebo_twin_finals": twins}
        cells[cad] = cell
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        print(f"[{cad}] placebo beaten {beaten}/20 — cell saved", flush=True)

    raw = {"slug": "vm-twosleeve", "integrity_runs": integ,
           "spy_orig_plumbing": spy_orig,
           "decade_spy_final": round(spy_dec, 2),
           "crosscheck_full_book": xcheck,
           "cells_summary": {c: {k: cell[k] for k in
                                 ("final", "cagr_pct", "max_dd_pct", "costs",
                                  "orders", "halts", "placebo_beaten")}
                             for c, cell in cells.items()}}
    with open(os.path.join(HERE, "sweep_raw.json"), "w") as f:
        json.dump(raw, f, indent=1)
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__" and False:
    main()


# ============================================================ CONFIRMATION
# THE GREAT RETEST (v10) — CONFIRMATION RUN for vm-twosleeve, SEMIANNUAL
# cadence (Terry's confirmation rule, SPEC.md). Everything above is the
# sweep script copied unchanged (original engine byte-for-byte + v10
# cadence module + v9 protections). This driver re-runs the two-sleeve
# at SEMIANNUAL and QUARTERLY on CONT and VAL (full pxfull book, same
# plumbing as the sweep, January 50/50 reset annual as published inside
# every cell), 20-seed placebos per cadence per road (same twin design),
# and fresh yearly folds 2017-2026 at semiannual. LONG (2010) is NOT
# run: the universe is the point-in-time top-30 pond as of Nov 2016 —
# a fixed later universe for 2010, so a 2010 start would be flattered.
# Writes ONLY into confirmation/. Simulation only.
# ============================================================

def conf_main():
    t0 = time.time()
    equity_rows, shares_rows = build_facts()
    print("facts built", flush=True)
    bars_full = {t: _bars_adj(_load_pxfull(t)) for t in E.UNIVERSE + ["SPY"]}
    pb = FastBook(bars_full)
    OUT = HERE  # this script lives inside confirmation/; write here

    def one_run(road, start, end, cad):
        sels, janr = cadence_dates(pb, start, end, cad)
        r = run_v10(pb, equity_rows, shares_rows, start, end, sels, janr,
                    label=f"{road} {cad}")
        m = metrics(r["final"], r["curve"], start, end)
        spy_final, _ = E.spy_net(pb, start, end, 100.0)
        twins = []
        for seed in PLACEBO_SEEDS:
            pr = run_v10(pb, equity_rows, shares_rows, start, end, sels, janr,
                         placebo_seed=seed, label=f"{road} {cad} PL{seed}")
            twins.append({"seed": seed, "final": round(pr["final"], 2),
                          "halts": len(pr["halt_events"]),
                          "restart": bool(pr["restarts"]),
                          "second_halt": pr["second_halt"] is not None})
        beaten = sum(1 for t in twins if r["final"] > t["final"])
        rec = {"slug": "vm-twosleeve", "road": road, "cadence": cad,
               "window": {"start": start, "end": end},
               "start_cash": START_CASH, **m,
               "costs": round(r["costs"], 2), "orders": r["orders"],
               "halts": len(r["halt_events"]), "halt_events": r["halt_events"],
               "restarts": r["restarts"], "second_halt": r["second_halt"],
               "episodes": r["episodes"],
               "selection_dates_count": len(sels),
               "spy_final": round(spy_final, 2),
               "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
               "placebo_beaten": beaten,
               "placebo_twin_finals": twins}
        with open(os.path.join(OUT, f"{road}-{cad}.json"), "w") as f:
            json.dump(rec, f, indent=1)
        print(f"[{road} {cad}] final=${r['final']:.2f} SPY=${spy_final:.2f} "
              f"placebo {beaten}/20 halts={len(r['halt_events'])} "
              f"costs=${r['costs']:.2f} orders={r['orders']} "
              f"({time.time()-t0:.0f}s)", flush=True)
        return rec

    results = {}
    for road, (s, e) in (("CONT", CONT), ("VAL", VAL)):
        for cad in ("semiannual", "quarterly"):
            results[(road, cad)] = one_run(road, s, e, cad)

    folds = []
    for y in range(2017, 2027):
        s = f"{y}-01-01"
        e = "2026-11-20" if y == 2026 else f"{y}-12-31"
        sels, janr = cadence_dates(pb, s, e, "semiannual")
        r = run_v10(pb, equity_rows, shares_rows, s, e, sels, janr,
                    label=f"FOLD {y}")
        m = metrics(r["final"], r["curve"], s, e)
        spy_final, _ = E.spy_net(pb, s, e, 100.0)
        folds.append({"year": y, "window": {"start": s, "end": e}, **m,
                      "costs": round(r["costs"], 2), "orders": r["orders"],
                      "halts": len(r["halt_events"]),
                      "halt_events": r["halt_events"],
                      "restarts": r["restarts"],
                      "second_halt": r["second_halt"],
                      "spy_final": round(spy_final, 2),
                      "beat_spy": bool(r["final"] > spy_final),
                      "above_start": bool(r["final"] > 100.0),
                      "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]]})
        print(f"[FOLD {y}] final=${r['final']:.2f} SPY=${spy_final:.2f} "
              f"beat_spy={r['final'] > spy_final} halts={len(r['halt_events'])} "
              f"({time.time()-t0:.0f}s)", flush=True)
    with open(os.path.join(OUT, "folds.json"), "w") as f:
        json.dump({"slug": "vm-twosleeve", "cadence": "semiannual",
                   "folds": folds}, f, indent=1)

    summary = {f"{rd}-{cd}": {k: rec[k] for k in
                               ("final", "cagr_pct", "max_dd_pct", "costs",
                                "orders", "halts", "placebo_beaten",
                                "spy_final")}
               for (rd, cd), rec in results.items()}
    with open(os.path.join(OUT, "conf_raw.json"), "w") as f:
        json.dump({"runs": summary,
                   "folds": [{k: v for k, v in fo.items()
                              if k != "equity_curve"} for fo in folds]},
                  f, indent=1)
    print(f"DONE in {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    conf_main()
