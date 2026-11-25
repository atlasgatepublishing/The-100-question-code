#!/usr/bin/env python3
"""
V13 BEST-RULES Darvas — JUDGMENT-CONSTRUCTED, frozen per BEST-RULES-SPEC.md.
Changes vs the v12 judgment stack (all frozen in the spec before this run):
no pilot (full 1/3-equity slot at entry), ONE pyramid add (1/6 equity) on the
first higher-box breakout, initial stop below the entry box's LOWER rail,
single leadership test (126d return > SPY) + rank-for-slots, ONE volume gate
(breakout day >= 1.5x prior-20d), PIT earnings leg, SPY>200d market gate,
NO J5/J6/J7 machinery, NO portfolio floor. Simulation only.
Reads ONLY cached data (read-only). Writes only here (results via stdout file
handled by caller / --out path inside this folder).
Usage: run_best.py [--confirm ROAD]
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
BUY_COST = 0.001
SELL_COST = 0.001
SELL_FEE = 0.01
MAX_POS = 3
ENTRY_FRAC = 1.0 / 3.0
ADD_FRAC = 1.0 / 6.0
MAX_ADDS = 1

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
        self.ret126 = [None]*len(bars)
        for i in range(126, len(bars)):
            if self.c[i-126] > 0:
                self.ret126[i] = self.c[i]/self.c[i-126]-1
        self.runmax_h = []
        m = 0.0
        for x in self.h:
            m = max(m, x); self.runmax_h.append(m)

def build_boxes(s):
    """Sequential Darvas boxes per the published 3-day rail rule (base spec)."""
    bars = s.bars; n = len(bars)
    boxes, events = [], []
    i = 0
    while i < n - 6:
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

def simulate(master, series_by, boxes_by, events_by, spy, funds, start, end, placebo=None):
    cash = START_CASH; pos = {}; curve = []; trades = []
    total_costs = 0.0; trips = []
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
        if "entry_date" in p:
            trips.append((p["entry_date"], d, p["entry_frac"]))
        return p

    for d in days:
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
                pos[t] = {"shares": budget / px, "exit_date": xd}
                trades.append([d, t, "BUY", round(px, 4), round(budget, 2), "placebo"])
            curve.append((d, equity(d)))
            continue
        # ---------- exits (box trailing stop) + pyramid adds
        for t in list(pos):
            s = series_by[t]; i = s.idx.get(d)
            if i is None or d <= pos[t]["entry_date"]:
                continue
            p = pos[t]
            bar = s.bars[i]
            for bx in boxes_by[t]:
                if p["entry_i"] < bx["confirm_i"] < i and bx["lower"] > p.get("trail_ref", -1):
                    p["stop"] = max(p["stop"], bx["lower"] * 0.999)
                    p["trail_ref"] = bx["lower"]
            if bar["l"] <= p["stop"]:
                px = bar["o"] if bar["o"] < p["stop"] else p["stop"]
                sell(t, d, px, "stop")
                continue
            # pyramid add: first higher-box breakout while held (volume rule waived)
            if p["adds"] < MAX_ADDS:
                for (tt, ev) in ev_by_date.get(d, []):
                    if tt == t and ev["break_i"] == i:
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
                                trades.append([d, t, "BUY", round(px, 4), round(budget, 2), "pyramid-add"])
        # ---------- entries
        si = spy.idx.get(d)
        if si is not None and si >= 199 and len(pos) < MAX_POS:
            spy_ma200 = sum(spy.c[si-199:si+1]) / 200
            if spy.c[si] > spy_ma200:
                cands = []
                for (t, ev) in ev_by_date.get(d, []):
                    if t in pos:
                        continue
                    s = series_by[t]; i = s.idx[d]
                    if i < 127:
                        continue
                    avg20 = sum(s.v[i-20:i]) / 20
                    if avg20 <= 0 or s.v[i] < 1.5 * avg20:
                        continue
                    if s.ret126[i] is None or spy.ret126[si] is None or s.ret126[i] <= spy.ret126[si]:
                        continue
                    if s.c[i] < 0.95 * s.runmax_h[i]:
                        continue
                    if not funds[t].eps_ok(d):
                        continue
                    cands.append((s.ret126[i], t, boxes_by[t][ev["box_i"]]))
                cands.sort(reverse=True)
                for (_r, t, bx) in cands:
                    if len(pos) >= MAX_POS:
                        break
                    s = series_by[t]; px = s.c[s.idx[d]]
                    eq = equity(d)
                    budget = min(ENTRY_FRAC * eq, cash / (1 + BUY_COST))
                    if budget < 1.0:
                        break
                    cst = budget * BUY_COST; cash -= budget + cst; total_costs += cst
                    pos[t] = {"shares": budget / px, "fill": px, "entry_date": d,
                              "entry_i": s.idx[d], "entry_frac": budget / eq if eq > 0 else 0.0,
                              "stop": bx["lower"] * 0.999,
                              "adds": 0, "last_add_upper": bx["upper"], "trail_ref": -1}
                    trades.append([d, t, "BUY", round(px, 4), round(budget, 2), "entry"])
        curve.append((d, equity(d)))
    if curve:
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
            "orders": len(trades), "max_dd_pct": round(mdd * 100, 2),
            "curve": [[d, round(v, 2)] for d, v in curve],
            "trades": trades, "trips": trips}

def period_stats(curve):
    """Monthly distribution + stretch-between-highs (trading days), from daily curve."""
    if not curve:
        return {}
    month_end = {}
    for d, v in curve:
        month_end[d[:7]] = v
    months = sorted(month_end)
    rets = []
    prev = START_CASH
    for m in months:
        rets.append(month_end[m] / prev - 1 if prev > 0 else 0.0)
        prev = month_end[m]
    srt = sorted(rets)
    n = len(srt)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    pos_share = sum(1 for r in rets if r > 0) / n if n else 0.0
    streak = longest = 0
    for r in rets:
        if r <= 0:
            streak += 1; longest = max(longest, streak)
        else:
            streak = 0
    peak = -1.0; last_high = 0; stretch = 0
    for i, (_d, v) in enumerate(curve):
        if v >= peak:
            peak = v; stretch = max(stretch, i - last_high); last_high = i
    stretch = max(stretch, len(curve) - 1 - last_high)
    return {"periods": n, "median_pct": round(median * 100, 2),
            "share_positive_pct": round(pos_share * 100, 1),
            "best_pct": round(max(rets) * 100, 2) if rets else None,
            "worst_pct": round(min(rets) * 100, 2) if rets else None,
            "mean_pct_secondary": round(sum(rets) / n * 100, 2) if n else None,
            "longest_losing_streak_periods": longest,
            "longest_stretch_between_highs_days": stretch}

def spy_buyhold(spy, start, end):
    days = [d for d in spy.dates if start <= d <= end]
    if len(days) < 2:
        return None
    return round(100.0 * spy.c[spy.idx[days[-1]]] / spy.c[spy.idx[days[0]]], 2)

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}

def load_all():
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
    boxes_by, events_by = {}, {}
    for t, s in series_by.items():
        if t == "SPY":
            continue
        boxes_by[t], events_by[t] = build_boxes(s)
    return series_by, funds, failures, spy, boxes_by, events_by

def run_road(master, series_by, boxes_by, events_by, spy, funds, pool, start, end, placebos=True):
    r = simulate(master, series_by, boxes_by, events_by, spy, funds, start, end)
    out = {"start": start, "end": end, "final": r["final"], "costs": r["costs"],
           "orders": r["orders"], "max_dd_pct": r["max_dd_pct"],
           "n_entries": sum(1 for tr in r["trades"] if tr[2] == "BUY" and tr[5] == "entry"),
           "n_adds": sum(1 for tr in r["trades"] if tr[2] == "BUY" and tr[5] == "pyramid-add"),
           "spy_buyhold": spy_buyhold(spy, start, end),
           "period_stats": period_stats(r["curve"]),
           "curve": r["curve"], "trades": r["trades"]}
    if placebos:
        beaten = 0; pfin = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            plan = []
            for (ed, xd, frac) in r["trips"]:
                cands = [t for t in pool if ed in series_by[t].idx and xd in series_by[t].idx]
                if cands:
                    plan.append((ed, xd, frac, rng.choice(cands)))
            pr = simulate(master, series_by, boxes_by, events_by, spy, funds, start, end, placebo=plan)
            pfin.append(pr["final"])
            if r["final"] > pr["final"]:
                beaten += 1
        out["placebo_beaten"] = beaten
        out["placebo_finals"] = pfin
        pf = sorted(pfin)
        out["placebo_median"] = pf[len(pf) // 2] if pf else None
    return out

def main():
    series_by, funds, failures, spy, boxes_by, events_by = load_all()
    master = spy.dates
    pool = [t for t in series_by if t != "SPY"]
    print(f"universe {len(pool)} names, failures {len(failures)}, "
          f"breakout events {sum(len(v) for v in events_by.values())}", flush=True)

    if len(sys.argv) > 2 and sys.argv[1] == "--confirm":
        road = sys.argv[2]
        start, end = ROADS[road]
        conf = {"road": road, "folds": [], "halves": []}
        y0, y1 = int(start[:4]), int(end[:4])
        for y in range(y0, y1 + 1):
            fs = max(start, f"{y}-01-01"); fe = min(end, f"{y}-12-31")
            if fs >= fe:
                continue
            fr = run_road(master, series_by, boxes_by, events_by, spy, funds, pool, fs, fe, placebos=False)
            conf["folds"].append({"year": y, "start": fs, "end": fe, "final": fr["final"],
                                  "spy": fr["spy_buyhold"], "max_dd_pct": fr["max_dd_pct"],
                                  "n_entries": fr["n_entries"]})
            print(f"fold {y}: final ${fr['final']} SPY ${fr['spy_buyhold']} entries {fr['n_entries']}", flush=True)
        days = [d for d in master if start <= d <= end]
        mid = days[len(days) // 2]
        for (hs, he, tag) in [(start, mid, "H1"), (mid, end, "H2")]:
            hr = run_road(master, series_by, boxes_by, events_by, spy, funds, pool, hs, he, placebos=True)
            conf["halves"].append({"tag": tag, "start": hs, "end": he, "final": hr["final"],
                                   "placebo_median": hr["placebo_median"],
                                   "placebo_beaten": hr["placebo_beaten"],
                                   "max_dd_pct": hr["max_dd_pct"], "n_entries": hr["n_entries"],
                                   "curve": hr["curve"], "trades": hr["trades"]})
            print(f"half {tag} {hs}->{he}: final ${hr['final']} placebo median ${hr['placebo_median']} beaten {hr['placebo_beaten']}/20", flush=True)
        with open(os.path.join(HERE, f"confirmation_{road}.json"), "w") as f:
            json.dump(conf, f)
        print("confirmation done")
        return

    results = {"label": "JUDGMENT-CONSTRUCTED (V13 best-rules): our frozen reconstruction of Darvas's documented judgment under Claude-designed rules (BEST-RULES-SPEC.md); not Darvas's own trading. Verdict ceiling CANDIDATE.",
               "universe_size": len(pool), "failures": failures, "roads": {}}
    for name, (start, end) in ROADS.items():
        r = run_road(master, series_by, boxes_by, events_by, spy, funds, pool, start, end)
        results["roads"][name] = r
        print(f"{name}: final ${r['final']} entries {r['n_entries']} adds {r['n_adds']} "
              f"orders {r['orders']} DD {r['max_dd_pct']}% placebo {r['placebo_beaten']}/20 "
              f"(median ${r['placebo_median']}) SPY-bh ${r['spy_buyhold']}", flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f)
    print("done")

if __name__ == "__main__":
    main()
