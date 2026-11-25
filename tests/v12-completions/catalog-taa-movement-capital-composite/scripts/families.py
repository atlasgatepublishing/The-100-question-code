#!/usr/bin/env python3
"""Slice-7 family signal functions. Each target_fn(date, rng) -> {ticker: weight}."""
import sys, os, random
sys.path.insert(0, "/tmp/slice7")
import pandas as pd
from engine import (ret_td, ret_months, sma_td, price_at, aligned, month_ends,
                    real_retail, real_pce, macro_monthly, icsa_monthly, yield_curve, vs_ma12, lagged)

# ---------- Muscular Mama Bear (author's site form) ----------
MAMA_U = ["VONE", "VIOO", "VEA", "VWO", "VNQ", "PDBC", "IAU", "VGLT", "SHV"]
def mama_scores(date):
    out = {}
    for t in MAMA_U:
        r = ret_td(t, date, 105)
        if r is not None: out[t] = r
    return out
def make_topn(scores_fn, n):
    def fn(date, rng=None):
        s = scores_fn(date)
        if not s: return {}
        top = sorted(s, key=s.get, reverse=True)[:n]
        return {t: 1.0 / len(top) for t in top}
    return fn
def make_topn_placebo(scores_fn, n):
    def fn(date, rng=None):
        s = scores_fn(date)
        if not s: return {}
        picks = rng.sample(sorted(s), min(n, len(s)))
        return {t: 1.0 / len(picks) for t in picks}
    return fn
mama = make_topn(mama_scores, 3)
mama_placebo = make_topn_placebo(mama_scores, 3)

# ---------- Muscular Papa Bear (author's site form) ----------
PAPA_U = ["VTV", "VUG", "VIOV", "VIOG", "VEA", "VWO", "VNQ", "PDBC", "IAU", "EDV", "VGIT", "VCLT", "BNDX"]
def papa_scores(date):
    out = {}
    for t in PAPA_U:
        rs = [ret_td(t, date, d) for d in (63, 126, 252)]
        if all(r is not None for r in rs): out[t] = sum(rs) / 3.0
    return out
papa = make_topn(papa_scores, 3)
papa_placebo = make_topn_placebo(papa_scores, 3)

# ---------- Novell Tactical Bond (AllocateSmartly published form) ----------
TB_U = ["SHY", "IEF", "TLT", "TIP", "LQD", "HYG", "BNDX", "EMB"]
def tb_scores(date):
    out = {}
    for t in TB_U:
        r = ret_months(t, date, 6)
        if r is not None: out[t] = r
    return out
def tacbond(date, rng=None):
    s = tb_scores(date); bil = ret_months("BIL", date, 6)
    if not s or bil is None: return {}
    top = sorted(s, key=s.get, reverse=True)[:3]
    w = {}
    for t in top:
        if s[t] > 0 and s[t] > bil: w[t] = 1.0 / 3.0
    return w
def tacbond_placebo(date, rng=None):
    s = tb_scores(date); bil = ret_months("BIL", date, 6)
    if not s or bil is None: return {}
    picks = rng.sample(sorted(s), min(3, len(s)))
    w = {}
    for t in picks:
        if s[t] > 0 and s[t] > bil: w[t] = 1.0 / 3.0
    return w

# ---------- macro helpers ----------
def gtt_flags(date):
    """Growth-Trend-Timing style flags (CONSTRUCTED trend convention):
    level series below its 12m MA = recession signal; UNRATE above = signal.
    Data lagged 1 month (AllocateSmartly econ-data convention)."""
    flags = {}
    v, m = vs_ma12(real_retail(), date, 1); flags["retail"] = (v is not None and m is not None and v < m)
    v, m = vs_ma12(macro_monthly("INDPRO"), date, 1); flags["indpro"] = (v is not None and m is not None and v < m)
    v, m = vs_ma12(macro_monthly("UNRATE"), date, 1); flags["unrate"] = (v is not None and m is not None and v > m)
    return flags

