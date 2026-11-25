#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — crypto-trend. SIMULATION ONLY.

Strategy (frozen, from backtests/v4/crypto-trend.py + .md): for each of
BTC-USD and ETH-USD, hold the asset when its close is above its 200-day
moving average (computed on DAILY bars), otherwise hold cash at 0%.
Original form: decisions WEEKLY (last bar of each ISO week), executed at
the next daily bar's open. Costs 0.25%/side (the engine's own cost code,
kept identical — crypto convention in this program, not the stock
0.10% + $0.01). Combo pot = two $50 sleeves, floor on combined equity.

This script does three things:
  1. INTEGRITY — re-runs the ORIGINAL engine form (weekly, last-bar evals)
     in (a) its original no-floor / plain-floor form and (b) the v9
     two-episode protection form, and compares against the published
     finals (v4 crypto-trend-results.json and v9-muse-rules v9-results.json:
     v9 FULL BTC $13,058.82 / ETH $731.61 / COMBO $953.90;
     v9 VAL  BTC $189.75 / ETH $132.33 / COMBO $161.04).
  2. SWEEP — DECADE road 2016-11-21 -> 2026-11-20 at 7 cadences under the
     SPEC's uniform cadence definition: the 200-day trend signal is always
     computed on daily bars; the CADENCE governs evaluation/entry/exit
     dates only. Eval dates = FIRST bar of each period (daily = every bar;
     weekly = first bar of each ISO week; biweekly = first bar of every
     second ISO week, anchored on Mondays since 1970-01-05; monthly /
     quarterly / semi-annual / annual = first bar of the calendar period).
     A decision made at an eval date's close executes at the next bar's
     open (the original engine's execution rule). The v9 protection floor
     is checked on every daily close (protection is not cadence-governed,
     exactly as in the v9 engine); on a first halt the pot sits in cash
     90 calendar days and restarts at the next CADENCE date on/after
     eligibility under an episode-2 floor of -15% from the restart
     balance; a second halt ends the run.
     NOTE: the sweep's weekly cell evaluates on the FIRST bar of the week
     (SPEC uniform definition); the original engine evaluated on the LAST
     bar. That placement difference is the only form difference between
     the sweep's native (weekly) cell and the original test.
  3. PLACEBOS — the original chassis design: random in/out timing at the
     cadence dates with the same average exposure as the trend rule at
     that cadence, 20 seeds (42..61), no floor, per leg; the combo
     placebo is the original's approximation (mean of the two legs'
     $100-pot placebo finals). Seeds beaten counted against the cell's
     v9 combo final (headline) and also recorded vs the no-floor trend.

Benchmarks on the decade road: BTC buy-and-hold, ETH buy-and-hold and
the 50/50 combo buy-and-hold (original engine, no floor, 0.25% entry
cost), and SPY buy-and-hold dividend-adjusted (program convention:
cached Yahoo payload in backtests/v7/long-hold/data/pxfull_SPY.json,
read-only; buy at 2016-11-21 open scaled by adjclose/close, sell at
2026-11-20 adjclose, 0.10%/side program costs) = $367.81 ~ SPEC $367.80.

