#!/usr/bin/env python3
"""V13 BEST RULES — Connors VIX RSI (hunt-connors-vix-rsi). Simulation only.

Implements BEST-RULES-SPEC.md (frozen before this run):
  ENTRY (published, unchanged): at close, SPY>SMA200, Wilder RSI(2) VIX>90,
    VIX open today > VIX close yesterday, Wilder RSI(2) SPY<30.
  EXIT (my rule): at close, first day SPY close < SMA200. No floor.
  Costs 0.10%/side + $0.01/share on sells. Cash 0%. $100 pots.
Also re-runs the published form (exit RSI(2)>65) on identical plumbing as a
validation comparator vs v12 finals, and 20-seed random-timing placebos
(random entries on eligible above-SMA200 days, matched signal count, same
200MA exit) on every road. Confirmation folds/halves run only if a road
beats champion V+M.
Data: SPY adj bars from shared v7 cache (read-only); VIX = CBOE published
daily OHLC history (VIX_History.csv, copied into this folder at fetch time).
"""
import csv, json, os, random, statistics, time

HERE = os.path.dirname(os.path.abspath(__file__))
SPY_PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
START = 100.0
COST = 0.001
SELLFEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
V12 = {"LONG": 125.01, "DECADE": 121.25, "CONT": 123.39, "VAL": 106.74}


def load_spy():
    j = json.load(open(SPY_PX))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None:
            continue
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)), "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    return bars


def load_vix():
    out = {}
    with open(os.path.join(HERE, "VIX_History.csv")) as f:
        for row in csv.DictReader(f):
            m, d, y = row["DATE"].split("/")
            out[f"{y}-{int(m):02d}-{int(d):02d}"] = {"o": float(row["OPEN"]), "c": float(row["CLOSE"])}
    return out


def sma(vals, n):
    out = [None] * len(vals); s = 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n: s -= vals[i - n]
        if i >= n - 1: out[i] = s / n
    return out


def rsi_wilder(vals, n):
    out = [None] * len(vals)
    if len(vals) <= n: return out
    g = sum(max(vals[i] - vals[i - 1], 0.0) for i in range(1, n + 1)) / n
    l = sum(max(vals[i - 1] - vals[i], 0.0) for i in range(1, n + 1)) / n
    for i in range(n, len(vals)):
        if i > n:
            d = vals[i] - vals[i - 1]
            g = (g * (n - 1) + max(d, 0.0)) / n
            l = (l * (n - 1) + max(-d, 0.0)) / n
        out[i] = 100.0 if l == 0 else 100.0 - 100.0 / (1.0 + g / l)
    return out


def max_dd(curve):
    peak, dd = curve[0][1], 0.0
    for _, v in curve:
        peak = max(peak, v); dd = min(dd, (v / peak - 1.0) * 100.0)
    return round(dd, 1)


def period_stats(curve, monthly=True):
    # bucket curve by calendar month, period return = last/first-1 chained on month-ends
    months = {}
    for d, v in curve: months[d[:7]] = v
    keys = sorted(months)
    rets = []
    prev = START
    for k in keys:
        rets.append(months[k] / prev - 1.0); prev = months[k]
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    # longest stretch between new highs (in monthly periods)
    peak, since, worst_stretch = START, 0, 0
    for k in keys:
        if months[k] >= peak: peak, since = months[k], 0
        else: since += 1; worst_stretch = max(worst_stretch, since)
    return {"n_periods": len(rets), "pct_positive": round(100.0 * pos / len(rets), 1) if rets else 0.0,
            "median_pct": round(statistics.median(rets) * 100, 2) if rets else 0.0,
            "best_pct": round(max(rets) * 100, 2) if rets else 0.0,
            "worst_pct": round(min(rets) * 100, 2) if rets else 0.0,
            "longest_losing_streak": streak, "longest_stretch_between_highs": worst_stretch,
            "avg_pct_secondary": round(statistics.mean(rets) * 100, 2) if rets else 0.0}


def run_timer(spy, state_fn, s, e):
    """state_fn(i)->desired position decided at close i (trades execute at close i).
    Equity marked daily at close; in-position days earn next-day return... no:
    position decided at close i earns return from close i to close i+1."""
    idx = [i for i, b in enumerate(spy) if s <= b["d"] <= e]
    cash, shares, trades, costs = START, 0.0, 0, 0.0
    curve = []
    pos = 0; entries = 0
    for k, i in enumerate(idx):
        price = spy[i]["c"]
        want = state_fn(i)
        if want == 1 and pos == 0:
            c = cash * COST; shares = (cash - c) / price; costs += c; cash = 0.0; pos = 1; trades += 1; entries += 1
        elif want == 0 and pos == 1:
            gross = shares * price; c = gross * COST + shares * SELLFEE
            cash = gross - c; costs += c; shares = 0.0; pos = 0; trades += 1
        curve.append((spy[i]["d"], round(cash + shares * price, 4)))
    return {"final": curve[-1][1], "trades": trades, "entries": entries, "costs": round(costs, 2),
            "maxdd_pct": max_dd(curve), "curve": curve, "periods": period_stats(curve)}


def buyhold(spy, s, e):
    idx = [b for b in spy if s <= b["d"] <= e]
    sh = (START - START * COST) / idx[0]["c"]
    return round(sh * idx[-1]["c"] - (sh * idx[-1]["c"] * COST + sh * SELLFEE), 2)


