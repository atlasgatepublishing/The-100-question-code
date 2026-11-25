#!/usr/bin/env python3
"""
V13 BEST RULES — N-3 QUARTER-END WINDOW-DRESSING REBOUND (novel-x3).
Implements BEST-RULES-SPEC.md in this folder, frozen before this run:
  - entry at close of L (last trading day of quarter): sell SPY, buy the
    5 lowest quarter-to-date pond names, equal weight;
  - GATE: trade only if the basket's mean QTD return <= -5.00%;
  - exit at close of the 20th trading day of the new quarter, back to SPY;
  - NO floor / halt / sit-out;
  - costs 0.10%/side + $0.01 per sell order (program standard);
  - a zero-cost twin of the ranked run is also scored (gross vs net).
Published form (for folds/confirmation comparison only): 5-day hold, no
gate, plain $85 floor — the v8 form.
Data: read-only shared cache backtests/v7/long-hold/data pxfull payloads
+ the v10 folder's pxfull_GOOGL.json (same plumbing the family's LONG
road was run on). Integrity: SPY buy-hold net must reproduce the
published road refs before any variant number is taken.
"""
import bisect, json, math, os, random, time

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
X3V10 = os.path.join(BT, "v10-retest", "novel-x3-window-dressing")

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
START_CASH = 100.0
TOP_N = 5
HOLD_DAYS = 20
GATE = -0.05
ROADS = (("LONG", "2010-01-04", "2026-11-20"),
         ("DECADE", "2016-11-21", "2026-11-20"),
         ("CONT", "2019-01-02", "2026-11-20"),
         ("VAL", "2023-01-03", "2026-11-20"))
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
PUBLISHED = {"LONG": 891.59, "DECADE": 356.03, "CONT": 302.36, "VAL": 180.79}
SEEDS = list(range(1, 21))


