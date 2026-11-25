#!/usr/bin/env python3
"""V13 Best Rules — Faber Tactical Yield.
Spec: ../BEST-RULES-SPEC.md (frozen before this run).
Published construction EXACTLY as v12 (term/credit premiums vs expanding
point-in-time medians, 50% IEF / 50% LQD, rest BIL, monthly check).
V13 chassis: trade ONLY on a premium state flip; no intra-state re-trim;
NO -15% floor. Cost 0.10% of traded value. $100 pots.
Data read-only from the v12 folder.
Also runs a faithful monthly-retrim replication of the published form to
validate plumbing against the v12 record ($178.10 LONG etc.).
"""
import json, os
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.dirname(HERE)
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/catalog-taa-faber-tactical-yield/data")
COST = 0.001
END = "2026-11-20"
ROADS = {"LONG": "2010-01-01", "DECADE": "2016-01-01", "CONT": "2019-01-01", "VAL": "2023-01-01"}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}

def load_prices():
    out = {}
    for t in ["IEF", "LQD", "BIL", "SPY"]:
        df = pd.read_csv(os.path.join(DATA, t + ".csv"), parse_dates=["date"])
        out[t] = df.set_index("date")["adjclose"]
    return pd.DataFrame(out).sort_index()

PX = load_prices()
_grp = PX.index.to_series().groupby([PX.index.year, PX.index.month])
ME = PX.loc[_grp.max().values]
DAYS = PX.index
REBAL_POS = set(PX.index.get_indexer(ME.index))
COL = {t: j for j, t in enumerate(PX.columns)}
PXV = PX.values

def fred(name):
    df = pd.read_csv(os.path.join(DATA, name + ".csv"))
    df.columns = ["date"] + list(df.columns[1:])
    df["date"] = pd.to_datetime(df["date"])
    return pd.to_numeric(df.set_index("date").iloc[:, 0], errors="coerce")

DGS10 = fred("DGS10"); DGS3MO = fred("DGS3MO"); BAA = fred("BAA")

_m10 = DGS10.resample("M").last(); _m3 = DGS3MO.resample("M").last()
TERM = (_m10 - _m3).dropna()
_baa = BAA.copy(); _baa.index = _baa.index + pd.offsets.MonthEnd(0)
CRED = (_baa - _m3.reindex(_baa.index, method="ffill")).dropna()

def state_at(me_date):
    """Published signal: (ief_on, lqd_on) using only data <= me_date."""
    th = TERM[TERM.index <= me_date]; ch = CRED[CRED.index <= me_date]
    if len(th) < 24 or len(ch) < 24: return None
    return (bool(th.iloc[-1] > th.median()), bool(ch.iloc[-1] > ch.median()))

STATE = {d: state_at(d) for d in ME.index}

def weights(state):
    w = {}
    if state[0]: w["IEF"] = 0.5
    if state[1]: w["LQD"] = 0.5
    rest = 1 - sum(w.values())
    if rest > 0: w["BIL"] = rest
    return w

def simulate(start, end, mode="state_change", placebo_seed=None):
    """mode='state_change' (v13 chassis) or 'monthly_retrim' (published engine)."""
    start = pd.Timestamp(start); end = pd.Timestamp(end)
    pos = np.where((DAYS >= start) & (DAYS <= end))[0]
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    shares = {}; cash = 100.0
    dates, vals = [], []
    prev_state = None
    n_trades = 0; total_cost = 0.0
    for p in pos:
        row = PXV[p]; d = DAYS[p]
        def equity():
            return cash + sum(s * row[COL[t]] for t, s in shares.items() if not np.isnan(row[COL[t]]))
        if p in REBAL_POS or p == pos[0]:
            mi_date = ME.index[ME.index <= d][-1]
            st = STATE[mi_date]
            if st is not None:
                do_trade = (mode == "monthly_retrim") or (st != prev_state) or (p == pos[0])
                if do_trade:
                    w = weights(st)
                    if rng is not None:
                        inv = sum(v for t, v in w.items() if t != "BIL")
                        k = sum(1 for v in w.values() if v > 0.01)
                        pool = ["IEF", "LQD"]
                        picks = list(rng.choice(pool, size=min(k, len(pool)), replace=False))
                        w = {t: inv / len(picks) for t in picks}
                        if inv < 0.999: w["BIL"] = 1 - inv
                    eq = equity()
                    target = {t: eq * v for t, v in w.items()}
                    traded = sum(abs(target.get(t, 0.0) - shares.get(t, 0.0) * row[COL[t]])
                                 for t in set(target) | set(shares))
                    if traded > 1e-9:
                        n_trades += 1; total_cost += COST * traded
                        scale = (eq - COST * traded) / eq if eq > 0 else 0
                        shares = {t: (target[t] / row[COL[t]]) * scale for t in target if target[t] > 0}
                        cash = 0.0
                    prev_state = st
        dates.append(d); vals.append(equity())
    ec = pd.Series(vals, index=pd.DatetimeIndex(dates))
    return ec, {"n_trade_events": n_trades, "total_cost_usd": round(total_cost, 4)}

