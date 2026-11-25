#!/usr/bin/env python3
"""Slice-5 TAA engine. FAMILY is set per copy. See SPEC-FROZEN.md /
CONSTRUCTION-SPEC.md in the family folder for the frozen form.
Monthly chassis: signals at month-end close, rebalance at that close,
cost 0.10% of traded value. Daily equity marking between rebalances.
House form: v9 -15% floor from $100 start (daily close check), first
breach -> BIL 90 calendar days + one restart; second breach -> BIL to end.
"""
import json, math, os
import numpy as np
import pandas as pd

FAMILY = "catalog-taa-elm-excess-earnings-yield"
HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.dirname(HERE)
DATA = os.path.join(FOLDER, "data")
COST = 0.001
ROADS = {"LONG": "2010-01-01", "DECADE": "2016-01-01", "CONT": "2019-01-01", "VAL": "2023-01-01"}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

def load_prices():
    out = {}
    for fn in os.listdir(DATA):
        if fn.endswith(".csv") and fn[:-4].isupper() and len(fn) <= 8:
            hdr = pd.read_csv(os.path.join(DATA, fn), nrows=0).columns
            if "adjclose" in hdr:
                df = pd.read_csv(os.path.join(DATA, fn), parse_dates=["date"])
                out[fn[:-4]] = df.set_index("date")["adjclose"]
    return pd.DataFrame(out).sort_index()

PX = load_prices()
_grp = PX.index.to_series().groupby([PX.index.year, PX.index.month])
ME = PX.loc[_grp.max().values]         # month-end closes, labeled by last trading day
MRET = ME.pct_change()
DAYS = PX.index
REBAL_SET = set(ME.index)

def fred(name):
    df = pd.read_csv(os.path.join(DATA, name + ".csv"))
    df.columns = ["date"] + list(df.columns[1:])
    df["date"] = pd.to_datetime(df["date"])
    return pd.to_numeric(df.set_index("date").iloc[:, 0], errors="coerce")

DFII10 = fred("DFII10"); DGS10 = fred("DGS10"); DGS3MO = fred("DGS3MO")
BAA = fred("BAA"); CPI = fred("CPIAUCNS"); CAPE = fred("CAPE")

def m13612w(i, t):
    if i < 12: return np.nan
    p = ME[t]
    return (12 * (p.iloc[i] / p.iloc[i-1] - 1) + 4 * (p.iloc[i] / p.iloc[i-3] - 1)
            + 2 * (p.iloc[i] / p.iloc[i-6] - 1) + (p.iloc[i] / p.iloc[i-12] - 1))

def ret_k(i, t, k):
    if i < k: return np.nan
    return ME[t].iloc[i] / ME[t].iloc[i-k] - 1

def sma_ratio(i, t):
    if i < 12: return np.nan
    return ME[t].iloc[i] / ME[t].iloc[i-12:i+1].mean()

def w_daa(i, topn_full=6, topn_half=3):
    can = [m13612w(i, "VWO"), m13612w(i, "BND")]
    if any(np.isnan(can)): return {}
    b = sum(1 for x in can if x <= 0)
    risk = ["SPY","QQQ","IWM","VGK","EWJ","VWO","VNQ","GSG","GLD","TLT","HYG","LQD"]
    cash = ["SHY","IEF","LQD"]
    rs = sorted(risk, key=lambda t: -m13612w(i, t))
    best_cash = max(cash, key=lambda t: m13612w(i, t))
    if b == 2: return {best_cash: 1.0}
    if b == 1:
        w = {t: 0.5/topn_half for t in rs[:topn_half]}; w[best_cash] = w.get(best_cash, 0) + 0.5
        return w
    return {t: 1.0/topn_full for t in rs[:topn_full]}

def w_baa(i, topn=6):
    can = [m13612w(i, t) for t in ["SPY","VWO","VEA","BND"]]
    if any(np.isnan(can)): return {}
    if all(x > 0 for x in can):
        off = ["SPY","QQQ","IWM","VGK","EWJ","VWO","VNQ","DBC","GLD","TLT","HYG","LQD"]
        rs = sorted(off, key=lambda t: -sma_ratio(i, t))
        return {t: 1.0/topn for t in rs[:topn]}
    dfn = ["TIP","DBC","BIL","IEF","TLT","LQD","BND"]
    rs = sorted(dfn, key=lambda t: -sma_ratio(i, t))
    bil_r = sma_ratio(i, "BIL")
    w = {}
    for t in rs[:3]:
        tgt = t if sma_ratio(i, t) >= bil_r else "BIL"
        w[tgt] = w.get(tgt, 0) + 1.0/3
    return w

