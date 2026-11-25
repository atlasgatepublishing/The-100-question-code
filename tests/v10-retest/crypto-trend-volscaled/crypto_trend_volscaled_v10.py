#!/usr/bin/env python3
"""
CRYPTO TREND, VOL-SCALED — v10 GREAT RETEST (cadence sweep). Simulation only.

Strategy (original, v4/crypto-trend-volscaled.py): per asset (BTC, ETH),
invested only when the close is above its 10-month moving average (mean of
the last 10 month-end closes); position size volatility-scaled: target
weight = min(1, 10% / realized vol), realized vol = trailing 60 daily log
returns annualized (x sqrt(365)). Pots: BTC-only, ETH-only, 50/50 COMBO.
Costs 0.40%/side (the engine's own cost code — kept identical). $100/pot.

KNOWN DIVERGENCE (documented, never silently fixed): the original primary
runs carried NO -15% floor. The v10 sweep applies the adopted v9
protections (plain -15% floor, 90-day cash sit, restart at the next
regular cadence decision point under an episode-2 -15% floor, second
halt ends the run). The integrity section below reproduces the original
published finals in the ORIGINAL no-floor form.

CADENCE RULE (stated once, uniform): cadence is the frequency at which
BOTH the trend signal AND the vol-scaling are re-evaluated and the pot is
rebalanced. The signal definitions themselves stay exactly as published,
in time units: trend = close vs the mean of the last 10 completed
month-end closes; vol = trailing 60 daily log returns. Evaluation happens
at the close of the last bar of each cadence period (daily = every bar;
weekly = last bar of each ISO week; biweekly = last bar of every second
ISO week, anchored on the first week in the asset's series; monthly =
month-end bar — the original form; quarterly / semi-annual / annual =
last bar of each calendar quarter / half-year / year). Trades execute at
the next bar's open, exactly as the original. Holdings drift between
evaluations; nothing is re-evaluated between cadence dates.

ROAD: DECADE 2016-11-21 -> 2026-11-20. BTC covers it fully. ETH data
starts 2017-11-09, so the ETH and COMBO legs run the longest honest
sub-window 2017-11-09 -> 2026-11-20 (documented in every cell).

PLACEBOS: the original's own design, per cadence, on the COMBO pot:
random in/out timing on the same execution dates, 20 seeds, same costs,
same v9 machinery; per-asset in-probability calibrated so the placebo's
expected exposure equals the strategy's average invested weight for that
asset at that cadence (from the single-asset legs); the placebo holds at
full sleeve weight when "in". All 20 finals saved per cell.

Data: copies of the original v4 cache in ./data/ (BTC-USD from
2014-09-17, ETH-USD from 2017-11-09; Yahoo daily bars, cut 2026-11-20).
"""
import bisect, json, math, os, random
from datetime import timedelta
import numpy as np
import pandas as pd

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(OUT_DIR, "data")

START_CASH = 100.0
COST = 0.0040
END_DATE = "2026-11-20"
VAL_START = "2023-01-01"
DESIGN_END = "2022-12-31"
VOL_TARGET = 0.10
VOL_WIN = 60
DEC_START = "2016-11-21"
SPY_DECADE = 367.80
CHAMPION_DECADE = 65.89

# ---------------------------------------------------------------- data ----
def load(symbol):
    df = pd.read_csv(os.path.join(CACHE, f"{symbol}.csv"), parse_dates=["date"])
    df = df[df["date"] <= END_DATE].sort_values("date").reset_index(drop=True)
    df["logret"] = np.log(df["close"] / df["close"].shift(1))
    return df

BTC = load("BTC-USD")
ETH = load("ETH-USD")
DATA = {"BTC": BTC, "ETH": ETH}

# ============================ ORIGINAL ENGINE (verbatim from v4) ==========
def build_schedule_orig(df):
    d = df.reset_index(drop=True)
    d["ym"] = d["date"].dt.year * 100 + d["date"].dt.month
    me_idx = d.groupby("ym").tail(1).index.tolist()
    me_closes = d.loc[me_idx, "close"].tolist()
    sched = {}
    for k, idx in enumerate(me_idx):
        if k < 9:
            continue
        ma10 = float(np.mean(me_closes[k - 9:k + 1]))
        close = float(d.loc[idx, "close"])
        rets = d.loc[:idx, "logret"].tail(VOL_WIN)
        if len(rets) < VOL_WIN:
            continue
        vol = float(rets.std(ddof=1) * math.sqrt(365))
        w = min(1.0, VOL_TARGET / vol) if (close > ma10 and vol > 0) else 0.0
        if idx + 1 < len(d):
            sched[d.loc[idx + 1, "date"]] = w
    return sched

