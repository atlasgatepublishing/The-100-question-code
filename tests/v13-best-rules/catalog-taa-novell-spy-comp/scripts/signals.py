#!/usr/bin/env python3
"""Signal functions for v13 Novell SPY-COMP best-rules run.

Indicator construction copied verbatim from the v12 folder's families.py
(read-only shared input): same six indicators, same growth-trend triggers,
same 1-month lag. The ONLY design change (frozen in BEST-RULES-SPEC.md):
the composite arms at >=3 of 6 signaling (majority) instead of any-1.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pandas as pd
from engine import (sma_td, price_at, real_retail, real_pce, macro_monthly,
                    icsa_monthly, yield_curve, vs_ma12, lagged)


def comp_flags(date):
    """The six constructed indicator flags, exactly as v12."""
    f = {}
    v, m = vs_ma12(real_retail(), date, 1); f["retail"] = bool(v is not None and m is not None and v < m)
    v, m = vs_ma12(macro_monthly("INDPRO"), date, 1); f["indpro"] = bool(v is not None and m is not None and v < m)
    v, m = vs_ma12(macro_monthly("UNRATE"), date, 1); f["unrate"] = bool(v is not None and m is not None and v > m)
    v, m = vs_ma12(icsa_monthly(), date, 1); f["claims"] = bool(v is not None and m is not None and v > m)
    v, m = vs_ma12(real_pce(), date, 1); f["pce"] = bool(v is not None and m is not None and v < m)
    yc = lagged(yield_curve(), date, 1); f["yieldcurve"] = bool(yc is not None and yc < 0)
    return f


def _trend_leg(date):
    p = price_at("SPY", date); s = sma_td("SPY", date, 200)
    if p is None or s is None: return {"SPY": 1.0}
    return {"SPY": 1.0} if p > s else {"IEF": 1.0}


def spycomp_v12(date, rng=None):
    """v12 constructed form: ANY 1 of 6 arms the trend test."""
    f = comp_flags(date)
    if not any(f.values()): return {"SPY": 1.0}
    return _trend_leg(date)


def spycomp_v13(date, rng=None):
    """MY RULES: >=3 of 6 (majority of the committee) arms the trend test."""
    f = comp_flags(date)
    if sum(f.values()) < 3: return {"SPY": 1.0}
    return _trend_leg(date)


def static_mix(date, rng=None):
    """Control: static 75% SPY / 25% IEF, rebalanced monthly (spec)."""
    return {"SPY": 0.75, "IEF": 0.25}


def spy_hold(date, rng=None):
    return {"SPY": 1.0}
