#!/usr/bin/env python3
"""Slice-8 runner: builds panels, runs roads + second-chance grid + placebos
per family, writes results.json into each family folder."""
import json, math, os, sys
sys.path.insert(0, os.path.expanduser("~/workspace/slice8-scratch"))
import engine
from engine import (Panel, load_t2, load_sector, load_etf_json, load_fred,
                    cadence_days, simulate, period_stats, ROADS, ROADS_2016,
                    SPY_REF, CHAMP)
import numpy as np

BASE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions")
FREDDIR = os.path.expanduser("~/workspace/slice8-scratch")

# ---------------- panels ----------------
def etf_panel():
    p = Panel(load_t2("SPY"))
    for s in ["SPY", "QQQ", "IWM", "IEFA", "EEM", "VNQ", "DBC", "GLD", "TLT", "AGG", "SHY"]:
        if s != "SPY": p.add(s, load_t2(s))
    p.series["SPY"] = p.series.get("SPY") or None
    # master loader already set SPY? Panel stores only added; add SPY raw:
    ds, cs = load_t2("SPY"); p.series["SPY"] = cs[:]
    p.add("IEF", load_etf_json("IEF"))
    return p

def sector_panel(extra_fred=None):
    p = Panel(load_sector("SPY"))
    ds, cs = load_sector("SPY"); p.series["SPY"] = cs[:]
    for s in ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]:
        p.add(s, load_sector(s))
    if extra_fred:
        for name, fn in extra_fred:
            p.add(name, load_fred(os.path.join(FREDDIR, fn)))
    return p

def trendyc_panel():
    p = sector_panel()
    for name, fn in [("DGS10", "DGS10.csv"), ("DGS3MO", "DGS3MO.csv"),
                     ("INDPRO", "INDPRO.csv"), ("HOUST", "HOUST.csv"),
                     ("RRSFS", "RRSFS.csv")]:
        p.add(name, load_fred(os.path.join(FREDDIR, fn)))
    return p

# ---------------- strategy factories ----------------
def aca_factory(p):
    sleeves = [("SPY", 126, 252), ("VNQ", 126, 252), ("GLD", 252, 126)]
    state = {s: True for s, _, _ in sleeves}
    def fn(i):
        w = {}
        for sym, up, dn in sleeves:
            c = p.close(sym, i)
            if c is None: continue
            if state[sym]:
                wdw = [p.close(sym, j) for j in range(max(0, i - dn), i)]
                wdw = [x for x in wdw if x is not None]
                if wdw and c < min(wdw): state[sym] = False
            else:
                wdw = [p.close(sym, j) for j in range(max(0, i - up), i)]
                wdw = [x for x in wdw if x is not None]
                if wdw and c > max(wdw): state[sym] = True
            tgt = sym if state[sym] else "IEF"
            w[tgt] = w.get(tgt, 0.0) + 1 / 3
        return w
    return fn

def trendyc_factory(p):
    state = {"long": False}
    def rachev(i):
        if i - 200 < 0: return None
        closes = p.series["SPY"][i - 200:i + 1]
        if any(v is None for v in closes): return None
        rets = [closes[k + 1] / closes[k] - 1 for k in range(200)]
        med = sorted(rets)[100]
        above = [r for r in rets if r > med]; below = [r for r in rets if r < med]
        if not above or not below: return None
        ab = sum(above) / len(above); be = sum(below) / len(below)
        if be == 0: return None
        return ab / be * -1
    def fn(i):
        lag = i - 21
        macro = True
        for s in ["RRSFS", "INDPRO", "HOUST"]:
            r = p.ret(s, lag, 252) if lag >= 0 else None
            if r is None or r <= 0: macro = False
        if macro and state["long"]:
            return {"SPY": 1.0}
        sma = p.sma("SPY", i, 200); c = p.close("SPY", i)
        rv = rachev(i)
        y10 = p.close("DGS10", i); y3 = p.close("DGS3MO", i)
        ok = (sma is not None and c is not None and c > sma and rv is not None
              and rv > 1 and y10 is not None and y3 is not None and y10 > y3)
        state["long"] = bool(ok)
        return {"SPY": 1.0} if ok else {}
    return fn