SCHED_ORIG = {a: build_schedule_orig(df) for a, df in DATA.items()}
PLACEBO_P = {}

def run_pot_orig(assets, w0, w1, sched_map, mode="strategy", floor=False,
                 seed=None, start_cash=None, floor_abs=None):
    """Original v4 engine (v9 parameterisation: start_cash/floor_abs)."""
    frames = {}
    for name, _ in assets:
        df = DATA[name]
        frames[name] = df[(df["date"] >= w0) & (df["date"] <= w1)].reset_index(drop=True)
    cal = pd.DatetimeIndex(frames[assets[0][0]]["date"])
    for name, _ in assets[1:]:
        cal = cal.union(pd.DatetimeIndex(frames[name]["date"]))
    cal = pd.DatetimeIndex(sorted(cal))
    opens = {n: frames[n].set_index("date")["open"] for n, _ in assets}
    closes = {n: frames[n].set_index("date")["close"] for n, _ in assets}
    cash = START_CASH if start_cash is None else float(start_cash)
    cash0 = cash
    units = {n: 0.0 for n, _ in assets}
    trades = 0
    total_costs = 0.0
    halted = None
    rng = random.Random(seed) if seed is not None else None
    eq_rows = []
    bought = False
    for dt in cal:
        do_trade = False
        targets = {}
        if not halted:
            if mode == "strategy":
                for name, alloc in assets:
                    if dt in sched_map[name]:
                        targets[name] = alloc * sched_map[name][dt]
                        do_trade = True
            elif mode == "placebo":
                for name, alloc in assets:
                    if dt in sched_map[name]:
                        p = PLACEBO_P.get(name, 0.0)
                        targets[name] = alloc if rng.random() < p else 0.0
                        do_trade = True
            elif mode == "buyhold" and not bought:
                for name, alloc in assets:
                    targets[name] = alloc
                do_trade = True
                bought = True
        if do_trade:
            equity_open = cash + sum(units[n] * opens[n].get(dt, closes[n].get(dt)) for n, _ in assets)
            for name, alloc in assets:
                if name not in targets:
                    continue
                px = opens[name].get(dt)
                if px is None or px <= 0:
                    continue
                tgt_units = targets[name] * equity_open / px
                delta = tgt_units - units[name]
                if abs(delta * px) > 1e-9:
                    c = abs(delta * px) * COST
                    cash -= delta * px + c
                    total_costs += c
                    units[name] = tgt_units
                    trades += 1
        eq = cash + sum(units[n] * closes[n].get(dt, 0.0) for n, _ in assets)
        invested = sum(units[n] * closes[n].get(dt, 0.0) for n, _ in assets)
        eq_rows.append((dt, eq, invested))
        if floor and not halted and eq <= (85.0 if floor_abs is None else floor_abs):
            halted = dt
            nxt = cal[cal > dt]
            if len(nxt) > 0:
                ndt = nxt[0]
                for name, _ in assets:
                    px = opens[name].get(ndt)
                    if units[name] > 0 and px:
                        c = units[name] * px * COST
                        cash += units[name] * px - c
                        total_costs += c
                        units[name] = 0.0
                        trades += 1
            eq_rows = [r for r in eq_rows if r[0] <= dt]
            for dt2 in cal[cal > dt]:
                eq_rows.append((dt2, cash, 0.0))
            break
    eqs = pd.Series({d: e for d, e, _ in eq_rows})
    inv = pd.Series({d: i for d, _, i in eq_rows})
    peak = eqs.cummax()
    max_dd = float(((eqs - peak) / peak).min() * 100) if len(eqs) else 0.0
    days = (eqs.index[-1] - eqs.index[0]).days if len(eqs) > 1 else 0
    final = float(eqs.iloc[-1])
    cagr = ((final / cash0) ** (365.25 / days) - 1) * 100 if days > 0 and final > 0 else 0.0
    return {
        "final": round(final, 2),
        "cagr_pct": round(cagr, 1),
        "max_dd_pct": round(max_dd, 1),
        "trades": trades,
        "costs": round(total_costs, 2),
        "avg_exposure_pct": round(float((inv / eqs).mean() * 100), 1) if len(eqs) else 0.0,
        "halted": str(halted.date()) if halted is not None else None,
        "start": str(eqs.index[0].date()), "end": str(eqs.index[-1].date()),
        "_eqs": eqs,
    }

