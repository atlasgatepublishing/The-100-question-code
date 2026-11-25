#!/usr/bin/env python3
"""
V12 JUDGMENT-CONSTRUCTED Darvas, FULL METHOD — frozen per JUDGMENT-SPEC.md.
Base box mechanics: hunt-darvas-box/SPEC-FROZEN.md (covered base, not the verdict).
Judgment layer J1-J7 per JUDGMENT-SPEC.md in this folder. Simulation only.
Reads ONLY cached data (read-only). Writes only here.
"""
import json, os, sys, math, random, gzip, time
from bisect import bisect_right
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
sys.path.insert(0, os.path.join(BT, "long-run-2010"))
import lr_common as lr

START_CASH = 100.0
FLOOR = 85.0
BUY_COST = 0.001
SELL_COST = 0.001
SELL_FEE = 0.01
MAX_POS = 3            # J4
PILOT_FRAC = 0.10      # J2
ADD_FRAC = 0.10        # J3
MAX_ADDS = 2

def load_bars(ticker):
    path = os.path.join(LH, f"pxfull_{ticker}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        payload = json.load(f)
    try:
        res = payload["chart"]["result"][0]
    except Exception:
        return None
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        c = q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        r = a / c if c else 1.0
        o, h, l = q["open"][i], q["high"][i], q["low"][i]
        v = q["volume"][i] or 0
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        bars.append({"d": d, "o": (o * r if o else a), "h": (h * r if h else a),
                     "l": (l * r if l else a), "c": a, "v": float(v)})
    bars.sort(key=lambda b: b["d"])
    out, seen = [], set()
    for b in bars:
        if b["d"] in seen:
            continue
        seen.add(b["d"]); out.append(b)
    return out

FACTS_DIRS = [os.path.join(BT, "v5", "vm-broad", "data"),
              os.path.join(BT, "long-run-2010", "data"), LH,
              os.path.join(BT, "v4", "data"),
              os.path.join(BT, "v9-muse-rules", "quality-momentum", "data"),
              os.path.join(BT, "v4", "basket-issuance-veto-data"),
              os.path.join(BT, "v4", "value-momentum-honest-data")]

def load_facts_for(ticker):
    try:
        cik = lr.cik_for(ticker)
    except Exception:
        return None
    cik = int(cik[0]) if isinstance(cik, (list, tuple)) else int(cik)
    for dd in FACTS_DIRS:
        p = os.path.join(dd, f"facts_{cik:010d}.json")
        if os.path.exists(p) and os.path.getsize(p) > 100:
            with open(p, "rb") as f:
                blob = f.read()
            if blob[:2] == b"\x1f\x8b":
                blob = gzip.decompress(blob)
            return json.loads(blob)
    return None

def concept_rows(facts, concept, dur_lo=None, dur_hi=None):
    try:
        units = facts["facts"]["us-gaap"][concept]["units"]
    except KeyError:
        return {}
    key = "USD" if "USD" in units else ("USD/shares" if "USD/shares" in units else list(units)[0])
    by_end = {}
    for e in units[key]:
        if "filed" not in e or "val" not in e or "end" not in e:
            continue
        if dur_lo is not None:
            if "start" not in e:
                continue
            dur = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days
            if not (dur_lo <= dur <= dur_hi):
                continue
        by_end.setdefault(e["end"], []).append((e["filed"], float(e["val"])))
    for k in by_end:
        by_end[k].sort()
    return by_end

def asof(by_end, end, d):
    rows = by_end.get(end)
    if not rows:
        return None
    vals = [v for f, v in rows if f < d]
    return vals[-1] if vals else None

def latest_end(by_end, d):
    best = None
    for end, rows in by_end.items():
        if any(f < d for f, _ in rows) and (best is None or end > best):
            best = end
    return best

def shift_year(end, years=-1):
    y, m, dd = int(end[:4]) + years, end[5:7], end[8:10]
    if m == "02" and dd == "29":
        dd = "28"
    return f"{y:04d}-{m}-{dd}"

def find_end_near(by_end, target, tol_days=25):
    t = date.fromisoformat(target).toordinal()
    best, bd = None, tol_days + 1
    for end in by_end:
        diff = abs(date.fromisoformat(end).toordinal() - t)
        if diff < bd:
            bd, best = diff, end
    return best

class Fund:
    def __init__(self, facts):
        self.q_eps = concept_rows(facts, "EarningsPerShareDiluted", 80, 100)
        self.a_eps = concept_rows(facts, "EarningsPerShareDiluted", 330, 400)
    def eps_ok(self, d):
        # J1c: quarterly EPS YoY > 0 (both positive) OR annual EPS up YoY
        end = latest_end(self.q_eps, d)
        if end is not None:
            cur = asof(self.q_eps, end, d)
            pe = find_end_near(self.q_eps, shift_year(end))
            prev = asof(self.q_eps, pe, d) if pe else None
            if cur is not None and prev is not None and cur > 0 and prev > 0 and cur > prev:
                return True
        ends = sorted(e for e in self.a_eps if any(f < d for f, _ in self.a_eps[e]))
        if len(ends) >= 2:
            v1 = asof(self.a_eps, ends[-1], d); v0 = asof(self.a_eps, ends[-2], d)
            if v1 is not None and v0 is not None and v0 > 0 and v1 > v0:
                return True
        return False

class Series:
    def __init__(self, bars):
        self.bars = bars
        self.dates = [b["d"] for b in bars]
        self.idx = {b["d"]: i for i, b in enumerate(bars)}
        self.c = [b["c"] for b in bars]
        self.v = [b["v"] for b in bars]
        self.h = [b["h"] for b in bars]
        self.l = [b["l"] for b in bars]
        self.o = [b["o"] for b in bars]
        self.ma50 = [None]*len(bars)
        for i in range(49, len(bars)):
            self.ma50[i] = sum(self.c[i-49:i+1])/50
        self.ret126 = [None]*len(bars)
        for i in range(126, len(bars)):
            if self.c[i-126] > 0:
                self.ret126[i] = self.c[i]/self.c[i-126]-1

def build_boxes(s):
    """Sequential Darvas boxes per the frozen base spec.
    Returns (boxes, events): boxes = [{upper, lower, confirm_i}], events =
    [{box_i, break_i}] breakouts (high > upper within 126 sessions, no prior
    close below lower)."""
    bars = s.bars; n = len(bars)
    boxes, events = [], []
    i = 0
    while i < n - 6:
        # seek upper: running max high, 3 consecutive days high < max
        run_max = bars[i]["h"]; cnt = 0; upper = None; j = i
        while j < n:
            h = bars[j]["h"]
            if h > run_max:
                run_max = h; cnt = 0
            elif h < run_max:
                cnt += 1
                if cnt >= 3:
                    upper = run_max; break
            else:
                cnt = 0
            j += 1
        if upper is None:
            break
        # seek lower after j
        run_min = None; cnt = 0; lower = None; k = j + 1
        while k < n:
            l = bars[k]["l"]
            if run_min is None or l < run_min:
                run_min = l; cnt = 0
            elif l > run_min:
                cnt += 1
                if cnt >= 3:
                    lower = run_min; break
            else:
                cnt = 0
            k += 1
        if lower is None:
            break
        bi = len(boxes)
        boxes.append({"upper": upper, "lower": lower, "confirm_i": k})
        # breakout watch
        broke = None
        for m in range(k + 1, min(n, k + 127)):
            if bars[m]["c"] < lower:
                break
            if bars[m]["h"] > upper:
                broke = m; break
        if broke is not None:
            events.append({"box_i": bi, "break_i": broke})
            i = broke + 1
        else:
            i = k + 1
    return boxes, events

def simulate(days_set, master, series_by, boxes_by, events_by, rs_rank, spy_ret,
             funds, start, end, placebo=None):
    """placebo: None = real run; else list of (entry_date, exit_date, frac)."""
    cash = START_CASH; pos = {}; curve = []; trades = []
    total_costs = 0.0; halted = None; entries_made = []
    days = [d for d in master if start <= d <= end]
    ev_by_date = {}
    if placebo is None:
        for t, evs in events_by.items():
            for ev in evs:
                ev_by_date.setdefault(series_by[t].dates[ev["break_i"]], []).append((t, ev))
    p_plan = {}
    if placebo is not None:
        for (ed, xd, frac, seed_t) in placebo:
            p_plan.setdefault(ed, []).append((xd, frac, seed_t))

    def equity(d):
        v = cash
        for t, p in pos.items():
            s = series_by[t]; j = bisect_right(s.dates, d) - 1
            v += p["shares"] * (s.c[j] if j >= 0 else 0.0)
        return v

    def sell(t, d, px, why):
        nonlocal cash, total_costs
        p = pos.pop(t)
        val = p["shares"] * px
        cst = val * SELL_COST + SELL_FEE if val > 0 else 0.0
        cash += val - cst; total_costs += cst
        trades.append([d, t, "SELL", round(px, 4), round(val, 2), why])
        return p

    stopped = {}  # ticker -> (rail, stop_date_idx) for J7
    for d in days:
        # ---------- placebo entries/exits (duration-matched)
        if placebo is not None:
            for t in list(pos):
                if pos[t].get("exit_date") == d:
                    s = series_by[t]; i = s.idx.get(d)
                    sell(t, d, s.c[i] if i is not None else 0.0, "placebo-exit")
            for (xd, frac, t) in p_plan.get(d, []):
                if t in pos or len(pos) >= MAX_POS:
                    continue
                s = series_by[t]; i = s.idx.get(d)
                if i is None:
                    continue
                px = s.c[i]
                budget = min(frac * equity(d), cash / (1 + BUY_COST))
                if budget < 1.0:
                    continue
                cst = budget * BUY_COST; cash -= budget + cst; total_costs += cst
                pos[t] = {"shares": budget / px, "fill": px, "exit_date": xd}
                trades.append([d, t, "BUY", round(px, 4), round(budget, 2), "placebo"])
            curve.append((d, equity(d)))
            if equity(d) <= FLOOR:
                for t in list(pos):
                    s = series_by[t]; j = bisect_right(s.dates, d) - 1
                    sell(t, d, s.c[j] if j >= 0 else 0.0, "floor")
                halted = d; curve[-1] = (d, cash); break
            continue
        # ---------- exits
        for t in list(pos):
            s = series_by[t]; i = s.idx.get(d)
            if i is None or d <= pos[t]["entry_date"]:
                continue
            p = pos[t]; p["days"] += 1
            bar = s.bars[i]
            # trailing stop update: most recent box completed before today
            for bx in boxes_by[t]:
                if p["entry_i"] < bx["confirm_i"] < i and bx["lower"] > p.get("trail_ref", -1):
                    p["stop"] = max(p["stop"], bx["lower"] * 0.999)
                    p["trail_ref"] = bx["lower"]
            # J6 scare-tighten
            if i >= 20:
                avg20 = sum(s.v[i-20:i]) / 20
                if avg20 > 0 and bar["v"] >= 2 * avg20 and s.c[i-1] > 0 and \
                        bar["c"] / s.c[i-1] - 1 <= -0.05:
                    p["stop"] = max(p["stop"], bar["l"] * 0.999)
            if bar["l"] <= p["stop"]:
                px = bar["o"] if bar["o"] < p["stop"] else p["stop"]
                sell(t, d, px, "stop")
                stopped[t] = (p["rail"], i)
                continue
            # J5 weakening exit
            if p["days"] >= 40 and bar["c"] > p["fill"] and s.ma50[i] and bar["c"] < s.ma50[i]:
                sell(t, d, bar["c"], "j5-weakening")
                continue
            # J3 pyramid adds on new higher box breakouts today
            for (tt, ev) in ev_by_date.get(d, []):
                if tt == t and ev["break_i"] == i and p["adds"] < MAX_ADDS:
                    bx = boxes_by[t][ev["box_i"]]
                    if bx["upper"] > p["last_add_upper"]:
                        budget = min(ADD_FRAC * equity(d), cash / (1 + BUY_COST))
                        if budget >= 1.0:
                            px = bar["c"]; cst = budget * BUY_COST
                            cash -= budget + cst; total_costs += cst
                            nsh = p["shares"] + budget / px
                            p["fill"] = (p["shares"] * p["fill"] + budget) / nsh
                            p["shares"] = nsh; p["adds"] += 1
                            p["last_add_upper"] = bx["upper"]
                            trades.append([d, t, "BUY", round(px, 4), round(budget, 2), "j3-pyramid"])
        # ---------- floor
        eq = equity(d)
        if eq <= FLOOR:
            for t in list(pos):
                s = series_by[t]; j = bisect_right(s.dates, d) - 1
                sell(t, d, s.c[j] if j >= 0 else 0.0, "floor")
            halted = d; curve.append((d, cash)); break
        # ---------- J7 re-entries
        for t, (rail, si) in list(stopped.items()):
            s = series_by[t]; i = s.idx.get(d)
            if i is None:
                continue
            if i - si > 10:
                del stopped[t]; continue
            if len(pos) < MAX_POS and t not in pos and i > si:
                avg20 = sum(s.v[i-20:i]) / 20 if i >= 20 else 0
                if s.c[i] > rail and avg20 > 0 and s.v[i] >= 1.5 * avg20 and funds[t].eps_ok(d):
                    px = s.c[i]
                    budget = min(PILOT_FRAC * equity(d), cash / (1 + BUY_COST))
                    if budget >= 1.0:
                        cst = budget * BUY_COST; cash -= budget + cst; total_costs += cst
                        pos[t] = {"shares": budget / px, "fill": px, "entry_date": d,
                                  "entry_i": i, "days": 0, "stop": rail * 0.999,
                                  "rail": rail, "adds": 0, "last_add_upper": rail,
                                  "trail_ref": -1}
                        trades.append([d, t, "BUY", round(px, 4), round(budget, 2), "j7-reentry"])
                        entries_made.append((d, t, PILOT_FRAC))
                    del stopped[t]
        # ---------- entries (J1 selection on base-spec box breakouts)
        if series_by["SPY"].c[series_by["SPY"].idx[d]] > 0:
            si = series_by["SPY"].idx[d]
            spy = series_by["SPY"]
            spy_ma200 = sum(spy.c[si-199:si+1]) / 200 if si >= 199 else None
            if spy_ma200 and spy.c[si] > spy_ma200 and len(pos) < MAX_POS:
                cands = []
                for (t, ev) in ev_by_date.get(d, []):
                    if t in pos:
                        continue
                    s = series_by[t]; i = s.idx[d]
                    bx = boxes_by[t][ev["box_i"]]
                    # base: breakout volume >= 1.5x prior 20d avg
                    if i < 80:
                        continue
                    avg20 = sum(s.v[i-20:i]) / 20
                    if avg20 <= 0 or s.v[i] < 1.5 * avg20:
                        continue
                    # J1a unusual activity into the box
                    avg_prior60 = sum(s.v[i-80:i-20]) / 60
                    avg_last20 = sum(s.v[i-20:i]) / 20
                    if avg_prior60 <= 0 or avg_last20 < 1.25 * avg_prior60:
                        continue
                    # J1b leadership
                    rk = rs_rank.get(d, {}).get(t)
                    if rk is None or rk < 0.70:
                        continue
                    if s.ret126[i] is None or spy_ret.get(d) is None or s.ret126[i] <= spy_ret[d]:
                        continue
                    # J1d within 5% of cache high
                    if s.c[i] < 0.95 * max(s.h[:i+1]):
                        continue
                    # J1c earnings
                    if not funds[t].eps_ok(d):
                        continue
                    cands.append((s.ret126[i], t, bx))
                cands.sort(reverse=True)
                for (_r, t, bx) in cands:
                    if len(pos) >= MAX_POS:
                        break
                    s = series_by[t]; px = s.c[s.idx[d]]
                    budget = min(PILOT_FRAC * equity(d), cash / (1 + BUY_COST))
                    if budget < 1.0:
                        break
                    cst = budget * BUY_COST; cash -= budget + cst; total_costs += cst
                    pos[t] = {"shares": budget / px, "fill": px, "entry_date": d,
                              "entry_i": s.idx[d], "days": 0,
                              "stop": bx["upper"] * 0.999, "rail": bx["upper"],
                              "adds": 0, "last_add_upper": bx["upper"], "trail_ref": -1}
                    trades.append([d, t, "BUY", round(px, 4), round(budget, 2), "j2-pilot"])
                    entries_made.append((d, t, PILOT_FRAC))
        curve.append((d, equity(d)))
    # ---------- end of road
    if halted is None and curve:
        for t in list(pos):
            s = series_by[t]
            if s.dates and s.dates[-1] >= end:
                px = s.c[s.idx[end]] if end in s.idx else s.c[-1]
                sell(t, end, px, "end")
            else:
                sell(t, end, 0.0, "vanished-zero")
        curve[-1] = (curve[-1][0], cash)
    peak, mdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return {"final": round(cash, 2), "costs": round(total_costs, 2),
            "orders": len(trades), "halted": halted,
            "max_dd_pct": round(mdd * 100, 2),
            "curve": [[d, round(v, 2)] for d, v in curve],
            "trades": trades, "entries": entries_made}

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}

