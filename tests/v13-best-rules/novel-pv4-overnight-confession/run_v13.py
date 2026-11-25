#!/usr/bin/env python3
"""
V13 BEST RULES — N-PV4 "THE OVERNIGHT CONFESSION".
Spec frozen in BEST-RULES-SPEC.md BEFORE this run. Simulation only.

MY FORM (v13):
  event: gap = Open_t/Close_{t-1} - 1 <= -2.0% AND Close_t >= Close_{t-1}*1.005
         (decisive reclaim), on adjusted prices.
  regime gate: SPY close on signal day > trailing 200-day mean of SPY closes
         (>=200 SPY bars required, else no trade).
  entry: next session open, 1/5 of pot marked at signal-day close, max 5
         concurrent, one per name, same-day overflow by gap size.
  exit: open of 3rd trading day after entry (2 full days held); falsification
         stop — a close below the signal day's LOW exits at the next open.
  NO pot floor. Costs 0.10%/side + $0.01/sell.

PUBLISHED FORM (comparison, v8 spec verbatim): gap <= -2.0%, Close_t >=
  Close_{t-1}; entry next open 1/5 slices, max 5; exit open of 11th trading
  day after entry; plain $85 floor with next-open halt liquidation.

Data: program v5 Yahoo cache (research/v5/cache/px_<T>.json, 2015-12-01 ->
2026-11-20), adjusted open/low = raw * adjclose/close, close = adjclose —
the champion engine's identical price basis. Public data only.
"""
import json, os, random, time

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/workspace/stock-app/research/v5/cache")
UNIVERSE = ['AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'BRK-B', 'JPM', 'XOM',
            'JNJ', 'PG', 'V', 'WMT', 'HD', 'BAC', 'CVX', 'PFE', 'VZ', 'T',
            'DIS', 'NFLX', 'INTC', 'CSCO', 'GE', 'IBM', 'MMM', 'UNH', 'MA',
            'KO', 'PEP', 'WFC']
