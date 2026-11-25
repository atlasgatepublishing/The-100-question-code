#!/usr/bin/env python3
"""
CRYPTO TREND TEST — BTC & ETH, for Terry's AI stock app. SIMULATION ONLY.

Rule (frozen, mirrors the stock ETF trend sleeve):
  For each asset: hold the asset when its close is above its 200-day moving
  average, otherwise hold cash (0% interest — conservative choice).
  Evaluate WEEKLY (last day of each calendar week, Sunday, on daily bars);
  enter/exit at the NEXT daily bar's open.
Data: Yahoo Finance chart API (free, no key), BTC-USD and ETH-USD daily bars.
Windows: FULL = all available history; DESIGN = start -> 2022-12-31;
         VALIDATION = 2023-01-01 -> 2026-11-20.
Costs: 0.25%/side (retail exchange taker). Fixed per-order fee ignored as
       immaterial in crypto (stated in the report).
Pot: $100 start, full compounding.
Protection variants: (none) raw rule, (ladder) Terry's floor+ladder,
  (plain) plain -15% floor from the starting balance.
  Floor logic (same as the stock program): checked on every daily close;
  if pot close <= floor, liquidate everything at the next bar's open and the
  pot stays in cash (halted). Ladder rungs (scaled to the $100 start):
  floor starts at $85; a close >= $125 raises it to $100; a close >= $150
  raises it to $125 (top rung).
Benchmarks: buy-and-hold per asset / 50-50 combo, raw and under both floors.
Placebo: random weekly in/out with the same average exposure as the trend
  rule on the validation window, 20 seeds, no floor; percentile reported.
Combo pot: two $50 sleeves, each following its own asset's rule; the floor
  is checked on the COMBINED pot equity.
"""
import json, math, os, random, sys
import requests
import pandas as pd

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(OUT_DIR, "crypto-trend-data")
os.makedirs(CACHE, exist_ok=True)

START_CASH = 100.0
COST = 0.0025            # 0.25% per side
END_DATE = "2026-11-20"
VAL_START = "2023-01-01"
DESIGN_END = "2022-12-31"

