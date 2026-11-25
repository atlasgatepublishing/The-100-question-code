#!/usr/bin/env python3
"""Crypto Wing 1 Group B: single-asset forms x every coin. Spec: CONSTRUCTION-SPEC.md (frozen)."""
import json, os, glob, math, random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "v4", "crypto-basket-pit-data")
COST = 0.006           # 0.60%/side
END = "2026-11-20"
START_CASH = 100.0
PEGGED = {"USDT","USDC","DAI","BUSD","USD1","USDE","USTC"}

def load_series():
    out = {}
    for f in sorted(glob.glob(os.path.join(DATA, "*.json"))):
        base = os.path.basename(f)
        if base == "snapshots.json": continue
        rows = json.load(open(f))
        if not rows: continue
        stem = base[:-5]
        sym = stem.split("_",1)[1]
        for suf in ("USDT","-USD","USD"):
            if sym.endswith(suf): sym = sym[:-len(suf)]; break
        if sym == "IOTA": sym = "MIOTA"
        rows = [r for r in rows if r["d"] <= END and r["c"] and r["c"] > 0 and r["o"] and r["o"] > 0]
        if not rows: continue
        if sym in out and len(out[sym][0]) >= len(rows): continue
        out[sym] = ([r["d"] for r in rows], [float(r["o"]) for r in rows], [float(r["c"]) for r in rows], base)
    return out

def sma(c, i, n):
    if i < n-1: return None
    return sum(c[i-n+1:i+1]) / n

def rsi2(c):
    """Wilder RSI(2) array (None until computable)."""
    n = len(c); out = [None]*n
    gains = [0.0]*n; losses = [0.0]*n
    for i in range(1, n):
        d = c[i]-c[i-1]
        gains[i] = max(d, 0.0); losses[i] = max(-d, 0.0)
    ag = al = None
    for i in range(1, n):
        if i == 2:
            ag = (gains[1]+gains[2])/2; al = (losses[1]+losses[2])/2
        elif i > 2:
            ag = (ag*1 + gains[i])/2; al = (al*1 + losses[i])/2
        else:
            continue
        out[i] = 100.0 if al == 0 else 100 - 100/(1 + ag/al) if ag > 0 else 0.0
        if al == 0 and ag == 0: out[i] = 50.0
    return out

# ---------- position schedules ----------
# 'cc': inv[i]=1 -> hold close[i]->close[i+1].  'oc': inv[i]=1 -> hold open[i]->open[i+1].

def sched_rsi2(d, o, c):
    n = len(c); r = rsi2(c); inv = [0]*n; pos = 0
    for i in range(n-1):
        if pos == 0:
            s200 = sma(c, i, 200)
            if s200 is not None and c[i] > s200 and r[i] is not None and r[i] < 5: pos = 1
        else:
            s5 = sma(c, i, 5)
            if s5 is not None and c[i] > s5: pos = 0
        inv[i] = pos
    return "cc", inv, 260

def sched_trend200(d, o, c):
    n = len(c); inv = [0]*n
    cur = 0
    for i in range(n):
        if date.fromisoformat(d[i]).weekday() == 0 or i == 0:  # weekly eval (Mon proxy for ISO-week first bar present)
            s200 = sma(c, i, 200)
            cur = 1 if (s200 is not None and c[i] > s200) else 0
        inv[i] = cur
    return "oc_raw", inv, 260

def _monthly_eval_idx(d):
    s = set(); seen = set()
    for i, ds in enumerate(d):
        k = ds[:7]
        if k not in seen: seen.add(k); s.add(i)
    return s

def sched_mom121(d, o, c):
    n = len(c); inv = [0]*n; cur = 0; ev = _monthly_eval_idx(d)
    for i in range(n):
        if i in ev:
            cur = 1 if (i >= 365 and c[i-30]/c[i-365] - 1 > 0) else 0
        inv[i] = cur
    return "oc_raw", inv, 430

def sched_gemcore(d, o, c):
    n = len(c); inv = [0]*n; cur = 0; ev = _monthly_eval_idx(d)
    for i in range(n):
        if i in ev:
            cur = 1 if (i >= 252 and c[i]/c[i-252] - 1 > 0) else 0
        inv[i] = cur
    return "oc_raw", inv, 430