def _eaa_scores(i):
    U = ["SPY","VEA","VWO","GSG","VNQ","BND","SHY"]
    if i < 12: return None
    rets = MRET[U].iloc[i-11:i+1]
    idx = rets.mean(axis=1)
    out = {}
    for t in U:
        r = (ret_k(i, t, 1) + ret_k(i, t, 3) + ret_k(i, t, 6) + ret_k(i, t, 12)) / 22.0
        v = rets[t].std()
        c = np.corrcoef(rets[t].values, idx.values)[0, 1] if rets[t].std() > 0 else 1.0
        out[t] = (r, v, c)
    return out

def w_eaa(i, ws=2.0, topn=None):
    sc = _eaa_scores(i)
    if sc is None: return {}
    U = list(sc.keys())
    if topn is None: topn = 1 + math.ceil(math.sqrt(len(U)))
    z = {t: (r * math.sqrt(max(1 - c, 0.0))) ** ws if r > 0 else 0.0 for t, (r, v, c) in sc.items()}
    top = sorted(U, key=lambda t: -z[t])[:topn]
    tot = sum(z[t] for t in top)
    cp = sum(1 for t in U if sc[t][0] <= 0) / len(U)
    if tot <= 0: return {"IEF": 1.0}
    w = {t: (1 - cp) * z[t] / tot for t in top if z[t] > 0}
    if cp > 0: w["IEF"] = w.get("IEF", 0) + cp
    return w

def w_caa(i, tv=0.10):
    from scipy.optimize import minimize
    U = ["SPY","EFA","EEM","QQQ","EWJ","HYG","BIL","IEF"]
    risky = U[:6]
    if i < 12: return {}
    mu = np.array([np.mean([ret_k(i, t, 1), ret_k(i, t, 3), ret_k(i, t, 6), ret_k(i, t, 12)]) for t in U])
    cov = MRET[U].iloc[i-11:i+1].cov().values
    n = len(U)
    bounds = [(0, 0.25) if t in risky else (0, 1.0) for t in U]
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}]
    def vol(w): return math.sqrt(max(w @ cov @ w, 0) * 12)
    rmin = minimize(lambda w: vol(w), np.ones(n)/n, method="SLSQP", bounds=bounds, constraints=cons)
    wmin = rmin.x
    if vol(wmin) > tv: return {t: float(w) for t, w in zip(U, wmin) if w > 1e-4}
    cons2 = cons + [{"type": "ineq", "fun": lambda w: tv - vol(w)}]
    r = minimize(lambda w: -mu @ w, wmin, method="SLSQP", bounds=bounds, constraints=cons2)
    w = r.x if r.success else wmin
    return {t: float(x) for t, x in zip(U, w) if x > 1e-4}

def _cape_lagged(month_end):
    s = CAPE[CAPE.index <= month_end - pd.DateOffset(months=3)]
    return s.iloc[-1] if len(s) else np.nan

def _tips_yield(month_end):
    s = DFII10[DFII10.index <= month_end]
    return s.iloc[-1] / 100.0 if len(s) else np.nan

def w_elm(i, momentum=False):
    me_date = ME.index[i]
    cape = _cape_lagged(me_date)
    if np.isnan(cape): return {}
    eey = 1.0 / cape - _tips_yield(me_date)
    if momentum:
        vals = []
        for j, d in enumerate(ME.index[:i+1]):
            cpi_s = CPI[CPI.index <= d - pd.DateOffset(months=2)]
            if len(cpi_s) == 0: vals.append(np.nan); continue
            yrs = (d - pd.Timestamp("2008-01-01")).days / 365.25
            vals.append(ME["SPY"].iloc[j] / cpi_s.iloc[-1] / (1.04 ** yrs))
        vals = np.array(vals, dtype=float)
        if i >= 11 and not np.isnan(vals[-1]):
            eey += 0.02 if vals[-1] > np.nanmean(vals[-12:]) else -0.02
    w_stock = min(max(eey / (2 * 0.182), 0.0), 1.0)
    w = {}
    if w_stock > 0: w["SPY"] = w_stock
    if w_stock < 1: w["TIP"] = 1 - w_stock
    return w