def xtsmom_factory(p):
    def fn(i):
        rs = p.ret("SPY", i, 252); ri = p.ret("IEF", i, 252)
        if rs is None or ri is None: return {}
        w = {}
        w["SPY" if (rs > 0 and ri > 0) else "SHY"] = 0.5
        s2 = "IEF" if (ri > 0 and rs < 0) else "SHY"
        w[s2] = w.get(s2, 0.0) + 0.5
        return w
    return fn

POS = ["XLE", "XLF", "XLI", "XLB"]; NEG = ["XLP", "XLV", "XLU"]
REGIME_MAP = {("u", "u"): "XLE", ("u", "d"): "XLK", ("d", "u"): "XLP", ("d", "d"): "XLU"}
def siei_ratio(p, i):
    pos = [p.close(s, i) for s in POS]; neg = [p.close(s, i) for s in NEG]
    if any(v is None for v in pos + neg): return None
    return (sum(pos) / len(pos)) / (sum(neg) / len(neg))
def growth_up(p, i):
    sma = p.sma("SPY", i, 200); c = p.close("SPY", i)
    return sma is not None and c is not None and c > sma
def gi_factory(p):
    def fn(i):
        r = siei_ratio(p, i)
        if r is None: return {}
        # SMA200 of ratio
        vals = [siei_ratio(p, j) for j in range(i - 199, i + 1)]
        if any(v is None for v in vals): return {}
        infl_up = r > sum(vals) / 200
        g = "u" if growth_up(p, i) else "d"
        return {REGIME_MAP[(g, "u" if infl_up else "d")]: 1.0}
    return fn

def compass_factory(p):
    def fn(i):
        t = p.close("T5YIE", i); t60 = p.close("T5YIE", i - 60) if i >= 60 else None
        r = siei_ratio(p, i); r60 = siei_ratio(p, i - 60) if i >= 60 else None
        if t is None or t60 is None or r is None or r60 is None: return {}
        infl_up = t > 2.0 and (t > t60 or r > r60)
        g = "u" if growth_up(p, i) else "d"
        return {REGIME_MAP[(g, "u" if infl_up else "d")]: 1.0}
    return fn

_corr_cache = {}
def corr_matrix(p, i, syms, n=126):
    key = (p.dates[i].year, p.dates[i].month, tuple(syms))
    if key in _corr_cache: return _corr_cache[key]
    if i - n < 0: return None
    arr = []
    for s in syms:
        w = p.series[s][i - n:i + 1]
        if any(v is None for v in w): return None
        arr.append([w[k + 1] / w[k] - 1 for k in range(n)])
    m = np.corrcoef(np.array(arr))
    _corr_cache[key] = m
    return m

def mincorr_factory(p, count=None):
    U = ["SPY", "IWM", "QQQ", "VNQ", "TLT", "EEM", "IEFA", "GLD"]
    def fn(i):
        m = corr_matrix(p, i, U)
        if m is None: return {}
        if count is None:
            pen = []
            for a in range(len(U)):
                vals = [(m[a][b] + 1) / 2 for b in range(len(U)) if b != a]
                pen.append(sum(vals) / len(vals))
            raw = [1.0 / max(x, 0.05) for x in pen]
            tot = sum(raw)
            return {U[a]: raw[a] / tot for a in range(len(U))}
        # stepwise top-K equal weight
        seed = max(U, key=lambda s: (p.ret(s, i, 126) if p.ret(s, i, 126) is not None else -9))
        sel = [seed]
        while len(sel) < min(count, len(U)):
            best, bestv = None, 9
            for s in U:
                if s in sel: continue
                v = sum(m[U.index(s)][U.index(x)] for x in sel) / len(sel)
                if v < bestv: bestv, best = v, s
            sel.append(best)
        return {s: 1.0 / len(sel) for s in sel}
    return fn

