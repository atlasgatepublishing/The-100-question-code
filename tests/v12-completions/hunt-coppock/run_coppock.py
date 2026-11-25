#!/usr/bin/env python3
"""Coppock Curve (hunt-coppock, v12 Deep-Hunt) — implements SPEC-FROZEN.md
EXACTLY. Simulation only.

Published (Barron's, 15 Oct 1962): monthly closes of a broad index;
Coppock = WMA(10) of [ROC(14mo) + ROC(11mo)], ROC in percent.
Buy: curve, below zero, turns up. NO sell signal was published.
CONSTRUCTED exit (labelled everywhere): exit to cash when the curve
turns down while the prior month was above zero (nearest documented
practitioner convention, frozen in the spec — one exit only).
Sizing CONSTRUCTED (program standard): all-in while in, cash while out,
$100 pot. Stocks: SPY only, program costs 0.10%/side + $0.01 sell fee.
Coins: BTC only (spec (d): BTC is the crypto-wing index analogue, an
APPLICATION not the published habitat; other coins NOT-APPLICABLE),
crypto cost 0.60%/side, bar = BTC buy-and-hold.
Forms: NATIVE (monthly, no floor, drawdown printed) and HOUSE (v9:
same signals + v9 chassis — floor checked on DAILY closes vs episode
start, -15%: first breach liquidates at next open and halts 90 days,
second breach ends the run; stated per spec (b)).
Execution: decide at month-end close, execute next trading day open.
Placebos: circular shift of the monthly in/out state series within the
road (20 seeds) — the program's timer convention (random-entry
matched-holding: shift preserves invested-month fraction and episode
lengths). Warmup: 24 months of monthly closes before the first curve
value; printed, not patched.
"""
import json, os, time, random, statistics
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
PX = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_SPY.json")
BTC = os.path.expanduser("~/workspace/stock-app/backtests/v4/crypto-trend-data/BTC-USD.csv")
START = 100.0
STK_COST = 0.001; STK_SELL_FEE = 0.01
CRY_COST = 0.006
ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
BTC_ROADS = {"FULL": (None, "2026-11-21"), "CONT": ("2019-01-01", "2026-11-21"),
             "VAL": ("2023-01-01", "2026-11-21")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}


def load_spy():
    j = json.load(open(PX))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"])
    return bars


def load_btc():
    bars = []
    with open(BTC) as f:
        next(f)
        for line in f:
            p = line.strip().split(",")
            if len(p) < 5:
                continue
            bars.append({"d": p[0], "o": float(p[1]), "c": float(p[4])})
    bars.sort(key=lambda b: b["d"])
    return bars


def monthly_closes(bars):
    """[(month_end_date, month_key, close)] in order."""
    seen = {}
    for b in bars:
        seen[b["d"][:7]] = (b["d"], b["c"])
    return [(d, m, c) for m, (d, c) in sorted(seen.items())]


def coppock_series(months):
    """Returns (curve list aligned with months, first_valid_index)."""
    closes = [c for _, _, c in months]
    n = len(closes)
    s = [None] * n
    for t in range(n):
        if t >= 14:
            s[t] = (closes[t] / closes[t - 14] - 1.0) * 100.0 + \
                   (closes[t] / closes[t - 11] - 1.0) * 100.0
    curve = [None] * n
    wts = list(range(1, 11))  # oldest weight 1 ... newest weight 10
    wsum = sum(wts)
    for t in range(n):
        if t >= 9 and all(s[t - k] is not None for k in range(10)):
            curve[t] = sum(s[t - 9 + i] * wts[i] for i in range(10)) / wsum
    first = next((i for i, v in enumerate(curve) if v is not None), None)
    return curve, first


