#!/usr/bin/env python3
"""V13 BEST RULES — Difficulty Ribbon (see BEST-RULES-SPEC.md, frozen before run).
Entry: fresh crossing of compression < 0.05 (published Glassnode threshold).
Exit: Phase 1 no trend exit until price has closed above its 200d SMA once
since entry; Phase 2 exit on first close below the 200d SMA. No floor.
Costs 0.60%/side. Data: v12 caches (blockchain.com difficulty = protocol
data, never restated; CoinMetrics PriceUSD) read-only.
Placebos: 20 seeds random threshold U[0.03,0.08]; 20 seeds random-timing
(same episode count, uniform eligible entry dates, same exit machinery)."""
import json, os, random, statistics, time as _t

SRC = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-difficulty-ribbon")
HERE = os.path.dirname(os.path.abspath(__file__))
COST = 0.006
END = "2026-11-20"

def load():
    diff = json.load(open(os.path.join(SRC, "difficulty.json")))["values"]
    dmap = {_t.strftime("%Y-%m-%d", _t.gmtime(v["x"])): v["y"] for v in diff}
    price = json.load(open(os.path.join(SRC, "cm_price.json")))
    dates = sorted(d for d in price if d in dmap)
    return dates, [price[d] for d in dates], [dmap[d] for d in dates]

def sma(vals, w):
    out = [None]*len(vals); run = 0.0
    for i, v in enumerate(vals):
        run += v
        if i >= w: run -= vals[i-w]
        if i >= w-1: out[i] = run/w
    return out

def compression(diffs):
    W = [9, 14, 25, 40, 60, 90, 128, 200]
    smas = [sma(diffs, w) for w in W]
    comp = [None]*len(diffs)
    for i in range(len(diffs)):
        vals = [s[i] for s in smas]
        if all(v is not None for v in vals):
            m = statistics.mean(vals)
            comp[i] = statistics.pstdev(vals)/m if m else None
    return comp

def entries_from_threshold(comp, thr):
    """Indices of fresh crossings below thr (prev computable close >= thr)."""
    out = []
    for i in range(1, len(comp)):
        if comp[i] is not None and comp[i-1] is not None and comp[i] < thr <= comp[i-1]:
            out.append(i)
    return out

def run_machine(dates, prices, psma, entry_idx, start, end):
    """Long-or-cash with frozen Phase1/Phase2 exit. Entry set = global episode
    entry indices; an episode whose entry predates the window is entered at
    window start only if the machine would still be holding (we simply run the
    machine from the first entry >= window start; episodes spanning the window
    boundary are handled by starting flat — stated simplification, same for
    placebos and buy-hold comparisons are unaffected)."""
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    if not idx: return None
    entries = set(e for e in entry_idx if idx[0] <= e <= idx[-1])
    eq = 100.0; curve = []; prev_long = False; armed = False; trades = 0; days_long = 0
    prev_i = None
    for i in idx:
        if prev_long and prev_i is not None:
            eq *= prices[i]/prices[prev_i]
        if prev_long: days_long += 1
        # exit check (Phase 2 armed)
        if prev_long and armed and psma[i] is not None and prices[i] < psma[i]:
            eq *= (1-COST); prev_long = False; armed = False; trades += 1
        # arm check
        if prev_long and psma[i] is not None and prices[i] > psma[i]:
            armed = True
        # entry check
        if not prev_long and i in entries:
            eq *= (1-COST); prev_long = True; armed = False
            if psma[i] is not None and prices[i] > psma[i]: armed = True
        curve.append((dates[i], round(eq, 4)))
        prev_i = i
    if prev_long:
        eq *= (1-COST); curve[-1] = (curve[-1][0], round(eq, 4)); trades += 1
    return {"final": round(eq, 2), "curve": curve, "round_trips": trades, "days_long": days_long}

def bh(dates, prices, start, end):
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    fin = 100*(1-COST)*prices[idx[-1]]/prices[idx[0]]*(1-COST)
    curve = [(dates[i], round(100*(1-COST)*prices[i]/prices[idx[0]], 4)) for i in idx]
    curve[-1] = (curve[-1][0], round(fin, 4))
    return {"final": round(fin, 2), "curve": curve}

def max_dd(curve):
    peak = -1e18; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, v/peak-1 if peak > 0 else 0.0)
    return round(mdd*100, 1)