Data: Yahoo daily bars cached in backtests/v4/crypto-trend-data/
(read-only shared cache); byte-identical copies live in this folder's
data/ and are what this script reads.
"""
import json, math, os, random, time
from datetime import timedelta
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CELLS = os.path.join(HERE, "cells")
os.makedirs(CELLS, exist_ok=True)

START_CASH = 100.0
COST = 0.0025            # 0.25% per side — the original crypto engine's cost
END_DATE = "2026-11-20"
VAL_START = "2023-01-01"
DEC0, DEC1 = "2016-11-21", "2026-11-20"
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ---------------------------------------------------------------- data ----
def load(symbol):
    df = pd.read_csv(os.path.join(DATA, f"{symbol}.csv"), parse_dates=["date"])
    return df.sort_values("date").reset_index(drop=True)

def prep(df):
    """Original prep: SMA200 on daily closes + original weekly eval flag
    (LAST bar of each ISO week) used by the integrity runs."""
    df = df.copy()
    df["sma200"] = df["close"].rolling(200).mean()
    iso = df["date"].dt.isocalendar()
    df["yw"] = iso["year"].astype(str) + "-" + iso["week"].astype(str).str.zfill(2)
    df["is_eval"] = df.index.isin(df.groupby("yw").tail(1).index)
    return df

def add_cadence_evals(df):
    """SPEC uniform cadence eval flags: first bar of each period."""
    d = df["date"]
    iso = d.dt.isocalendar()
    df["ev_daily"] = True
    wk = (iso["year"].astype(int) * 100 + iso["week"].astype(int))
    df["ev_weekly"] = wk != wk.shift(1)
    # biweekly: ordinal week count from Monday 1970-01-05, even weeks, first bar
    ordinal = (d - pd.Timestamp("1970-01-05")).dt.days // 7
    df["ev_biweekly"] = (ordinal % 2 == 0) & (wk != wk.shift(1))
    mo = d.dt.year * 100 + d.dt.month
    df["ev_monthly"] = mo != mo.shift(1)
    q = d.dt.year * 10 + (d.dt.month - 1) // 3
    df["ev_quarterly"] = q != q.shift(1)
    h = d.dt.year * 10 + (d.dt.month - 1) // 6
    df["ev_semiannual"] = h != h.shift(1)
    df["ev_annual"] = d.dt.year != d.dt.year.shift(1)
    return df

# ------------------------------------------------- original engine (v4/v9) ----
# run_asset / run_combo / buy_hold / buy_hold_combo are the original v4
# engine's functions, copied with three mechanical changes only:
#   (a) an `eval_col` parameter (default "is_eval" = original behaviour)
#       so the sweep can point evaluation at a cadence flag column;
#   (b) a `start_cash` parameter replacing the module-global START_CASH
#       the v9 driver mutated (identical arithmetic);
#   (c) run_combo gains per-sleeve start cash (for episode-2 restarts).
# Signal, costs, floor mechanics and execution are byte-equivalent logic.
def run_asset(df, w0, w1, floor_mode="none", seed=None, placebo_p=None,
              eval_col="is_eval", start_cash=START_CASH):
    d = df[(df["date"] >= w0) & (df["date"] <= w1)].reset_index(drop=True)
    full_idx = df[(df["date"] >= w0) & (df["date"] <= w1)].index
    cash, units = start_cash, 0.0
    start = start_cash
    floor = 0.85 * start
    halted, halt_date = False, None
    trades, total_costs = 0, 0.0
    invested_days, total_days = 0, 0
    equity_curve = []
    pending = None
    rng = random.Random(seed) if seed is not None else None
    invested_weeks, total_weeks = 0, 0
    for i, row in d.iterrows():
        gi = full_idx[i]
        if pending is not None and not halted:
            px = row["open"]
            if pending == "in" and units == 0.0 and cash > 0:
                fee = cash * COST
                units = (cash - fee) / px
                total_costs += fee; cash = 0.0; trades += 1
            elif pending == "out" and units > 0:
                gross = units * px
                fee = gross * COST
                cash = gross - fee
                total_costs += fee; units = 0.0; trades += 1
            pending = None
        eq_close = cash + units * row["close"]
        equity_curve.append((row["date"], eq_close))
        total_days += 1
        if units > 0:
            invested_days += 1
        if halted:
            continue
        if floor_mode in ("plain", "ladder") and eq_close <= floor:
            nxt = gi + 1
            if units > 0 and nxt < len(df):
                px = df.loc[nxt, "open"]
                gross = units * px
                fee = gross * COST
                cash = gross - fee
                total_costs += fee; units = 0.0; trades += 1
                halt_date = df.loc[nxt, "date"]
            else:
                halt_date = row["date"]
            halted = True
            pending = None
            continue
        if row[eval_col]:
            total_weeks += 1
            if rng is not None:
                want_in = rng.random() < placebo_p
            else:
                sma = row["sma200"]
                want_in = (not pd.isna(sma)) and (row["close"] > sma)
            if want_in:
                invested_weeks += 1
            target = "in" if want_in else "out"
            if (target == "in") != (units > 0):
                pending = target
    if units > 0:
        final = cash + units * d.iloc[-1]["close"]
    else:
        final = cash
    eq = pd.Series([e for _, e in equity_curve])
    max_dd = ((eq / eq.cummax()) - 1).min() * 100 if len(eq) else 0.0
    years = max((d.iloc[-1]["date"] - d.iloc[0]["date"]).days / 365.25, 1e-9)
    cagr = ((final / start) ** (1 / years) - 1) * 100 if final > 0 else -100.0
    return {
        "final": final, "cagr": cagr, "max_dd": max_dd, "trades": trades,
        "costs": total_costs, "halted": halted,
        "halt_date": (halt_date.strftime("%Y-%m-%d") if halt_date is not None else None),
        "exposure_days_pct": invested_days / total_days * 100 if total_days else 0.0,
        "exposure_evals": invested_weeks / total_weeks if total_weeks else 0.0,
        "equity": equity_curve,
    }

def run_combo(dfs, w0, w1, floor_mode="none", eval_col="is_eval",
              start_cash=START_CASH):
    sleeves = []
    for sym, df in dfs.items():
        d = df[(df["date"] >= w0) & (df["date"] <= w1)].reset_index(drop=True)
        sleeves.append({"sym": sym, "df": df, "d": d, "cash": start_cash / 2.0,
                        "units": 0.0, "pending": None, "trades": 0, "costs": 0.0,
                        "invested_days": 0})
    start = start_cash
    floor = 0.85 * start
    halted, halt_date = False, None
    all_dates = sorted(set().union(*[set(s["d"]["date"]) for s in sleeves]))
    rows = {s["sym"]: {r["date"]: r for _, r in s["d"].iterrows()} for s in sleeves}
    full_rows = {s["sym"]: {r["date"]: r for _, r in s["df"].iterrows()} for s in sleeves}
    next_open = {}
    for s in sleeves:
        dl = list(s["df"]["date"])
        next_open[s["sym"]] = {dl[i]: (dl[i + 1] if i + 1 < len(dl) else None)
                               for i in range(len(dl))}
    equity_curve = []
    sleeve_curves = {s["sym"]: [] for s in sleeves}
    total_days = 0
    for dt in all_dates:
        for s in sleeves:
            r = rows[s["sym"]].get(dt)
            if r is None or s["pending"] is None or halted:
                continue
            px = r["open"]
            if s["pending"] == "in" and s["units"] == 0 and s["cash"] > 0:
                fee = s["cash"] * COST
                s["units"] = (s["cash"] - fee) / px
                s["costs"] += fee; s["cash"] = 0.0; s["trades"] += 1
            elif s["pending"] == "out" and s["units"] > 0:
                gross = s["units"] * px
                fee = gross * COST
                s["cash"] = gross - fee
                s["costs"] += fee; s["units"] = 0.0; s["trades"] += 1
            s["pending"] = None
        eq = 0.0
        for s in sleeves:
            r = rows[s["sym"]].get(dt)
            last_close = r["close"] if r is not None else s.get("last_close", 0.0)
            if r is not None:
                s["last_close"] = last_close
                if s["units"] > 0:
                    s["invested_days"] += 1
            sv = s["cash"] + s["units"] * last_close
            sleeve_curves[s["sym"]].append((dt, sv))
            eq += sv
        equity_curve.append((dt, eq))
        total_days += 1
        if halted:
            continue
        if floor_mode in ("plain", "ladder") and eq <= floor:
            for s in sleeves:
                if s["units"] > 0:
                    nd = next_open[s["sym"]].get(dt)
                    px = full_rows[s["sym"]][nd]["open"] if nd is not None else s["last_close"]
                    gross = s["units"] * px
                    fee = gross * COST
                    s["cash"] = gross - fee
                    s["costs"] += fee; s["units"] = 0.0; s["trades"] += 1
                    halt_date = nd if nd is not None else dt
            halted = True
            for s in sleeves:
                s["pending"] = None
            continue
        for s in sleeves:
            r = rows[s["sym"]].get(dt)
            if r is not None and r[eval_col]:
                sma = r["sma200"]
                want_in = (not pd.isna(sma)) and (r["close"] > sma)
                target = "in" if want_in else "out"
                if (target == "in") != (s["units"] > 0):
                    s["pending"] = target
    final = sum(s["cash"] + s["units"] * s.get("last_close", 0.0) for s in sleeves)
    eqs = pd.Series([e for _, e in equity_curve])
    max_dd = ((eqs / eqs.cummax()) - 1).min() * 100 if len(eqs) else 0.0
    d0, d1 = equity_curve[0][0], equity_curve[-1][0]
    years = max((d1 - d0).days / 365.25, 1e-9)
    cagr = ((final / start) ** (1 / years) - 1) * 100 if final > 0 else -100.0
    return {
        "final": final, "cagr": cagr, "max_dd": max_dd,
        "trades": sum(s["trades"] for s in sleeves),
        "costs": sum(s["costs"] for s in sleeves),
        "halted": halted,
        "halt_date": (halt_date.strftime("%Y-%m-%d") if halt_date is not None else None),
        "equity": equity_curve, "sleeve_equity": sleeve_curves,
    }

def buy_hold(df, w0, w1):
    d = df[(df["date"] >= w0) & (df["date"] <= w1)].reset_index(drop=True)
    fee0 = START_CASH * COST
    units = (START_CASH - fee0) / d.iloc[0]["open"]
    eqs = [units * c for c in d["close"]]
    final = units * d.iloc[-1]["close"]
    eq = pd.Series(eqs)
    max_dd = ((eq / eq.cummax()) - 1).min() * 100
    years = max((d.iloc[-1]["date"] - d.iloc[0]["date"]).days / 365.25, 1e-9)
    cagr = ((final / START_CASH) ** (1 / years) - 1) * 100
    curve = [(d.iloc[i]["date"], eqs[i]) for i in range(len(d))]
    return {"final": final, "cagr": cagr, "max_dd": max_dd, "trades": 1,
            "costs": fee0, "equity": curve}

def buy_hold_combo(dfs, w0, w1):
    tot_curve = None
    finals, costs = 0.0, 0.0
    for sym, df in dfs.items():
        r = buy_hold(df, w0, w1)  # $100 scale; halve for the $50 sleeve
        finals += r["final"] / 2.0
        costs += r["costs"] / 2.0
        c = pd.Series([e / 2.0 for _, e in r["equity"]],
                      index=[dt for dt, _ in r["equity"]])
        tot_curve = c if tot_curve is None else tot_curve.add(c, fill_value=None)
    tot_curve = tot_curve.dropna()
    max_dd = ((tot_curve / tot_curve.cummax()) - 1).min() * 100
    years = max((tot_curve.index[-1] - tot_curve.index[0]).days / 365.25, 1e-9)
    cagr = ((finals / START_CASH) ** (1 / years) - 1) * 100
    curve = [(dt, v) for dt, v in tot_curve.items()]
    return {"final": finals, "cagr": cagr, "max_dd": max_dd, "trades": 2,
            "costs": costs, "equity": curve}

# ------------------------------------------------------------- v9 episodes ----
def stitch(ep1, ep2, restart_cash, cal_dates):
    """Combined equity curve: episode 1, flat cash while halted, episode 2."""
    curve = list(ep1["equity"])
    if ep2 is None:
        return curve
    last_ep1_date = curve[-1][0]
    rdate = ep2["equity"][0][0]
    for dt in cal_dates:
        if last_ep1_date < dt < rdate:
            curve.append((dt, restart_cash))
    curve.extend(ep2["equity"])
    return curve

def curve_stats(curve, start_cash):
    eq = pd.Series([e for _, e in curve])
    max_dd = ((eq / eq.cummax()) - 1).min() * 100 if len(eq) else 0.0
    years = max((curve[-1][0] - curve[0][0]).days / 365.25, 1e-9)
    final = curve[-1][1]
    cagr = ((final / start_cash) ** (1 / years) - 1) * 100 if final > 0 else -100.0
    return final, cagr, max_dd

def run_v9_asset(df, w0, w1, eval_col="is_eval"):
    ep1 = run_asset(df, w0, w1, "plain", eval_col=eval_col)
    out = {"episodes": [ep1], "halts": 0, "restart": False, "restart_date": None,
           "second_halt": False, "second_halt_date": None, "halt_dates": []}
    if not ep1["halted"]:
        out["final"], out["cagr"], out["max_dd"] = ep1["final"], ep1["cagr"], ep1["max_dd"]
        out["costs"], out["trades"] = ep1["costs"], ep1["trades"]
        out["curve"] = ep1["equity"]
        return out
    out["halts"] = 1
    out["halt_dates"].append(ep1["halt_date"])
    restart_cash = ep1["final"]
    earliest = pd.Timestamp(ep1["halt_date"]) + timedelta(days=90)
    evals = df[(df[eval_col]) & (df["date"] >= earliest) & (df["date"] <= w1)]
    if len(evals) == 0:
        out["final"], out["cagr"], out["max_dd"] = ep1["final"], ep1["cagr"], ep1["max_dd"]
        out["costs"], out["trades"] = ep1["costs"], ep1["trades"]
        out["curve"] = ep1["equity"]
        out["restart_note"] = "halt + 90 days ran past window end; run ends in cash"
        return out
    rdate = evals.iloc[0]["date"]
    ep2 = run_asset(df, str(rdate.date()), w1, "plain", eval_col=eval_col,
                    start_cash=restart_cash)
    out["episodes"].append(ep2)
    out["restart"] = True
    out["restart_date"] = str(rdate.date())
    out["restart_cash"] = restart_cash
    out["ep2_floor"] = round(0.85 * restart_cash, 4)
    cal = list(df[(df["date"] >= w0) & (df["date"] <= w1)]["date"])
    out["curve"] = stitch(ep1, ep2, restart_cash, cal)
    out["final"], out["cagr"], out["max_dd"] = curve_stats(out["curve"], START_CASH)
    out["costs"] = ep1["costs"] + ep2["costs"]
    out["trades"] = ep1["trades"] + ep2["trades"]
    if ep2["halted"]:
        out["halts"] = 2
        out["second_halt"] = True
        out["second_halt_date"] = ep2["halt_date"]
        out["halt_dates"].append(ep2["halt_date"])
    return out

def run_v9_combo(dfs, w0, w1, eval_col="is_eval"):
    ep1 = run_combo(dfs, w0, w1, "plain", eval_col=eval_col)
    out = {"episodes": [ep1], "halts": 0, "restart": False, "restart_date": None,
           "second_halt": False, "second_halt_date": None, "halt_dates": []}
    if not ep1["halted"]:
        out.update({"final": ep1["final"], "cagr": ep1["cagr"], "max_dd": ep1["max_dd"],
                    "costs": ep1["costs"], "trades": ep1["trades"],
                    "curve": ep1["equity"], "sleeve_curves": ep1["sleeve_equity"]})
        return out
    out["halts"] = 1
    out["halt_dates"].append(ep1["halt_date"])
    restart_cash = ep1["final"]
    earliest = pd.Timestamp(ep1["halt_date"]) + timedelta(days=90)
    ref = dfs["BTC"]
    evals = ref[(ref[eval_col]) & (ref["date"] >= earliest) & (ref["date"] <= w1)]
    if len(evals) == 0:
        out.update({"final": ep1["final"], "cagr": ep1["cagr"], "max_dd": ep1["max_dd"],
                    "costs": ep1["costs"], "trades": ep1["trades"],
                    "curve": ep1["equity"], "sleeve_curves": ep1["sleeve_equity"],
                    "restart_note": "halt + 90 days ran past window end; run ends in cash"})
        return out
    rdate = evals.iloc[0]["date"]
    ep2 = run_combo(dfs, str(rdate.date()), w1, "plain", eval_col=eval_col,
                    start_cash=restart_cash)
    out["episodes"].append(ep2)
    out["restart"] = True
    out["restart_date"] = str(rdate.date())
    out["restart_cash"] = restart_cash
    out["ep2_floor"] = round(0.85 * restart_cash, 4)
    all_dates = sorted(set().union(*[set(df[(df["date"] >= w0) & (df["date"] <= w1)]["date"])
                                     for df in dfs.values()]))
    out["curve"] = stitch(ep1, ep2, restart_cash, all_dates)
    out["final"], out["cagr"], out["max_dd"] = curve_stats(out["curve"], START_CASH)
    out["costs"] = ep1["costs"] + ep2["costs"]
    out["trades"] = ep1["trades"] + ep2["trades"]
    # sleeve curves stitched the same way (each sleeve restarts with half)
    sc = {}
    for sym in dfs:
        c1 = ep1["sleeve_equity"][sym]
        c2 = ep2["sleeve_equity"][sym]
        cal = list(dfs[sym][(dfs[sym]["date"] >= w0) & (dfs[sym]["date"] <= w1)]["date"])
        sc[sym] = stitch({"equity": c1}, {"equity": c2}, restart_cash / 2.0, cal)
    out["sleeve_curves"] = sc
    if ep2["halted"]:
        out["halts"] = 2
        out["second_halt"] = True
        out["second_halt_date"] = ep2["halt_date"]
        out["halt_dates"].append(ep2["halt_date"])
    return out

# ------------------------------------------------------------------- SPY ----
def spy_decade():
    """Dividend-adjusted SPY buy-and-hold, decade road, program convention."""
    path = os.path.join(HERE, "..", "..", "v7", "long-hold", "data", "pxfull_SPY.json")
    p = json.load(open(path))
    res = p["chart"]["result"][0]
    ts, q = res["timestamp"], res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        c = q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        bars.append((d, q["open"][i] * (a / c) if q["open"][i] else a, a))
    bars.sort()
    w = [b for b in bars if DEC0 <= b[0] <= DEC1]
    units = (100.0 * 0.999) / w[0][1]          # 0.10% buy cost
    final = units * w[-1][2] * 0.999           # 0.10% sell cost
    return round(final, 2)

# --------------------------------------------------------------- integrity ----
def integrity(btc, eth):
    dfs = {"BTC": btc, "ETH": eth}
    pub_v9 = {  # v9-muse-rules/crypto-trend/v9-results.json (the published finals)
        "FULL": {"BTC": 13058.82, "ETH": 731.61, "COMBO": 953.90},
        "VAL": {"BTC": 189.75, "ETH": 132.33, "COMBO": 161.04},
    }
    pub_orig_nofloor = {  # v4 crypto-trend-results.json, trend_none
        "FULL": {"BTC": 17342.56, "ETH": 1046.61, "COMBO": 953.90},
        "VAL": {"BTC": 189.75, "ETH": 132.33, "COMBO": 161.04},
    }
    windows = {"FULL": (None, END_DATE), "VAL": (VAL_START, END_DATE)}
    rep_v9, rep_orig = {}, {}
    for wname, (w0, w1) in windows.items():
        rep_v9[wname], rep_orig[wname] = {}, {}
        for sym, df in dfs.items():
            start = w0 if w0 else str(df["date"].iloc[0].date())
            r = run_v9_asset(df, start, w1, "is_eval")
            rep_v9[wname][sym] = round(r["final"], 2)
            rep_orig[wname][sym] = round(run_asset(df, start, w1, "none")["final"], 2)
        cstart = w0 if w0 else str(eth["date"].iloc[0].date())
        rc = run_v9_combo(dfs, cstart, w1, "is_eval")
        rep_v9[wname]["COMBO"] = round(rc["final"], 2)
        rep_orig[wname]["COMBO"] = round(run_combo(dfs, cstart, w1, "none")["final"], 2)
    ok = all(abs(rep_v9[w][s] - pub_v9[w][s]) < 0.02 for w in pub_v9 for s in pub_v9[w])
    ok = ok and all(abs(rep_orig[w][s] - pub_orig_nofloor[w][s]) < 0.02
                    for w in pub_orig_nofloor for s in pub_orig_nofloor[w])
    return {"status": "reproduced" if ok else "FAILED",
            "original_finals": {"v9_two_episode": pub_v9, "original_no_floor": pub_orig_nofloor},
            "reproduced_finals": {"v9_two_episode": rep_v9, "original_no_floor": rep_orig}}

# ------------------------------------------------------------------- main ----
def ser_curve(curve):
    return [[str(dt.date()), round(float(v), 2)] for dt, v in curve]

def leg_block(r):
    return {"final": round(r["final"], 2), "cagr_pct": round(r["cagr"], 2),
            "max_dd_pct": round(r["max_dd"], 2), "costs": round(r["costs"], 2),
            "orders": r["trades"], "halts": r["halts"],
            "halt_dates": r["halt_dates"], "restart": r["restart"],
            "restart_date": r["restart_date"], "second_halt": r["second_halt"],
            "second_halt_date": r["second_halt_date"]}

def main():
    btc = add_cadence_evals(prep(load("BTC-USD")))
    eth = add_cadence_evals(prep(load("ETH-USD")))
    dfs = {"BTC": btc, "ETH": eth}

    integ = integrity(btc, eth)
    print("INTEGRITY:", integ["status"])
    print(json.dumps(integ["reproduced_finals"], indent=1))

    spy = spy_decade()
    print("SPY decade (computed):", spy)
    bh = {"BTC": buy_hold(btc, DEC0, DEC1), "ETH": buy_hold(eth, DEC0, DEC1),
          "COMBO": buy_hold_combo(dfs, DEC0, DEC1)}
    print("BTC hold decade:", round(bh["BTC"]["final"], 2),
          "| ETH hold:", round(bh["ETH"]["final"], 2),
          "| combo hold:", round(bh["COMBO"]["final"], 2))

    cells, cell_jsons = {}, {}
    for cad in CADENCES:
        ecol = f"ev_{cad}"
        legs = {"BTC": run_v9_asset(btc, DEC0, DEC1, ecol),
                "ETH": run_v9_asset(eth, DEC0, DEC1, ecol)}
        combo = run_v9_combo(dfs, DEC0, DEC1, ecol)
        # placebos: original design — random timing, matched exposure, no floor
        placebo = {}
        combo_finals = None
        for sym, df in dfs.items():
            base = run_asset(df, DEC0, DEC1, "none", eval_col=ecol)
            p = base["exposure_evals"]
            finals = [run_asset(df, DEC0, DEC1, "none", seed=s, placebo_p=p,
                                eval_col=ecol)["final"] for s in range(42, 62)]
            placebo[sym] = {"exposure": round(p, 4), "finals": [round(f, 2) for f in finals],
                            "trend_no_floor_final": round(base["final"], 2),
                            "beaten_vs_cell_v9_leg": sum(1 for f in finals if legs[sym]["final"] > f),
                            "beaten_vs_no_floor_trend": sum(1 for f in finals if base["final"] > f)}
            cf = finals if combo_finals is None else [a + b for a, b in zip(combo_finals, finals)]
            combo_finals = cf
        combo_placebo = [round(f / 2.0, 2) for f in combo_finals]
        beaten_combo = sum(1 for f in combo_placebo if combo["final"] > f)
        cells[cad] = {
            "final": round(combo["final"], 2), "cagr_pct": round(combo["cagr"], 2),
            "max_dd_pct": round(combo["max_dd"], 2), "halts": combo["halts"],
            "restart": combo["restart"], "second_halt": combo["second_halt"],
            "costs": round(combo["costs"], 2), "orders": combo["trades"],
            "placebo_beaten": beaten_combo,
            "placebo_note": ("Original chassis placebo: random in/out timing at this "
                             "cadence with the trend rule's matched exposure, 20 seeds "
                             "42-61, no floor; combo = mean of the two legs' $100-pot "
                             "finals (the original's approximation). Beaten counted "
                             "against the cell's v9 combo final."),
            "legs": {s: leg_block(legs[s]) for s in legs},
            "btc_hold_final": round(bh["BTC"]["final"], 2),
            "eth_hold_final": round(bh["ETH"]["final"], 2),
            "combo_hold_final": round(bh["COMBO"]["final"], 2),
            "spy_final": spy,
            "beats_btc_hold": bool(combo["final"] > bh["COMBO"]["final"]),
            "beats_spy": bool(combo["final"] > spy),
        }
        cj = {"slug": "crypto-trend", "cadence": cad, "road": [DEC0, DEC1],
              "start_cash": START_CASH, "cost_per_side": COST,
              "combo": {**leg_block(combo), "equity_curve": ser_curve(combo["curve"])},
              "legs": {s: {**leg_block(legs[s]), "equity_curve": ser_curve(legs[s]["curve"])}
                       for s in legs},
              "sleeve_curves_from_combo": {s: ser_curve(combo["sleeve_curves"][s]) for s in dfs},
              "benchmarks": {
                  "btc_buy_hold": {"final": round(bh["BTC"]["final"], 2),
                                   "cagr_pct": round(bh["BTC"]["cagr"], 2),
                                   "max_dd_pct": round(bh["BTC"]["max_dd"], 2),
                                   "equity_curve": ser_curve(bh["BTC"]["equity"])},
                  "eth_buy_hold": {"final": round(bh["ETH"]["final"], 2),
                                   "cagr_pct": round(bh["ETH"]["cagr"], 2),
                                   "max_dd_pct": round(bh["ETH"]["max_dd"], 2),
                                   "equity_curve": ser_curve(bh["ETH"]["equity"])},
                  "combo_buy_hold": {"final": round(bh["COMBO"]["final"], 2),
                                     "cagr_pct": round(bh["COMBO"]["cagr"], 2),
                                     "max_dd_pct": round(bh["COMBO"]["max_dd"], 2),
                                     "equity_curve": ser_curve(bh["COMBO"]["equity"])},
                  "spy_buy_hold_div_adj_final": spy, "spy_spec_reference": 367.80},
              "placebos": {**placebo,
                           "COMBO": {"finals": combo_finals and combo_placebo,
                                     "beaten_vs_cell_v9_combo": beaten_combo}}}
        with open(os.path.join(CELLS, f"{cad}.json"), "w") as f:
            json.dump(cj, f, indent=1)
        cell_jsons[cad] = cj
        print(f"{cad:11s} BTC ${legs['BTC']['final']:9.2f}  ETH ${legs['ETH']['final']:9.2f}  "
              f"COMBO ${combo['final']:9.2f}  halts={combo['halts']} "
              f"placebo {beaten_combo}/20")

    money = [c for c in CADENCES
             if cells[c]["final"] > spy and cells[c]["placebo_beaten"] >= 11]
    beats_hold = [c for c in CADENCES if cells[c]["final"] > cells[c]["combo_hold_final"]]
    results = {
        "slug": "crypto-trend",
        "area": ("Crypto era on its own universe (BTC/ETH): the decade road "
                 "2016-11-21 -> 2026-11-20, scored against BTC buy-and-hold on the "
                 "same road AND against SPY — the original chapter's verdict was "
                 "that holding beat the rules on the judging years."),
        "area_source": "SPEC W10 assignment + v4/crypto-trend.md (the program's crypto chapter)",
        "native_cadence": "weekly",
        "cadence_source": ("v4/crypto-trend.md: 'Decisions are made weekly (last day of "
                           "each week) and executed at the next daily bar's open'; SPEC "
                           "CADENCE GRID W10 also lists crypto-trend as weekly. The "
                           "200-day signal itself is computed on daily bars — the "
                           "decision cadence is weekly."),
        "original_cadence_foreign": False,
        "original_cadence_note": ("Original test ran at the native weekly cadence — not "
                                  "foreign. Sweep treatment per SPEC: signals computed on "
                                  "daily bars; cadence governs evaluation/entry/exit dates; "
                                  "sweep eval dates are the FIRST bar of each period (SPEC "
                                  "uniform definition), where the original weekly engine "
                                  "used the LAST bar of each ISO week — the only form "
                                  "difference in the sweep's weekly cell."),
        "integrity": integ,
        "decade_spy_final": 367.80,
        "decade_spy_computed": spy,
        "decade_btc_hold_final": round(bh["BTC"]["final"], 2),
        "decade_eth_hold_final": round(bh["ETH"]["final"], 2),
        "decade_combo_hold_final": round(bh["COMBO"]["final"], 2),
        "champion_decade_final": 65.89,
        "champion_decade_caveat": ("Champion (value+momentum) DECADE final $65.89 after two "
                                   "halts — its crown rests on the 2010 and 2019 roads; the "
                                   "decade caveat applies wherever the decade matrix is "
                                   "summarized. Crypto-trend is not scored against the "
                                   "champion (different universe); it is printed here per "
                                   "the SPEC headline requirement."),
        "cells": cells,
        "money_cadences": money,
        "cadences_beating_combo_buy_hold": beats_hold,
        "verdict_area": None,  # filled below
        "verdict_change": None,
    }
    # verdict logic (mechanical, from the cells): a money cadence must beat
    # BOTH benchmarks and its placebo per the SPEC guardrail.
    true_money = [c for c in money if cells[c]["final"] > cells[c]["combo_hold_final"]]
    if true_money:
        results["verdict_area"] = "OWNS ITS GROUND — PROVISIONAL (unconfirmed flip)"
        results["verdict_change"] = (
            "FLIP vs the original program verdict (trend lost to holding on the judging "
            "years): cadence(s) " + ", ".join(true_money) + " beat SPY, BTC/combo "
            "buy-and-hold and their placebos on the decade road. Per the CONFIRMATION "
            "RULE this is PROVISIONAL — decade-only, unconfirmed until re-run on the "
            "other roads (LONG/CONT/VAL + yearly folds).")
    elif money or beats_hold:
        results["verdict_area"] = "REAL BUT SMALL"
        results["verdict_change"] = (
            "No flip. Some cadence(s) beat one benchmark or their placebo but no cadence "
            "beat SPY, buy-and-hold and placebos together; the original verdict "
            "(holding beat the rules; trend is drawdown insurance) stands, narrowed to "
            "the cadences named in RESULTS.md.")
    else:
        results["verdict_area"] = "NO GROUND"
        results["verdict_change"] = (
            "No flip. On its own universe and era, at every tempo, the trend rule again "
            "failed to beat simply holding (and/or SPY and its own placebos) — the "
            "original program verdict stands at every cadence.")
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("money cadences (SPY+placebo):", money, "| true money (also beats hold):", true_money)
    print("verdict:", results["verdict_area"])

if __name__ == "__main__":
    main()