# ---------------------------------------------------------------- data ----
def fetch(symbol):
    path = os.path.join(CACHE, f"{symbol}.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, parse_dates=["date"])
        return df
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?period1=0&period2=1799999999&interval=1d")
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame({
        "date": pd.to_datetime(ts, unit="s", utc=True).tz_localize(None).normalize(),
        "open": q["open"], "high": q["high"], "low": q["low"], "close": q["close"],
    }).dropna(subset=["open", "close"]).sort_values("date").reset_index(drop=True)
    df.to_csv(path, index=False)
    return df

def prep(df):
    df = df.copy()
    df["sma200"] = df["close"].rolling(200).mean()
    # weekly evaluation points: last bar of each ISO week
    iso = df["date"].dt.isocalendar()
    df["yw"] = iso["year"].astype(str) + "-" + iso["week"].astype(str).str.zfill(2)
    last_idx = df.groupby("yw").tail(1).index
    df["is_eval"] = df.index.isin(last_idx)
    return df

# ------------------------------------------------------------ strategy ----
def run_asset(df, w0, w1, floor_mode="none", seed=None, placebo_p=None):
    """Run one asset sleeve over [w0, w1]. Returns dict of results.
    floor_mode: 'none' | 'plain' | 'ladder' (floor applied at sleeve level
    only when called standalone; combo passes floor_mode='none' and applies
    the floor at pot level in run_combo)."""
    d = df[(df["date"] >= w0) & (df["date"] <= w1)].reset_index(drop=True)
    full_idx = df[(df["date"] >= w0) & (df["date"] <= w1)].index  # for opens
    cash, units = START_CASH, 0.0
    start = START_CASH
    floor = 0.85 * start
    halted, halt_date = False, None
    trades, total_costs = 0, 0.0
    invested_days, total_days = 0, 0
    equity_curve = []           # (date, equity at close)
    pending = None              # target state to execute at next open
    rng = random.Random(seed) if seed is not None else None
    invested_weeks, total_weeks = 0, 0

    # map from position in d to the row in df for next-open execution
    pos_of = {idx: i for i, idx in enumerate(full_idx)}

    for i, row in d.iterrows():
        gi = full_idx[i]
        # execute pending decision at today's open
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
        # floor liquidation pending executes before new decisions
        eq_close = cash + units * row["close"]
        equity_curve.append((row["date"], eq_close))
        total_days += 1
        if units > 0:
            invested_days += 1
        if halted:
            continue
        # floor check on the close
        if floor_mode == "ladder":
            if eq_close >= 1.50 * start:
                floor = max(floor, 1.25 * start)
            elif eq_close >= 1.25 * start:
                floor = max(floor, start)
        if floor_mode in ("plain", "ladder") and eq_close <= floor:
            # liquidate at next bar's open
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
        # weekly evaluation
        if row["is_eval"]:
            total_weeks += 1
            if rng is not None:  # placebo
                want_in = rng.random() < placebo_p
            else:
                sma = row["sma200"]
                want_in = (not pd.isna(sma)) and (row["close"] > sma)
            if want_in:
                invested_weeks += 1
            target = "in" if want_in else "out"
            cur_in = units > 0
            if (target == "in") != cur_in:
                pending = target
    final = cash + (units * d.iloc[-1]["close"] if units > 0 else 0.0)
    if units > 0:
        final = cash + units * d.iloc[-1]["close"]
    else:
        final = cash
    eq = pd.Series([e for _, e in equity_curve])
    max_dd = ((eq / eq.cummax()) - 1).min() * 100 if len(eq) else 0.0
    years = max((d.iloc[-1]["date"] - d.iloc[0]["date"]).days / 365.25, 1e-9)
    cagr = ((final / start) ** (1 / years) - 1) * 100 if final > 0 else -100.0
    # per-year returns from the equity curve
    ec = pd.DataFrame(equity_curve, columns=["date", "eq"]).set_index("date")["eq"]
    yearly = {}
    for y, grp in ec.groupby(ec.index.year):
        prev = ec[ec.index.year == y - 1]
        base = prev.iloc[-1] if len(prev) else start
        yearly[int(y)] = (grp.iloc[-1] / base - 1) * 100
    return {
        "final": final, "cagr": cagr, "max_dd": max_dd, "trades": trades,
        "costs": total_costs, "halted": halted,
        "halt_date": (halt_date.strftime("%Y-%m-%d") if halt_date is not None else None),
        "exposure_days_pct": invested_days / total_days * 100 if total_days else 0.0,
        "exposure_weeks": invested_weeks / total_weeks if total_weeks else 0.0,
        "yearly": yearly, "equity": equity_curve,
    }

def run_combo(dfs, w0, w1, floor_mode="none"):
    """50/50 combo: two $50 sleeves, floor on combined equity."""
    sleeves = []
    for sym, df in dfs.items():
        d = df[(df["date"] >= w0) & (df["date"] <= w1)].reset_index(drop=True)
        sleeves.append({"sym": sym, "df": df, "d": d, "cash": 50.0, "units": 0.0,
                        "pending": None, "trades": 0, "costs": 0.0,
                        "invested_days": 0})
    start = START_CASH
    floor = 0.85 * start
    halted, halt_date = False, None
    # unified calendar
    all_dates = sorted(set().union(*[set(s["d"]["date"]) for s in sleeves]))
    rows = {s["sym"]: {r["date"]: r for _, r in s["d"].iterrows()} for s in sleeves}
    full_rows = {s["sym"]: {r["date"]: r for _, r in s["df"].iterrows()} for s in sleeves}
    next_open = {}
    for s in sleeves:
        dl = list(s["df"]["date"])
        next_open[s["sym"]] = {dl[i]: (dl[i + 1] if i + 1 < len(dl) else None) for i in range(len(dl))}
    equity_curve = []
    total_days = 0
    for dt in all_dates:
        # execute pendings at today's open
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
            eq += s["cash"] + s["units"] * last_close
        equity_curve.append((dt, eq))
        total_days += 1
        if halted:
            continue
        if floor_mode == "ladder":
            if eq >= 1.50 * start:
                floor = max(floor, 1.25 * start)
            elif eq >= 1.25 * start:
                floor = max(floor, start)
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
            if r is not None and r["is_eval"]:
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
    ec = pd.DataFrame(equity_curve, columns=["date", "eq"]).set_index("date")["eq"]
    yearly = {}
    for y, grp in ec.groupby(ec.index.year):
        prev = ec[ec.index.year == y - 1]
        base = prev.iloc[-1] if len(prev) else start
        yearly[int(y)] = (grp.iloc[-1] / base - 1) * 100
    return {
        "final": final, "cagr": cagr, "max_dd": max_dd,
        "trades": sum(s["trades"] for s in sleeves),
        "costs": sum(s["costs"] for s in sleeves),
        "halted": halted,
        "halt_date": (halt_date.strftime("%Y-%m-%d") if halt_date is not None else None),
        "exposure_days_pct": sum(s["invested_days"] for s in sleeves) / (2 * total_days) * 100 if total_days else 0.0,
        "yearly": yearly, "equity": equity_curve,
    }

def buy_hold(df, w0, w1, floor_mode="none"):
    d = df[(df["date"] >= w0) & (df["date"] <= w1)].reset_index(drop=True)
    start = START_CASH
    fee0 = start * COST
    units = (start - fee0) / d.iloc[0]["open"]
    cash = 0.0
    total_costs = fee0
    floor = 0.85 * start
    halted, halt_date, trades = False, None, 1
    eqs = []
    for i, row in d.iterrows():
        eq = cash + units * row["close"]
        eqs.append(eq)
        if halted:
            continue
        if floor_mode == "ladder":
            if eq >= 1.50 * start:
                floor = max(floor, 1.25 * start)
            elif eq >= 1.25 * start:
                floor = max(floor, start)
        if floor_mode in ("plain", "ladder") and eq <= floor and units > 0:
            gi = df[df["date"] == row["date"]].index[0]
            if gi + 1 < len(df):
                px = df.loc[gi + 1, "open"]
                gross = units * px
                fee = gross * COST
                cash = gross - fee
                total_costs += fee; units = 0.0; trades += 1
                halt_date = df.loc[gi + 1, "date"]
            else:
                halt_date = row["date"]
            halted = True
    final = cash + units * d.iloc[-1]["close"]
    eq = pd.Series(eqs)
    max_dd = ((eq / eq.cummax()) - 1).min() * 100
    years = max((d.iloc[-1]["date"] - d.iloc[0]["date"]).days / 365.25, 1e-9)
    cagr = ((final / start) ** (1 / years) - 1) * 100 if final > 0 else -100.0
    return {"final": final, "cagr": cagr, "max_dd": max_dd, "trades": trades,
            "costs": total_costs, "halted": halted,
            "halt_date": (halt_date.strftime("%Y-%m-%d") if halt_date is not None else None)}

def buy_hold_combo(dfs, w0, w1, floor_mode="none"):
    # two $50 sleeves buy & hold; floor on combined equity
    sleeves = []
    for sym, df in dfs.items():
        d = df[(df["date"] >= w0) & (df["date"] <= w1)].reset_index(drop=True)
        fee0 = 50.0 * COST
        sleeves.append({"sym": sym, "df": df, "d": d, "cash": 0.0,
                        "units": (50.0 - fee0) / d.iloc[0]["open"],
                        "costs": fee0, "trades": 1, "last_close": d.iloc[0]["close"]})
    start = START_CASH
    floor = 0.85 * start
    halted, halt_date = False, None
    all_dates = sorted(set().union(*[set(s["d"]["date"]) for s in sleeves]))
    rows = {s["sym"]: {r["date"]: r for _, r in s["d"].iterrows()} for s in sleeves}
    full_rows = {s["sym"]: {r["date"]: r for _, r in s["df"].iterrows()} for s in sleeves}
    dl_map = {s["sym"]: list(s["df"]["date"]) for s in sleeves}
    eqs = []
    for dt in all_dates:
        eq = 0.0
        for s in sleeves:
            r = rows[s["sym"]].get(dt)
            if r is not None:
                s["last_close"] = r["close"]
            eq += s["cash"] + s["units"] * s["last_close"]
        eqs.append(eq)
        if halted:
            continue
        if floor_mode == "ladder":
            if eq >= 1.50 * start:
                floor = max(floor, 1.25 * start)
            elif eq >= 1.25 * start:
                floor = max(floor, start)
        if floor_mode in ("plain", "ladder") and eq <= floor:
            for s in sleeves:
                if s["units"] > 0:
                    dl = dl_map[s["sym"]]
                    i = dl.index(dt)
                    nd = dl[i + 1] if i + 1 < len(dl) else None
                    px = full_rows[s["sym"]][nd]["open"] if nd is not None else s["last_close"]
                    gross = s["units"] * px
                    fee = gross * COST
                    s["cash"] = gross - fee
                    s["costs"] += fee; s["units"] = 0.0; s["trades"] += 1
                    halt_date = nd if nd is not None else dt
            halted = True
    final = sum(s["cash"] + s["units"] * s["last_close"] for s in sleeves)
    eq = pd.Series(eqs)
    max_dd = ((eq / eq.cummax()) - 1).min() * 100
    years = max((all_dates[-1] - all_dates[0]).days / 365.25, 1e-9)
    cagr = ((final / start) ** (1 / years) - 1) * 100 if final > 0 else -100.0
    return {"final": final, "cagr": cagr, "max_dd": max_dd,
            "trades": sum(s["trades"] for s in sleeves),
            "costs": sum(s["costs"] for s in sleeves), "halted": halted,
            "halt_date": (halt_date.strftime("%Y-%m-%d") if halt_date is not None else None)}

# ---------------------------------------------------------------- main ----
def slim(r, keep_yearly=False):
    out = {k: r[k] for k in ("final", "cagr", "max_dd", "trades", "costs",
                             "halted", "halt_date") if k in r}
    if "exposure_days_pct" in r:
        out["exposure_days_pct"] = r["exposure_days_pct"]
    if keep_yearly and "yearly" in r:
        out["yearly"] = {str(k): v for k, v in r["yearly"].items()}
    return out

def main():
    btc = prep(fetch("BTC-USD"))
    eth = prep(fetch("ETH-USD"))
    data = {"BTC": btc, "ETH": eth}
    dfs = {"BTC": btc, "ETH": eth}
    meta = {s: {"first": str(d["date"].iloc[0].date()), "last": str(d["date"].iloc[-1].date())}
            for s, d in data.items()}
    windows = {
        "FULL": (None, END_DATE),
        "DESIGN": (None, DESIGN_END),
        "VALIDATION": (VAL_START, END_DATE),
    }
    results = {"meta": meta, "windows": {}}
    for wname, (w0, w1) in windows.items():
        W = {}
        for sym, df in data.items():
            start = w0 if w0 else str(df["date"].iloc[0].date())
            W[sym] = {
                "trend_none": slim(run_asset(df, start, w1, "none"), keep_yearly=(wname == "FULL")),
                "trend_plain": slim(run_asset(df, start, w1, "plain")),
                "trend_ladder": slim(run_asset(df, start, w1, "ladder")),
                "bh_none": slim(buy_hold(df, start, w1, "none")),
                "bh_plain": slim(buy_hold(df, start, w1, "plain")),
                "bh_ladder": slim(buy_hold(df, start, w1, "ladder")),
            }
        # combo window starts when BOTH assets exist (ETH start) for FULL/DESIGN
        cstart = w0 if w0 else str(eth["date"].iloc[0].date())
        W["COMBO"] = {
            "trend_none": slim(run_combo(dfs, cstart, w1, "none"), keep_yearly=(wname == "FULL")),
            "trend_plain": slim(run_combo(dfs, cstart, w1, "plain")),
            "trend_ladder": slim(run_combo(dfs, cstart, w1, "ladder")),
            "bh_none": slim(buy_hold_combo(dfs, cstart, w1, "none")),
            "bh_plain": slim(buy_hold_combo(dfs, cstart, w1, "plain")),
            "bh_ladder": slim(buy_hold_combo(dfs, cstart, w1, "ladder")),
        }
        results["windows"][wname] = W
    # ---- placebo on VALIDATION, no floor ----
    placebo = {}
    for sym, df in data.items():
        base = run_asset(df, VAL_START, END_DATE, "none")
        p = base["exposure_weeks"]
        finals = []
        for seed in range(42, 62):
            r = run_asset(df, VAL_START, END_DATE, "none", seed=seed, placebo_p=p)
            finals.append(r["final"])
        finals_sorted = sorted(finals)
        pct = sum(1 for f in finals if f < base["final"]) / len(finals) * 100
        placebo[sym] = {"trend_final": base["final"], "exposure_weeks": p,
                        "placebo_median": finals_sorted[len(finals) // 2],
                        "placebo_min": finals_sorted[0], "placebo_max": finals_sorted[-1],
                        "trend_percentile": pct, "finals": finals}
    # combo placebo: per-sleeve random with each sleeve's own exposure — approximate
    # by running each asset's placebo with matched seeds and halving the sum.
    combo_finals = []
    for seed in range(42, 62):
        tot = 0.0
        for sym, df in data.items():
            base = run_asset(df, VAL_START, END_DATE, "none")
            # scale: run_asset starts at $100; halve contribution for $50 sleeve
            r = run_asset(df, VAL_START, END_DATE, "none", seed=seed, placebo_p=base["exposure_weeks"])
            tot += r["final"] / 2.0
        combo_finals.append(tot)
    base_combo = results["windows"]["VALIDATION"]["COMBO"]["trend_none"]["final"]
    cs = sorted(combo_finals)
    placebo["COMBO"] = {"trend_final": base_combo,
                        "placebo_median": cs[len(cs) // 2],
                        "placebo_min": cs[0], "placebo_max": cs[-1],
                        "trend_percentile": sum(1 for f in combo_finals if f < base_combo) / len(combo_finals) * 100,
                        "finals": combo_finals}
    results["placebo_validation"] = placebo
    with open(os.path.join(OUT_DIR, "crypto-trend-results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    print(json.dumps(results, indent=1, default=str))

if __name__ == "__main__":
    main()