def native_targets(months, curve):
    """State machine -> desired in/out AFTER each month-end check.
    Buy (published): flat, curve < 0, curve turns up.
    Exit (CONSTRUCTED): in, prior month curve > 0, curve turns down."""
    pos = False
    targets = []
    events = []
    for t in range(len(months)):
        c, cp = curve[t], curve[t - 1] if t >= 1 else None
        if c is not None and cp is not None:
            if not pos and c < 0 and c > cp:
                pos = True
                events.append([months[t][0], "BUY-SIGNAL (published)", round(c, 3)])
            elif pos and cp > 0 and c < cp:
                pos = False
                events.append([months[t][0], "EXIT-SIGNAL (CONSTRUCTED)", round(c, 3)])
        targets.append(pos)
    return targets, events


def simulate(bars, months, targets, start, end, cost, sell_fee, chassis=False,
             shift=0, seed=None):
    """Daily engine. targets aligned with months (month-end check dates).
    Entry state: target of last check on/before the first road day."""
    by_date = {b["d"]: b for b in bars}
    days = [b["d"] for b in bars if (start is None or b["d"] >= start) and b["d"] <= end]
    checkmap = {months[i][0]: targets[i] for i in range(len(months))}
    # circular shift of targets within the road's check window (placebo)
    if shift:
        # rotate only the road segment: the entry check (last before the
        # road) plus every check inside the road; earlier history fixed
        pre = [i for i in range(len(months)) if months[i][0] < days[0]]
        rel_idx = (pre[-1:] if pre else []) + \
                  [i for i in range(len(months)) if days[0] <= months[i][0] <= end]
        vals = [targets[i] for i in rel_idx]
        if len(vals) > 1:
            rng = random.Random(seed)
            k = rng.randrange(1, len(vals))
            vals = vals[k:] + vals[:k]
            checkmap = {months[i][0]: v for i, v in zip(rel_idx, vals)}
    desired = False
    for i in range(len(months)):
        if months[i][0] < days[0]:
            desired = checkmap.get(months[i][0], targets[i])
    cash, shares, costs = START, 0.0, 0.0
    trades, curve_out = [], []
    pending = None
    ep_start, halts, halt_until, ended = START, 0, None, False
    days_invested = 0
    if desired:
        pending = True
    for d in days:
        bar = by_date[d]
        if halt_until is not None and d >= halt_until:
            halt_until = None; ep_start = cash + shares * bar["o"]
        if pending is not None and halt_until is None and not ended:
            if pending and shares == 0.0 and cash > 0:
                bv = cash / (1 + cost); cfee = bv * cost
                shares = bv / bar["o"]; cash -= bv + cfee; costs += cfee
                trades.append([d, "BUY", round(bar["o"], 4), round(bv, 2), round(cfee, 2)])
            elif not pending and shares > 0:
                val = shares * bar["o"]; cfee = val * cost + sell_fee
                cash += val - cfee; costs += cfee; shares = 0.0
                trades.append([d, "SELL", round(bar["o"], 4), round(val, 2), round(cfee, 2)])
            pending = None
        if d in checkmap:
            if checkmap[d] != (shares > 0) and halt_until is None and not ended:
                pending = checkmap[d]
            desired = checkmap[d]
        eq = cash + shares * bar["c"]
        if shares > 0:
            days_invested += 1
        curve_out.append([d, round(eq, 4)])
        if chassis and not ended and halt_until is None and eq <= 0.85 * ep_start:
            # floor breach at today's close -> liquidate at next open
            halts += 1
            nxt = None
            # find next day via days list position
            idx = days.index(d)
            if idx + 1 < len(days):
                nb = by_date[days[idx + 1]]
                if shares > 0:
                    val = shares * nb["o"]; cfee = val * cost + sell_fee
                    cash += val - cfee; costs += cfee; shares = 0.0
                    trades.append([days[idx + 1], "SELL-FLOOR", round(nb["o"], 4),
                                   round(val, 2), round(cfee, 2)])
            if halts == 1:
                halt_until = (date.fromisoformat(d) .toordinal() + 90)
                halt_until = date.fromordinal(halt_until).isoformat()
            else:
                ended = True
    if shares > 0:
        last = days[-1]; val = shares * by_date[last]["c"]; cfee = val * cost + sell_fee
        cash += val - cfee; costs += cfee; shares = 0.0
        trades.append([last, "SELL-END", round(by_date[last]["c"], 4), round(val, 2), round(cfee, 2)])
        curve_out[-1] = [last, round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve_out:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0 * days_invested / len(days), 1) if days else 0.0,
            "halts": halts, "equity_curve": curve_out}


