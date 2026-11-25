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


def main():
    pb, equity_rows, shares_rows = build_inputs()
    out = {"strategy": "two-sleeve value/momentum blend (AMP 2013), $50/$50, "
                       "quarterly top-5 per sleeve, January 50/50 reset, "
                       "plain -15% whole-pot floor",
           "universe": E.UNIVERSE, "pot": START_CASH, "floor": FLOOR0,
           "baseline_promoted_vm": {"validation_final": 288.05,
                                    "continuous_final": 544.47,
                                    "placebo_beaten_validation": "18/20",
                                    "placebo_beaten_continuous": "19/20",
                                    "fold_record": "4 wins, 3 losses"}}

    # ---- ranked runs
    ranked = {}
    for wname, (ws, we) in (("CONTINUOUS", CONT), ("VALIDATION", VAL)):
        r = run_two_sleeve(pb, equity_rows, shares_rows, ws, we,
                           label=f"{wname} RANKED", quiet=True)
        spy, _ = E.spy_net(pb, ws, we, START_CASH)
        diag = diagnostics(r, FLOOR0)
        corr = sleeve_correlations(r)
        ranked[wname] = {"start": ws, "end": we,
                         "final": round(r["final"], 2),
                         "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
                         "costs": round(r["costs"], 2), "orders": r["orders"],
                         "halted": r["halted"], "halt_info": r["halt_info"],
                         "spy_net_final": round(spy, 2),
                         "spy_return_pct": round(spy / START_CASH * 100 - 100, 2),
                         "sleeve_finals": [round(x, 2) for x in r["sleeve_finals"]],
                         "january_transfers": r["transfers"],
                         "sleeve_correlation": corr, "diag": diag,
                         "picks": r["picks"]}
        print(f"== {wname} RANKED final=${r['final']:,.2f} "
              f"({ranked[wname]['return_pct']:+.2f}%) costs=${r['costs']:,.2f} "
              f"orders={r['orders']} halted={r['halted']} | SPY net=${spy:,.2f}",
              flush=True)
        print(f"   sleeves end A=${r['sleeve_finals'][0]:,.2f} "
              f"B=${r['sleeve_finals'][1]:,.2f} | corr daily={corr['daily_corr']} "
              f"monthly={corr['monthly_corr']} | worst close "
              f"${diag['worst_close']:,.2f} on {diag['worst_close_date']} "
              f"(margin ${diag['worst_close_above_floor']:,.2f}) | maxDD "
              f"{diag['max_drawdown_pct']}% | COVID worst "
              f"${diag['covid_worst_close']} on {diag['covid_worst_date']}",
              flush=True)
    out["ranked"] = ranked

    # ---- placebo, both windows
    out["placebo_continuous"] = placebo_block(
        pb, equity_rows, shares_rows, CONT, ranked["CONTINUOUS"]["final"],
        "CONTINUOUS")
    out["placebo_validation"] = placebo_block(
        pb, equity_rows, shares_rows, VAL, ranked["VALIDATION"]["final"],
        "VALIDATION")
    print(f"PLACEBO CONTINUOUS: ranked beats "
          f"{out['placebo_continuous']['ranked_beats_seeds']}/20 "
          f"(median ${out['placebo_continuous']['median']:,.2f})", flush=True)
    print(f"PLACEBO VALIDATION: ranked beats "
          f"{out['placebo_validation']['ranked_beats_seeds']}/20 "
          f"(median ${out['placebo_validation']['median']:,.2f})", flush=True)

    # ---- walk-forward folds
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_two_sleeve(pb, equity_rows, shares_rows, fs, fe,
                            label=f"FOLD {y}", quiet=True)
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        fdiag = diagnostics(fr, FLOOR0)
        row = {"year": y, "start": fs, "end": fe,
               "final": round(fr["final"], 2),
               "return_pct": round(fr["final"] / START_CASH * 100 - 100, 2),
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "max_drawdown_pct": fdiag["max_drawdown_pct"],
               "worst_close": fdiag["worst_close"],
               "orders": fr["orders"], "costs": round(fr["costs"], 2),
               "halted": fr["halted"]}
        folds.append(row)
        print(f"FOLD {y}: two-sleeve ${fr['final']:,.2f} "
              f"({row['return_pct']:+.2f}%) vs SPY ${fspy:,.2f} "
              f"({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"maxDD={row['max_drawdown_pct']}% halted={row['halted']}",
              flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"

    with open(os.path.join(HERE, "vm-twosleeve-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
