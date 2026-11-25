#!/usr/bin/env python3
"""v13 BEST RULES — hunt-fosback-seasonality-timing (Fosback STS).

MY RULES (BEST-RULES-SPEC.md, frozen before this run):
- Windows: Fosback's published windows EXACTLY as in the v12 frozen spec
  (turn-of-month + pre-holiday + three exceptions, merged). Window builder
  copied verbatim from the v12 run (read-only source).
- Inside windows: 100% SSO (2x S&P 500 ETF, real adjusted price path).
- Outside windows: 100% SPY. Never cash.
- Swaps execute at the closes the rules name; program costs on every leg
  (0.10%/side + $0.01 sell fee).
- NO floor / stop / ladder.
- Placebos: phase-shifted calendars, 20 seeds, v12 convention (random
  day-offset applied to the buys/sells sets), identical swap chassis.
Arms printed for scale: published form (v12 sts_sim, copied verbatim,
cash outside windows) and SPY buy-and-hold, same plumbing.
Confirmation (spec choice 8) runs ONLY if a road beats champion V+M:
yearly folds + half-windows + placebo >= 18/20 bars, all frozen in spec.
"""
import json, os, time, random, statistics
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
START = 100.0
STK_COST = 0.001; STK_SELL_FEE = 0.01
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBFORM = {"LONG": 137.75, "DECADE": 133.47, "CONT": 131.25, "VAL": 106.29}
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")


def load_pxfull(ticker, path=None):
    p = path or os.path.join(PXDIR, f"pxfull_{ticker}.json")
    j = json.load(open(p))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "h": q["high"][i] * ratio,
                     "l": q["low"][i] * ratio, "c": adj[i],
                     "v": q["volume"][i] or 0})
    bars.sort(key=lambda b: b["d"])
    return bars


def buy_hold(bars, start, end, cost, sell_fee):
    days = [b for b in bars if (start is None or b["d"] >= start) and b["d"] <= end]
    if not days:
        return None
    o = days[0]["o"]; sh = (START / (1 + cost)) / o
    curve = [[b["d"], round(sh * b["c"], 4)] for b in days]
    val = sh * days[-1]["c"]
    final = val - (val * cost + sell_fee)
    curve[-1] = [days[-1]["d"], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2),
            "equity_curve": curve}


def period_stats(curve, freq="monthly"):
    if not curve:
        return None
    def key(d):
        if freq == "monthly":
            return d[:7]
        if freq == "annual":
            return d[:4]
        y, m, dd = map(int, d.split("-"))
        iso = date(y, m, dd).isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    vals, last = [], None
    for d, v in curve:
        k = key(d)
        if k != last:
            vals.append(v); last = k
        else:
            vals[-1] = v
    series = [START] + vals
    if len(series) < 2:
        return None
    rets = [(series[i] / series[i - 1] - 1.0) * 100.0 if series[i - 1] > 0 else 0.0
            for i in range(1, len(series))]
    pos = sum(1 for r in rets if r > 0)
    streak = worst = 0
    for r in rets:
        if r < 0:
            streak += 1; worst = max(worst, streak)
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
            "longest_losing_streak": worst, "longest_between_highs": longest}


# ---------------------------------------------------------------------------
# Window builder + published-form simulator: copied VERBATIM from the v12
# run (~/workspace/stock-app/backtests/v12-completions/
# hunt-fosback-seasonality-timing/run_sts.py, read-only source).
# ---------------------------------------------------------------------------