def main():
    spy = load_spy(); vix = load_vix()
    closes = [b["c"] for b in spy]; s200 = sma(closes, 200); r2s = rsi_wilder(closes, 2)
    vdates = sorted(vix); vcloses = [vix[d]["c"] for d in vdates]
    vr = rsi_wilder(vcloses, 2); vrmap = {vdates[i]: vr[i] for i in range(len(vdates))}
    vprev = {vdates[i]: vdates[i - 1] for i in range(1, len(vdates))}

    def entry_signal(i):
        d = spy[i]["d"]; vb = vix.get(d)
        if not vb or d not in vprev or s200[i] is None or r2s[i] is None or vrmap.get(d) is None:
            return False
        return (closes[i] > s200[i] and vrmap[d] > 90 and r2s[i] < 30
                and vb["o"] > vix[vprev[d]]["c"])

    # my-rules state machine: in until close < SMA200
    def make_state(exit_mode):
        st = {"pos": 0}
        def fn(i):
            if st["pos"] == 0:
                if entry_signal(i): st["pos"] = 1
            else:
                if exit_mode == "trend" and s200[i] is not None and closes[i] < s200[i]: st["pos"] = 0
                if exit_mode == "published" and r2s[i] is not None and r2s[i] > 65: st["pos"] = 0
            return st["pos"]
        return fn

    signals = [spy[i]["d"] for i in range(len(spy)) if entry_signal(i)]
    res = {"family": "hunt-connors-vix-rsi", "program": "v13-best-rules",
           "n_entry_signals_total": len(signals), "signal_dates": signals, "roads": {}, "placebos": {}}
    curves = {}
    for road, (s, e) in ROADS.items():
        mine = run_timer(spy, make_state("trend"), s, e)
        pub = run_timer(spy, make_state("published"), s, e)
        res["roads"][road] = {
            "my_rules_final": mine["final"], "my_maxdd_pct": mine["maxdd_pct"],
            "my_trades": mine["trades"], "my_entries": mine["entries"], "my_costs": mine["costs"],
            "published_form_final_same_plumbing": pub["final"], "published_maxdd_pct": pub["maxdd_pct"],
            "v12_published_final": V12[road], "champion_vm": CHAMP[road],
            "spy_program_ref": SPYREF[road], "buyhold_same_plumbing": buyhold(spy, s, e),
            "periods_monthly_my_rules": mine["periods"]}
        curves[road] = {"my_rules": mine["curve"], "published_form": pub["curve"]}
        # random-timing placebos (frozen spec): PRIMARY = matched to the number of
        # entries my system actually took on the road. SECONDARY (labeled) =
        # matched to all signal condition-days in the road (saturated re-entry,
        # approximates a pure trend system) — kept from the first run, disclosed.
        elig = [i for i, b in enumerate(spy) if s <= b["d"] <= e and s200[i] and closes[i] > s200[i]]
        def placebo_finals(n_match, seed_base):
            finals = []
            for seed in range(1, 21):
                rng = random.Random(seed * seed_base + len(road))
                picks = set(rng.sample(elig, min(n_match, len(elig)))) if n_match else set()
                st = {"pos": 0}
                def pfn(i, picks=picks, st=st):
                    if st["pos"] == 0:
                        if i in picks: st["pos"] = 1
                    elif s200[i] is not None and closes[i] < s200[i]: st["pos"] = 0
                    return st["pos"]
                finals.append(run_timer(spy, pfn, s, e)["final"])
            return finals
        n_taken = mine["entries"]
        n_cond = sum(1 for d in signals if s <= d <= e)
        f1 = placebo_finals(n_taken, 131)
        f2 = placebo_finals(n_cond, 131)
        res["placebos"][road] = {
            "primary_entries_taken": {"n_entries_matched": n_taken,
                "median": round(statistics.median(f1), 2),
                "n_beaten_by_my_rules": sum(1 for f in f1 if mine["final"] > f),
                "finals": [round(f, 2) for f in f1]},
            "secondary_condition_days_saturated": {"n_entries_matched": n_cond,
                "median": round(statistics.median(f2), 2),
                "n_beaten_by_my_rules": sum(1 for f in f2 if mine["final"] > f),
                "finals": [round(f, 2) for f in f2]}}
    res["curves"] = curves

    # confirmation (frozen bars) — only if a road beats champion
    beaten = [r for r in ROADS if res["roads"][r]["my_rules_final"] > CHAMP[r]]
    res["roads_beating_champion"] = beaten
    if beaten:
        conf = {}
        for road in beaten:
            s, e = ROADS[road]
            years = sorted({d[:4] for d in signals if s <= d <= e} |
                           {b["d"][:4] for b in spy if s <= b["d"] <= e})
            folds = {}
            for y in years:
                fs, fe = f"{y}-01-01", f"{y}-12-31"
                if fe < s or fs > e: continue
                folds[y] = run_timer(spy, make_state("trend"), max(fs, s), min(fe, e))["final"]
            idx = [b["d"] for b in spy if s <= b["d"] <= e]
            mid = idx[len(idx) // 2]
            halves = {"first_half": run_timer(spy, make_state("trend"), s, mid)["final"],
                      "second_half": run_timer(spy, make_state("trend"), mid, e)["final"]}
            conf[road] = {"yearly_folds_start100": folds, "halves_start100": halves}
        res["confirmation"] = conf

    json.dump(res, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    for r in ROADS:
        print(r, res["roads"][r])
    print("placebos primary:", {r: (res["placebos"][r]["primary_entries_taken"]["median"], res["placebos"][r]["primary_entries_taken"]["n_beaten_by_my_rules"]) for r in ROADS})
    print("placebos secondary(saturated):", {r: (res["placebos"][r]["secondary_condition_days_saturated"]["median"], res["placebos"][r]["secondary_condition_days_saturated"]["n_beaten_by_my_rules"]) for r in ROADS})
    print("signals total:", len(signals), "| roads beating champion:", beaten)


if __name__ == "__main__":
    main()