def main():
    series_by, funds, failures = {}, {}, []
    for t in lr.POOL:
        bars = load_bars(t)
        if not bars or len(bars) < 300:
            failures.append((t, "no/short price cache")); continue
        facts = load_facts_for(t)
        if facts is None:
            failures.append((t, "no facts cache")); continue
        series_by[t] = Series(bars); funds[t] = Fund(facts)
    spy = series_by.get("SPY") or Series(load_bars("SPY"))
    series_by["SPY"] = spy
    if "SPY" not in funds:
        funds["SPY"] = Fund(load_facts_for("SPY")) if load_facts_for("SPY") else None
    master = spy.dates
    boxes_by, events_by = {}, {}
    for t, s in series_by.items():
        if t == "SPY":
            continue
        boxes_by[t], events_by[t] = build_boxes(s)
    print(f"universe {len(series_by)-1} names, failures {len(failures)}, "
          f"breakout events {sum(len(v) for v in events_by.values())}", flush=True)
    # RS rank percentile per day + SPY ret126
    rs_rank = {}; spy_ret = {}
    pool = [t for t in series_by if t != "SPY"]
    for d in master:
        si = spy.idx[d]
        spy_ret[d] = spy.ret126[si] if si is not None else None
        vals = []
        for t in pool:
            s = series_by[t]; i = s.idx.get(d)
            if i is not None and s.ret126[i] is not None:
                vals.append((s.ret126[i], t))
        if len(vals) < 20:
            continue
        vals.sort(); n = len(vals)
        rs_rank[d] = {t: r / max(n - 1, 1) for r, (_v, t) in enumerate(vals)}
    results = {"label": "JUDGMENT-CONSTRUCTED: our frozen reconstruction of Darvas's documented judgment around the boxes (hunt-darvas-box base); not Darvas's own trading.",
               "universe_size": len(series_by) - 1, "failures": failures, "roads": {}}
    for name, (start, end) in ROADS.items():
        r = simulate(None, master, series_by, boxes_by, events_by, rs_rank, spy_ret,
                     funds, start, end)
        # build matched placebo plans from real round trips
        trips = []  # (entry_date, exit_date, frac)
        open_entries = []
        for tr in r["trades"]:
            if tr[2] == "BUY" and tr[5] in ("j2-pilot", "j7-reentry"):
                open_entries.append(tr)
            elif tr[2] == "SELL":
                for k, oe in enumerate(open_entries):
                    if oe[1] == tr[1]:
                        trips.append((oe[0], tr[0], PILOT_FRAC)); open_entries.pop(k); break
        beaten = 0; pfin = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            plan = []
            for (ed, xd, frac) in trips:
                cands = [t for t in pool if ed in series_by[t].idx and xd in series_by[t].idx]
                if cands:
                    plan.append((ed, xd, frac, rng.choice(cands)))
            pr = simulate(None, master, series_by, boxes_by, events_by, rs_rank,
                          spy_ret, funds, start, end, placebo=plan)
            pfin.append(pr["final"])
            if r["final"] > pr["final"]:
                beaten += 1
        results["roads"][name] = {
            "start": start, "end": end, "final": r["final"], "costs": r["costs"],
            "orders": r["orders"], "halted": r["halted"], "max_dd_pct": r["max_dd_pct"],
            "n_entries": len(r["entries"]), "placebo_beaten": beaten,
            "placebo_finals": pfin, "curve": r["curve"], "trades": r["trades"]}
        print(f"{name}: final ${r['final']} entries {len(r['entries'])} orders {r['orders']} "
              f"halted {r['halted']} DD {r['max_dd_pct']}% placebo {beaten}/20", flush=True)
    tmp = "/tmp/darvas_results.json"
    with open(tmp, "w") as f:
        json.dump(results, f)
    import shutil
    shutil.copy(tmp, os.path.join(HERE, "results.json"))
    print("done")

if __name__ == "__main__":
    main()