def buy_hold(bars, start, end, cost, sell_fee):
    days = [b["d"] for b in bars if (start is None or b["d"] >= start) and b["d"] <= end]
    by_date = {b["d"]: b for b in bars}
    o = by_date[days[0]]["o"]; sh = (START / (1 + cost)) / o
    curve = [[d, round(sh * by_date[d]["c"], 4)] for d in days]
    val = sh * by_date[days[-1]]["c"]
    final = val - (val * cost + sell_fee)
    curve[-1] = [days[-1], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "equity_curve": curve}


def period_stats_monthly(curve):
    """Reporting standard: monthly periods from the equity curve."""
    if not curve:
        return None
    vals, last_key = [], None
    for d, v in curve:
        if d[:7] != last_key:
            vals.append(v); last_key = d[:7]
        else:
            vals[-1] = v
    series = [START] + vals
    if len(series) < 2:
        return None
    rets = [(series[i] / series[i - 1] - 1.0) * 100.0 if series[i - 1] > 0 else 0.0
            for i in range(1, len(series))]
    pos = sum(1 for r in rets if r > 0)
    streak = worst_streak = 0
    for r in rets:
        if r < 0:
            streak += 1; worst_streak = max(worst_streak, streak)
        else:
            streak = 0
    peak = series[0]; last_high = 0; longest = 0
    for i, v in enumerate(series):
        if v >= peak:
            peak = v; longest = max(longest, i - last_high); last_high = i
    longest = max(longest, len(series) - 1 - last_high)
    return {"periods": len(rets), "pct_positive": round(100.0 * pos / len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary_average_only": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak_months": worst_streak,
            "longest_between_highs_months": longest}


def run_asset(bars, roads, cost, sell_fee, bench_name):
    months = monthly_closes(bars)
    curve, first_valid = coppock_series(months)
    targets, events = native_targets(months, curve)
    out = {"months": len(months), "first_month": months[0][1],
           "last_month": months[-1][1],
           "first_curve_value": {"month": months[first_valid][1],
                                 "date": months[first_valid][0],
                                 "value": round(curve[first_valid], 3)},
           "signal_events": events,
           "curve_monthly": [[months[i][0], (round(curve[i], 4) if curve[i] is not None else None),
                              targets[i]] for i in range(len(months))],
           "roads": {}}
    for name, (s, e) in roads.items():
        rec = {}
        for form, chassis in (("native", False), ("house_v9", True)):
            r = simulate(bars, months, targets, s, e, cost, sell_fee, chassis=chassis)
            rec[form] = {**r, "period_stats_monthly": period_stats_monthly(r["equity_curve"])}
        bh = buy_hold(bars, s, e, cost, sell_fee)
        rec["benchmark_hold"] = {"name": bench_name, "final": bh["final"],
                                 "max_dd_pct": bh["max_dd_pct"],
                                 "period_stats_monthly": period_stats_monthly(bh["equity_curve"])}
        # placebos on the NATIVE form: circular shift of monthly state, 20 seeds
        finals, beaten = [], None
        for seed in range(1, 21):
            pr = simulate(bars, months, targets, s, e, cost, sell_fee,
                          chassis=False, shift=1, seed=seed)
            finals.append(pr["final"])
        beaten = sum(1 for p in finals if rec["native"]["final"] > p)
        rec["placebo_native"] = {"seed_finals": finals, "beaten_of_20": beaten,
                                 "design": "circular shift of monthly in/out state within road; preserves invested-month fraction and episode lengths (matched-holding timer placebo)"}
        out["roads"][name] = rec
    return out


def main():
    out = {"family": "hunt-coppock (Coppock Curve, Barron's 1962)",
           "ledger_disposition": "HUNT-FOUND (deep-hunt-nonus)",
           "form": "FROZEN SPEC: published buy (below-zero upturn) + CONSTRUCTED exit (turn down while prior month above zero); monthly; $100; native = no floor; house = v9 chassis (daily-close floor check, -15%, 90-day first halt, second breach ends)",
           "warmup_note": "24 months of monthly closes before the first curve value; printed per asset, not patched",
           "stocks": {}, "coins": {}}
    spy = load_spy()
    st = run_asset(spy, ROADS, STK_COST, STK_SELL_FEE, "SPY buy-and-hold (same plumbing)")
    for name in ROADS:
        st["roads"][name]["champion_vm"] = CHAMP[name]
        st["roads"][name]["spy_program_ref"] = SPYREF[name]
    st["instrument"] = "SPY (spec: broad index, SPY only; holdings sweep NOT-APPLICABLE — single-asset timer)"
    st["data_range"] = f"{spy[0]['d']} -> {spy[-1]['d']}"
    out["stocks"] = st
    print("SPY months", st["months"], "first curve", st["first_curve_value"])
    print("SPY events:", st["signal_events"])
    for name, rec in st["roads"].items():
        print(f"SPY {name}: native ${rec['native']['final']} (DD {rec['native']['max_dd_pct']}%, "
              f"inv {rec['native']['invested_pct']}%, orders {rec['native']['orders']}, "
              f"placebos {rec['placebo_native']['beaten_of_20']}/20) | house ${rec['house_v9']['final']} "
              f"(halts {rec['house_v9']['halts']}) | hold ${rec['benchmark_hold']['final']}")

    btc = load_btc()
    bt = run_asset(btc, BTC_ROADS, CRY_COST, 0.0, "BTC buy-and-hold (same plumbing)")
    bt["instrument"] = "BTC only (spec (d): crypto-wing index analogue, an APPLICATION not the published habitat; all other coins NOT-APPLICABLE — a single-coin monthly series is not the broad index the system was designed on)"
    bt["data_range"] = f"{btc[0]['d']} -> {btc[-1]['d']}"
    out["coins"] = bt
    print("BTC months", bt["months"], "first curve", bt["first_curve_value"])
    print("BTC events:", bt["signal_events"])
    for name, rec in bt["roads"].items():
        print(f"BTC {name}: native ${rec['native']['final']} (DD {rec['native']['max_dd_pct']}%, "
              f"inv {rec['native']['invested_pct']}%, orders {rec['native']['orders']}, "
              f"placebos {rec['placebo_native']['beaten_of_20']}/20) | house ${rec['house_v9']['final']} "
              f"(halts {rec['house_v9']['halts']}) | hold ${rec['benchmark_hold']['final']}")

    # Confirmation folds (only meaningful if something beat its benchmark;
    # computed regardless and flagged in RESULTS)
    folds = {}
    for y in range(2010, 2027):
        s = f"{y}-01-01"; e = "2026-11-20" if y == 2026 else f"{y}-12-31"
        months = monthly_closes(spy); curve, _ = coppock_series(months)
        targets, _ = native_targets(months, curve)
        rn = simulate(spy, months, targets, s, e, STK_COST, STK_SELL_FEE)
        bh = buy_hold(spy, s, e, STK_COST, STK_SELL_FEE)
        folds[str(y)] = {"native": rn["final"], "spy_hold": bh["final"],
                         "beat_hold": rn["final"] > bh["final"]}
    out["stocks"]["year_folds_native"] = folds
    print("SPY year folds:", folds)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