def sched_trendsleeve(d, o, c):
    n = len(c); inv = [0]*n; cur = 0; ev = _monthly_eval_idx(d)
    for i in range(n):
        if i in ev:
            if i >= 252:
                score = sum(1 for lag in (63,126,252) if c[i]/c[i-lag] - 1 > 0)
                cur = 1 if score >= 2 else 0
            else: cur = 0
        inv[i] = cur
    return "oc_raw", inv, 430

def _donchian(d, o, c, entry_n, exit_n, skip_rule=False):
    n = len(c); inv = [0]*n; pos = 0; last_win = None; entry_px = None
    for i in range(n-1):
        if pos == 0:
            if i >= entry_n:
                hi = max(c[i-entry_n:i])
                if c[i] > hi:
                    take = True
                    if skip_rule and last_win: take = False
                    if take: pos = 1; entry_px = c[i]
            if pos == 0 and skip_rule and i >= 55 and c[i] > max(c[i-55:i]):  # S1 failsafe = 55d breakout
                pos = 1; entry_px = c[i]
        else:
            if i >= exit_n and c[i] < min(c[i-exit_n:i]):
                last_win = c[i] > entry_px; pos = 0
        inv[i] = pos
    return "cc", inv, 120

def sched_donchian55(d, o, c): return _donchian(d, o, c, 55, 20)
def sched_donchian20(d, o, c): return _donchian(d, o, c, 20, 10, skip_rule=True)

def sched_breakout52(d, o, c):
    n = len(c); inv = [0]*n; pos = 0; entry_px = None
    # oc schedule: inv[i]=1 means buy at open i. Signals at close i-1.
    for i in range(1, n):
        j = i-1
        if pos == 0:
            if j >= 252 and c[j] > max(c[j-252:j]):
                pos = 1; entry_px = o[i]
        else:
            s20 = sma(c, j, 20)
            if (s20 is not None and c[j] < s20) or c[j] <= entry_px*0.92: pos = 0
        inv[i] = pos
    return "oc", inv, 320

FORMS = {
    "rsi2": sched_rsi2, "mom12-1": sched_mom121, "trend200": sched_trend200,
    "donchian55": sched_donchian55, "donchian20": sched_donchian20,
    "breakout52": sched_breakout52, "trendsleeve": sched_trendsleeve, "gemcore": sched_gemcore,
}

# ---------- simulator ----------
def simulate(d, px_a, px_b, inv, mode_v9, i0=0):
    """inv[i]=1 earns px_b[i]/px_a[i]-1 over step i (i from i0..len-2 conceptually;
    here arrays already aligned: step i uses inv[i], prices px_a[i]->px_b[i])."""
    eq = START_CASH; peak = eq; maxdd = 0.0; prev = 0; costs = 0.0; trades = 0
    floor_level = 0.85*START_CASH; ep = 1; halt_until = -1; dead = False
    n = len(inv)
    curve = []
    for i in range(i0, n):
        cur_inv = inv[i] if not dead and i > halt_until else 0
        if cur_inv != prev:
            costs += eq*COST; eq *= (1-COST); trades += 1; prev = cur_inv
        if cur_inv:
            eq *= px_b[i]/px_a[i]
        peak = max(peak, eq); maxdd = min(maxdd, eq/peak - 1)
        curve.append(eq)
        if mode_v9 and not dead and i > halt_until and eq < floor_level:
            if prev: costs += eq*COST; eq *= (1-COST); trades += 1; prev = 0
            if ep == 1:
                ep = 2; floor_level = 0.85*eq
                hd = date.fromisoformat(d[i]) + timedelta(days=90)
                halt_until = i
                while halt_until < n-1 and date.fromisoformat(d[halt_until]) < hd: halt_until += 1
            else:
                dead = True
    if prev and not dead:
        costs += eq*COST; eq *= (1-COST); trades += 1
    return {"final": round(eq,2), "max_dd_pct": round(maxdd*100,2), "costs": round(costs,2), "trades": trades}, curve