# ============================ CADENCE SCHEDULES ===========================
def eval_indices(df, cadence):
    d = df.reset_index(drop=True)
    n = len(d)
    if cadence == "daily":
        return list(range(n))
    if cadence == "monthly":
        d["ym"] = d["date"].dt.year * 100 + d["date"].dt.month
        return d.groupby("ym").tail(1).index.tolist()
    if cadence in ("weekly", "biweekly"):
        iso = d["date"].dt.isocalendar()
        keys = list(zip(iso["year"].astype(int), iso["week"].astype(int)))
        last = {}
        order = []
        for i, k in enumerate(keys):
            if k not in last:
                order.append(k)
            last[k] = i
        if cadence == "weekly":
            return [last[k] for k in order]
        return [last[k] for j, k in enumerate(order) if j % 2 == 0]
    if cadence == "quarterly":
        key = d["date"].dt.year * 10 + ((d["date"].dt.month - 1) // 3)
    elif cadence == "semiannual":
        key = d["date"].dt.year * 10 + ((d["date"].dt.month - 1) // 6)
    elif cadence == "annual":
        key = d["date"].dt.year
    else:
        raise ValueError(cadence)
    return d.groupby(key.values).tail(1).index.tolist()

def build_schedule_cad(df, cadence):
    d = df.reset_index(drop=True)
    d["ym"] = d["date"].dt.year * 100 + d["date"].dt.month
    me = d.groupby("ym").tail(1)
    me_idx = sorted(me.index.tolist())
    me_closes = [float(d.loc[i, "close"]) for i in me_idx]
    logret = d["logret"].values
    closes = d["close"].values
    dates = d["date"]
    sched = {}
    for idx in eval_indices(df, cadence):
        j = bisect.bisect_right(me_idx, idx)
        if j < 10:
            continue
        ma10 = float(np.mean(me_closes[j - 10:j]))
        rets = pd.Series(logret[:idx + 1]).tail(VOL_WIN)
        if len(rets) < VOL_WIN:
            continue
        vol = float(rets.std(ddof=1) * math.sqrt(365))
        w = min(1.0, VOL_TARGET / vol) if (closes[idx] > ma10 and vol > 0) else 0.0
        if idx + 1 < len(d):
            sched[dates.iloc[idx + 1]] = w
    return sched

CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
SCHED_CAD = {c: {a: build_schedule_cad(df, c) for a, df in DATA.items()}
             for c in CADENCES}

# ============================ V9 WRAPPER ==================================
def run_v9(assets, w0, w1, cadence, mode="strategy", seed=None):
    """One full v9 run: episode 1 with plain -15% floor; on halt, liquidate
    (engine), sit 90 calendar days, restart at the next cadence execution
    date on/after day 90 under an episode-2 floor; second halt ends it."""
    sched_map = SCHED_CAD[cadence]
    ep1 = run_pot_orig(assets, w0, w1, sched_map, mode=mode, floor=True,
                       seed=seed, start_cash=100.0, floor_abs=85.0)
    out = {"final": ep1["final"], "costs": ep1["costs"], "orders": ep1["trades"],
           "max_dd_pct": ep1["max_dd_pct"], "halts": 0, "halt_dates": [],
           "restart": False, "second_halt": False, "restart_info": None,
           "avg_exposure_pct": ep1["avg_exposure_pct"], "_eqs": ep1["_eqs"]}
    if ep1["halted"] is None:
        out["cagr_pct"] = ep1["cagr_pct"]
        return out
    out["halts"] = 1
    out["halt_dates"] = [ep1["halted"]]
    breach = pd.Timestamp(ep1["halted"])
    all_dates = DATA[assets[0][0]]["date"]
    fill = all_dates[all_dates > breach].iloc[0]
    restart_cash = ep1["final"]
    earliest = fill + timedelta(days=90)
    exec_dates = sorted({d for n, _ in assets for d in sched_map[n]
                         if d >= earliest and d <= pd.Timestamp(w1)})
    if not exec_dates:
        out["restart_info"] = {"status": "no_decision_point_in_window",
                               "fill_date": str(fill.date()),
                               "earliest": str(earliest.date()),
                               "restart_cash": restart_cash}
        out["cagr_pct"] = ep1["cagr_pct"]
        return out
    rdate = exec_dates[0]
    ep2 = run_pot_orig(assets, str(rdate.date()), w1, sched_map, mode=mode,
                       floor=True, seed=(seed + 10000) if seed is not None else None,
                       start_cash=restart_cash, floor_abs=0.85 * restart_cash)
    out["restart"] = True
    out["restart_info"] = {"status": "restarted", "fill_date": str(fill.date()),
                           "earliest": str(earliest.date()),
                           "restart_date": str(rdate.date()),
                           "restart_cash": restart_cash,
                           "ep2_floor": round(0.85 * restart_cash, 2),
                           "ep2_orders": ep2["trades"], "ep2_costs": ep2["costs"]}
    out["final"] = ep2["final"]
    out["costs"] = round(ep1["costs"] + ep2["costs"], 2)
    out["orders"] = ep1["trades"] + ep2["trades"]
    if ep2["halted"] is not None:
        out["halts"] = 2
        out["second_halt"] = True
        out["halt_dates"].append(ep2["halted"])
    # stitch curves: ep1 flat-cash tail replaced by ep2 from restart date
    eq1 = ep1["_eqs"]
    eq1 = eq1[eq1.index < rdate]
    eqs = pd.concat([eq1, ep2["_eqs"]]).sort_index()
    eqs = eqs[~eqs.index.duplicated(keep="last")]
    out["_eqs"] = eqs
    peak = eqs.cummax()
    out["max_dd_pct"] = round(float(((eqs - peak) / peak).min() * 100), 1)
    days = (eqs.index[-1] - eqs.index[0]).days
    out["cagr_pct"] = round(((eqs.iloc[-1] / 100.0) ** (365.25 / days) - 1) * 100, 1) if days > 0 else 0.0
    return out

def curve_list(eqs):
    return [[str(d.date()), round(float(v), 4)] for d, v in eqs.items()]

def strip(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}

POTS = {"BTC": [("BTC", 1.0)], "ETH": [("ETH", 1.0)],
        "COMBO": [("BTC", 0.5), ("ETH", 0.5)]}
DATA_START = {"BTC": str(BTC["date"].iloc[0].date()),
              "ETH": str(ETH["date"].iloc[0].date())}

# ============================ INTEGRITY ===================================
PUBLISHED = {
    ("FULL", "BTC"): 375.07, ("FULL", "ETH"): 118.95, ("FULL", "COMBO"): 152.54,
    ("DESIGN", "BTC"): 286.76, ("DESIGN", "ETH"): 130.17, ("DESIGN", "COMBO"): 139.11,
    ("VALIDATION", "BTC"): 130.80, ("VALIDATION", "ETH"): 91.38,
    ("VALIDATION", "COMBO"): 109.65,
}

def integrity():
    rep = {}
    ok = True
    for pot, assets in POTS.items():
        w_full = DATA_START["ETH"] if pot == "COMBO" else DATA_START[assets[0][0]]
        for label, (w0, w1) in {"FULL": (w_full, END_DATE),
                                "DESIGN": (w_full, DESIGN_END),
                                "VALIDATION": (VAL_START, END_DATE)}.items():
            r = run_pot_orig(assets, w0, w1, SCHED_ORIG, mode="strategy", floor=False)
            pub = PUBLISHED[(label, pot)]
            match = abs(r["final"] - pub) < 0.011
            ok = ok and match
            rep[f"{label}|{pot}"] = {"published": pub, "reproduced": r["final"],
                                     "match": match}
            print(f"integrity {label} {pot}: published ${pub} reproduced ${r['final']} match={match}")
    return ("reproduced" if ok else "FAILED"), rep

# ============================ SWEEP =======================================
def main():
    status, rep = integrity()
    # benchmarks on the roads actually run
    btc_hold_full = run_pot_orig([("BTC", 1.0)], DEC_START, END_DATE,
                                 SCHED_ORIG, mode="buyhold")
    btc_hold_ethroad = run_pot_orig([("BTC", 1.0)], DATA_START["ETH"], END_DATE,
                                    SCHED_ORIG, mode="buyhold")
    eth_hold = run_pot_orig([("ETH", 1.0)], DATA_START["ETH"], END_DATE,
                            SCHED_ORIG, mode="buyhold")
    print(f"BTC hold decade ${btc_hold_full['final']}; BTC hold ETH-road ${btc_hold_ethroad['final']}; ETH hold ${eth_hold['final']}")

    cells = {}
    for cad in CADENCES:
        legs = {}
        for pot, assets in POTS.items():
            w0 = DEC_START if pot == "BTC" else DATA_START["ETH"]
            r = run_v9(assets, w0, END_DATE, cad)
            legs[pot] = r
            print(f"{cad} {pot}: final ${r['final']} DD {r['max_dd_pct']} halts {r['halts']} orders {r['orders']} costs ${r['costs']}")
        # placebo calibration from single-asset legs at this cadence
        global PLACEBO_P
        PLACEBO_P = {"BTC": min(1.0, legs["BTC"]["avg_exposure_pct"] / 100.0),
                     "ETH": min(1.0, legs["ETH"]["avg_exposure_pct"] / 100.0)}
        placebo_finals = []
        for s in range(20):
            pr = run_v9(POTS["COMBO"], DATA_START["ETH"], END_DATE, cad,
                        mode="placebo", seed=1000 + s)
            placebo_finals.append(pr["final"])
        combo_final = legs["COMBO"]["final"]
        beaten = sum(1 for f in placebo_finals if f < combo_final)
        print(f"{cad} COMBO placebo: beaten {beaten}/20, finals {sorted(placebo_finals)}")
        head = legs["COMBO"]
        cell = {
            "final": head["final"], "cagr_pct": head["cagr_pct"],
            "max_dd_pct": head["max_dd_pct"], "halts": head["halts"],
            "halt_dates": head["halt_dates"], "restart": head["restart"],
            "second_halt": head["second_halt"],
            "restart_info": head["restart_info"],
            "costs": head["costs"], "orders": head["orders"],
            "placebo_beaten": beaten,
            "placebo_finals": sorted(round(f, 2) for f in placebo_finals),
            "placebo_note": ("Original placebo design on the COMBO pot: random in/out "
                             "on the same cadence execution dates, 20 seeds (1000-1019), "
                             "same costs and v9 machinery (fresh seed offset per episode); "
                             f"per-asset in-probability = strategy avg exposure at this cadence "
                             f"(BTC p={PLACEBO_P['BTC']:.3f}, ETH p={PLACEBO_P['ETH']:.3f}); "
                             "placebo holds at full sleeve weight when in."),
            "headline_pot": "COMBO (50/50 BTC/ETH) — the strategy's diversified pot; BTC and ETH legs saved in full below",
            "btc_hold_same_road": btc_hold_ethroad["final"],
            "eth_hold_same_road": eth_hold["final"],
            "btc_hold_full_decade": btc_hold_full["final"],
            "spy_decade_reference": SPY_DECADE,
            "champion_decade_reference": CHAMPION_DECADE,
            "road": {"start": DATA_START["ETH"], "end": END_DATE,
                     "note": "COMBO/ETH legs: longest honest sub-window of DECADE — ETH data starts 2017-11-09. BTC leg ran the full DECADE from 2016-11-21 (see legs). SPY $367.80 and BTC-full-decade are full-decade references on longer roads."},
            "equity_curve": curve_list(head["_eqs"]),
            "legs": {pot: {"final": r["final"], "cagr_pct": r["cagr_pct"],
                           "max_dd_pct": r["max_dd_pct"], "halts": r["halts"],
                           "halt_dates": r["halt_dates"], "restart": r["restart"],
                           "second_halt": r["second_halt"],
                           "restart_info": r["restart_info"],
                           "costs": r["costs"], "orders": r["orders"],
                           "avg_exposure_pct": r["avg_exposure_pct"],
                           "road_start": (DEC_START if pot == "BTC" else DATA_START["ETH"]),
                           "equity_curve": curve_list(r["_eqs"])}
                     for pot, r in legs.items()},
        }
        with open(os.path.join(OUT_DIR, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cad] = {k: cell[k] for k in ("final", "cagr_pct", "max_dd_pct",
                                           "halts", "restart", "second_halt",
                                           "costs", "orders", "placebo_beaten")}
        cells[cad]["placebo_note"] = cell["placebo_note"]
        cells[cad]["btc_leg_final"] = legs["BTC"]["final"]
        cells[cad]["eth_leg_final"] = legs["ETH"]["final"]
        cells[cad]["btc_hold_same_road"] = cell["btc_hold_same_road"]

    money = [c for c in CADENCES
             if cells[c]["final"] > SPY_DECADE and cells[c]["placebo_beaten"] > 10]
    money_btc = [c for c in CADENCES
                 if cells[c]["final"] > cells[c]["btc_hold_same_road"]
                 and cells[c]["placebo_beaten"] > 10]
    results = {
        "slug": "crypto-trend-volscaled",
        "area": "Crypto era — volatility-scaled trend on BTC/ETH (the strategy's own universe and era)",
        "area_source": "SPEC W10: crypto strategies on their universe and era, FULL + DECADE-equivalent + CONT + VAL, judged vs BTC buy-hold AND vs SPY. Sweep road = DECADE per the CADENCE SWEEP restructure.",
        "native_cadence": "monthly",
        "cadence": "monthly",
        "original_cadence_foreign": False,
        "native_change": "none in form — the original test was already monthly (native). The sweep varies cadence only, under the uniform rule stated in the script header: cadence governs BOTH trend evaluation and vol-scaling re-evaluation; signal definitions (10 completed month-end closes MA, trailing 60 daily log-return vol, 10% target) stay as published.",
        "integrity": {
            "status": status,
            "original_finals": {f"{k[0]}|{k[1]}": v for k, v in PUBLISHED.items()},
            "reproduced_finals": {k: v["reproduced"] for k, v in rep.items()},
            "note": ("Original form reproduced through the verbatim v4 engine: monthly "
                     "10-month MA + 10% vol target, 0.40%/side, NO FLOOR in the primary "
                     "runs (the known divergence). All nine published pot-window finals "
                     "checked. The batch-worker scratch figures (FULL $375.07/$118.95/"
                     "$152.54) are the FULL-window BTC/ETH/COMBO finals."),
        },
        "divergence": ("KNOWN DIVERGENCE: the original run carried NO -15% floor — its "
                       "primary runs were unfloored; the only floored original run was a "
                       "FULL-window diagnostic that never fired. The v10 sweep applies "
                       "the adopted v9 protections (floor ON). What the floor changes on "
                       "the sweep road is reported per cell (halts/restarts); on the "
                       "original windows the v9 re-check (v9 folder) found the floor "
                       "never fired and finals were identical to the cent."),
        "decade_spy_final": SPY_DECADE,
        "btc_hold_same_road": btc_hold_ethroad["final"],
        "btc_hold_full_decade": btc_hold_full["final"],
        "eth_hold_same_road": eth_hold["final"],
        "champion_decade_reference": CHAMPION_DECADE,
        "cells": cells,
        "money_cadences": money,
        "money_cadences_note": "SPEC sweep definition (headline COMBO pot): cadences beating SPY $367.80 AND their own placebo majority (>10/20).",
        "money_cadences_both_benchmarks": money_btc,
        "money_cadences_both_benchmarks_note": "Cadences whose COMBO final also beats BTC buy-and-hold on the same (ETH-start) road AND beat their placebos.",
        "provisional": False,
        "verdict_area": "PENDING — filled in RESULTS.md after reading the cells",
        "verdict_change": "PENDING",
    }
    with open(os.path.join(OUT_DIR, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print("money cadences (SPY+placebo):", money, "| also beat BTC hold:", money_btc)
    print("saved cells + results.json")

if __name__ == "__main__":
    main()
