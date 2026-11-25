#!/usr/bin/env python3
"""
CRYPTO-FEAR-GREED — V12 CRYPTO WING RUNS.
Frozen form: see ../CONSTRUCTION-SPEC.md. Reads v4 caches READ-ONLY.
Writes only inside this folder.

Forms: A BINARY (in at F&G<=25, out at F&G>=76, hysteresis, start cash)
       B LADDER (CONSTRUCTED weights EF100/F75/N50/G25/EG0, daily)
Rule sets: native (no floor), v9 (episode floors -15%, 90d sit, 1 restart)
Assets: BTC primary; PIT top-20 equal-weight overlay basket.
Lag: value dated D first traded on D+1 (signal for day t = last F&G
value published on a date < t). Costs 0.60%/side. Close execution.
"""
import csv, json, math, os, random
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
FAM = os.path.dirname(HERE)
V4 = os.path.join(FAM, "..", "..", "v4")
V4CACHE = os.path.join(V4, "crypto-basket-pit-data")
POT = 100.0
COST = 0.006
WINDOWS = {"full": ("2018-02-01", "2026-11-20"),
           "design": ("2018-02-01", "2022-12-31"),
           "validation": ("2023-01-01", "2026-11-20")}
CREDIBLE_START = {2280: "2020-10-15", 11841: "2023-03-23", 22861: "2023-10-31"}
GRACE_DAYS = 30

# ---------------------------------------------------------------- data ----
def load_fng():
    with open(os.path.join(FAM, "data", "fng_api_full.json")) as f:
        raw = json.load(f)["data"]
    out = {}
    for x in raw:
        d = datetime.utcfromtimestamp(int(x["timestamp"])).strftime("%Y-%m-%d")
        out[d] = int(x["value"])
    return out  # date -> value

def load_btc():
    rows = []
    with open(os.path.join(V4, "crypto-trend-data", "BTC-USD.csv")) as f:
        for r in csv.DictReader(f):
            rows.append((r["date"], float(r["close"])))
    return rows  # [(date, close)]

def load_registry():
    with open(os.path.join(V4, "crypto-basket-pit-results.json")) as f:
        v4res = json.load(f)
    reg = {}
    for cid_s, info in v4res["registry"].items():
        cid = int(cid_s)
        if info["source"] == "excluded":
            reg[cid] = {**info, "rows": []}
            continue
        kind, name = info["source"].split(":", 1)
        fn = {"yahoo": f"y_{name}.json", "binance": f"b_{name}.json",
              "kraken": f"k_{name}.json"}[kind]
        with open(os.path.join(V4CACHE, fn)) as f:
            rows = json.load(f)
        if cid in CREDIBLE_START:
            rows = [r for r in rows if r["d"] >= CREDIBLE_START[cid]]
        reg[cid] = {**info, "rows": rows}
    return reg

def load_snapshots():
    with open(os.path.join(V4CACHE, "snapshots.json")) as f:
        return json.load(f)

# ------------------------------------------------------------- signals ----
def band(v):
    if v <= 25: return "EF"
    if v <= 46: return "F"
    if v <= 54: return "N"
    if v <= 75: return "G"
    return "EG"

LADDER = {"EF": 1.0, "F": 0.75, "N": 0.50, "G": 0.25, "EG": 0.0}

def signal_series(cal, fng):
    """sig[i] = last F&G value published on a date strictly before cal[i]
    (1-day availability lag + carry-forward over the published gaps)."""
    sig, last = [], None
    fi = sorted(fng.items())
    j = 0
    for d in cal:
        while j < len(fi) and fi[j][0] < d:
            last = fi[j][1]; j += 1
        sig.append(last)
    return sig

def targets(form, sig):
    """Daily target weights from the lagged signal series."""
    out = []
    if form == "binary":
        state = 0.0
        for v in sig:
            if v is None: out.append(0.0); continue
            if v <= 25: state = 1.0
            elif v >= 76: state = 0.0
            out.append(state)
    else:  # ladder
        for v in sig:
            out.append(0.0 if v is None else LADDER[band(v)])
    return out

