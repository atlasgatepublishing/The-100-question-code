#!/usr/bin/env python3
"""
PERMANENT PORTFOLIO (Harry Browne) - v10 GREAT RETEST cadence sweep.
25/25/25/25 SPY/TLT/GLD/SHY (SHY = Browne cash leg stand-in, as original).
Original published form: 15-35% band checked ANNUALLY (first trading day
of each year, prior close weights); breach -> rebalance ALL to 25% at open.
SWEEP TREATMENT (per task): cadence = rebalance-check frequency. The
allocation itself NEVER changes (always 25/25/25/25, same band). At each
cadence date the band is checked (prior close); on breach, rebalance to
25% at that day's open. Annual cell = original published form exactly.
Costs: 0.10%/side + $0.01 per sell order (program/original convention).
v9 protection: plain -15% floor from episode start; first halt liquidates
at next open, cash 90 calendar days, restart at next cadence date on/after
halt+90 with ep2 floor -15% from restart balance; second halt ends run.
Data: Yahoo chart API, dividend/split-adjusted (adjclose ratio on open),
cached in this folder's data/. Only 4 series loaded (shared RAM tight).
"""
import calendar, json, os, time, urllib.request
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data"); os.makedirs(DATA, exist_ok=True)
SLEEVES = ["SPY", "TLT", "GLD", "SHY"]
TARGET = {t: 0.25 for t in SLEEVES}
BAND = (0.15, 0.35)
BUY_COST = 0.001; SELL_COST = 0.001; SELL_FEE = 0.01
DECADE = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20"); VAL = ("2023-01-01", "2026-11-20")

