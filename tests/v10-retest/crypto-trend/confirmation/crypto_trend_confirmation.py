#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — crypto-trend CONFIRMATION RUN. SIMULATION ONLY.

Cross-year confirmation of the sweep's flipped verdict (daily + weekly
combo crowns on the DECADE road), per the CONFIRMATION RULE in
../SPEC.md. Step 1 reproduces the sweep's decade daily ($4,532.28) and
weekly ($4,500.00) combo cells exactly; only if that gate passes does
the script run the other roads (LONG / CONT / VAL) and fresh yearly
folds (2018-2025).

The engine functions below (load/prep/add_cadence_evals/run_asset/
run_combo/buy_hold/buy_hold_combo/stitch/curve_stats/run_v9_asset/
run_v9_combo) are copied VERBATIM from ../crypto_trend_v10.py — the
exact code that produced the sweep — with the single mechanical change
that DATA points at ../data (this script lives one folder deeper).
Rules unchanged: $100 start, 0.25%/side engine costs, 200-day signal on
daily bars, cadence governs evaluation/entry/exit dates only (first bar
of each period), v9 protections (plain -15% floor from episode start,
checked on daily closes, 90-day sit-out, restart at next cadence date
under an episode-2 -15% floor, second halt ends the run). Placebos are
the original chassis design: random in/out timing at the cadence with
matched exposure, 20 seeds 42-61, no floor, per leg; combo placebo =
mean of the two legs' $100-pot finals.

