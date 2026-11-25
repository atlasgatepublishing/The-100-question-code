#!/usr/bin/env python3
"""
CRYPTO TREND, VOLATILITY-SCALED MONTHLY VARIANT — BTC & ETH, for Terry's
AI stock app. SIMULATION ONLY — no orders, no broker.

The audit's #1 crypto spec (research/crypto-evidence.md, ranked list #1):
the direct port of the stock ETF trend sleeve's implementation style
(monthly evaluation), replacing the weekly 200-day binary rule of
crypto-trend.py.

RULE (frozen):
  Evaluate MONTHLY, on the last bar of each calendar month (UTC daily bars).
  For each asset (BTC, ETH):
    trend signal = month-end close above its 10-month moving average
                   (mean of the last 10 month-end closes, incl. current)
                   -> invested; below -> cash (0% interest, conservative).
    target weight = min(1, 10% / realized_vol), where realized_vol is the
                   annualized vol of the trailing 60 daily log returns
                   (x sqrt(365); crypto trades every day).
  Trades execute at the NEXT bar's open. Rebalance to target weights then;
  holdings drift between evaluations.
POTS: (1) BTC-only — BTC target weight applies to the whole pot.
      (2) 50/50 BTC/ETH — each asset's target = 0.50 x its vol-scaled
          weight x pot equity; the rest is cash. One shared cash pool.
DATA: Yahoo Finance daily bars, cached in crypto-trend-data/ (BTC-USD from
      2014-09-17, ETH-USD from 2017-11-09). Runs cut at 2026-11-20.
WINDOWS: FULL = data start -> 2026-11-20; DESIGN = start -> 2022-12-31;
         VALIDATION = 2023-01-01 -> 2026-11-20 (fresh $100 pots; signals
         use pre-window history as lookback only — no look-ahead).
COSTS: 0.40% per side (documented US retail reality: Kraken Pro / Coinbase
      Advanced entry tiers, per the crypto evidence audit). No fixed fee.
POT: $100 start, full compounding.
PROTECTION: NO floor in the primary runs (crypto-trend.md proved no -15%
      floor survives crypto). One diagnostic run per pot over the FULL
      window WITH the plain -15% floor ($85, checked on daily closes,
      liquidate next open, halted for good) is reported for the record.
BENCHMARKS: buy-and-hold BTC / ETH / 50-50 (bought at window-start open,
      entry cost only, 50-50 = initial split, never rebalanced).
PLACEBO: random monthly in/out timing, validation window, 20 seeds.
      Per asset, the in-probability is set so the placebo's expected
      exposure equals the strategy's average invested weight for that
      asset (placebo holds at full sleeve weight when "in"). Same costs.
"""
import json, math, os, random
import numpy as np
import pandas as pd

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(OUT_DIR, "crypto-trend-data")

START_CASH = 100.0
COST = 0.0040            # 0.40% per side — US retail crypto reality
END_DATE = "2026-11-20"
VAL_START = "2023-01-01"
DESIGN_END = "2022-12-31"
FLOOR = 85.0             # plain -15% floor, diagnostic only
VOL_TARGET = 0.10
VOL_WIN = 60

# ---------------------------------------------------------------- data ----
def load(symbol):
    df = pd.read_csv(os.path.join(CACHE, f"{symbol}.csv"), parse_dates=["date"])
    df = df[df["date"] <= END_DATE].sort_values("date").reset_index(drop=True)
    df["logret"] = np.log(df["close"] / df["close"].shift(1))
    return df

BTC = load("BTC-USD")
ETH = load("ETH-USD")
DATA = {"BTC": BTC, "ETH": ETH}

# ------------------------------------------------------------- signals ----
def build_schedule(df):
    """Return dict exec_date(Timestamp) -> target weight (0..1) for one asset.
    Signal computed at each month-end close; execution at next bar's open."""
    d = df.reset_index(drop=True)
    d["ym"] = d["date"].dt.year * 100 + d["date"].dt.month
    me_idx = d.groupby("ym").tail(1).index.tolist()          # month-end bars
    me_closes = d.loc[me_idx, "close"].tolist()
    sched = {}
    for k, idx in enumerate(me_idx):
        if k < 9:                                            # need 10 month-ends
            continue
        ma10 = float(np.mean(me_closes[k - 9:k + 1]))
        close = float(d.loc[idx, "close"])
        rets = d.loc[:idx, "logret"].tail(VOL_WIN)
        if len(rets) < VOL_WIN:
            continue
        vol = float(rets.std(ddof=1) * math.sqrt(365))
        w = min(1.0, VOL_TARGET / vol) if (close > ma10 and vol > 0) else 0.0
        if idx + 1 < len(d):
            exec_date = d.loc[idx + 1, "date"]
            sched[exec_date] = w
    return sched