def run_form(form, d, o, c, i0=0):
    kind, inv, _ = FORMS[form](d, o, c)
    if kind == "cc": pa, pb = c, c[1:]+[c[-1]]; invx = inv[:]
    elif kind == "oc_raw":  # decision at close i -> executed at open i+1 (no look-ahead)
        pa, pb = o, o[1:]+[o[-1]]; invx = [0] + inv[:-1]
    else: pa, pb = o, o[1:]+[o[-1]]; invx = inv[:]
    # last step has zero return by construction (pb==pa at end); harmless
    nat, curve = simulate(d, pa, pb, invx, False, i0)
    v9, _ = simulate(d, pa, pb, invx, True, i0)
    return kind, invx, pa, pb, nat, v9, curve

def buy_hold(d, o, c, i0=0):
    eq = START_CASH*(1-COST); peak = eq; maxdd = 0.0
    for i in range(i0, len(c)):
        eq = START_CASH*(1-COST) * c[i]/o[i0] if False else eq
        break
    eq = START_CASH*(1-COST)
    base = o[i0]; peak = eq; maxdd = 0.0; last = eq
    for i in range(i0, len(c)):
        last = START_CASH*(1-COST) * c[i]/base
        peak = max(peak, last); maxdd = min(maxdd, last/peak-1)
    return {"final": round(last*(1-COST),2), "max_dd_pct": round(maxdd*100,2)}

def seg_form(d, o, c, which, mode_v9, i0=0):
    """overnight: close[i]->open[i+1]; intraday: open[i]->close[i]. Daily round trips."""
    eq = START_CASH; peak = eq; maxdd = 0.0; costs = 0.0; trades = 0
    floor_level = 0.85*START_CASH; ep = 1; halt_until = -1; dead = False
    n = len(c); seg_curve = []
    rng = range(i0, n-1) if which == "overnight" else range(i0, n)
    for i in rng:
        if dead or i <= halt_until: 
            curve_eq = eq
        else:
            r = (o[i+1]/c[i]) if which == "overnight" else (c[i]/o[i])
            costs += eq*COST*2; eq *= (1-COST); eq *= r; eq *= (1-COST); trades += 2
        peak = max(peak, eq); maxdd = min(maxdd, eq/peak-1); seg_curve.append(eq)
        if mode_v9 and not dead and i > halt_until and eq < floor_level:
            if ep == 1:
                ep = 2; floor_level = 0.85*eq
                hd = date.fromisoformat(d[i]) + timedelta(days=90)
                halt_until = i
                while halt_until < n-1 and date.fromisoformat(d[halt_until]) < hd: halt_until += 1
            else: dead = True
    return {"final": round(eq,2), "max_dd_pct": round(maxdd*100,2), "costs": round(costs,2), "trades": trades}, seg_curve