def build_windows(bars):
    n = len(bars)
    dates = [b["d"] for b in bars]
    dobj = [date.fromisoformat(d) for d in dates]
    idx_of = {d: i for i, d in enumerate(dates)}
    buys, sells = set(), set()
    months = {}
    for i, d in enumerate(dates):
        months.setdefault(d[:7], []).append(i)
    mkeys = sorted(months)
    for mi, mk in enumerate(mkeys):
        days = months[mk]
        if len(days) < 3 or mi + 1 >= len(mkeys):
            continue
        buy_i = days[-3]
        ndays = months[mkeys[mi + 1]]
        if len(ndays) < 5:
            continue
        sell_i = ndays[4]
        buys.add(buy_i); sells.add(sell_i)
    trading = set(dobj)
    holidays = []
    d0, d1 = dobj[0], dobj[-1]
    cur = d0
    gap = []
    while cur <= d1:
        if cur.weekday() < 5 and cur not in trading:
            gap.append(cur)
        else:
            if gap:
                holidays.append(list(gap)); gap = []
        cur = date.fromordinal(cur.toordinal() + 1)
    if gap:
        holidays.append(gap)
    for gap in holidays:
        first_hol = gap[0]
        prev = date.fromordinal(first_hol.toordinal() - 1)
        while prev not in trading and prev >= d0:
            prev = date.fromordinal(prev.toordinal() - 1)
        if prev < d0:
            continue
        last_before = idx_of[prev.isoformat()]
        if last_before < 2:
            continue
        buy_i = last_before - 2
        sell_i = last_before
        if any(h.weekday() == 3 for h in gap):
            nxt = date.fromordinal(gap[-1].toordinal() + 1)
            while nxt not in trading and nxt <= d1:
                nxt = date.fromordinal(nxt.toordinal() + 1)
            if nxt <= d1:
                sell_i = idx_of[nxt.isoformat()]
        wk_start = date.fromordinal(prev.toordinal() - prev.weekday())
        first_td_week = wk_start
        while first_td_week not in trading and first_td_week <= prev:
            first_td_week = date.fromordinal(first_td_week.toordinal() + 1)
        if first_td_week == prev and sell_i == last_before:
            nxt = date.fromordinal(gap[-1].toordinal() + 1)
            while nxt not in trading and nxt <= d1:
                nxt = date.fromordinal(nxt.toordinal() + 1)
            if nxt <= d1:
                sell_i = idx_of[nxt.isoformat()]
        buys.add(buy_i); sells.add(sell_i)
    third_fridays = set()
    for mk in mkeys:
        y, m = map(int, mk.split("-"))
        d = date(y, m, 1)
        fridays = []
        while d.month == m:
            if d.weekday() == 4:
                fridays.append(d)
            d = date.fromordinal(d.toordinal() + 1)
        if len(fridays) >= 3:
            third_fridays.add(fridays[2])
    def is_first_td_after_expiry(i):
        dd = dobj[i]
        back = dd
        for _ in range(7):
            back = date.fromordinal(back.toordinal() - 1)
            if back.weekday() == 4:
                break
        if back not in third_fridays:
            return False
        nxt = date.fromordinal(back.toordinal() + 1)
        while nxt not in trading and nxt <= d1:
            nxt = date.fromordinal(nxt.toordinal() + 1)
        return nxt == dd
    sells2 = set()
    for s in sells:
        if is_first_td_after_expiry(s) and s + 1 < n:
            sells2.add(s + 1)
        else:
            sells2.add(s)
    sells = sells2
    invested = [False] * n
    pos = False
    events = []
    for i in range(n):
        if i in buys and not pos:
            pos = True; events.append([dates[i], "BUY-CLOSE"])
        if pos:
            invested[i] = True
        if i in sells and pos:
            pos = False; events.append([dates[i], "SELL-CLOSE"])
            invested[i] = True
            invested[i] = True
    return invested, buys, sells, events