def period_stats(curve):
    # monthly periods from daily curve: last value per month
    months = {}
    for d, v in curve: months[d[:7]] = v
    keys = sorted(months)
    rets = []
    prev = 100.0
    for k in keys:
        rets.append(months[k]/prev-1); prev = months[k]
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    # longest losing streak (non-positive months)
    streak = cur = 0
    for r in rets:
        cur = cur+1 if r <= 0 else 0; streak = max(streak, cur)
    # longest stretch between new highs (months)
    peak = -1e18; since = 0; longest = 0
    for k in keys:
        if months[k] > peak: peak = months[k]; since = 0
        else: since += 1; longest = max(longest, since)
    return {"periods": len(rets), "median_pct": round(statistics.median(rets)*100, 2),
            "share_positive_pct": round(100*pos/len(rets), 1),
            "best_pct": round(max(rets)*100, 2), "worst_pct": round(min(rets)*100, 2),
            "longest_losing_streak": streak, "longest_between_highs_periods": longest,
            "mean_pct_secondary": round(statistics.mean(rets)*100, 2)}

def main():
    dates, prices, diffs = load()
    comp = compression(diffs)
    psma = sma(prices, 200)
    first = next(dates[i] for i in range(len(dates)) if comp[i] is not None and psma[i] is not None)
    windows = {"FULL": (first, END), "DESIGN": (first, "2022-12-31"), "VALIDATION": ("2023-01-01", END)}
    real_entries = entries_from_threshold(comp, 0.05)
    entry_dates = [dates[i] for i in real_entries]
    res = {"family": "hunt-difficulty-ribbon", "program": "v13-best-rules",
           "first_computable": first, "windows": {k: list(v) for k, v in windows.items()},
           "episode_entry_dates_all_history": entry_dates,
           "cost_per_side": COST}
    curves = {}
    for wname, (s, e) in windows.items():
        m = run_machine(dates, prices, psma, real_entries, s, e)
        b = bh(dates, prices, s, e)
        eps_in = [d for d in entry_dates if s <= d <= e]
        res[wname] = {"final": m["final"], "buyhold_final": b["final"],
                      "maxdd_pct": max_dd(m["curve"]), "buyhold_maxdd_pct": max_dd(b["curve"]),
                      "round_trips": m["round_trips"], "days_long": m["days_long"],
                      "episodes_in_window": len(eps_in), "episode_entries": eps_in,
                      "periods_monthly": period_stats(m["curve"]),
                      "buyhold_periods_monthly": period_stats(b["curve"])}
        curves[wname] = {"strategy": m["curve"], "buyhold": b["curve"]}
    res["curves"] = curves
    # Placebos on FULL and VALIDATION
    pl = {}
    for wname in ["FULL", "VALIDATION"]:
        s, e = windows[wname]
        idx = [i for i, d in enumerate(dates) if s <= d <= e]
        n_eps = res[wname]["episodes_in_window"]
        thr_finals, tim_finals = [], []
        for seed in range(1, 21):
            rng = random.Random(1000*seed + len(wname))
            thr = rng.uniform(0.03, 0.08)
            te = entries_from_threshold(comp, thr)
            thr_finals.append(run_machine(dates, prices, psma, te, s, e)["final"])
            rng2 = random.Random(7000*seed + len(wname))
            # eligible: inside window, compression computable, spaced >=30d apart
            cand = [i for i in idx if comp[i] is not None]
            picks = []
            tries = 0
            while len(picks) < n_eps and tries < 5000:
                tries += 1
                c = rng2.choice(cand)
                if all(abs(c-p) >= 30 for p in picks): picks.append(c)
            tim_finals.append(run_machine(dates, prices, psma, sorted(picks), s, e)["final"])
        pl[wname] = {
            "threshold_placebo": {"median": round(statistics.median(thr_finals), 2),
                                  "n_beaten_by_strategy": sum(1 for f in thr_finals if res[wname]["final"] > f),
                                  "finals": [round(f, 2) for f in thr_finals]},
            "random_timing_placebo": {"median": round(statistics.median(tim_finals), 2),
                                      "n_beaten_by_strategy": sum(1 for f in tim_finals if res[wname]["final"] > f),
                                      "n_episodes_matched": n_eps,
                                      "finals": [round(f, 2) for f in tim_finals]}}
    res["placebos"] = pl
    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    for w in windows: print(w, {k: v for k, v in res[w].items() if "periods" not in k})
    print(pl)

if __name__ == "__main__": main()
