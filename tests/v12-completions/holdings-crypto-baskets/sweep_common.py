"""Shared period-distribution computation (Terry's reporting standard)."""
import math
from datetime import datetime

def period_stats(curve, freq="monthly"):
    """curve: [[date, equity], ...] daily. Period = calendar month.
    Returns count, % profitable, median, best, worst, longest losing run,
    longest stretch between new highs (in periods and in days), average (secondary)."""
    # month-end equity (last observation in each month)
    months = {}
    for d, e in curve:
        months[d[:7]] = (d, e)
    keys = sorted(months)
    rets = []
    prev = 100.0
    # first month: from pot start (curve starts at window start; use first
    # curve value's month baseline = 100 pot convention of these engines)
    for k in keys:
        d, e = months[k]
        if prev and prev > 0:
            rets.append(e / prev - 1.0)
        prev = e
    if not rets:
        return None
    s = sorted(rets)
    n = len(s)
    med = s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])
    # longest losing run
    run = mx = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        mx = max(mx, run)
    # longest stretch between new highs (days, from daily curve)
    peak, peak_d, worst_days = -1.0, None, 0
    for d, e in curve:
        if e > peak:
            if peak_d is not None:
                dd = (datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(peak_d, "%Y-%m-%d")).days
                worst_days = max(worst_days, dd)
            peak, peak_d = e, d
    if peak_d is not None and curve:
        dd = (datetime.strptime(curve[-1][0], "%Y-%m-%d") - datetime.strptime(peak_d, "%Y-%m-%d")).days
        worst_days = max(worst_days, dd)
    return {
        "periods": len(rets),
        "pct_profitable": round(100.0 * sum(1 for r in rets if r > 0) / len(rets), 1),
        "median_pct": round(med * 100, 2),
        "best_pct": round(max(rets) * 100, 2),
        "worst_pct": round(min(rets) * 100, 2),
        "longest_losing_run": mx,
        "longest_between_highs_days": worst_days,
        "average_pct_secondary": round(100.0 * sum(rets) / len(rets), 2),
    }

def pct(vals, q):
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    p = q * (len(s) - 1)
    lo, hi = int(math.floor(p)), int(math.ceil(p))
    return s[lo] if lo == hi else s[lo] * (1 - (p - lo)) + s[hi] * (p - lo)