# ------------------------------------------------------------- basket -----
def build_basket(cal, ci, reg, snaps):
    """Daily equal-weight PIT top-20 basket index (close-based), with the
    death rule and monthly-rebalance turnover charged at COST.
    Returns (index_series, info) aligned to cal."""
    snap_keys = sorted(snaps.keys())
    def universe_for(month_start):
        k = None
        for key in snap_keys:
            if key <= month_start: k = key
            else: break
        if k is None: return []
        return [c["cmc_id"] for c in snaps[k]["top20"]]
    # per-coin close maps + last-bar index
    closes, lastbar = {}, {}
    for cid, info in reg.items():
        if not info["rows"]: continue
        closes[cid] = {r["d"]: r["c"] for r in info["rows"]}
        lastbar[cid] = max(closes[cid])
    def eff_price(cid, i):
        """Effective price on cal[i]: last close carried; 0 after the
        30-day grace once the series has ended; None before first bar."""
        d = cal[i]
        cm = closes.get(cid)
        if not cm: return None
        if d in cm: return cm[d]
        # carry: find last bar <= d
        # (precomputed below in the main loop instead for speed)
        return None
    # Precompute effective prices per coin over the calendar (carry + grace)
    eff = {}
    for cid, cm in closes.items():
        arr, last, last_i = [], None, -10**9
        for i, d in enumerate(cal):
            if d in cm: last, last_i = cm[d], i
            if last is None: arr.append(None)
            elif i - last_i <= GRACE_DAYS: arr.append(last)
            else: arr.append(0.0)
        eff[cid] = arr
    idx = [1.0]
    weights = {}   # cid -> weight (drifted)
    cur_month = None
    rebal_log = []
    start_i = ci[WINDOWS["full"][0]]
    for i in range(start_i, len(cal)):
        d = cal[i]
        month = d[:7]
        if month != cur_month:
            # monthly rebalance at this day's open-of-day state: use prior
            # close values (weights as drifted), charge turnover, reset EW.
            uni = [c for c in universe_for(d)
                   if c in eff and eff[c][i] not in (None, 0.0)]
            neww = {c: 1.0 / len(uni) for c in uni} if uni else {}
            keys = set(weights) | set(neww)
            turnover = 0.5 * sum(abs(neww.get(c, 0.0) - weights.get(c, 0.0))
                                 for c in keys)
            if i > start_i and turnover > 0:
                idx[-1] *= (1.0 - turnover * COST)
                rebal_log.append((d, round(turnover, 4), len(uni)))
            weights = neww
            cur_month = month
        if i == start_i:
            idx = [1.0]
            prev = {c: eff[c][i] for c in weights}
            continue
        # daily return from drifted weights
        r = 0.0
        newprev = {}
        for c, w in weights.items():
            p0, p1 = prev.get(c), eff[c][i]
            newprev[c] = p1
            if p0 and p0 > 0 and p1 is not None:
                r += w * (p1 / p0 - 1.0)
            elif p0 and p0 > 0 and (p1 == 0.0):
                r += w * (-1.0)
        idx.append(idx[-1] * (1.0 + r))
        # drift weights
        if 1.0 + r != 0:
            for c in list(weights):
                p0, p1 = prev.get(c), newprev[c]
                if p0 and p0 > 0 and p1 is not None:
                    weights[c] *= (p1 / p0) / (1.0 + r)
                elif p1 == 0.0:
                    weights[c] = 0.0
        prev = newprev
    dates = cal[start_i:]
    return dates, idx, rebal_log

# ------------------------------------------------------------- engine -----
def max_dd(curve):
    peak, mdd = -1e18, 0.0
    for v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1.0)
    return mdd