def w_faber_high(i):
    if i < 11: return {}
    w = {}
    for t in ["SPY","EFA","DBC","VNQ","GLD"]:
        hi = ME[t].iloc[i-11:i+1].max()
        tgt = t if ME[t].iloc[i] >= 0.95 * hi else "IEF"
        w[tgt] = w.get(tgt, 0) + 0.2
    return w

_TY = {}
def w_tactical_yield(i):
    me_date = ME.index[i]
    if "done" not in _TY:
        m10 = DGS10.resample("M").last(); m3 = DGS3MO.resample("M").last()
        _TY["term"] = (m10 - m3).dropna()
        baa_m = BAA.copy(); baa_m.index = baa_m.index + pd.offsets.MonthEnd(0)
        _TY["cred"] = (baa_m - m3.reindex(baa_m.index, method="ffill")).dropna()
        _TY["done"] = 1
    th = _TY["term"][_TY["term"].index <= me_date]
    ch = _TY["cred"][_TY["cred"].index <= me_date]
    if len(th) < 24 or len(ch) < 24: return {}
    w = {}
    if th.iloc[-1] > th.median(): w["IEF"] = 0.5
    if ch.iloc[-1] > ch.median(): w["LQD"] = 0.5
    rest = 1 - sum(w.values())
    if rest > 0: w["BIL"] = rest
    return w

def w_paired(i):
    if i < 3: return {}
    return {"SPY": 1.0} if ret_k(i, "SPY", 3) >= ret_k(i, "TLT", 3) else {"TLT": 1.0}

def w_quint(i, filtered=True):
    U = ["SPY","QQQ","EFA","EEM","TLT"]
    if i < 3: return {}
    r = {t: ret_k(i, t, 3) for t in U}
    if filtered and any(x <= 0 for x in r.values()): return {"IEF": 1.0}
    return {max(r, key=r.get): 1.0}

def w_gold(i):
    if i < 12: return {}
    if ret_k(i, "GLD", 12) > 0 and ret_k(i, "IEF", 12) > 0: return {"GLD": 1.0}
    return {"BIL": 1.0}

STRATS = {
    "catalog-taa-keller-daa":   (lambda i, o: w_daa(i, o.get("full", 6), o.get("half", 3)), ["SPY","QQQ","IWM","VGK","EWJ","VWO","VNQ","GSG","GLD","TLT","HYG","LQD","SHY","IEF"]),
    "catalog-taa-keller-baa":   (lambda i, o: w_baa(i, o.get("topn", 6)), ["SPY","QQQ","IWM","VGK","EWJ","VWO","VEA","VNQ","DBC","GLD","TLT","HYG","LQD","TIP","BIL","IEF","BND"]),
    "catalog-taa-keller-eaa":   (lambda i, o: w_eaa(i, o.get("ws", 2.0), o.get("topn")), ["SPY","VEA","VWO","GSG","VNQ","BND","SHY","IEF"]),
    "catalog-taa-classical-aa": (lambda i, o: w_caa(i, o.get("tv", 0.10)), ["SPY","EFA","EEM","QQQ","EWJ","HYG","BIL","IEF"]),
    "catalog-taa-elm-excess-earnings-yield": (lambda i, o: w_elm(i, o.get("momentum", False)), ["SPY","TIP"]),
    "catalog-taa-faber-12m-high-switch": (lambda i, o: w_faber_high(i), ["SPY","EFA","DBC","VNQ","GLD","IEF"]),
    "catalog-taa-faber-tactical-yield": (lambda i, o: w_tactical_yield(i), ["IEF","LQD","BIL"]),
    "catalog-taa-glenn-paired-switching": (lambda i, o: w_paired(i), ["SPY","TLT"]),
    "catalog-taa-glenn-quint-switching": (lambda i, o: w_quint(i, o.get("filtered", True)), ["SPY","QQQ","EFA","EEM","TLT","IEF"]),
    "catalog-taa-gold-crossasset-momentum": (lambda i, o: w_gold(i), ["GLD","BIL"]),
}
FN, HOLDABLE = STRATS[FAMILY]
WCACHE = {}

PXV = PX.values
COL = {t: j for j, t in enumerate(PX.columns)}
REBAL_POS = set(PX.index.get_indexer(ME.index))
BIL_C = COL["BIL"]