def pctchan_factory(p):
    U = ["SPY", "VNQ", "DBC", "AGG"]; LBS = [60, 120, 180, 252]
    state = {s: {L: 0 for L in LBS} for s in U}
    last = {"i": -1}
    def update(i):
        for j in range(last["i"] + 1, i + 1):
            for s in U:
                c = p.close(s, j)
                if c is None: continue
                for L in LBS:
                    if j - L + 1 < 0: continue
                    w = [p.close(s, k) for k in range(j - L + 1, j + 1)]
                    if any(v is None for v in w): continue
                    hi = float(np.quantile(w, 0.75)); lo = float(np.quantile(w, 0.25))
                    if c > hi: state[s][L] = 1
                    elif c < lo: state[s][L] = -1
        last["i"] = i
    def fn(i):
        update(i)
        w = {}
        for s in U:
            comp = sum(state[s].values()) / 4
            if comp >= 0.5:
                v = p.vol(s, i, 20)
                if v and v > 0: w[s] = comp / v
        tot = sum(w.values())
        if tot <= 0: return {"SHY": 1.0}
        w = {s: v / tot for s, v in w.items()}
        return w
    return fn

def virag_factory(p, count=4):
    U = ["SPY", "QQQ", "IWM", "IEFA", "EEM", "VNQ", "DBC", "GLD", "AGG", "TLT"]
    def fn(i):
        scored = [(p.ret(s, i, 252), s) for s in U]
        if any(r is None for r, _ in scored): return {}
        scored.sort(reverse=True)
        w = {}
        for r, s in scored[:count]:
            tgt = s if r > 0 else "SHY"
            w[tgt] = w.get(tgt, 0.0) + 1.0 / count
        return w
    return fn

def vitral_factory(p, count=5):
    U = ["SPY", "QQQ", "IWM", "IEFA", "EEM", "VNQ", "DBC", "GLD", "TLT", "AGG"]
    def score(i):
        m = corr_matrix(p, i, U)
        if m is None: return None
        sig = {s: [] for s in U}
        for s in U:
            for n in (63, 126, 252):
                r = p.ret(s, i, n)
                if r is None: return None
                sig[s].append(r)
                v = p.vol(s, i, n)
                sig[s].append(r / (v * math.sqrt(n)) if v else 0.0)
            for n in (50, 100, 200):
                sma = p.sma(s, i, n); c = p.close(s, i)
                if sma is None: return None
                sig[s].append(1.0 if c > sma else 0.0)
        # percentile ranks per signal
        ranks = {s: [] for s in U}
        for k in range(9):
            vals = sorted((sig[s][k], s) for s in U)
            for pos, (_, s) in enumerate(vals):
                ranks[s].append(pos / (len(U) - 1))
        out = {}
        for a, s in enumerate(U):
            avgc = sum(m[a][b] for b in range(len(U)) if b != a) / (len(U) - 1)
            out[s] = (sum(ranks[s]) / 9) / (1 + max(avgc, 0))
        return out
    def fn(i):
        sc = score(i)
        if sc is None: return {}
        top = sorted(sc, key=sc.get, reverse=True)[:count]
        w = {}
        for s in top:
            if p.ret(s, i, 252) is not None and p.ret(s, i, 252) < 0:
                ro = max(["IEF", "SHY"], key=lambda x: (p.ret(x, i, 63) or -9))
                if (p.ret(ro, i, 63) or -9) < 0: ro = "SHY"
                w[ro] = w.get(ro, 0.0) + 1.0 / count
            else:
                w[s] = w.get(s, 0.0) + 1.0 / count
        return w
    return fn