def buyhold(tickers_weights, start, end):
    days = DAYS[(DAYS >= pd.Timestamp(start)) & (DAYS <= pd.Timestamp(end))]
    ec = None
    for t, w in tickers_weights.items():
        s = 100.0 * w * PX[t].loc[days] / PX[t].loc[days].iloc[0]
        ec = s if ec is None else ec + s
    return ec

def stats(ec):
    dd = float((ec / ec.cummax() - 1).min())
    m = ec.resample("M").last(); mr = m.pct_change().dropna()
    streak = cur = 0
    for x in mr:
        cur = cur + 1 if x < 0 else 0; streak = max(streak, cur)
    last_high = 0; maxgap = 0; cm = m.cummax()
    for j in range(len(m)):
        if m.iloc[j] >= cm.iloc[j] - 1e-12: last_high = j
        maxgap = max(maxgap, j - last_high)
    return {"final": round(float(ec.iloc[-1]), 2), "max_dd_pct": round(100 * dd, 1),
            "months": int(len(mr)), "share_pos": round(float((mr > 0).mean()), 3),
            "median_month_pct": round(100 * float(mr.median()), 2),
            "avg_month_pct": round(100 * float(mr.mean()), 2),
            "best_month_pct": round(100 * float(mr.max()), 2),
            "worst_month_pct": round(100 * float(mr.min()), 2),
            "longest_losing_streak_months": int(streak),
            "longest_below_high_months": int(maxgap)}

def main():
    out = {"family": "catalog-taa-faber-tactical-yield", "program": "v13-best-rules",
           "roads": {}, "champions": CHAMP, "spy_program_refs": SPY_REF}
    for road, st in ROADS.items():
        ec, meta = simulate(st, END, mode="state_change")
        s = stats(ec); s.update(meta)
        ecp, metap = simulate(st, END, mode="monthly_retrim")
        sp = stats(ecp); sp.update(metap)
        spy = buyhold({"SPY": 1.0}, st, END)
        mix = buyhold({"IEF": 0.5, "LQD": 0.5}, st, END)
        bil = buyhold({"BIL": 1.0}, st, END)
        beaten = 0; pfin = []
        for seed in range(20):
            epl, _ = simulate(st, END, mode="monthly_retrim", placebo_seed=seed)
            pfin.append(round(float(epl.iloc[-1]), 2))
            if s["final"] > float(epl.iloc[-1]): beaten += 1
        out["roads"][road] = {
            "v13_best_rules": s,
            "published_form_replication": sp,
            "spy_same_window": stats(spy),
            "static_ief_lqd_5050_buyhold": stats(mix),
            "bil_buyhold": stats(bil),
            "placebos_beaten_of_20": beaten,
            "placebo_finals": sorted(pfin),
            "champion_vm": CHAMP[road],
            "curve_v13": {str(d.date()): round(float(v), 4) for d, v in ec.items()},
            "curve_published_replication": {str(d.date()): round(float(v), 4) for d, v in ecp.items()},
        }
        print(road, "v13", s["final"], "DD", s["max_dd_pct"], "| published-repl", sp["final"],
              "| SPY", round(float(spy.iloc[-1]), 2), "| mix", round(float(mix.iloc[-1]), 2),
              "| placebos", beaten, "/20 | trades v13/pub", s["n_trade_events"], "/", sp["n_trade_events"])
    # folds (context only; confirmation bars in spec bind only on champion-beaters)
    folds = {}
    for nm, (a, b) in {"fold_2010_2018": ("2010-01-01", "2018-12-31"),
                       "fold_2019_2026": ("2019-01-01", END)}.items():
        ec, _ = simulate(a, b, mode="state_change")
        folds[nm] = {"final": stats(ec)["final"], "max_dd_pct": stats(ec)["max_dd_pct"]}
    out["folds_v13"] = folds
    with open(os.path.join(FOLDER, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("folds", folds)

if __name__ == "__main__":
    main()
