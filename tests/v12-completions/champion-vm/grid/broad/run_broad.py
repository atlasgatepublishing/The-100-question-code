#!/usr/bin/env python3
"""champion-vm — BROAD-UNIVERSE grid slice (v12 Second-Chance Protocol).
Simulation only. No broker orders were placed.

The champion's frozen form (holdings-champion-vm/run_sweep.py header):
  AMP signals — book-to-market (EDGAR PIT StockholdersEquity / shares x
  close) + 12-1 momentum, percentile-rank averaged, equal weight,
  QUARTERLY re-pick, NATIVE COUNT = 5, program costs 0.10%/side +
  $0.01/sell order, v9 protections (plain -15% floor per episode checked
  at closes; first halt -> liquidate, 90-day cash sit-out, restart at the
  next quarterly selection date under a -15% floor from the restart
  balance; second halt ends the run).

This slice runs that SAME form on the BROAD universe: the W04 broad
stack (v11-native-rules/_w04_broad_data/, READ-ONLY) — 658 candidate
CIKs, EDGAR frames fundamentals, monthly Yahoo adjclose/raw prices
2016-01..2026-11.

Monthly-plumbing conventions (the stack's granularity, stated, not
tuned):
  - Selections take effect at the first month of each calendar quarter
    (Jan/Apr/Jul/Oct); signals use data through the prior month-end.
  - Value: B/M from the most recent W04 June-30 snapshot available at
    the selection (snapshot(F) uses CY F-1 frames — the W04 engine's own
    PIT convention); B/M = equity / cap exactly as W04 computes cap
    (shares x raw close x split factor).
  - Momentum 12-1 on monthly adjclose: adj[sm-1] / adj[sm-12] - 1,
    where sm is the last completed month (skips the signal month-end
    print itself, the monthly analogue of skipping the last month).
  - Trades execute at the signal month-end adjclose (the last price
    known at selection). Marks are monthly adjcloses. The v9 floor is
    checked at monthly closes (the only closes this stack has).
  - A held name whose price series ends is marked at its last available
    month-end adjclose thereafter (W04 Data.price convention — the
    stack's own convention; names in this stack are current-ticker
    mapped, so the whole run carries the stack's documented
    survivorship FLATTERING fence: delisted filers that lost their
    ticker mapping are absent).
Roads: DECADE 2016-11-21->2026-11-20, CONT 2019-01-02->2026-11-20,
VAL 2023-01-03->2026-11-20 (monthly marks 2016-12..2026-11 etc.).
LONG 2010 is NOT runnable: stack prices begin 2016-01 (named closure
for that road in BROAD.md).
Placebos: 20 seeds per road — random 5-name draws from the same scored
pool at each selection, same costs/floor machinery.
"""
import importlib.util, json, os, random, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
W04 = os.path.join(BT, "v11-native-rules", "_w04_broad_data")
sys.path.insert(0, W04)
spec = importlib.util.spec_from_file_location("engine_w04", os.path.join(W04, "engine_w04.py"))
W = importlib.util.module_from_spec(spec); spec.loader.exec_module(W)
W.D = W.Data()
D = W.D

MONTHS = [f"{y:04d}-{m:02d}" for y in range(2016, 2027) for m in range(1, 13)]
MONTHS = [m for m in MONTHS if m <= "2026-11"]
MIDX = {m: i for i, m in enumerate(MONTHS)}

def adj(cik, ym):
    s = D.px.get(cik)
    if not s: return None
    if ym in s: return s[ym][0]
    prev = [m for m in s if m <= ym]
    return s[max(prev)][0] if prev else None

_snap_cache = {}
def snapshot(F):
    if F not in _snap_cache: _snap_cache[F] = W.snapshot(F)
    return _snap_cache[F]

def scored_pool(sel_month):
    """sel_month = first month of quarter (e.g. '2019-01'). Returns
    ranked [(cik, score)] best-first."""
    sm = MONTHS[MIDX[sel_month] - 1]              # last completed month
    F = int(sm[:4]) if int(sm[5:]) >= 6 else int(sm[:4]) - 0
    # most recent June-30 snapshot whose formation date <= selection:
    # snapshot(F) is formed June 30 of year F.
    Fy = int(sm[:4]) if int(sm[5:]) >= 7 else int(sm[:4]) - 1
    # selections in Jan..Jun use snapshot of prior year; Jul..Dec use
    # this year's June snapshot only if sm >= June.
    Fy = int(sm[:4]) if sm[5:] >= "06" else int(sm[:4]) - 1
    snap = snapshot(Fy)
    m1 = MONTHS[MIDX[sm] - 1]; m12 = MONTHS[MIDX[sm] - 12] if MIDX[sm] >= 12 else None
    if m12 is None: return []
    rows = []
    for cik, v in snap.items():
        if not v["cap"] or not v["equity"] or v["equity"] <= 0: continue
        p1, p12 = adj(cik, m1), adj(cik, m12)
        if not p1 or not p12: continue
        rows.append((cik, v["equity"] / v["cap"], p1 / p12 - 1.0))
    if len(rows) < 5: return []
    n = len(rows)
    bv = sorted(rows, key=lambda r: r[1]); bm = sorted(rows, key=lambda r: r[2])
    rv = {r[0]: i / (n - 1) for i, r in enumerate(bv)}
    rm = {r[0]: i / (n - 1) for i, r in enumerate(bm)}
    return sorted(rows, key=lambda r: -(rv[r[0]] + rm[r[0]]) / 2.0)