def comp_triggered(date):
    """Novell COMP construction: any 1 of 6 indicators signaling -> triggered."""
    f = gtt_flags(date)
    v, m = vs_ma12(icsa_monthly(), date, 1); f["claims"] = (v is not None and m is not None and v > m)
    v, m = vs_ma12(real_pce(), date, 1); f["pce"] = (v is not None and m is not None and v < m)
    yc = lagged(yield_curve(), date, 1); f["yieldcurve"] = (yc is not None and yc < 0)
    return any(f.values()), f

# ---------- Movement Capital Composite (AllocateSmartly published form) ----------
def movement(date, rng=None):
    w = {}
    # Trend sleeve (25%)
    def mom(t):
        rs = [ret_months(t, date, k) for k in (3, 6, 9, 12, 15)]
        return None if any(r is None for r in rs) else sum(rs) / len(rs)
    ms, me, mshv = mom("SPY"), mom("EFA"), mom("SHV")
    if ms is not None and me is not None and mshv is not None:
        winner = "SPY" if ms >= me else "EFA"
        pick = winner if max(ms, me) > mshv else "IEF"
        w[pick] = w.get(pick, 0.0) + 0.25
    # Macro sleeve (25%)
    f = gtt_flags(date)
    if sum(f.values()) >= 2: w["IEF"] = w.get("IEF", 0.0) + 0.25
    else:
        w["SPY"] = w.get("SPY", 0.0) + 0.125; w["EFA"] = w.get("EFA", 0.0) + 0.125
    # Passive sleeves (50%)
    w["SPY"] = w.get("SPY", 0.0) + 0.125; w["EFA"] = w.get("EFA", 0.0) + 0.125
    w["IEF"] = w.get("IEF", 0.0) + 0.125; w["TIP"] = w.get("TIP", 0.0) + 0.125
    return w

# ---------- Novell SPY-COMP (CONSTRUCTED from published skeleton) ----------
def spycomp(date, rng=None):
    trig, _ = comp_triggered(date)
    if not trig: return {"SPY": 1.0}
    p = price_at("SPY", date); s = sma_td("SPY", date, 200)
    if p is None or s is None: return {"SPY": 1.0}
    return {"SPY": 1.0} if p > s else {"IEF": 1.0}

# ---------- Novell Bond-COMP (CONSTRUCTED) ----------
CREDIT = ["LQD", "HYG", "EMB"]; DEFENSIVE = ["IEF", "GLD"]
def _ew(tickers, date):
    elig = [t for t in tickers if price_at(t, date) is not None]
    return {t: 1.0 / len(elig) for t in elig} if elig else {}
def bondcomp(date, rng=None):
    trig, _ = comp_triggered(date)
    if not trig: return _ew(CREDIT, date)
    rs = [ret_months(t, date, 6) for t in CREDIT]
    bil = ret_months("BIL", date, 6)
    if all(r is not None for r in rs) and bil is not None and sum(rs) / len(rs) > bil:
        return _ew(CREDIT, date)
    return _ew(DEFENSIVE, date)

# ---------- Novell Bond UI1 (CONSTRUCTED) ----------
def bondui1(date, rng=None):
    v, m = vs_ma12(macro_monthly("UNRATE"), date, 1)
    if v is not None and m is not None and v > m: return _ew(DEFENSIVE, date)
    return _ew(CREDIT, date)

# ---------- shuffled-decision placebo (timing placebo for switch/composite forms) ----------
def shuffled_placebo(native_fn):
    cache = {}
    def build(rng):
        mes = month_ends("2009-01-01", "2026-11-20")
        dec = {d: native_fn(d, None) for d in mes}
        vals = list(dec.values()); rng.shuffle(vals)
        cache["map"] = dict(zip(dec.keys(), vals))
    def fn(date, rng=None):
        if "map" not in cache: build(rng or random.Random(0))
        return cache["map"].get(date, {})
    fn._reset = lambda: cache.clear()
    return fn

def make_shuffled(native_fn):
    """Returns a placebo factory: each call gives a fresh shuffled placebo fn."""
    mes = month_ends("2009-01-01", "2026-11-20")
    dec = {d: native_fn(d, None) for d in mes}
    keys = list(dec.keys()); vals = list(dec.values())
    def factory(rng):
        v = vals[:]; rng.shuffle(v)
        m = dict(zip(keys, v))
        return lambda date, rng=None: m.get(date, {})
    return factory