FAMILIES = {
 "catalog-taa-stoken-aca": dict(panel="etf", factory=aca_factory, native="daily",
    tempo="monthly", pool=(["SPY", "VNQ", "GLD", "IEF"], 3),
    cadences=["daily", "weekly", "monthly", "quarterly"], counts=None, roads="2016"),
 "catalog-taa-trendyieldcurve-macro": dict(panel="trendyc", factory=trendyc_factory,
    native="monthly", tempo="monthly", pool=("SWITCH", "SPY"),
    cadences=["monthly", "quarterly", "semiannual", "annual"], counts=None, roads="2010"),
 "catalog-taa-us-crossasset-momentum": dict(panel="etf", factory=xtsmom_factory,
    native="monthly", tempo="monthly", pool=(["SPY", "IEF", "SHY"], 2),
    cadences=["weekly", "monthly", "quarterly", "semiannual", "annual"], counts=None, roads="2016"),
 "catalog-taa-varadi-growth-inflation": dict(panel="sector", factory=gi_factory,
    native="daily", tempo="monthly", pool=("SWITCH", None),
    cadences=["daily", "weekly", "monthly", "quarterly"], counts=None, roads="2010"),
 "catalog-taa-varadi-inflation-compass": dict(panel="compass", factory=compass_factory,
    native="monthly", tempo="monthly", pool=("SWITCH", None),
    cadences=["weekly", "monthly", "quarterly", "semiannual", "annual"], counts=None, roads="2010"),
 "catalog-taa-varadi-mincorr": dict(panel="etf", factory=mincorr_factory,
    native="monthly", tempo="monthly", pool=(["SPY", "IWM", "QQQ", "VNQ", "TLT", "EEM", "IEFA", "GLD"], 8),
    cadences=["weekly", "monthly", "quarterly", "semiannual", "annual"],
    counts=[1, 2, 3, 5, 8], roads="2016"),
 "catalog-taa-varadi-percentile-channels": dict(panel="etf", factory=pctchan_factory,
    native="monthly", tempo="monthly", pool=(["SPY", "VNQ", "DBC", "AGG", "SHY"], 3),
    cadences=["weekly", "monthly", "quarterly", "semiannual", "annual"], counts=None, roads="2016"),
 "catalog-taa-virag-momentum-balancing": dict(panel="etf", factory=virag_factory,
    native="monthly", tempo="monthly", pool=(["SPY", "QQQ", "IWM", "IEFA", "EEM", "VNQ", "DBC", "GLD", "AGG", "TLT"], 4),
    cadences=["weekly", "monthly", "quarterly", "semiannual", "annual"],
    counts=[1, 2, 3, 5, 8, 10], roads="2016"),
 "catalog-taa-vitral-multiasset-momentum": dict(panel="etf", factory=vitral_factory,
    native="monthly", tempo="monthly", pool=(["SPY", "QQQ", "IWM", "IEFA", "EEM", "VNQ", "DBC", "GLD", "TLT", "AGG"], 5),
    cadences=["weekly", "monthly", "quarterly", "semiannual", "annual"],
    counts=[1, 2, 3, 5, 8, 10], roads="2016"),
}
# switch-pool families: placebo picks random held asset from regime map
SWITCH_ASSETS = {"catalog-taa-varadi-growth-inflation": ["XLK", "XLE", "XLP", "XLU"],
                 "catalog-taa-varadi-inflation-compass": ["XLK", "XLE", "XLP", "XLU"]}