def run_road(start_month, end_month, placebo_seed=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    cash, shares = 100.0, {}
    curve, costs, orders, halts = [], 0.0, 0, []
    episode_start, ep = 100.0, 1
    sit_out_until = None  # month index
    dead = False
    sel_months = [m for m in MONTHS if m[5:] in ("01", "04", "07", "10")
                  and start_month <= m <= end_month]
    for ym in MONTHS:
        if ym < start_month or ym > end_month: continue
        # value at month-end close
        val = cash + sum(sh * (adj(c, ym) or 0.0) for c, sh in shares.items())
        if not dead and ym in sel_months and (sit_out_until is None or MIDX[ym] >= sit_out_until):
            if sit_out_until is not None and MIDX[ym] >= sit_out_until:
                episode_start, sit_out_until = val, None
            pool = scored_pool(ym)
            if pool:
                picks = [r[0] for r in pool[:5]] if rng is None else [r[0] for r in rng.sample(pool, 5)]
                sm = MONTHS[MIDX[ym] - 1]
                # sell all at signal month-end prices
                for c, sh in list(shares.items()):
                    p = adj(c, sm)
                    if p:
                        amt = sh * p; fee = amt * 0.001 + 0.01
                        cash += amt - fee; costs += fee; orders += 1
                    shares.pop(c)
                val = cash
                each = val / len(picks)
                for c in picks:
                    p = adj(c, sm)
                    if not p: continue
                    fee = each * 0.001; costs += fee; orders += 1
                    shares[c] = (each - fee) / p
                    cash -= each
                val = cash + sum(sh * (adj(c, ym) or 0.0) for c, sh in shares.items())
        curve.append([ym, round(val, 4)])
        # v9 floor at monthly close
        if not dead and sit_out_until is None and shares and val <= episode_start * 0.85:
            if ep == 1:
                # liquidate at this close
                for c, sh in list(shares.items()):
                    p = adj(c, ym)
                    if p:
                        amt = sh * p; fee = amt * 0.001 + 0.01
                        cash += amt - fee; costs += fee; orders += 1
                    shares.pop(c)
                halts.append({"month": ym, "close": round(val, 2)})
                val = cash; curve[-1][1] = round(val, 4)
                sit_out_until = MIDX[ym] + 3  # ~90 days in monthly plumbing
                ep = 2
            else:
                halts.append({"month": ym, "close": round(val, 2), "final": True})
                dead = True
                for c, sh in list(shares.items()):
                    p = adj(c, ym)
                    if p:
                        amt = sh * p; fee = amt * 0.001 + 0.01
                        cash += amt - fee; costs += fee; orders += 1
                    shares.pop(c)
                val = cash; curve[-1][1] = round(val, 4)
        if dead:
            curve[-1][1] = round(cash, 4)
    final = curve[-1][1] if curve else 100.0
    return {"final": round(final, 2), "curve": curve, "costs": round(costs, 2),
            "orders": orders, "halts": halts}

def spy_road(start_month, end_month):
    s = D.spy
    ks = sorted(s)
    p0 = s[[k for k in ks if k <= start_month][-1]] if any(k <= start_month for k in ks) else None
    curve = []
    for ym in MONTHS:
        if start_month <= ym <= end_month and ym in s and p0:
            curve.append([ym, round(100.0 * s[ym] / p0, 4)])
    return {"final": curve[-1][1] if curve else None, "curve": curve}

def period_stats(curve):
    vals = [100.0] + [c[1] for c in curve]
    rets = [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals)) if vals[i - 1] > 0]
    if not rets: return {}
    srt = sorted(rets)
    med = srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt)//2-1] + srt[len(srt)//2]) / 2
    longest_loss, cur = 0, 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; longest_loss = max(longest_loss, cur)
    peak, since, longest_h = vals[0], 0, 0
    for v in vals:
        if v >= peak: peak, since = v, 0
        else: since += 1; longest_h = max(longest_h, since)
    return {"periods": len(rets), "pct_positive": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1),
            "median_pct": round(100 * med, 2), "best_pct": round(100 * max(rets), 2),
            "worst_pct": round(100 * min(rets), 2), "longest_losing_run": longest_loss,
            "longest_months_between_new_highs": longest_h,
            "average_pct_secondary": round(100 * sum(rets) / len(rets), 2)}

ROADS = {"DECADE": ("2016-12", "2026-11"), "CONT": ("2019-01", "2026-11"), "VAL": ("2023-01", "2026-11")}
out = {"family": "champion-vm", "slice": "grid/broad", "form": "champion V+M frozen form (B/M + 12-1 momentum percentile-rank average, top-5, quarterly, equal weight, v9 floor, program costs) on W04 broad universe (658 candidates)",
       "fences": ["SURVIVORSHIP: W04 stack maps CIKs via current tickers; delisted filers absent — broad finals are UPPER BOUNDS (stack's own documented fence).",
                  "Monthly plumbing: floor checked at monthly closes only; trades at signal month-end adjclose."],
       "roads": {}}
for road, (s, e) in ROADS.items():
    r = run_road(s, e)
    twins = [run_road(s, e, placebo_seed=seed)["final"] for seed in range(1, 21)]
    beaten = sum(1 for t in twins if r["final"] > t)
    spy = spy_road(s, e)
    out["roads"][road] = {**r, "placebo_beaten": f"{beaten}/20", "placebo_finals": twins,
                          "spy_broad_stack_basis": spy, "period_stats_monthly": period_stats(r["curve"])}
    print(road, r["final"], "placebos", beaten, "/20  spy(stack)", spy["final"], "halts", r["halts"], flush=True)
json.dump(out, open(os.path.join(HERE, "broad_results.json"), "w"), indent=1)
print("saved broad_results.json")