def simulate(start, end, opts=None, house=False, placebo_seed=None, cadence=1):
    opts = opts or {}
    start = pd.Timestamp(start); end = pd.Timestamp(end)
    pos = np.where((DAYS >= start) & (DAYS <= end))[0]
    rng = np.random.default_rng(placebo_seed) if placebo_seed is not None else None
    shares = {}; cash = 100.0; curve_dates = []; curve_vals = []
    halted_until = None; halts = 0; in_halt = False
    last_rebal_key = None
    for p in pos:
        row = PXV[p]
        d = DAYS[p]
        def equity():
            return cash + sum(s * row[COL[t]] for t, s in shares.items() if not np.isnan(row[COL[t]]))
        if house and not in_halt and halts < 2 and equity() <= 85.0:
            val = equity()
            cost = COST * sum(abs(s * row[COL[t]]) for t, s in shares.items())
            cash = val - cost; shares = {}
            if cash > 0: shares = {"BIL": cash / row[BIL_C]}; cash = 0.0
            halts += 1; in_halt = True; halted_until = d + pd.Timedelta(days=90)
        if house and in_halt and halts < 2 and d >= halted_until: in_halt = False
        is_rebal = (p in REBAL_POS) or (p == pos[0])
        if is_rebal and cadence > 1:
            mk = d.year * 12 + d.month
            if last_rebal_key is not None and (mk - last_rebal_key) % cadence != 0: is_rebal = False
            else: last_rebal_key = mk
        elif is_rebal: last_rebal_key = d.year * 12 + d.month
        if is_rebal and not in_halt:
            mi = ME.index.get_indexer([ME.index[ME.index <= d][-1]])[0]
            ck = (json.dumps(opts, sort_keys=True, default=str), mi)
            if ck not in WCACHE: WCACHE[ck] = FN(mi, opts)
            w = WCACHE[ck]
            if w:
                eq = equity()
                if rng is not None:
                    inv = sum(v for t, v in w.items() if t != "BIL")
                    k = sum(1 for v in w.values() if v > 0.01)
                    pool = [t for t in HOLDABLE if t != "BIL"]
                    picks = list(rng.choice(pool, size=min(k, len(pool)), replace=False))
                    w = {t: inv / len(picks) for t in picks}
                    if inv < 0.999: w["BIL"] = 1 - inv
                target_val = {t: eq * v for t, v in w.items()}
                traded = 0.0; new_shares = {}
                for t in set(target_val) | set(shares):
                    cur = shares.get(t, 0.0) * row[COL[t]]
                    traded += abs(target_val.get(t, 0.0) - cur)
                    if target_val.get(t, 0.0) > 0: new_shares[t] = target_val[t] / row[COL[t]]
                scale = (eq - COST * traded) / eq if eq > 0 else 0
                shares = {t: s * scale for t, s in new_shares.items()}; cash = 0.0
        curve_dates.append(d); curve_vals.append(equity())
    return pd.Series(curve_vals, index=pd.DatetimeIndex(curve_dates))

def spy_road(start, end):
    days = DAYS[(DAYS >= pd.Timestamp(start)) & (DAYS <= pd.Timestamp(end))]
    s = PX["SPY"].loc[days]
    return 100.0 * s / s.iloc[0]

def stats(ec):
    if len(ec) == 0: return {}
    dd = float((ec / ec.cummax() - 1).min())
    m = ec.resample("M").last()
    mr = m.pct_change().dropna()
    streak = cur = 0
    for x in mr:
        cur = cur + 1 if x < 0 else 0; streak = max(streak, cur)
    last_high = 0; maxgap = 0
    cm = m.cummax()
    for j in range(len(m)):
        if m.iloc[j] >= cm.iloc[j] - 1e-12: last_high = j
        maxgap = max(maxgap, j - last_high)
    return {"final": round(float(ec.iloc[-1]), 2), "max_dd_pct": round(100 * dd, 1),
            "months": int(len(mr)), "share_pos": round(float((mr > 0).mean()), 3) if len(mr) else None,
            "median_month_pct": round(100 * float(mr.median()), 2) if len(mr) else None,
            "avg_month_pct": round(100 * float(mr.mean()), 2) if len(mr) else None,
            "best_month_pct": round(100 * float(mr.max()), 2) if len(mr) else None,
            "worst_month_pct": round(100 * float(mr.min()), 2) if len(mr) else None,
            "longest_losing_streak_months": int(streak), "longest_below_high_months": int(maxgap)}