START = 100.0
ROADS = {"DECADE": ("2016-01-01", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"),
         "VAL": ("2023-01-03", "2026-11-20")}


def load(t):
    j = json.load(open(os.path.join(CACHE, f"px_{t}.json")))
    res = j["chart"]["result"][0]
    ts, q = res["timestamp"], res["indicators"]["quote"][0]
    adj = res["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, x in enumerate(ts):
        c = q["close"][i]
        if c is None or q["open"][i] is None:
            continue
        a = adj[i] if adj[i] else c
        r = a / c
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(x)),
                     "o": q["open"][i] * r, "l": q["low"][i] * r, "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


BARS = {t: load(t) for t in UNIVERSE + ["SPY"]}
IDX = {t: {b["d"]: i for i, b in enumerate(BARS[t])} for t in BARS}
BAR = {t: {b["d"]: b for b in BARS[t]} for t in BARS}
DATES = sorted(BAR["SPY"].keys())

# SPY 200-day trailing mean of closes (point-in-time: bars <= d only)
SPY_MA = {}
spy = BARS["SPY"]
run = 0.0
for i, b in enumerate(spy):
    run += b["c"]
    if i >= 200:
        run -= spy[i - 200]["c"]
    SPY_MA[b["d"]] = (run / 200.0) if i >= 199 else None


def close_on_or_before(t, d):
    i = IDX[t].get(d)
    if i is None:
        cand = [x for x in BARS[t] if x["d"] <= d]
        return cand[-1]["c"] if cand else None
    return BARS[t][i]["c"]


def next_open(t, d):
    i = IDX[t].get(d)
    if i is None or i + 1 >= len(BARS[t]):
        return None, None
    nb = BARS[t][i + 1]
    return nb["d"], nb["o"]


def scan_events(decisive, gated):
    evs = []
    for t in UNIVERSE:
        bl = BARS[t]
        for i in range(1, len(bl)):
            p, cur = bl[i - 1], bl[i]
            g = cur["o"] / p["c"] - 1.0
            if g > -0.02:
                continue
            if decisive:
                if cur["c"] < p["c"] * 1.005:
                    continue
            elif cur["c"] < p["c"]:
                continue
            if gated:
                ma = SPY_MA.get(cur["d"])
                spy_c = BAR["SPY"].get(cur["d"])
                if ma is None or spy_c is None or spy_c["c"] <= ma:
                    continue
            evs.append({"ticker": t, "signal": cur["d"], "gap_pct": round(g * 100, 3),
                        "sig_low": cur["l"]})
    evs.sort(key=lambda e: (e["signal"], e["gap_pct"]))
    return evs


def window_events(evs, start, end):
    out = []
    for ev in evs:
        if not (start <= ev["signal"] <= end):
            continue
        nd, _ = next_open(ev["ticker"], ev["signal"])
        if nd is None or nd > end:
            continue
        out.append({**ev, "entry": nd})
    return out


def run_pot(sched, start, end, names, hold_after, floor, falsify):
    cash, positions, trades, taken, skipped = START, {}, [], [], []
    total_costs, halted = 0.0, None
    curve = []
    days = [d for d in DATES if start <= d <= end]
    entries = {}
    for i, ev in enumerate(sched):
        entries.setdefault(ev["entry"], []).append(i)

    def pot_close(d):
        v = cash
        for t, p in positions.items():
            c = close_on_or_before(t, d)
            if c:
                v += p["shares"] * c
        return v

    def sell(t, sh, px, d, kind):
        nonlocal cash, total_costs
        val = sh * px
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((d, t, kind, round(sh, 4), round(px, 4), round(val, 2), round(c, 4)))

    pending_halt = False
    for di, d in enumerate(days):
        if pending_halt:
            for t in list(positions):
                b = BAR[t].get(d)
                if b:
                    sell(t, positions[t]["shares"], b["o"], d, "SELL-HALT")
                del positions[t]
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "curve": curve, "taken": taken,
                    "skipped": skipped}
        # exits due today (scheduled or falsification flagged yesterday)
        for t in list(positions):
            if positions[t]["exit"] == d:
                b = BAR[t].get(d)
                if b:
                    sell(t, positions[t]["shares"], b["o"], d,
                         positions[t].get("exit_kind", "SELL-EXIT"))
                del positions[t]
        # entries
        for i in entries.get(d, []):
            ev, t = sched[i], names[i]
            if t in positions:
                skipped.append({**ev, "bought": t, "why": "name already held"})
                continue
            if len(positions) >= 5:
                skipped.append({**ev, "bought": t, "why": "5 positions already open"})
                continue
            sig = ev["signal"]
            marked = cash + sum(p["shares"] * (close_on_or_before(tt, sig) or 0)
                                for tt, p in positions.items())
            target = marked / 5.0
            b = BAR[t].get(d)
            if not b:
                skipped.append({**ev, "bought": t, "why": "no bar on entry day"})
                continue
            buy_val = min(target, cash / 1.001)
            if buy_val <= 0.005:
                skipped.append({**ev, "bought": t, "why": "insufficient cash"})
                continue
            sh = buy_val / b["o"]
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            ei = IDX[t][d]
            exit_d = BARS[t][ei + hold_after]["d"] if ei + hold_after < len(BARS[t]) else None
            # falsification reference: drawn/actual name's low on the signal date
            sb = BAR[t].get(sig)
            positions[t] = {"shares": sh, "entry": d, "exit": exit_d,
                            "sig_low": sb["l"] if sb else None}
            trades.append((d, t, "BUY", round(sh, 4), round(b["o"], 4),
                           round(buy_val, 2), round(c, 4)))
            taken.append({**ev, "bought": t, "entry": d, "exit": exit_d})
        # end of day: falsification check, then floor check
        v = pot_close(d)
        curve.append((d, round(v, 4)))
        if falsify:
            for t, p in positions.items():
                c = close_on_or_before(t, d)
                if c is not None and p["sig_low"] is not None and c < p["sig_low"]:
                    nd, _ = next_open(t, d)
                    if nd and (p["exit"] is None or nd < p["exit"]):
                        p["exit"] = nd
                        p["exit_kind"] = "SELL-FALSIFY"
        if floor is not None and v <= floor and di < len(days) - 1:
            halted = d
            pending_halt = True
    last = days[-1]
    for t in list(positions):
        px = close_on_or_before(t, last)
        if px:
            sell(t, positions[t]["shares"], px, last, "SELL-END")
        del positions[t]
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": halted, "curve": curve, "taken": taken, "skipped": skipped}