def period_stats(curve):
    """Daily-tempo record from an equity curve (coordinator requirement)."""
    rets = [curve[i] / curve[i-1] - 1.0 for i in range(1, len(curve))]
    if not rets: return {}
    srt = sorted(rets)
    n = len(rets)
    med = srt[n // 2] if n % 2 else 0.5 * (srt[n//2 - 1] + srt[n//2])
    longest_loss, run = 0, 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        longest_loss = max(longest_loss, run)
    # longest stretch between new highs (days underwater)
    peak_i, longest_uw = 0, 0
    for i, v in enumerate(curve):
        if v >= curve[peak_i]: peak_i = i
        longest_uw = max(longest_uw, i - peak_i)
    return {"periods": n, "share_positive": round(sum(1 for r in rets if r > 0) / n, 4),
            "median_period": round(med, 6), "mean_period_secondary": round(sum(rets) / n, 6),
            "best_period": round(max(rets), 6), "worst_period": round(min(rets), 6),
            "longest_losing_run": longest_loss, "longest_between_new_highs_days": longest_uw}

def simulate(dates, prices, tgts, ruleset):
    """Daily close-execution sim. tgts aligned to dates. Returns dict."""
    cash, units = POT, 0.0
    curve, expo = [], []
    trades, turnover = 0, 0.0
    # v9 state
    ep_start_eq, floor = POT, POT * 0.85
    halted_until, episode, dead = -1, 1, False
    halts = []
    n = len(dates)
    force_flat_next = False
    for i in range(n):
        p = prices[i]
        eq = cash + units * p
        if ruleset == "v9" and not dead and i > halted_until:
            if eq <= floor:
                force_flat_next = True
                halts.append((dates[i], round(eq, 2), episode))
        if i <= halted_until or dead:
            tgt = 0.0
        elif force_flat_next:
            tgt = 0.0
        else:
            tgt = tgts[i]
        # execute at close
        eq = cash + units * p
        desired = tgt * eq
        cur = units * p
        delta = desired - cur
        if abs(delta) > 1e-9:
            cost = abs(delta) * COST
            units = desired / p if p > 0 else 0.0
            cash = eq - desired - cost
            trades += 1; turnover += abs(delta)
        eq = cash + units * p
        curve.append(eq)
        expo.append((units * p / eq) if eq > 0 else 0.0)
        if force_flat_next:
            force_flat_next = False
            if episode == 1:
                episode = 2
                halted_until = i + 90
                ep_start_eq = eq; floor = eq * 0.85
            else:
                dead = True
    return {"final": round(curve[-1], 2), "max_dd": round(max_dd(curve), 4),
            "trades": trades, "turnover": round(turnover, 2),
            "avg_exposure": round(sum(expo) / len(expo), 4),
            "halts": halts, "curve": [round(v, 4) for v in curve],
            "period_stats": period_stats(curve)}

def buy_hold(dates, prices):
    p0, p1 = prices[0], prices[-1]
    units = POT * (1 - COST) / p0
    curve = [units * p for p in prices]
    final = units * p1 * (1 - COST)
    curve[-1] = final
    return {"final": round(final, 2), "max_dd": round(max_dd(curve), 4),
            "curve": [round(v, 4) for v in curve],
            "period_stats": period_stats(curve)}

def const_weight(dates, prices, w):
    """Exposure-matched control: invest fraction w on day 1, hold, exit end."""
    p0, p1 = prices[0], prices[-1]
    units = POT * w * (1 - COST) / p0
    cash = POT * (1 - w)
    curve = [cash + units * p for p in prices]
    curve[-1] = cash + units * p1 * (1 - COST)
    return {"final": round(curve[-1], 2), "max_dd": round(max_dd(curve), 4)}

# ---------------------------------------------------------------- main ----
def main():
    fng = load_fng()
    btc = load_btc()
    cal = [d for d, _ in btc]
    ci = {d: i for i, d in enumerate(cal)}
    btc_close = [c for _, c in btc]
    reg = load_registry()
    snaps = load_snapshots()
    bd, bidx, rebal_log = build_basket(cal, ci, reg, snaps)
    bci = {d: i for i, d in enumerate(bd)}
    sig = signal_series(cal, fng)
    tg = {f: targets(f, sig) for f in ("binary", "ladder")}

    out = {"cost_per_side": COST, "windows": WINDOWS,
           "basket_rebalances": len(rebal_log), "cells": {}, "placebos": {}}

    assets = {"BTC": (cal, btc_close), "PIT_BASKET": (bd, bidx)}
    for aname, (acal, aclose) in assets.items():
        ai = {d: i for i, d in enumerate(acal)}
        for wname, (ws, we) in WINDOWS.items():
            i0, i1 = ai[ws], ai[we]
            dates = acal[i0:i1+1]; prices = aclose[i0:i1+1]
            # signals/targets are on the BTC calendar; basket calendar ==
            # BTC calendar from full-start onward, so indices coincide.
            t_i0, t_i1 = ci[ws], ci[we]
            bh = buy_hold(dates, prices)
            cell = {"btc_hold": {"final": bh["final"], "max_dd": bh["max_dd"],
                                 "period_stats": bh["period_stats"]}}
            for form in ("binary", "ladder"):
                t = tg[form][t_i0:t_i1+1]
                for rs in ("native", "v9"):
                    r = simulate(dates, prices, t, rs)
                    key = f"{form}_{rs}"
                    cell[key] = {k: r[k] for k in
                                 ("final", "max_dd", "trades", "turnover",
                                  "avg_exposure", "halts", "period_stats")}
                    if aname == "BTC" and rs == "native":
                        cell[key]["curve"] = r["curve"]
                        cell[key]["const_weight_control"] = const_weight(
                            dates, prices, r["avg_exposure"])
                    if aname == "BTC":
                        cell.setdefault("curves", {})[key] = r["curve"]
            out["cells"][f"{aname}|{wname}"] = cell

    # ---- placebos: circularly shifted F&G, BTC, native, full+validation
    span_dates = [d for d in cal if WINDOWS["full"][0] <= d <= "2026-11-21"]
    span_vals = []
    last = None
    for d in span_dates:
        if d in fng: last = fng[d]
        span_vals.append(last)
    N = len(span_dates)
    for form in ("binary", "ladder"):
        for wname in ("full", "validation"):
            ws, we = WINDOWS[wname]
            i0, i1 = ci[ws], ci[we]
            dates = cal[i0:i1+1]; prices = btc_close[i0:i1+1]
            real = out["cells"][f"BTC|{wname}"][f"{form}_native"]["final"]
            finals = []
            for seed in range(1, 21):
                rng = random.Random(seed)
                k = rng.randint(30, N - 30)
                shifted = {}
                for j, d in enumerate(span_dates):
                    shifted[d] = span_vals[(j - k) % N]
                ssig = signal_series(cal, shifted)
                st = targets(form, ssig)[i0:i1+1]
                r = simulate(dates, prices, st, "native")
                finals.append(r["final"])
            finals_s = sorted(finals)
            out["placebos"][f"{form}|{wname}"] = {
                "real_final": real,
                "placebo_finals": [round(x, 2) for x in finals],
                "placebo_median": round(finals_s[10], 2),
                "placebo_max": round(finals_s[-1], 2),
                "n_placebos_ge_real": sum(1 for x in finals if x >= real)}
    with open(os.path.join(FAM, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("done")
    for k, c in out["cells"].items():
        print(k, "hold", c["btc_hold"]["final"],
              "| bin_nat", c["binary_native"]["final"],
              "| bin_v9", c["binary_v9"]["final"],
              "| lad_nat", c["ladder_native"]["final"],
              "| lad_v9", c["ladder_v9"]["final"])
    for k, p in out["placebos"].items():
        print("PLACEBO", k, "real", p["real_final"], "median", p["placebo_median"],
              "max", p["placebo_max"], "n_ge_real", p["n_placebos_ge_real"])

if __name__ == "__main__":
    main()