SCHED = {a: build_schedule(df) for a, df in DATA.items()}

# -------------------------------------------------------------- engine ----
def run_pot(assets, w0, w1, mode="strategy", floor=False, seed=None):
    """assets: list of (name, alloc). mode: 'strategy' | 'buyhold' | 'placebo'.
    Returns results dict incl. daily equity series."""
    frames = {}
    for name, _ in assets:
        df = DATA[name]
        frames[name] = df[(df["date"] >= w0) & (df["date"] <= w1)].reset_index(drop=True)
    # common calendar: union of dates (BTC trades every day; ETH same grid here)
    cal = pd.DatetimeIndex(frames[assets[0][0]]["date"])
    for name, _ in assets[1:]:
        cal = cal.union(pd.DatetimeIndex(frames[name]["date"]))
    cal = pd.DatetimeIndex(sorted(cal))
    opens = {n: frames[n].set_index("date")["open"] for n, _ in assets}
    closes = {n: frames[n].set_index("date")["close"] for n, _ in assets}

    cash = START_CASH
    units = {n: 0.0 for n, _ in assets}
    trades = 0
    total_costs = 0.0
    halted = None
    rng = random.Random(seed) if seed is not None else None
    # placebo in-probabilities are set by caller via PLACEBO_P
    eq_rows = []
    bought = False

    for dt in cal:
        # --- execute pending rebalance at today's open ---
        do_trade = False
        targets = {}
        if not halted:
            if mode == "strategy":
                for name, alloc in assets:
                    if dt in SCHED[name]:
                        targets[name] = alloc * SCHED[name][dt]
                        do_trade = True
            elif mode == "placebo":
                for name, alloc in assets:
                    # same execution dates as the strategy schedule
                    if dt in SCHED[name]:
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
        # --- mark to close ---
        eq = cash + sum(units[n] * closes[n].get(dt, 0.0) for n, _ in assets)
        invested = sum(units[n] * closes[n].get(dt, 0.0) for n, _ in assets)
        eq_rows.append((dt, eq, invested))
        # --- floor diagnostic: breach on close -> liquidate next open ---
        if floor and not halted and eq <= FLOOR:
            halted = dt
            # liquidate at next bar's open
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
            # rebuild remaining rows as flat cash
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
    cagr = ((final / START_CASH) ** (365.25 / days) - 1) * 100 if days > 0 and final > 0 else 0.0
    return {
        "final": round(final, 2),
        "return_pct": round((final / START_CASH - 1) * 100, 1),
        "cagr_pct": round(cagr, 1),
        "max_dd_pct": round(max_dd, 1),
        "trades": trades,
        "costs": round(total_costs, 2),
        "avg_exposure_pct": round(float((inv / eqs).mean() * 100), 1) if len(eqs) else 0.0,
        "halted": str(halted.date()) if halted is not None else None,
        "start": str(eqs.index[0].date()), "end": str(eqs.index[-1].date()),
        "_eqs": eqs,
    }

PLACEBO_P = {}

def per_year(eqs, start_year):
    out = {}
    yrs = sorted(set(eqs.index.year))
    prev = START_CASH
    for y in yrs:
        if y < start_year:
            continue
        sub = eqs[eqs.index.year == y]
        if len(sub) == 0:
            continue
        out[y] = round((float(sub.iloc[-1]) / prev - 1) * 100, 1)
        prev = float(sub.iloc[-1])
    return out

# ---------------------------------------------------------------- runs ----
POTS = {
    "BTC": [("BTC", 1.0)],
    "ETH": [("ETH", 1.0)],
    "COMBO": [("BTC", 0.5), ("ETH", 0.5)],
}
DATA_START = {"BTC": str(BTC["date"].iloc[0].date()), "ETH": str(ETH["date"].iloc[0].date())}
COMBO_START = DATA_START["ETH"]  # combo needs both assets