def run_family(slug, cfg):
    if cfg["panel"] == "etf": p = etf_panel()
    elif cfg["panel"] == "sector": p = sector_panel()
    elif cfg["panel"] == "compass": p = sector_panel(extra_fred=[("T5YIE", "t5yie.csv")])
    else: p = trendyc_panel()
    roads = ROADS_2016 if cfg["roads"] == "2016" else ROADS
    ridx = engine.road_indices(p, roads)
    out = {"family": slug, "roads": {}, "grid": {}, "native_cadence": cfg["native"]}
    dec_cache = {}
    def decisions(cad):
        if cad not in dec_cache: dec_cache[cad] = cadence_days(p.dates, cad)
        return dec_cache[cad]
    # main roads at native cadence, both rulebooks + placebos (house)
    for rname, idx in ridx.items():
        dec = decisions(cfg["native"])
        for rb in ("native", "house"):
            fn = cfg["factory"](p)
            r = simulate(p, idx, dec, fn, rulebook=rb)
            out["roads"][f"{rname}|{rb}"] = {k: r[k] for k in ("final", "max_dd_pct", "costs", "orders", "halts")}
            if rname in ("DECADE", "LONG"):
                out.setdefault("curves", {})[f"{rname}|{rb}"] = r["curve"]
                out.setdefault("period_stats", {})[f"{rname}|{rb}"] = period_stats(r["curve"], p.dates, cfg["tempo"])
        # placebos house
        engine._placebo_pool = cfg["pool"] if cfg["pool"][0] != "SWITCH" or cfg["pool"][1] else (SWITCH_ASSETS[slug], 1)
        if slug in SWITCH_ASSETS and cfg["pool"][0] == "SWITCH":
            engine._placebo_pool = (SWITCH_ASSETS[slug], 1)
        twins = []
        for seed in range(1, 21):
            fn = cfg["factory"](p)
            t = simulate(p, idx, dec, fn, rulebook="house", placebo_seed=seed)
            twins.append(t["final"])
        real = out["roads"][f"{rname}|house"]["final"]
        out["roads"][f"{rname}|house"]["placebo_finals"] = twins
        out["roads"][f"{rname}|house"]["placebos_beaten"] = sum(1 for t in twins if real > t)
    # grid: cadence cells on DECADE (house), counts at native cadence on DECADE
    didx = ridx["DECADE"]
    for cad in cfg["cadences"]:
        fn = cfg["factory"](p)
        r = simulate(p, didx, decisions(cad), fn, rulebook="house")
        engine._placebo_pool = (SWITCH_ASSETS[slug], 1) if slug in SWITCH_ASSETS else cfg["pool"]
        twins = []
        for seed in range(1, 21):
            fn2 = cfg["factory"](p)
            twins.append(simulate(p, didx, decisions(cad), fn2, rulebook="house", placebo_seed=seed)["final"])
        out["grid"][f"cadence={cad}"] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"],
            "placebos_beaten": sum(1 for t in twins if r["final"] > t), "placebo_finals": twins}
    if cfg["counts"]:
        for k in cfg["counts"]:
            if slug.endswith("mincorr"):
                fn = mincorr_factory(p, count=k)
            elif slug.endswith("momentum-balancing"):
                fn = virag_factory(p, count=k)
            else:
                fn = vitral_factory(p, count=k)
            r = simulate(p, didx, decisions(cfg["native"]), fn, rulebook="house")
            out["grid"][f"count={k}"] = {"final": r["final"], "max_dd_pct": r["max_dd_pct"]}
    out["crypto"] = "NOT-APPLICABLE — cross-asset allocation among stock/bond/commodity ETFs has no point-in-time coin analogue in the program pond; crypto momentum cross-runs live in the existing crypto-x-momentum family."
    folder = os.path.join(BASE, slug)
    os.makedirs(os.path.join(folder, "grid"), exist_ok=True)
    with open(os.path.join(folder, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    with open(os.path.join(folder, "grid", "grid.json"), "w") as fh:
        json.dump(out["grid"], fh, indent=1)
    print(slug, {k: v["final"] for k, v in out["roads"].items()})
    return out

if __name__ == "__main__":
    only = sys.argv[1:] or list(FAMILIES)
    for slug in only:
        _corr_cache.clear()
        run_family(slug, FAMILIES[slug])