def run_cell(start, end, **kw):
    ec = simulate(start, end, **kw)
    return ec, stats(ec)

def placebo_beaten(final, start, end, **kw):
    beaten = 0
    for seed in range(20):
        ec = simulate(start, end, placebo_seed=seed, **kw)
        if final > float(ec.iloc[-1]): beaten += 1
    return beaten

def main():
    out = {"family": FAMILY, "roads": {}, "grid": [], "variants": {}}
    end = "2026-11-20"
    flavors = {"native": {}}
    if FAMILY == "catalog-taa-keller-baa": flavors = {"balanced": {"topn": 6}, "aggressive": {"topn": 1}}
    if FAMILY == "catalog-taa-keller-eaa": flavors = {"offensive": {"ws": 2.0}, "defensive": {"ws": 1.0}}
    if FAMILY == "catalog-taa-classical-aa": flavors = {"offensive": {"tv": 0.10}, "defensive": {"tv": 0.05}}
    if FAMILY == "catalog-taa-elm-excess-earnings-yield": flavors = {"valuation_only": {"momentum": False}, "with_momentum": {"momentum": True}}
    headline = list(flavors.keys())[0]
    for fl, opts in flavors.items():
        out["variants"][fl] = {}
        for road, st in ROADS.items():
            ec, s = run_cell(st, end, opts=opts)
            ech, sh = run_cell(st, end, opts=opts, house=True)
            spy = spy_road(st, end)
            pb = placebo_beaten(float(ec.iloc[-1]), st, end, opts=opts)
            out["variants"][fl][road] = {"native": s, "house_final": sh["final"],
                                         "house_max_dd_pct": sh["max_dd_pct"],
                                         "spy_final": round(float(spy.iloc[-1]), 2),
                                         "placebos_beaten": pb}
            if fl == headline:
                out["roads"][road] = out["variants"][fl][road]
                if road == "LONG":
                    out["native_long_curve"] = {str(d.date()): round(float(v), 4) for d, v in ec.items()}
    hopts = flavors[headline]
    grid_cells = []
    for cad in (3, 6, 12):
        for rb, h in (("native", False), ("house", True)):
            ec, s = run_cell(ROADS["LONG"], end, opts=hopts, cadence=cad, house=h)
            pb = placebo_beaten(float(ec.iloc[-1]), ROADS["LONG"], end, opts=hopts, cadence=cad) if not h else None
            grid_cells.append({"cell": f"cadence={cad}m|{rb}", "final_LONG": s["final"], "max_dd_pct": s["max_dd_pct"], "placebos_beaten_LONG": pb})
    counts = None
    if FAMILY == "catalog-taa-keller-daa": counts = [(f"full={n}", {"full": n, "half": max(1, n // 2)}) for n in (1, 2, 3, 5, 8, 10, 12)]
    if FAMILY == "catalog-taa-keller-baa": counts = [(f"topn={n}", {"topn": n}) for n in (2, 3, 5, 8, 10, 12)]
    if FAMILY == "catalog-taa-keller-eaa": counts = [(f"topn={n}", {"ws": 2.0, "topn": n}) for n in (1, 2, 3, 5, 7)]
    if FAMILY == "catalog-taa-glenn-quint-switching": counts = [("unfiltered-QS", {"filtered": False})]
    if counts:
        for name, o in counts:
            if o == hopts: continue
            ec, s = run_cell(ROADS["LONG"], end, opts=o)
            pb = placebo_beaten(float(ec.iloc[-1]), ROADS["LONG"], end, opts=o)
            grid_cells.append({"cell": f"holdings:{name}|monthly|native", "final_LONG": s["final"], "max_dd_pct": s["max_dd_pct"], "placebos_beaten_LONG": pb})
    out["grid"] = grid_cells
    def fold_run(**kw):
        r = {}
        for nm, (a, b) in {"fold_2010_2018": ("2010-01-01", "2018-12-31"), "fold_2019_2026": ("2019-01-01", "2026-11-20")}.items():
            ec, s = run_cell(a, b, **kw)
            spy = spy_road(a, b)
            r[nm] = {"final": s["final"], "spy_final": round(float(spy.iloc[-1]), 2)}
        return r
    out["folds"] = {"native": fold_run(opts=hopts)}
    with open(os.path.join(FOLDER, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(FAMILY, "done", {r: out["roads"][r]["native"]["final"] for r in ROADS})

if __name__ == "__main__":
    main()
