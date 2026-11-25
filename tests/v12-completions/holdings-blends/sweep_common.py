"""Shared helpers for the holdings-blends count sweep (quarterly tempo
period distributions per Terry's reporting standard, diagnostics)."""
from datetime import date as _date


def max_dd(curve):
    peak, mdd = -1.0, 0.0
    for d, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return round(mdd * 100, 2)


def period_distribution(curve):
    """Quarterly period record from a daily equity curve: per-calendar-
    quarter returns (last close in quarter vs previous quarter end)."""
    qtrs = {}
    for d, v in curve:
        qtrs[(d[:4], d[5:7])] = v
    keys = sorted(qtrs)
    rets = []
    prev = curve[0][1]
    for k in keys:
        v = qtrs[k]
        rets.append(v / prev - 1.0)
        prev = v
    if not rets:
        return None
    srt = sorted(rets)
    m = len(srt)
    median = srt[m // 2] if m % 2 else 0.5 * (srt[m // 2 - 1] + srt[m // 2])
    longest_loss = run = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        longest_loss = max(longest_loss, run)
    peak, last_high_d, longest_gap = -1.0, None, 0
    for d, v in curve:
        if v >= peak:
            if last_high_d is not None:
                gap = (_date.fromisoformat(d)
                       - _date.fromisoformat(last_high_d)).days
                longest_gap = max(longest_gap, gap)
            peak, last_high_d = v, d
    tail = (_date.fromisoformat(curve[-1][0])
            - _date.fromisoformat(last_high_d)).days if last_high_d else 0
    longest_gap = max(longest_gap, tail)
    return {"periods": len(rets),
            "pct_periods_profitable": round(
                100.0 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "median_period_pct": round(median * 100, 2),
            "best_period_pct": round(max(rets) * 100, 2),
            "worst_period_pct": round(min(rets) * 100, 2),
            "avg_period_pct_secondary": round(
                sum(rets) / len(rets) * 100, 2),
            "longest_losing_run_periods": longest_loss,
            "longest_stretch_between_new_highs_days": longest_gap}
