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


def main():
    pb, equity_rows, shares_rows = build_inputs()
    print("inputs built", flush=True)

    # Main windows: floor never fired under his rules (continuous worst
    # close $93.11 on 2020-03-23; validation worst close $94.67 on
    # 2023-03-22; both halted=None) -> identical under v9, NOT re-run.
    # Folds 2020 (halt 2020-03-09) and 2022 (halt 2022-04-29) fired.
    runs = {}
    for y, (fs, fe, exp_final, exp_halt) in {
            2020: ("2020-01-01", "2020-12-31", 86.36, "2020-03-09"),
            2022: ("2022-01-01", "2022-12-31", 84.37, "2022-04-29")}.items():
        r = run_two_sleeve_v9(pb, equity_rows, shares_rows, fs, fe,
                              label=f"V9 FOLD {y}")
        print(f"FOLD {y} EP1 final=${r['ep1_final']:.2f} halted={r['halted']} "
              f"liq={r['ep1_liq']} (recorded his: ${exp_final}, halt {exp_halt})",
              flush=True)
        assert abs(r["ep1_final"] - exp_final) < 0.02 and r["halted"] == exp_halt, \
            f"fold {y} episode-1 reproduction failed"
        print(f"V9 FOLD {y} final=${r['final']:.2f} restarts={r['restarts']} "
              f"second_halt={r['second_halt']}", flush=True)
        runs[y] = r

    v9_folds = []
    for f in HIS_FOLDS:
        if f["year"] in runs:
            r = runs[f["year"]]
            v9_folds.append({"year": f["year"], "final": round(r["final"], 2),
                             "spy_net": f["spy_net"],
                             "beat_spy": r["final"] > f["spy_net"],
                             "halted_ep1": r["halted"],
                             "second_halt": r["second_halt"]})
        else:
            v9_folds.append({"year": f["year"], "final": f["final"],
                             "spy_net": f["spy_net"],
                             "beat_spy": f["final"] > f["spy_net"],
                             "halted_ep1": f["halted"], "second_halt": None})
    his_wins = sum(1 for f in HIS_FOLDS if f["final"] > f["spy_net"])
    v9_wins = sum(1 for f in v9_folds if f["beat_spy"])
    def comp(folds):
        c = 100.0
        for f in folds:
            c *= f["final"] / 100.0
        return round(c, 2)
    v9_min = min([v for r in runs.values() for _, v in r["curve"]] +
                 [r["final"] for r in runs.values()])
    restarts = [{"window": f"fold-{y}", **x}
                for y, r in sorted(runs.items()) for x in r["restarts"]]
    out = {
        "slug": "vm-twosleeve",
        "name": "AMP two-sleeve value/momentum blend ($50/$50, January reset)",
        "status": "partial-rerun",
        "his": {"continuous_final": 442.01, "validation_final": 263.09},
        "v9": {
            "continuous_final": 442.01, "validation_final": 263.09,
            "continuous_status": "identical - floor never fired (worst close $93.11 on 2020-03-23 vs $85 floor; halted=None in v5 results)",
            "validation_status": "identical - floor never fired (worst close $94.67 on 2023-03-22 vs $85 floor; halted=None in v5 results)",
            "restarts": restarts,
            "folds_note": (f"His folds 4/7 vs SPY (fold-compounded ${comp(HIS_FOLDS)}); "
                           f"v9 folds {v9_wins}/7 vs SPY (fold-compounded ${comp(v9_folds)}). "
                           f"Folds 2020 (halt 2020-03-09, final $86.36) and 2022 (halt 2022-04-29, final $84.37) "
                           f"fired under his rules and were re-run under v9: 2020 final ${round(runs[2020]['final'],2)}, "
                           f"2022 final ${round(runs[2022]['final'],2)}. Other folds never fired, unchanged."),
            "worst_total_loss_pct": round(v9_min / 100.0 * 100 - 100, 2),
        },
        "notes": ("Simulation only. Main windows NOT re-run: floor never fired there under his rules. "
                  "Both re-run folds' episode 1 reproduced the recorded his-rules results before "
                  "restarts were applied. His worst total loss from $100: -17.19% (2020 fold worst "
                  "close $82.81, v5 results JSON). "
                  f"V9 fold detail: {v9_folds}"),
        "detail": {f"fold_{y}_v9": {"ep1_final": round(r["ep1_final"], 2),
                                    "ep1_liquidation_date": r["ep1_liq"],
                                    "final": round(r["final"], 2),
                                    "costs": round(r["costs"], 2),
                                    "orders": r["orders"],
                                    "restarts": r["restarts"],
                                    "second_halt": r["second_halt"]}
                   for y, r in sorted(runs.items())},
    }
    out["detail"]["his_fold_compounded"] = comp(HIS_FOLDS)
    out["detail"]["v9_fold_compounded"] = comp(v9_folds)
    out["detail"]["his_fold_record"] = f"{his_wins} wins, {7-his_wins} losses vs SPY"
    out["detail"]["v9_fold_record"] = f"{v9_wins} wins, {7-v9_wins} losses vs SPY"
    with open(os.path.join(HERE, "v9-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
