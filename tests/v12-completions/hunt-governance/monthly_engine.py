#!/usr/bin/env python3
"""Monthly long-only EW basket runner on the W04 broad stack.
pick_fn(ym) -> list of ciks to hold during month ym (the return from
end of ym-1 to end of ym). A held name whose price series has ENDED
before ym is written to ZERO (program convention); a name with a gap
month but a continuing series is carried at its last price (the W04
engine price() convention). Costs: engine tiered cost_rate on traded
fractions (entries + exits) each month. HOUSE form: v9 plain -15%
floor at monthly marks, 3-month sit-out, one restart, second halt
ends the run in cash."""
import statistics

def month_list(start, end):
    y, m = int(start[:4]), int(start[5:7]); out = []
    while f"{y:04d}-{m:02d}" <= end:
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12: y += 1; m = 1
    return out

def prev_month(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return f"{y-1:04d}-12" if m == 1 else f"{y:04d}-{m-1:02d}"

def run_monthly(months, pick_fn, D, cost_rate, form="native"):
    eq = 100.0; curve = []; trades = 0; costs = 0.0
    held = {}  # cik -> weight share of eq at last rebalance (drift ignored for cost accounting)
    anchor = 100.0; halts = 0; sitout = 0; ended = False
    peak = 100.0; maxdd = 0.0
    monthly = []
    for ym in months:
        pm = prev_month(ym)
        if ended or sitout > 0:
            if sitout > 0:
                sitout -= 1
                if sitout == 0 and not ended: anchor = eq
            curve.append([ym, round(eq, 4)]); monthly.append(0.0)
            held = {}
            continue
        if form == "house" and held and eq <= 0.85 * anchor:
            # liquidate: charge exit costs
            c = sum(w * eq * cost_rate(cik) for cik, w in held.items())
            costs += c; eq -= c; trades += len(held); held = {}
            halts += 1
            if halts >= 2: ended = True
            else: sitout = 3
            curve.append([ym, round(eq, 4)]); monthly.append(0.0)
            continue
        picks = pick_fn(ym)
        pickset = set(picks)
        # exits and entries (cost accounting on set changes, equal weights)
        exits = [c for c in held if c not in pickset]
        entries = [c for c in pickset if c not in held]
        if exits:
            c = sum((eq / max(len(held), 1)) * cost_rate(cik) for cik in exits)
            costs += c; eq -= c; trades += len(exits)
        if entries and picks:
            c = sum((eq / len(picks)) * cost_rate(cik) for cik in entries)
            costs += c; eq -= c; trades += len(entries)
        if not picks:
            held = {}
            curve.append([ym, round(eq, 4)]); monthly.append(0.0)
            continue
        # monthly return: EW mean of member returns pm -> ym
        rets = []
        for cik in picks:
            p0 = D.price(cik, pm, adj=True); p1 = D.price(cik, ym, adj=True)
            if p0 is None or p0 <= 0: continue
            series_end = max(D.px.get(cik, {"": 0}).keys()) if cik in D.px else None
            if series_end is not None and series_end < ym and not D.has_price_month(cik, ym):
                rets.append(-1.0)  # delisted: written to zero
            elif p1 is None:
                continue
            else:
                rets.append(p1 / p0 - 1)
        r = sum(rets) / len(rets) if rets else 0.0
        eq *= (1 + r); monthly.append(round(r, 4))
        held = {c: 1.0 / len(picks) for c in picks}
        curve.append([ym, round(eq, 4)])
        peak = max(peak, eq); maxdd = max(maxdd, 1 - eq / peak)
    return {"final": round(eq, 2), "curve": curve, "trades": trades,
            "costs": round(costs, 2), "halts": halts, "max_dd": round(maxdd, 4),
            "monthly_returns": monthly}

def period_stats_monthly(monthly, start_val=100.0):
    rets = monthly
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    v = start_val; peak = v; since = cur2 = 0
    for r in rets:
        v *= (1 + r)
        if v >= peak: peak = v; cur2 = 0
        else: cur2 += 1
        since = max(since, cur2)
    return {"periods": len(rets), "share_positive": round(pos / len(rets), 3),
            "median": round(statistics.median(rets), 4), "best": round(max(rets), 4),
            "worst": round(min(rets), 4), "longest_losing_streak": streak,
            "longest_below_high_periods": since,
            "average_secondary": round(sum(rets) / len(rets), 4)}