CURVES = {}
def main():
    series = load_series()
    results = {"cost_per_side": COST, "end": END, "forms": {}, "coins": {}}
    placebo_summary = {}
    for sym, (d, o, c, src) in sorted(series.items()):
        results["coins"][sym] = {"source_file": src, "bars": len(c), "first": d[0], "last": d[-1],
                                  "pegged": sym in PEGGED, "hold_full": buy_hold(d, o, c)}
        i23 = next((i for i, ds in enumerate(d) if ds >= "2023-01-01"), None)
        if i23 is not None:
            results["coins"][sym]["hold_conf"] = buy_hold(d, o, c, i23)
    for form in list(FORMS) + ["overnight", "intraday"]:
        fkey = "overnight-effect" if form in ("overnight","intraday") else form
        results["forms"].setdefault(fkey, {})
        sub = results["forms"][fkey].setdefault(form, {"coins": {}, "skipped": []}) if form in ("overnight","intraday") else results["forms"][fkey]
        if form not in ("overnight","intraday"):
            sub = results["forms"][fkey] = {"coins": {}, "skipped": []}
        beaten = total = 0; plac_beaten = plac_total = 0
        for sym, (d, o, c, src) in sorted(series.items()):
            n = len(c)
            if form in ("overnight","intraday"):
                if n < 60: sub["skipped"].append(sym); continue
                i23 = next((i for i, ds in enumerate(d) if ds >= "2023-01-01"), None)
                nat, scurve = seg_form(d, o, c, form, False); v9, _ = seg_form(d, o, c, form, True)
                CURVES.setdefault(form, {})[sym] = [round(x,4) for x in scurve]
                conf = seg_form(d, o, c, form, False, i23)[0] if i23 is not None and n-i23 >= 60 else None
                sub["coins"][sym] = {"native": nat, "v9": v9, "native_conf": conf}
                continue
            kind, inv, minbars = FORMS[form](d, o, c)
            if n < minbars: sub["skipped"].append(sym); continue
            _, _, pa, pb, nat, v9, curve = run_form(form, d, o, c)
            CURVES.setdefault(form, {})[sym] = [round(x,4) for x in curve]
            i23 = next((i for i, ds in enumerate(d) if ds >= "2023-01-01"), None)
            conf = None
            if i23 is not None and n - i23 >= 60:
                conf, _ = simulate(d, pa, pb, inv, False, i23)
            sub["coins"][sym] = {"native": nat, "v9": v9, "native_conf": conf}
            # pooled placebos: 10 rotations
            rng = random.Random(12345)
            for s in range(10):
                off = rng.randrange(30, max(31, n-30))
                pinv = inv[off:] + inv[:off]
                pf, _ = simulate(d, pa, pb, pinv, False)
                plac_total += 1
                if nat["final"] > pf["final"]: plac_beaten += 1
        if form not in ("overnight","intraday"):
            sub["placebo_pooled"] = {"real_beats_share": round(plac_beaten/plac_total, 3) if plac_total else None,
                                     "pairs": plac_total, "design": "10 seeded rotations of the position series per coin, pooled"}
        else:
            sub["placebo_pooled"] = {"real_beats_share": None, "design": "N/A - full-coverage deterministic form; a rotation placebo is identical by construction"}
    # ---- period-by-period record at each form's native tempo (coordinator addendum) ----
    import gzip, statistics
    TEMPO = {"rsi2":"daily","donchian55":"daily","donchian20":"daily","breakout52":"daily",
             "trend200":"weekly","mom12-1":"monthly","trendsleeve":"monthly","gemcore":"monthly",
             "overnight":"daily","intraday":"daily"}
    def resample(dts, curve, tempo):
        pts = []
        last_key = None
        for ds, v in zip(dts, curve):
            if tempo == "daily": key = ds
            elif tempo == "weekly": 
                dt = date.fromisoformat(ds); key = (dt.isocalendar()[0], dt.isocalendar()[1])
            else: key = ds[:7]
            if key != last_key: pts.append(v); last_key = key
            else: pts[-1] = v
        return pts
    def pstats(form, per_coin):
        tempo = TEMPO[form]; all_rets = []; streaks = []; droughts = []
        for sym, (dts, curve) in per_coin.items():
            pts = resample(dts, curve, tempo)
            rets = [pts[i+1]/pts[i]-1 for i in range(len(pts)-1) if pts[i] > 0]
            all_rets += rets
            run = mx = 0
            for r in rets:
                run = run+1 if r < 0 else 0; mx = max(mx, run)
            streaks.append(mx)
            peak = -1; last_high = 0; mx_d = 0
            for i, v in enumerate(pts):
                if v >= peak: peak = v; last_high = i
                mx_d = max(mx_d, i-last_high)
            droughts.append(mx_d)
        if not all_rets: return None
        return {"tempo": tempo, "periods_pooled": len(all_rets),
                "share_positive_pct": round(100*sum(1 for r in all_rets if r > 0)/len(all_rets), 1),
                "median_period_pct": round(statistics.median(all_rets)*100, 3),
                "best_period_pct": round(max(all_rets)*100, 2), "worst_period_pct": round(min(all_rets)*100, 2),
                "longest_losing_streak_periods_max": max(streaks), "longest_losing_streak_periods_median": statistics.median(streaks),
                "longest_below_high_periods_max": max(droughts), "longest_below_high_periods_median": statistics.median(droughts),
                "mean_period_pct_secondary_average": round(statistics.mean(all_rets)*100, 3)}
    results["period_stats"] = {}
    for form, coins in CURVES.items():
        pc = {}
        for sym, curve in coins.items():
            d = series[sym][0]
            pc[sym] = (d[len(d)-len(curve):], curve)
        results["period_stats"][form] = pstats(form, pc)
    with gzip.open(os.path.join(HERE, "equity_curves.json.gz"), "wt") as fh:
        json.dump(CURVES, fh)
    json.dump(results, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("done", {k: len(v.get('coins', v)) if isinstance(v, dict) else v for k, v in results["forms"].items()})

if __name__ == "__main__":
    main()