def sts_sim(bars, buys, sells, start, end, chassis=False, shift=0, seed=None):
    """v12 published-form simulator, verbatim (cash outside windows)."""
    n = len(bars)
    idx = [i for i, b in enumerate(bars) if b["d"] >= start and b["d"] <= end]
    if not idx:
        return None
    bset, sset = set(buys), set(sells)
    if shift:
        rng = random.Random(seed)
        k = rng.randrange(-15, 16) or 5
        seg_lo, seg_hi = idx[0], idx[-1]
        bset = {min(seg_hi, max(seg_lo, i + k)) for i in buys if seg_lo <= i <= seg_hi}
        sset = {min(seg_hi, max(seg_lo, i + k)) for i in sells if seg_lo <= i <= seg_hi}
    cash, shares, costs = START, 0.0, 0.0
    trades, curve = [], []
    ep_start, halts, halt_until, ended = START, 0, None, False
    days_invested = 0
    pos = False
    for i in range(idx[0]):
        if i in bset:
            pos = True
        if i in sset:
            pos = False
    for posn, i in enumerate(idx):
        b = bars[i]
        if halt_until is not None and b["d"] >= halt_until:
            halt_until = None; ep_start = cash + shares * b["c"]
        if pos and shares == 0.0 and halt_until is None and not ended and cash > 0:
            bv = cash / (1 + STK_COST); cfee = bv * STK_COST
            shares = bv / b["c"]; cash -= bv + cfee; costs += cfee
            trades.append([b["d"], "BUY-CLOSE", round(b["c"], 4), round(bv, 2), round(cfee, 2)])
        eq = cash + shares * b["c"]
        if shares > 0:
            days_invested += 1
        curve.append([b["d"], round(eq, 4)])
        if i in bset:
            pos = True
            if shares == 0.0 and halt_until is None and not ended and cash > 0:
                bv = cash / (1 + STK_COST); cfee = bv * STK_COST
                shares = bv / b["c"]; cash -= bv + cfee; costs += cfee
                trades.append([b["d"], "BUY-CLOSE", round(b["c"], 4), round(bv, 2), round(cfee, 2)])
                curve[-1] = [b["d"], round(cash + shares * b["c"], 4)]
        if i in sset and shares > 0:
            val = shares * b["c"]; cfee = val * STK_COST + STK_SELL_FEE
            cash += val - cfee; costs += cfee; shares = 0.0
            trades.append([b["d"], "SELL-CLOSE", round(b["c"], 4), round(val, 2), round(cfee, 2)])
            curve[-1] = [b["d"], round(cash, 4)]
            pos = False
        elif i in sset:
            pos = False
        if chassis and not ended and halt_until is None:
            eq_now = curve[-1][1]
            if eq_now <= 0.85 * ep_start:
                halts += 1
                if shares > 0:
                    val = shares * b["c"]; cfee = val * STK_COST + STK_SELL_FEE
                    cash += val - cfee; costs += cfee; shares = 0.0
                    trades.append([b["d"], "SELL-FLOOR", round(b["c"], 4), round(val, 2), round(cfee, 2)])
                    curve[-1] = [b["d"], round(cash, 4)]
                pos = False
                if halts == 1:
                    halt_until = date.fromordinal(date.fromisoformat(b["d"]).toordinal() + 90).isoformat()
                else:
                    ended = True
    if shares > 0:
        last = bars[idx[-1]]; val = shares * last["c"]
        cfee = val * STK_COST + STK_SELL_FEE
        cash += val - cfee; costs += cfee; shares = 0.0
        trades.append([last["d"], "SELL-END", round(last["c"], 4), round(val, 2), round(cfee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "invested_pct": round(100.0 * days_invested / len(idx), 1) if idx else 0.0,
            "halts": halts, "equity_curve": curve}


# ---------------------------------------------------------------------------
# v13 swap chassis: SPY outside windows, SSO inside. Exposure state after
# each close replicates sts_sim's event order exactly:
#   state_after = False if sell-event else (state_before or buy-event)
# The asset held over interval (i -> i+1) is SSO iff state_after[i].
# Swaps execute at close i (sell old leg + buy new leg, costs both sides).
# ---------------------------------------------------------------------------

def state_series(n, buys, sells):
    st = [False] * n
    pos = False
    for i in range(n):
        if i in buys:
            pos = True
        if i in sells:
            pos = False
        st[i] = pos
    return st


def swap_sim(spy, sso_close, state, start, end, shift_seed=None):
    idx = [i for i, b in enumerate(spy) if b["d"] >= start and b["d"] <= end]
    if not idx:
        return None
    st = list(state)
    if shift_seed is not None:
        # v12 placebo convention: shift the buys/sells sets is equivalent to
        # shifting event indices; here we shift via precomputed shifted sets
        # (caller passes state built from shifted sets) — not used.
        raise ValueError("pass shifted state instead")
    cash, shares, costs = START, 0.0, 0.0
    asset = None  # 'SSO' if state entering, else 'SPY'
    trades, curve = [], []
    swaps = 0
    days_sso = 0

    def px(i, a):
        return sso_close[spy[i]["d"]] if a == "SSO" else spy[i]["c"]

    # state entering the road = state after close of the bar before idx[0]
    enter_state = st[idx[0] - 1] if idx[0] > 0 else False
    for posn, i in enumerate(idx):
        b = spy[i]
        if posn == 0:
            asset = "SSO" if enter_state else "SPY"
            bv = cash / (1 + STK_COST); cfee = bv * STK_COST
            shares = bv / px(i, asset); cash -= bv + cfee; costs += cfee
            trades.append([b["d"], f"BUY-INIT-{asset}", round(px(i, asset), 4),
                           round(bv, 2), round(cfee, 2)])
        eq = cash + shares * px(i, asset)
        if asset == "SSO":
            days_sso += 1
        curve.append([b["d"], round(eq, 4)])
        # events at this close: target asset for the next interval
        want = "SSO" if st[i] else "SPY"
        if want != asset:
            val = shares * px(i, asset); sfee = val * STK_COST + STK_SELL_FEE
            cash += val - sfee; costs += sfee
            trades.append([b["d"], f"SELL-{asset}", round(px(i, asset), 4),
                           round(val, 2), round(sfee, 2)])
            bv = cash / (1 + STK_COST); bfee = bv * STK_COST
            shares = bv / px(i, want); cash -= bv + bfee; costs += bfee
            trades.append([b["d"], f"BUY-{want}", round(px(i, want), 4),
                           round(bv, 2), round(bfee, 2)])
            asset = want; swaps += 1
            curve[-1] = [b["d"], round(cash + shares * px(i, asset), 4)]
    if shares > 0:
        last = spy[idx[-1]]; val = shares * px(idx[-1], asset)
        cfee = val * STK_COST + STK_SELL_FEE
        cash += val - cfee; costs += cfee; shares = 0.0
        trades.append([last["d"], f"SELL-END-{asset}", round(px(idx[-1], asset), 4),
                       round(val, 2), round(cfee, 2)])
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "orders": len(trades), "trades": trades,
            "swaps": swaps,
            "sso_pct": round(100.0 * days_sso / len(idx), 1) if idx else 0.0,
            "equity_curve": curve}


def shifted_state(n, buys, sells, lo, hi, seed):
    """v12 placebo convention: shift buys/sells by k in [-15,15] (rng per
    seed), clamped inside [lo,hi]; rebuild the state series."""
    rng = random.Random(seed)
    k = rng.randrange(-15, 16) or 5
    bset = {min(hi, max(lo, i + k)) for i in buys if lo <= i <= hi}
    sset = {min(hi, max(lo, i + k)) for i in sells if lo <= i <= hi}
    # state entering the segment: replay unshifted events before lo, then
    # shifted events from lo on (matches sts_sim's shift handling, which
    # replays the shifted sets only inside the road and the original state
    # before it — sts_sim replays bset/sset from index 0; the shifted sets
    # only contain in-road indices, so pre-road replay sees no events.
    # To mirror v12 exactly we rebuild state from the shifted sets alone
    # for i>=lo and from the ORIGINAL sets for i<lo is NOT what v12 does;
    # v12's sts_sim replays the SHIFTED sets over range(idx[0]) too, but
    # those sets contain only in-road indices, so pre-road pos=False.
    # We mirror that: state before lo = False for placebos.)
    st = [False] * n
    pos = False
    for i in range(n):
        if i in bset:
            pos = True
        if i in sset:
            pos = False
        st[i] = pos
    return st, k


def main():
    out = {"family": "hunt-fosback-seasonality-timing (Fosback Market Logic STS, 1976)",
           "program": "v13 BEST RULES — spec frozen in BEST-RULES-SPEC.md before this run",
           "my_rules": "Fosback windows EXACTLY as published (1976); SSO (2x) inside windows, SPY outside, never cash; swaps at the rule-named closes; program costs every leg; NO floor",
           "costs": "stocks 0.10%/side + $0.01 sell fee, every leg",
           "coins": {"status": "NOT-APPLICABLE per v12 spec: defined on exchange holidays and options-expiration days; a 24/7 market has neither"},
           "roads": {}}
    spy = load_pxfull("SPY")
    sso = load_pxfull("SSO", path=os.path.join(HERE, "data", "SSO.json"))
    sso_close = {b["d"]: b["c"] for b in sso}
    missing = [b["d"] for b in spy if b["d"] >= "2010-01-04" and b["d"] not in sso_close]
    assert not missing, f"SSO missing {len(missing)} SPY dates, first {missing[:3]}"
    invested, buys, sells, events = build_windows(spy)
    state = state_series(len(spy), buys, sells)
    out["windows"] = {"buys": len(buys), "sells": len(sells),
                      "in_window_day_share_pct": round(100.0 * sum(state) / len(state), 1)}
    out["sso_data"] = {"range": f"{sso[0]['d']} -> {sso[-1]['d']}", "bars": len(sso),
                        "source": "fresh public Yahoo chart pull, ./data/SSO.json (this folder)"}
    out["spy_data"] = {"range": f"{spy[0]['d']} -> {spy[-1]['d']}", "bars": len(spy)}
    print("windows:", out["windows"])
    champ_beats = []
    for name, (s, e) in ROADS.items():
        idx = [i for i, b in enumerate(spy) if b["d"] >= s and b["d"] <= e]
        lo, hi = idx[0], idx[-1]
        mine = swap_sim(spy, sso_close, state, s, e)
        pub = sts_sim(spy, buys, sells, s, e, chassis=False)
        bh = buy_hold(spy, s, e, STK_COST, STK_SELL_FEE)
        finals, ks = [], []
        for seed in range(1, 21):
            st_s, k = shifted_state(len(spy), buys, sells, lo, hi, seed)
            pr = swap_sim(spy, sso_close, st_s, s, e)
            finals.append(pr["final"]); ks.append(k)
        rec = {"my_rules": {**mine, "period_stats": period_stats(mine["equity_curve"], "monthly")},
               "published_form_inrun": {k2: pub[k2] for k2 in
                                        ("final", "max_dd_pct", "costs", "orders", "invested_pct")},
               "published_form_v12_final": PUBFORM[name],
               "benchmark_hold": {"name": "SPY buy-and-hold (same plumbing)",
                                  "final": bh["final"], "max_dd_pct": bh["max_dd_pct"],
                                  "period_stats": period_stats(bh["equity_curve"], "monthly")},
               "spy_program_ref": SPYREF[name],
               "champion_vm": CHAMP[name],
               "placebo_my_rules": {
                   "seed_finals": finals, "seed_offsets": ks,
                   "beaten_of_20": sum(1 for p in finals if mine["final"] > p),
                   "median": round(statistics.median(finals), 2),
                   "design": "phase-shifted calendars: buys/sells shifted by a random offset in [-15,15] trading days (20 seeds, v12 convention), identical SPY/SSO swap chassis and costs"}}
        out["roads"][name] = rec
        if mine["final"] > CHAMP[name]:
            champ_beats.append(name)
        print(f"{name}: MINE ${mine['final']} (DD {mine['max_dd_pct']}%, SSO {mine['sso_pct']}%, "
              f"swaps {mine['swaps']}, costs ${mine['costs']}, placebos {rec['placebo_my_rules']['beaten_of_20']}/20) | "
              f"published in-run ${pub['final']} (v12 ${PUBFORM[name]}) | hold ${bh['final']} (ref ${SPYREF[name]}) | champ ${CHAMP[name]}")
    # ---- confirmation, ONLY if a champion fell (spec choice 8, frozen) ----
    conf = {}
    for name in champ_beats:
        s, e = ROADS[name]
        years = sorted({b["d"][:4] for b in spy if s <= b["d"] <= e})
        folds, wins = [], 0
        for y in years:
            ys = max(s, f"{y}-01-01"); ye = min(e, f"{y}-12-31")
            fm = swap_sim(spy, sso_close, state, ys, ye)
            fb = buy_hold(spy, ys, ye, STK_COST, STK_SELL_FEE)
            if fm is None or fb is None:
                continue
            folds.append({"year": y, "mine": fm["final"], "spy_hold": fb["final"],
                          "beat_hold": fm["final"] > fb["final"]})
            wins += fm["final"] > fb["final"]
        comp = 100.0
        for f in folds:
            comp *= f["mine"] / 100.0
        mid = spy[[i for i, b in enumerate(spy) if s <= b["d"] <= e][
            len([i for i, b in enumerate(spy) if s <= b["d"] <= e]) // 2]]["d"]
        halves = []
        for hs, he in ((s, mid), (mid, e)):
            hm = swap_sim(spy, sso_close, state, hs, he)
            hb = buy_hold(spy, hs, he, STK_COST, STK_SELL_FEE)
            halves.append({"span": f"{hs}->{he}", "mine": hm["final"],
                           "spy_hold": hb["final"], "beat_hold": hm["final"] > hb["final"]})
        bars = {"yearly_folds_compounded": round(comp, 2),
                "folds_beat_champion": comp > CHAMP[name],
                "majority_years_beat_hold": wins * 2 > len(folds),
                "years_beat_hold": f"{wins}/{len(folds)}",
                "both_halves_beat_hold": all(h["beat_hold"] for h in halves),
                "placebo_ge_18": out["roads"][name]["placebo_my_rules"]["beaten_of_20"] >= 18}
        bars["CONFIRMED"] = all([bars["folds_beat_champion"],
                                 bars["majority_years_beat_hold"],
                                 bars["both_halves_beat_hold"], bars["placebo_ge_18"]])
        conf[name] = {"folds": folds, "halves": halves, "bars": bars}
        print(f"CONFIRMATION {name}: {bars}")
    out["confirmation"] = conf
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