results = {}

def strip(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}

for pot, assets in POTS.items():
    w_full = COMBO_START if pot == "COMBO" else DATA_START[assets[0][0]]
    runs = {}
    for label, (w0, w1) in {
        "full": (w_full, END_DATE),
        "design": (w_full, DESIGN_END),
        "validation": (VAL_START, END_DATE),
    }.items():
        strat = run_pot(assets, w0, w1, mode="strategy")
        bh_assets = assets if pot != "ETH" else assets
        bh = run_pot(bh_assets, w0, w1, mode="buyhold")
        runs[label] = {"strategy": strip(strat), "buyhold": strip(bh),
                       "_strat": strat}
    # placebo on validation: calibrate per-asset p from strategy avg weights
    strat_v = runs["validation"]["_strat"]
    # strategy average asset weight = avg invested fraction attributable:
    # recompute per-asset weights from a dedicated pass is overkill; use
    # total avg exposure split by allocation as the exposure target.
    # (BTC-only pot: p = avg exposure. Combo: per-asset p from sleeve runs.)
    finals = []
    if pot == "BTC":
        PLACEBO_P = {"BTC": min(1.0, strat_v["avg_exposure_pct"] / 100.0)}
    elif pot == "ETH":
        PLACEBO_P = {"ETH": min(1.0, strat_v["avg_exposure_pct"] / 100.0)}
    else:
        # use the single-asset validation runs' exposures for each sleeve
        PLACEBO_P = {
            "BTC": min(1.0, results["BTC"]["validation"]["strategy"]["avg_exposure_pct"] / 100.0),
            "ETH": min(1.0, results["ETH"]["validation"]["strategy"]["avg_exposure_pct"] / 100.0),
        }
    for s in range(20):
        pr = run_pot(assets, VAL_START, END_DATE, mode="placebo", seed=1000 + s)
        finals.append(pr["final"])
    finals_sorted = sorted(finals)
    strat_final = runs["validation"]["strategy"]["final"]
    pct = sum(1 for f in finals if f < strat_final) / len(finals) * 100
    runs["placebo_validation"] = {
        "median": round(float(np.median(finals)), 2),
        "min": round(min(finals), 2), "max": round(max(finals), 2),
        "strategy_percentile": round(pct, 0),
        "finals": [round(f, 2) for f in finals_sorted],
    }
    # floor diagnostic, full window
    fl = run_pot(assets, w_full, END_DATE, mode="strategy", floor=True)
    runs["floor_diagnostic_full"] = strip(fl)
    # per-year for full strategy run
    runs["per_year_full"] = per_year(runs["full"]["_strat"]["_eqs"],
                                     int(w_full[:4]))
    for label in ("full", "design", "validation"):
        runs[label].pop("_strat", None)
    results[pot] = runs

with open(os.path.join(OUT_DIR, "crypto-trend-volscaled-results.json"), "w") as f:
    json.dump(results, f, indent=2)

# ------------------------------------------------------------- summary ----
for pot in POTS:
    r = results[pot]
    print(f"\n=== {pot} ===")
    for label in ("design", "validation", "full"):
        s, b = r[label]["strategy"], r[label]["buyhold"]
        print(f"{label:10s} STRAT final ${s['final']:>9} ({s['return_pct']:+.1f}%, CAGR {s['cagr_pct']:+.1f}%, "
              f"DD {s['max_dd_pct']:.1f}%, trades {s['trades']}, costs ${s['costs']}, expo {s['avg_exposure_pct']}%) | "
              f"B&H ${b['final']:>9} ({b['return_pct']:+.1f}%, DD {b['max_dd_pct']:.1f}%)")
    pb = r["placebo_validation"]
    print(f"placebo val: median ${pb['median']}, range ${pb['min']}-${pb['max']}, strategy percentile {pb['strategy_percentile']:.0f}th")
    fd = r["floor_diagnostic_full"]
    print(f"floor diag (full): final ${fd['final']}, halted {fd['halted']}")
    print(f"per-year full: {r['per_year_full']}")
print("\nDone. Results JSON written.")