def pxfull(ticker):
    path = (os.path.join(X3V10, "pxfull_GOOGL.json") if ticker == "GOOGL"
            else os.path.join(LH, f"pxfull_{ticker}.json"))
    j = json.load(open(path))
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        bars.append({"d": d, "o": (o * r if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


class Bars:
    def __init__(self, bars_by_t):
        self.bars = bars_by_t
        self.dates = {t: [b["d"] for b in bl] for t, bl in bars_by_t.items()}
        self.by_date = {t: {b["d"]: b for b in bl}
                        for t, bl in bars_by_t.items()}

    def close_on_or_before(self, t, d):
        ds = self.dates[t]
        j = bisect.bisect_right(ds, d) - 1
        return self.bars[t][j]["c"] if j >= 0 else None

    def open_on(self, t, d):
        b = self.by_date[t].get(d)
        return b["o"] if b else None


def spy_net(bx, calendar, start, end):
    days = [d for d in calendar if start <= d <= end]
    o = bx.open_on("SPY", days[0])
    sh = (START_CASH / 1.001) / o
    c = bx.close_on_or_before("SPY", days[-1])
    val = sh * c
    return val - (val * 0.001 + 0.01)


def build_events(calendar, hold_days):
    cal_idx = {d: i for i, d in enumerate(calendar)}
    qends = []
    for i, d in enumerate(calendar):
        if d[5:7] in ("03", "06", "09", "12"):
            if i == len(calendar) - 1 or calendar[i + 1][5:7] != d[5:7]:
                qends.append(d)
    events = []
    for j, L in enumerate(qends):
        i = cal_idx[L]
        if i + hold_days >= len(calendar) or j == 0:
            continue
        events.append({"L": L, "exit": calendar[i + hold_days],
                       "prev_L": qends[j - 1]})
    return events


def qtd_table(bx, ev):
    out = {}
    for t in UNIVERSE:
        c0 = bx.close_on_or_before(t, ev["prev_L"])
        c1 = bx.close_on_or_before(t, ev["L"])
        if c0 and c1 and c0 > 0:
            out[t] = c1 / c0 - 1.0
    return out


def simulate(bx, calendar, start, end, events, picker, cost_rate=0.001,
             floor=None, gate=None):
    """picker(ev, qtd) -> picks list. gate: if not None, ranked events are
    skipped when mean QTD of picks > gate (placebo runs pass gate=None and
    instead receive the ranked run's traded-event L set via picker)."""
    days = [d for d in calendar if start <= d <= end]
    ev_by_L = {e["L"]: e for e in events}
    ev_by_exit = {e["exit"]: e for e in events}
    cash = START_CASH
    positions = {}
    trades = []
    total_costs = 0.0
    curve = []
    halted = None
    event_log = []
    traded_L = []
    active_exits = set()

    def value(d):
        v = cash
        for t, sh in positions.items():
            c = bx.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def sell_all_at_close(d, tag="SELL"):
        nonlocal cash, total_costs
        for t in list(positions):
            c = bx.close_on_or_before(t, d)
            if c is None:
                continue
            val = positions[t] * c
            cost = val * cost_rate + (0.01 if cost_rate > 0 else 0.0)
            cash += val - cost
            total_costs += cost
            trades.append((d, t, tag, positions[t], c, val, cost))
            del positions[t]

    def buy_value(t, d, price, target):
        nonlocal cash, total_costs
        if price is None or price <= 0:
            return 0.0
        buy_val = min(target, cash / (1.0 + cost_rate))
        if buy_val <= 0.005:
            return 0.0
        sh = buy_val / price
        cost = buy_val * cost_rate
        cash -= buy_val + cost
        total_costs += cost
        positions[t] = positions.get(t, 0.0) + sh
        trades.append((d, t, "BUY", sh, price, buy_val, cost))
        return buy_val

    def do_entry(ev, d, boundary=False):
        qtd = qtd_table(bx, ev)
        picks = picker(ev, qtd)
        if not picks:
            return
        if gate is not None and picks:
            mean_qtd = sum(qtd[t] for t in picks) / len(picks)
            if mean_qtd > gate:
                event_log.append({"L": ev["L"], "exit": ev["exit"],
                                  "picks": [], "gated_out": True,
                                  "basket_mean_qtd_pct": round(mean_qtd * 100, 2)})
                return
        v_pre = value(d) if not boundary else START_CASH
        if not boundary:
            sell_all_at_close(d)
        for t in picks:
            buy_value(t, d, bx.close_on_or_before(t, d), v_pre / TOP_N)
        traded_L.append(ev["L"])
        active_exits.add(ev["exit"])
        rels = []
        for t in picks:
            a = bx.close_on_or_before(t, ev["L"])
            b = bx.close_on_or_before(t, ev["exit"])
            if a and b:
                rels.append(b / a)
        spy_c0 = bx.close_on_or_before("SPY", ev["L"])
        spy_c1 = bx.close_on_or_before("SPY", ev["exit"])
        event_log.append({
            "L": ev["L"], "exit": ev["exit"], "boundary": boundary,
            "picks": list(picks), "gated_out": False,
            "picks_qtd_pct": {t: round(qtd[t] * 100, 2) for t in picks if t in qtd},
            "basket_gross_pct": round((sum(rels) / len(rels) - 1) * 100, 2) if rels else None,
            "spy_gross_pct": round((spy_c1 / spy_c0 - 1) * 100, 2) if spy_c0 and spy_c1 else None})

    def do_exit(ev, d):
        sell_all_at_close(d)
        buy_value("SPY", d, bx.close_on_or_before("SPY", d), cash)

    first_ev = events[0] if events else None
    if first_ev is not None and first_ev["L"] < start:
        do_entry(first_ev, first_ev["L"], boundary=True)
    else:
        buy_value("SPY", days[0], bx.open_on("SPY", days[0]), cash)

    for k, d in enumerate(days):
        v = value(d)
        curve.append((d, v))
        if floor is not None and v <= floor and k < len(days) - 1:
            halted = d
            nd = days[k + 1]
            for t in list(positions):
                opx = bx.open_on(t, nd) or bx.close_on_or_before(t, nd)
                val = positions[t] * opx
                cost = val * cost_rate + (0.01 if cost_rate > 0 else 0.0)
                cash += val - cost
                total_costs += cost
                trades.append((nd, t, "SELL-HALT", positions[t], opx, val, cost))
            positions = {}
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "curve": curve, "events": event_log,
                    "traded_L": traded_L}
        if d in ev_by_L:
            do_entry(ev_by_L[d], d)
        if d in ev_by_exit and d in active_exits:
            do_exit(ev_by_exit[d], d)

    sell_all_at_close(days[-1], tag="SELL-END")
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "curve": curve, "events": event_log,
            "traded_L": traded_L}


def ranked_picker(ev, qtd):
    ranked = sorted(qtd.items(), key=lambda kv: (kv[1], kv[0]))
    return [t for t, _ in ranked[:TOP_N]]


def make_placebo_picker(seed, traded_L):
    rng = random.Random(seed)
    traded = set(traded_L)

    def pick(ev, qtd):
        if ev["L"] not in traded:
            return []
        return rng.sample(sorted(qtd), TOP_N)
    return pick


def diagnostics(curve):
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = round(v, 2)
    # quarterly periods
    q_end = {}
    for d, v in curve:
        q_end[d[:4] + "Q" + str((int(d[5:7]) - 1) // 3 + 1)] = v
    keys = sorted(q_end)
    rets = []
    prev = START_CASH
    for k in keys:
        rets.append(q_end[k] / prev - 1.0)
        prev = q_end[k]
    pos = sum(1 for r in rets if r > 0)
    srt = sorted(rets)
    median = srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt) // 2 - 1] + srt[len(srt) // 2]) / 2
    streak = longest = 0
    for r in rets:
        streak = streak + 1 if r <= 0 else 0
        longest = max(longest, streak)
    run_high, since, max_since = -1.0, 0, 0
    for k in keys:
        if q_end[k] >= run_high:
            run_high, since = q_end[k], 0
        else:
            since += 1
        max_since = max(max_since, since)
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "max_drawdown_pct": round(maxdd * 100, 2), "max_drawdown_date": maxdd_d,
            "year_end_closes": year_end,
            "periods": {"unit": "calendar quarter", "n": len(rets),
                        "pct_positive": round(100.0 * pos / len(rets), 1) if rets else None,
                        "median_pct": round(median * 100, 2) if rets else None,
                        "mean_pct": round(sum(rets) / len(rets) * 100, 2) if rets else None,
                        "best_pct": round(max(rets) * 100, 2) if rets else None,
                        "worst_pct": round(min(rets) * 100, 2) if rets else None,
                        "longest_losing_streak": longest,
                        "longest_stretch_between_new_highs_periods": max_since,
                        "returns_pct": [round(r * 100, 2) for r in rets]}}


def pct(sorted_vals, q):
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    f = pos - lo
    return sorted_vals[lo] * (1 - f) + sorted_vals[hi] * f


def placebo_stats(ranked_final, finals):
    s = sorted(finals)
    beat = sum(1 for f in finals if ranked_final > f)
    return {"n": len(finals), "median": round(pct(s, 0.5), 2),
            "q1": round(pct(s, 0.25), 2), "q3": round(pct(s, 0.75), 2),
            "best": round(s[-1], 2), "worst": round(s[0], 2), "beat": beat,
            "percentile": round(100.0 * beat / len(finals), 1),
            "finals": [round(f, 2) for f in finals]}


def main():
    bars = {t: pxfull(t) for t in UNIVERSE + ["SPY"]}
    bx = Bars(bars)
    calendar = [b["d"] for b in bars["SPY"]]
    print(f"calendar {calendar[0]}..{calendar[-1]} ({len(calendar)} days)", flush=True)

    integrity = {}
    for wname, ws, we in ROADS:
        s = spy_net(bx, calendar, ws, we)
        integrity[wname] = round(s, 2)
        print(f"INTEGRITY {wname}: spy_net=${s:,.2f} (published ${SPY_REF[wname]:,.2f})", flush=True)
        assert abs(round(s, 2) - SPY_REF[wname]) < 0.02, f"SPY integrity failed {wname}"

    events20 = build_events(calendar, HOLD_DAYS)
    events5 = build_events(calendar, 5)
    out = {"family": "novel-x3-window-dressing", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "my_rules": {"hold_days": HOLD_DAYS, "gate_mean_qtd_lte": GATE,
                        "top_n": TOP_N, "floor": None,
                        "costs": "0.10%/side + $0.01 per sell order"},
           "integrity_spy_net": integrity, "spy_ref": SPY_REF,
           "champion": CHAMPION, "published_form": PUBLISHED, "roads": {}}

    beats_champion = []
    for wname, ws, we in ROADS:
        evs = [e for e in events20 if ws <= e["exit"] <= we]
        r = simulate(bx, calendar, ws, we, evs, ranked_picker, gate=GATE)
        g = simulate(bx, calendar, ws, we, evs, ranked_picker,
                     cost_rate=0.0, gate=GATE)
        diag = diagnostics(r["curve"])
        traded = [e for e in r["events"] if not e["gated_out"]]
        gated = [e for e in r["events"] if e["gated_out"]]
        finals, phalted = [], 0
        for seed in SEEDS:
            pr = simulate(bx, calendar, ws, we, evs,
                          make_placebo_picker(seed, r["traded_L"]))
            finals.append(pr["final"])
            phalted += 1 if pr["halted"] else 0
        ps = placebo_stats(r["final"], finals)
        ps["halted"] = phalted
        ev_excess = [e["basket_gross_pct"] - e["spy_gross_pct"] for e in traded
                     if e["basket_gross_pct"] is not None]
        print(f"== {wname}: NET=${r['final']:,.2f} GROSS=${g['final']:,.2f} "
              f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
              f"events traded={len(traded)} gated_out={len(gated)} "
              f"maxDD={diag['max_drawdown_pct']}% placebo beat={ps['beat']}/20",
              flush=True)
        if r["final"] > CHAMPION[wname]:
            beats_champion.append(wname)
        out["roads"][wname] = {
            "start": ws, "end": we, "net_final": round(r["final"], 2),
            "gross_final_zero_cost": round(g["final"], 2),
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "halted": r["halted"], "diag": diag,
            "events_traded": len(traded), "events_gated_out": len(gated),
            "events": r["events"],
            "event_gross_excess_mean_pts": round(sum(ev_excess) / len(ev_excess), 2) if ev_excess else None,
            "event_basket_beat_spy_gross": sum(1 for x in ev_excess if x > 0),
            "placebo": ps, "spy_net": SPY_REF[wname],
            "champion": CHAMPION[wname], "published_form": PUBLISHED[wname],
            "curve": [[d, round(v, 4)] for d, v in r["curve"]],
            "trades": r["trades"]}

    out["beats_champion_roads"] = beats_champion

    # Confirmation (Terry's rule): only if a champion was beaten — fresh
    # $100 yearly folds, my form vs published form (5-day, no gate, floor).
    if beats_champion:
        folds = {}
        for year in range(2010, 2027):
            ws, we = f"{year}-01-01", f"{year}-12-31"
            evs_m = [e for e in events20 if ws <= e["exit"] <= we]
            evs_p = [e for e in events5 if ws <= e["exit"] <= we]
            if not evs_m and not evs_p:
                continue
            rm = simulate(bx, calendar, ws, we, evs_m, ranked_picker, gate=GATE)
            rp = simulate(bx, calendar, ws, we, evs_p, ranked_picker, floor=85.0)
            folds[str(year)] = {"mine": round(rm["final"], 2),
                                "published": round(rp["final"], 2)}
        comp_m = comp_p = 100.0
        won = 0
        for y, f in folds.items():
            comp_m *= f["mine"] / 100.0
            comp_p *= f["published"] / 100.0
            won += 1 if f["mine"] > f["published"] else 0
        out["confirmation_folds"] = {"folds": folds,
                                     "mine_compounded": round(comp_m, 2),
                                     "published_compounded": round(comp_p, 2),
                                     "years_won": won, "years": len(folds),
                                     "confirmed": comp_m > comp_p and won >= math.ceil(0.6 * len(folds))}
        print(f"CONFIRMATION: mine=${comp_m:,.2f} published=${comp_p:,.2f} "
              f"won {won}/{len(folds)} confirmed={out['confirmation_folds']['confirmed']}",
              flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