Data: ../data/BTC-USD.csv + ETH-USD.csv (the sweep folder's own copies)
and the read-only v7 SPY cache (backtests/v7/long-hold/data/
pxfull_SPY.json) for the dividend-adjusted SPY benchmark. The 1.7GB
long-run cache is NOT loaded.
"""
import json, math, os, random, time
from datetime import timedelta
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
START_CASH = 100.0
COST = 0.0025            # 0.25% per side — the original crypto engine's cost
END_DATE = "2026-11-20"

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


# ------------------------------------------------- confirmation driver ----
# Roads (SPEC canonical windows; LONG = longest honest road the data in
# ../data supports: BTC bars begin 2014-09-17, ETH bars begin 2017-11-09.
# A 2010 start is impossible and nothing is backfilled. On LONG (and on
# DECADE, which also starts before ETH existed) the ETH sleeve sits in
# cash until its first real bar, exactly as the sweep's engine does.)
ROADS = {
    "DECADE": ("2016-11-21", "2026-11-20"),   # integrity reproduction road
    "LONG":   ("2014-09-17", "2026-11-20"),   # BTC first bar -> road end
    "CONT":   ("2019-01-02", "2026-11-20"),
    "VAL":    ("2023-01-03", "2026-11-20"),
}
CONF_CADENCES = ["daily", "weekly"]
EXPECTED_DECADE = {"daily": 4532.28, "weekly": 4500.00}
FOLD_YEARS = list(range(2018, 2026))  # full years where BOTH legs have data
                                      # for the whole year (ETH starts
                                      # 2017-11-09; 2026 ends 2026-11-20)

def load_spy_bars():
    path = os.path.join(HERE, "..", "..", "..", "v7", "long-hold", "data",
                        "pxfull_SPY.json")
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
    return bars

SPY_BARS = None

def spy_window(w0, w1):
    """Dividend-adjusted SPY buy-and-hold on [w0, w1], program convention:
    buy at first bar's open (adj-scaled) with 0.10% cost, value at last
    bar's adjclose with 0.10% sell cost. Same code as the sweep's
    spy_decade(), generalised to any window."""
    w = [b for b in SPY_BARS if w0 <= b[0] <= w1]
    units = (100.0 * 0.999) / w[0][1]
    final = units * w[-1][2] * 0.999
    curve = [[b[0], round(units * b[2], 2)] for b in w]
    eq = pd.Series([v for _, v in curve])
    max_dd = ((eq / eq.cummax()) - 1).min() * 100
    years = max((pd.Timestamp(w[-1][0]) - pd.Timestamp(w[0][0])).days / 365.25, 1e-9)
    cagr = ((final / 100.0) ** (1 / years) - 1) * 100
    return {"final": round(final, 2), "cagr_pct": round(cagr, 2),
            "max_dd_pct": round(float(max_dd), 2), "equity_curve": curve}

def ser_curve(curve):
    return [[str(dt.date()), round(float(v), 2)] for dt, v in curve]

def leg_block(r):
    return {"final": round(r["final"], 2), "cagr_pct": round(r["cagr"], 2),
            "max_dd_pct": round(r["max_dd"], 2), "costs": round(r["costs"], 2),
            "orders": r["trades"], "halts": r["halts"],
            "halt_dates": r["halt_dates"], "restart": r["restart"],
            "restart_date": r["restart_date"], "second_halt": r["second_halt"],
            "second_halt_date": r["second_halt_date"]}

def run_cadence(dfs, w0, w1, cad):
    ecol = f"ev_{cad}"
    legs = {sym: run_v9_asset(dfs[sym], w0, w1, ecol) for sym in dfs}
    combo = run_v9_combo(dfs, w0, w1, ecol)
    placebo = {}
    combo_finals = None
    for sym, df in dfs.items():
        base = run_asset(df, w0, w1, "none", eval_col=ecol)
        p = base["exposure_evals"]
        finals = [run_asset(df, w0, w1, "none", seed=s, placebo_p=p,
                            eval_col=ecol)["final"] for s in range(42, 62)]
        placebo[sym] = {"exposure": round(p, 4),
                        "finals": [round(f, 2) for f in finals],
                        "trend_no_floor_final": round(base["final"], 2)}
        combo_finals = finals if combo_finals is None else \
            [a + b for a, b in zip(combo_finals, finals)]
    combo_placebo = [round(f / 2.0, 2) for f in combo_finals]
    beaten = sum(1 for f in combo_placebo if combo["final"] > f)
    placebo["COMBO"] = {"finals": combo_placebo, "beaten_vs_v9_combo": beaten}
    bh = {"BTC": buy_hold(dfs["BTC"], w0, w1), "ETH": buy_hold(dfs["ETH"], w0, w1),
          "COMBO": buy_hold_combo(dfs, w0, w1)}
    spy = spy_window(w0, w1)
    block = {
        "combo": {**leg_block(combo), "equity_curve": ser_curve(combo["curve"])},
        "legs": {s: {**leg_block(legs[s]), "equity_curve": ser_curve(legs[s]["curve"])}
                 for s in legs},
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
            "spy_buy_hold_div_adj": spy},
        "placebos": placebo,
        "placebo_beaten": beaten,
        "beats_combo_hold": bool(combo["final"] > bh["COMBO"]["final"]),
        "beats_btc_hold": bool(combo["final"] > bh["BTC"]["final"]),
        "beats_spy": bool(combo["final"] > spy["final"]),
    }
    return block

def main():
    global SPY_BARS
    SPY_BARS = load_spy_bars()
    btc = add_cadence_evals(prep(load("BTC-USD")))
    eth = add_cadence_evals(prep(load("ETH-USD")))
    dfs = {"BTC": btc, "ETH": eth}
    print("BTC bars:", btc["date"].iloc[0].date(), "->", btc["date"].iloc[-1].date(),
          "| ETH bars:", eth["date"].iloc[0].date(), "->", eth["date"].iloc[-1].date())

    summary = {"slug": "crypto-trend", "confirmation_of": "v10 sweep daily+weekly crowns",
               "data": {"btc_first_bar": str(btc["date"].iloc[0].date()),
                        "eth_first_bar": str(eth["date"].iloc[0].date()),
                        "note": ("LONG starts 2014-09-17 (BTC first bar); a 2010 "
                                 "start is impossible on this data and nothing is "
                                 "backfilled. ETH sleeve is cash until 2017-11-09 "
                                 "on roads that start earlier.")},
               "roads": {}}

    # ---- STEP 1: integrity gate — reproduce the sweep's decade cells ----
    dec = {}
    for cad in CONF_CADENCES:
        dec[cad] = run_cadence(dfs, *ROADS["DECADE"], cad)
        got = dec[cad]["combo"]["final"]
        print(f"DECADE {cad}: reproduced ${got:.2f} (sweep ${EXPECTED_DECADE[cad]:.2f})")
    ok = all(abs(dec[c]["combo"]["final"] - EXPECTED_DECADE[c]) < 0.005
             for c in CONF_CADENCES)
    summary["integrity_gate"] = {
        "status": "reproduced" if ok else "FAILED",
        "expected_decade_combo": EXPECTED_DECADE,
        "reproduced_decade_combo": {c: dec[c]["combo"]["final"] for c in CONF_CADENCES}}
    with open(os.path.join(HERE, "road_DECADE.json"), "w") as f:
        json.dump({"road": "DECADE", "window": list(ROADS["DECADE"]),
                   "integrity_gate": summary["integrity_gate"],
                   "cadences": dec}, f, indent=1)
    if not ok:
        with open(os.path.join(HERE, "summary.json"), "w") as f:
            json.dump(summary, f, indent=1)
        print("INTEGRITY GATE FAILED — stopping, per task instructions.")
        return
    print("INTEGRITY GATE: reproduced — proceeding to the other roads.")

    # ---- STEP 2: the other roads ----
    for road in ["LONG", "CONT", "VAL"]:
        w0, w1 = ROADS[road]
        blocks = {}
        for cad in CONF_CADENCES:
            blocks[cad] = run_cadence(dfs, w0, w1, cad)
            c = blocks[cad]["combo"]; b = blocks[cad]["benchmarks"]
            print(f"{road} {cad}: combo ${c['final']:.2f} | BTC hold "
                  f"${b['btc_buy_hold']['final']:.2f} | combo hold "
                  f"${b['combo_buy_hold']['final']:.2f} | SPY "
                  f"${b['spy_buy_hold_div_adj']['final']:.2f} | placebo "
                  f"{blocks[cad]['placebo_beaten']}/20 | halts {c['halts']}")
        summary["roads"][road] = {
            cad: {"final": blocks[cad]["combo"]["final"],
                  "placebo_beaten": blocks[cad]["placebo_beaten"],
                  "beats_combo_hold": blocks[cad]["beats_combo_hold"],
                  "beats_btc_hold": blocks[cad]["beats_btc_hold"],
                  "beats_spy": blocks[cad]["beats_spy"]} for cad in CONF_CADENCES}
        with open(os.path.join(HERE, f"road_{road}.json"), "w") as f:
            json.dump({"road": road, "window": [w0, w1], "cadences": blocks}, f, indent=1)

    # ---- STEP 3: fresh yearly folds ----
    folds = {}
    for y in FOLD_YEARS:
        w0, w1 = f"{y}-01-01", f"{y}-12-31"
        folds[str(y)] = {}
        for cad in CONF_CADENCES:
            blk = run_cadence(dfs, w0, w1, cad)
            folds[str(y)][cad] = blk
            c = blk["combo"]; b = blk["benchmarks"]
            print(f"FOLD {y} {cad}: combo ${c['final']:.2f} | combo hold "
                  f"${b['combo_buy_hold']['final']:.2f} | SPY "
                  f"${b['spy_buy_hold_div_adj']['final']:.2f} | placebo "
                  f"{blk['placebo_beaten']}/20 | halts {c['halts']}")
    with open(os.path.join(HERE, "folds.json"), "w") as f:
        json.dump({"fold_years": FOLD_YEARS,
                   "note": ("Fresh $100 each Jan 1, v9 protections per fold. "
                            "2018-2025 are the full calendar years where BOTH "
                            "BTC and ETH bars cover the whole year (ETH begins "
                            "2017-11-09). 2014 and 2026 are partial years and "
                            "2015-2017 lack full-year ETH data, so no combo "
                            "fold is claimed for them. SMA200 is computed on "
                            "full daily history up to each bar (point-in-time)."),
                   "folds": folds}, f, indent=1)
    summary["folds"] = {y: {cad: {"final": folds[y][cad]["combo"]["final"],
                                  "combo_hold": folds[y][cad]["benchmarks"]["combo_buy_hold"]["final"],
                                  "spy": folds[y][cad]["benchmarks"]["spy_buy_hold_div_adj"]["final"],
                                  "placebo_beaten": folds[y][cad]["placebo_beaten"],
                                  "beats_combo_hold": folds[y][cad]["beats_combo_hold"]}
                            for cad in CONF_CADENCES} for y in folds}
    with open(os.path.join(HERE, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    print("DONE.")

if __name__ == "__main__":
    main()