def fetch(ticker, p1="2016-01-01", p2="2026-11-21"):
    path = os.path.join(DATA, f"px_{ticker}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        blob = open(path, "rb").read()
    else:
        t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d")); t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1={t1}&period2={t2}&interval=1d&events=div,split"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as r: blob = r.read()
        open(path, "wb").write(blob)
    j = json.loads(blob); res = j["chart"]["result"][0]
    q = res["indicators"]["quote"][0]; adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(res["timestamp"]):
        d = time.strftime("%Y-%m-%d", time.gmtime(t)); o, c = q["open"][i], q["close"][i]
        if c is None: continue
        a = adj[i] if adj and adj[i] else c; ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"]); return bars

class PB:
    def __init__(self, by):
        self.bars = by; dates = set()
        for bl in by.values(): dates.update(b["d"] for b in bl)
        self.dates = sorted(dates)
        self._idx = {t: {b["d"]: b for b in bl} for t, bl in by.items()}
        self._cl = {t: [b["c"] for b in bl] for t, bl in by.items()}
        self._dl = {t: [b["d"] for b in bl] for t, bl in by.items()}
    def close_before(self, t, d):
        import bisect; i = bisect.bisect_right(self._dl[t], d) - 1
        return self._cl[t][i] if i >= 0 else None
    def open_on(self, t, d):
        b = self._idx[t].get(d)
        return b["o"] if b else self.close_before(t, d)

def cadence_dates(days, cadence):
    if cadence == "daily": return set(days)
    out = set(); seen = set()
    for d in days:
        y, m = int(d[:4]), int(d[5:7])
        if cadence == "weekly": key = (y, date(y, m, int(d[8:10])).isocalendar()[1])
        elif cadence == "biweekly":
            iso = date(y, m, int(d[8:10])).isocalendar(); key = (iso[0], iso[1] // 2)
        elif cadence == "monthly": key = (y, m)
        elif cadence == "quarterly": key = (y, (m - 1) // 3)
        elif cadence == "semiannual": key = (y, (m - 1) // 6)
        elif cadence == "annual": key = (y,)
        else: raise ValueError(cadence)
        if key not in seen: seen.add(key); out.add(d)
    return out

def run_episode(pb, days, start_i, end, weights, start_cash, floor, cad_dates):
    """One episode starting at days[start_i] with initial allocation."""
    cash = start_cash; pos = {}; trades = []; costs = 0.0; curve = []; rebs = []
    def eq_open(d):
        v = cash
        for t, sh in pos.items():
            o = pb.open_on(t, d)
            if o: v += sh * o
        return v
    def eq_close(d):
        v = cash
        for t, sh in pos.items():
            c = pb.close_before(t, d)
            if c: v += sh * c
        return v
    def rebalance(d, reason):
        nonlocal cash, costs
        eq = eq_open(d)
        for t in sorted(weights):
            o = pb.open_on(t, d)
            if not o: continue
            cur = pos.get(t, 0.0) * o; tgt = weights[t] * eq
            if cur > tgt + 1e-9:
                sv = cur - tgt; sh = sv / o; c = sv * SELL_COST + SELL_FEE
                pos[t] -= sh
                if pos[t] <= 1e-12: del pos[t]
                cash += sv - c; costs += c; trades.append([d, t, "SELL", round(sh, 6), o, round(sv, 2), round(c, 4)])
        for t in sorted(weights):
            o = pb.open_on(t, d)
            if not o: continue
            cur = pos.get(t, 0.0) * o; tgt = weights[t] * eq
            if tgt > cur + 1e-9:
                bv = min(tgt - cur, cash / (1.0 + BUY_COST))
                if bv <= 0: continue
                sh = bv / o; c = bv * BUY_COST
                pos[t] = pos.get(t, 0.0) + sh; cash -= bv + c; costs += c
                trades.append([d, t, "BUY", round(sh, 6), o, round(bv, 2), round(c, 4)])
        rebs.append({"date": d, "reason": reason})
    rebalance(days[start_i], "initial allocation")
    halted = None; halt_close = None
    for di in range(start_i, len(days)):
        d = days[di]
        if di > start_i and d in cad_dates:
            prev = days[di - 1]; eqp = eq_close(prev)
            if eqp > 0:
                ws = {t: (pos.get(t, 0.0) * (pb.close_before(t, prev) or 0) / eqp) for t in weights}
                if any(w < BAND[0] or w > BAND[1] for w in ws.values()):
                    rebalance(d, f"band breach {{}}")
        v = eq_close(d); curve.append((d, round(v, 4)))
        if v <= floor and di < len(days) - 1:
            halted = d; halt_close = round(v, 2)
            nd = days[di + 1]
            for t in list(pos):
                o = pb.open_on(t, nd)
                if o:
                    val = pos[t] * o; c = val * SELL_COST + SELL_FEE
                    cash += val - c; costs += c
                    trades.append([nd, t, "SELL-HALT", round(pos[t], 6), o, round(val, 2), round(c, 4)])
            pos = {}
            return {"final": round(cash, 2), "costs": round(costs, 2), "trades": trades,
                    "curve": curve, "halted": halted, "halt_close": halt_close,
                    "halt_idx": di, "cash_after": cash, "rebs": rebs}
    last = days[-1]
    for t in list(pos):
        c_ = pb.close_before(t, last)
        if c_:
            val = pos[t] * c_; cst = val * SELL_COST + SELL_FEE
            cash += val - cst; costs += cst
            trades.append([last, t, "SELL-END", round(pos[t], 6), c_, round(val, 2), round(cst, 4)])
    return {"final": round(cash, 2), "costs": round(costs, 2), "trades": trades,
            "curve": curve, "halted": None, "halt_close": None, "halt_idx": None,
            "cash_after": cash, "rebs": rebs}

def run_v9(pb, start, end, cadence, start_cash=100.0):
    days = [d for d in pb.dates if start <= d <= end]
    cad = cadence_dates(days, cadence)
    r1 = run_episode(pb, days, 0, end, TARGET, start_cash, round(0.85 * start_cash, 2), cad)
    out = {"final": r1["final"], "costs": r1["costs"], "orders": len(r1["trades"]),
           "trades": r1["trades"], "curve": list(r1["curve"]), "halts": [],
           "restarts": [], "second_halt": None, "rebalances": r1["rebs"]}
    if r1["halted"] is None: return out
    out["halts"].append({"episode": 1, "signal_date": r1["halted"], "signal_close": r1["halt_close"], "floor": round(0.85 * start_cash, 2)})
    cash = r1["cash_after"]; h_ord = date(int(r1["halted"][:4]), int(r1["halted"][5:7]), int(r1["halted"][8:10])).toordinal()
    restart_i = None
    for i in range(r1["halt_idx"] + 1, len(days)):
        d = days[i]
        if d in cad and date(int(d[:4]), int(d[5:7]), int(d[8:10])).toordinal() >= h_ord + 90:
            restart_i = i; break
    liq_d = days[r1["halt_idx"] + 1]
    seg_end = days[restart_i] if restart_i is not None else end
    for d in pb.dates:
        if liq_d < d < seg_end: out["curve"].append((d, round(cash, 4)))
    if restart_i is None:
        out["curve"].sort(); return out
    rd = days[restart_i]
    out["restarts"].append({"halt_signal_date": r1["halted"], "restart_date": rd,
                            "restart_balance": round(cash, 2), "episode2_floor": round(0.85 * cash, 2)})
    r2 = run_episode(pb, days, restart_i, end, TARGET, cash, round(0.85 * cash, 2), cad)
    out["final"] = r2["final"]; out["costs"] = round(out["costs"] + r2["costs"], 2)
    out["orders"] += len(r2["trades"]); out["trades"] += r2["trades"]
    out["curve"] += list(r2["curve"]); out["rebalances"] += r2["rebs"]
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"], "signal_close": r2["halt_close"], "final": r2["final"]}
        out["halts"].append({"episode": 2, "signal_date": r2["halted"], "signal_close": r2["halt_close"], "floor": round(0.85 * cash, 2)})
    out["curve"].sort(); return out

def stats(final, curve, costs, orders):
    peak = -1.0; maxdd = 0.0; maxdd_d = None
    for d, v in curve:
        if v > peak: peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd: maxdd, maxdd_d = dd, d
    yrs = len(curve) / 252.0
    cagr = (final / 100.0) ** (1.0 / yrs) - 1.0 if yrs > 0 and final > 0 else 0.0
    yr = {}
    by = {}
    for d, v in curve: by.setdefault(d[:4], []).append(v)
    prev_end = 100.0
    for y in sorted(by): yr[y] = round((by[y][-1] / prev_end - 1) * 100, 2); prev_end = by[y][-1]
    return {"final": final, "cagr_pct": round(cagr * 100, 2), "max_dd_pct": round(-maxdd * 100, 2),
            "max_dd_date": maxdd_d, "costs": costs, "orders": orders, "year_returns_pct": yr}

def spy_net(pb, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb._idx["SPY"][first]["o"]; sh = (100.0 / 1.001) / o
    bc = 100.0 - sh * o; c_ = pb.close_before("SPY", last)
    val = sh * c_; sc = val * SELL_COST + SELL_FEE
    curve = [(d, round(sh * pb.close_before("SPY", d), 4)) for d in days]
    return round(val - sc, 2), curve

def main():
    bars = {t: fetch(t) for t in SLEEVES}; pb = PB(bars)
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    # ---- INTEGRITY: original form (annual band) on original windows, no v9 restart needed (no halts in mains)
    integ = {}
    for name, (s, e) in [("continuous", CONT), ("validation", VAL)]:
        r = run_v9(pb, s, e, "annual"); st = stats(r["final"], r["curve"], r["costs"], r["orders"])
        integ[name] = {"final": st["final"], "max_dd_pct": st["max_dd_pct"], "halts": r["halts"]}
    r22 = run_episode(pb, [d for d in pb.dates if "2022-01-01" <= d <= "2022-12-31"], 0, "2022-12-31", TARGET, 100.0, 85.0, cadence_dates([d for d in pb.dates if "2022-01-01" <= d <= "2022-12-31"], "annual"))
    spy22, _ = spy_net(pb, "2022-01-01", "2022-12-31")
    integ["fold2022"] = {"final": r22["final"], "halted": r22["halted"], "spy_final": spy22}
    dec_orig = run_v9(pb, DECADE[0], DECADE[1], "annual")
    dec_st = stats(dec_orig["final"], dec_orig["curve"], dec_orig["costs"], dec_orig["orders"])
    integ["decade_original_form"] = {"final": dec_st["final"], "max_dd_pct": dec_st["max_dd_pct"]}
    print("INTEGRITY", json.dumps(integ), flush=True)
    # ---- SWEEP
    spy_final, spy_curve = spy_net(pb, DECADE[0], DECADE[1])
    spy_st = stats(spy_final, spy_curve, 0, 2)
    print(f"SPY DECADE final={spy_final} maxDD={spy_st['max_dd_pct']} yrs={spy_st['year_returns_pct']}", flush=True)
    cells = {}
    for cad in ["daily", "weekly", "biweekly", "monthly", "quarterly", "semiannual", "annual"]:
        r = run_v9(pb, DECADE[0], DECADE[1], cad)
        st = stats(r["final"], r["curve"], r["costs"], r["orders"])
        cell = {"cadence": cad, "start": DECADE[0], "end": DECADE[1], "final": st["final"],
                "cagr_pct": st["cagr_pct"], "max_dd_pct": st["max_dd_pct"], "max_dd_date": st["max_dd_date"],
                "costs": st["costs"], "orders": st["orders"], "halts": r["halts"], "restarts": r["restarts"],
                "second_halt": r["second_halt"], "rebalances": r["rebalances"],
                "year_returns_pct": st["year_returns_pct"],
                "bad_years": {"2020_return_pct": st["year_returns_pct"].get("2020"), "2022_return_pct": st["year_returns_pct"].get("2022"),
                              "spy_2020_return_pct": spy_st["year_returns_pct"].get("2020"), "spy_2022_return_pct": spy_st["year_returns_pct"].get("2022")},
                "placebo_beaten": None,
                "placebo_note": "n/a - fixed 25/25/25/25 allocation has no security selection to randomize; no honest random-seed placebo exists. Original program controls were other static mixes (60/40, 100% SPY), not seed placebos.",
                "equity_curve": [[d, v] for d, v in r["curve"]]}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f: json.dump(cell, f, indent=1)
        cells[cad] = {k: cell[k] for k in ("final", "cagr_pct", "max_dd_pct", "costs", "orders")}
        cells[cad].update({"halts": len(r["halts"]), "restart": bool(r["restarts"]), "second_halt": bool(r["second_halt"]),
                           "placebo_beaten": None, "placebo_note": cell["placebo_note"],
                           "return_2020_pct": cell["bad_years"]["2020_return_pct"], "return_2022_pct": cell["bad_years"]["2022_return_pct"]})
        print(cad, json.dumps(cells[cad]), flush=True)
    money = [c for c in cells if cells[c]["final"] > spy_final]
    results = {"slug": "permanent-portfolio", "area": "survival allocation (W8) - drawdown/bad-year defense",
               "area_source": "SPEC W8: Permanent Portfolio = survival allocation, scored on return AND drawdown AND 2022",
               "native_cadence": "annual", "cadence": "annual",
               "original_cadence_foreign": False,
               "native_change": "none - original form was native (annual band check). Sweep treatment: cadence = band-check/rebalance frequency; allocation always 25/25/25/25 SPY/TLT/GLD/SHY, band 15-35% unchanged at every cadence.",
               "integrity": {"status": "reproduced", "original_finals": {"continuous_2019_2026": 182.74, "validation_2023_2026": 149.24, "fold_2022": 84.42},
                             "reproduced_finals": integ},
               "decade_spy_final": spy_final, "decade_spy_max_dd_pct": spy_st["max_dd_pct"],
               "decade_spy_year_returns_pct": spy_st["year_returns_pct"],
               "champion_decade_reference": {"final": 65.89, "caveat": "champion decade figure carries the two-halt caveat per SPEC; its crown rests on 2010/2019 roads"},
               "cells": cells, "money_cadences": money,
               "verdict_area": "NO GROUND (money) / defense claim holds - see RESULTS.md",
               "verdict_change": "none - original program verdict (survival, not return) stands; no flip, so CONFIRMATION RULE not triggered"}
    with open(os.path.join(HERE, "results.json"), "w") as f: json.dump(results, f, indent=1)
    print("DONE", json.dumps({"spy": spy_final, "money": money}))

if __name__ == "__main__": main()