def diagnostics(curve):
    if not curve:
        return {}
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    worst_v, worst_d = min(curve, key=lambda kv: kv[1])[1], min(curve, key=lambda kv: kv[1])[0]
    for d, v in curve:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    # quarterly distribution
    q = {}
    for d, v in curve:
        q[d[:4] + "Q" + str((int(d[5:7]) - 1) // 3 + 1)] = v
    keys = sorted(q)
    rets, prev = [], START
    for k in keys:
        rets.append((k, q[k] / prev - 1.0))
        prev = q[k]
    vals = sorted(r for _, r in rets)
    n = len(vals)
    median = vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2
    pos = sum(1 for r in vals if r > 0)
    streak = longest = 0
    for _, r in rets:
        streak = streak + 1 if r <= 0 else 0
        longest = max(longest, streak)
    peak, since, longest_nh = -1.0, 0, 0
    for k in keys:
        if q[k] > peak:
            peak, since = q[k], 0
        else:
            since += 1
        longest_nh = max(longest_nh, since)
    return {"max_drawdown_pct": round(maxdd * 100, 2), "max_drawdown_date": maxdd_d,
            "worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "periods": n, "median_period_pct": round(median * 100, 2),
            "pct_periods_positive": round(pos / n * 100, 1) if n else None,
            "best_period_pct": round(max(vals) * 100, 2) if vals else None,
            "worst_period_pct": round(min(vals) * 100, 2) if vals else None,
            "longest_losing_streak_periods": longest,
            "longest_stretch_between_new_highs_periods": longest_nh,
            "avg_period_pct_secondary": round(sum(vals) / n * 100, 2) if n else None,
            "quarterly": [(k, round(r * 100, 2)) for k, r in rets]}


def spy_net(start, end):
    bl = [b for b in BARS["SPY"] if start <= b["d"] <= end]
    sh = (START / 1.001) / bl[0]["o"]
    val = sh * bl[-1]["c"]
    return round(val - (val * 0.001 + 0.01), 2)


def main():
    my_events_all = scan_events(decisive=True, gated=True)
    pub_events_all = scan_events(decisive=False, gated=False)
    out = {"family": "novel-pv4-overnight-confession",
           "spec": "v13 BEST-RULES-SPEC.md (frozen before run)",
           "data": "research/v5/cache Yahoo bars 2015-12-01..2026-11-20, adjusted o/l/c",
           "roads": {}}
    print(f"events total: mine(gated,decisive)={len(my_events_all)} published={len(pub_events_all)}", flush=True)
    for road, (ws, we) in ROADS.items():
        sched = window_events(my_events_all, ws, we)
        mine = run_pot(sched, ws, we, [e["ticker"] for e in sched],
                       hold_after=2, floor=None, falsify=True)
        psched = window_events(pub_events_all, ws, we)
        pub = run_pot(psched, ws, we, [e["ticker"] for e in psched],
                      hold_after=11, floor=85.0, falsify=False)
        seeds = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            names = [rng.choice([t for t in UNIVERSE if t != e["ticker"]]) for e in sched]
            pr = run_pot(sched, ws, we, names, hold_after=2, floor=None, falsify=True)
            seeds.append(round(pr["final"], 2))
        ss = sorted(seeds)
        med = (ss[9] + ss[10]) / 2.0
        beaten = sum(1 for s in seeds if mine["final"] > s)
        per_year = {}
        for e in sched:
            per_year[e["signal"][:4]] = per_year.get(e["signal"][:4], 0) + 1
        out["roads"][road] = {
            "window": [ws, we], "my_events": len(sched), "events_per_year": per_year,
            "my_taken": len(mine["taken"]), "my_skipped": len(mine["skipped"]),
            "my_final": round(mine["final"], 2),
            "my_return_pct": round((mine["final"] / START - 1) * 100, 2),
            "my_costs": round(mine["costs"], 2), "my_orders": len(mine["trades"]),
            "my_diag": diagnostics(mine["curve"]), "my_curve": mine["curve"],
            "my_trades": mine["trades"],
            "placebo_median": round(med, 2), "placebo_beaten": beaten,
            "placebo_seeds": seeds,
            "published_events": len(psched), "published_taken": len(pub["taken"]),
            "published_final": round(pub["final"], 2),
            "published_costs": round(pub["costs"], 2),
            "published_orders": len(pub["trades"]), "published_halted": pub["halted"],
            "published_diag": diagnostics(pub["curve"]),
            "spy_net_this_data": spy_net(ws, we)}
        print(f"{road}: MINE ${mine['final']:,.2f} (ev {len(sched)}, taken {len(mine['taken'])}, "
              f"costs ${mine['costs']:.2f}) placebo med ${med:,.2f} beaten {beaten}/20 | "
              f"PUBLISHED ${pub['final']:,.2f} halted={pub['halted']} | SPY(this data) ${spy_net(ws, we):,.2f}",
              flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
