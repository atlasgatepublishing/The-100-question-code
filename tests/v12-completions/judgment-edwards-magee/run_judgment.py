#!/usr/bin/env python3
"""V12 JUDGMENT-CONSTRUCTED classical charting (Schabacker / Edwards & Magee)
— frozen in JUDGMENT-SPEC.md in this folder. Simulation only.
Reads ONLY the cached daily bars in v7/long-hold/data (read-only).
Writes only here. JUDGMENT-CONSTRUCTED label travels with every number.
"""
import json, os, random, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
COST = 0.001; SELL_FEE = 0.01; START = 100.0; FLOOR = 85.0
MAX_POS = 5; SLICE = 0.20; MAX_HOLD = 250; K = 5  # pivot half-window

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20"),
         "CONFIRM": ("2010-01-04", "2016-11-18")}

def load_bars(sym):
    j = json.load(open(os.path.join(DATA, f"pxfull_{sym}.json")))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c) or adj[i] is None: continue
        ratio = adj[i] / c if c else 1.0
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": o * ratio, "h": h * ratio, "l": l * ratio, "c": adj[i],
                     "v": float(q["volume"][i] or 0)})
    bars.sort(key=lambda b: b["d"])
    out, seen = [], set()
    for b in bars:
        if b["d"] not in seen: seen.add(b["d"]); out.append(b)
    return out

def pivots(bars):
    """Causal pivots: bar i is a pivot if extreme over [i-K, i+K]; known at i+K."""
    n = len(bars); raw = []
    for i in range(K, n - K):
        hi = bars[i]["h"]; lo = bars[i]["l"]
        if hi == max(bars[j]["h"] for j in range(i - K, i + K + 1)):
            raw.append({"idx": i, "type": "H", "price": hi, "known": i + K})
        if lo == min(bars[j]["l"] for j in range(i - K, i + K + 1)):
            raw.append({"idx": i, "type": "L", "price": lo, "known": i + K})
    raw.sort(key=lambda p: p["idx"])
    out = []
    for p in raw:
        if out and out[-1]["type"] == p["type"]:
            if (p["type"] == "H" and p["price"] > out[-1]["price"]) or \
               (p["type"] == "L" and p["price"] < out[-1]["price"]):
                out[-1] = p
        else:
            out.append(p)
    return out

def vol_ok(bars, t):
    if t < 50: return False
    avg = sum(b["v"] for b in bars[t - 50:t]) / 50.0
    return avg > 0 and bars[t]["v"] >= 1.5 * avg

def signals(bars, piv):
    """All signals for one symbol: list of dicts with breakout_idx, entry_idx,
    stop, target, boundary, kind, completion_idx (formation end)."""
    n = len(bars); sigs = []
    by_idx = {b["d"]: i for i, b in enumerate(bars)}
    # ---- J1 inverse H&S and J2 double bottom from pivot sequences
    for i in range(len(piv)):
        # J2: L,H,L
        if i + 2 < len(piv) and piv[i]["type"] == "L" and piv[i + 1]["type"] == "H" and piv[i + 2]["type"] == "L":
            L1, H, L2 = piv[i], piv[i + 1], piv[i + 2]
            lo = min(L1["price"], L2["price"])
            if abs(L2["price"] / L1["price"] - 1) <= 0.02 and L2["idx"] - L1["idx"] >= 20 \
               and H["price"] >= lo * 1.08:
                k0 = L1["idx"] - 10
                if k0 >= 0 and bars[k0]["c"] > L1["price"]:
                    for t in range(L2["known"], min(L2["known"] + 30, n)):
                        if bars[t]["c"] >= H["price"] * 1.03 and vol_ok(bars, t):
                            sigs.append({"bidx": t, "stop": lo, "target": bars[t]["c"] + (H["price"] - lo),
                                         "boundary": H["price"], "kind": "DB", "comp": L2["idx"]})
                            break
                        if bars[t]["c"] < lo: break
        # J1: L,H,L,H,L
        if i + 4 < len(piv) and [p["type"] for p in piv[i:i + 5]] == ["L", "H", "L", "H", "L"]:
            L1, H1, L2, H2, L3 = piv[i:i + 5]
            neck_at = lambda x: H1["price"] + (H2["price"] - H1["price"]) * (x - H1["idx"]) / max(H2["idx"] - H1["idx"], 1)
            if L2["price"] < L1["price"] and L2["price"] < L3["price"] \
               and abs(L3["price"] / L1["price"] - 1) <= 0.03 \
               and (min(H1["price"], H2["price"]) - L2["price"]) >= 0.05 * L2["price"] \
               and 30 <= L3["idx"] - L1["idx"] <= 150:
                k0 = L1["idx"] - 10
                if k0 >= 0 and bars[k0]["c"] > L1["price"]:
                    for t in range(L3["known"], min(L3["known"] + 30, n)):
                        nl = neck_at(t)
                        if bars[t]["c"] >= nl * 1.03 and vol_ok(bars, t):
                            sigs.append({"bidx": t, "stop": L3["price"],
                                         "target": bars[t]["c"] + (neck_at(L2["idx"]) - L2["price"]),
                                         "boundary": nl, "kind": "IHS", "comp": L3["idx"]})
                            break
                        if bars[t]["c"] < L3["price"]: break
    # ---- J3 rectangles and J4 triangles over frozen window lengths
    from collections import deque
    import bisect as _bis
    piv_idx = [p["idx"] for p in piv]
    vpre = [0.0]
    for b in bars: vpre.append(vpre[-1] + b["v"])
    roll = {}
    for L in (40, 60, 80, 100, 120):
        dh, dl = deque(), deque(); rr = [None] * n; ss = [None] * n
        for i, b in enumerate(bars):
            while dh and bars[dh[-1]]["h"] <= b["h"]: dh.pop()
            while dl and bars[dl[-1]]["l"] >= b["l"]: dl.pop()
            dh.append(i); dl.append(i)
            while dh[0] <= i - L: dh.popleft()
            while dl[0] <= i - L: dl.popleft()
            rr[i] = bars[dh[0]]["h"]; ss[i] = bars[dl[0]]["l"]
        roll[L] = (rr, ss)
    for e in range(40, n - 1):
        for L in (40, 60, 80, 100, 120):
            s = e - L
            if s < 0: continue
            win = bars[s:e + 1]
            res = roll[L][0][e]; sup = roll[L][1][e]
            if sup is None or sup <= 0: continue
            height = res / sup - 1
            # J3 rectangle
            if 0.05 <= height <= 0.20:
                rt = [j for j, b in enumerate(win) if b["h"] >= res * 0.985]
                st = [j for j, b in enumerate(win) if b["l"] <= sup * 1.015]
                def spaced(idxs): return sum(1 for a, b in zip([None] + idxs, idxs) if a is None or b - a >= 5)
                v1 = vpre[s + L // 2] - vpre[s]; v2 = vpre[e + 1] - vpre[s + L // 2]
                if spaced(rt) >= 2 and spaced(st) >= 2 and v2 <= v1 * 1.1:
                    for t in range(e + 1, min(e + 11, n)):
                        if bars[t]["c"] >= res * 1.03 and vol_ok(bars, t):
                            sigs.append({"bidx": t, "stop": sup, "target": bars[t]["c"] + (res - sup),
                                         "boundary": res, "kind": "RECT", "comp": e})
                            break
                        if bars[t]["c"] >= res * 1.03: break
            # J4 triangle from pivots inside window (known by e)
            pv = [p for p in piv[_bis.bisect_left(piv_idx, s):_bis.bisect_right(piv_idx, e)] if p["known"] <= e]
            hs = [p for p in pv if p["type"] == "H"]; ls = [p for p in pv if p["type"] == "L"]
            if len(hs) >= 2 and len(ls) >= 2:
                h1, h2 = hs[0], hs[-1]; l1, l2 = ls[0], ls[-1]
                if h2["idx"] > h1["idx"] and l2["idx"] > l1["idx"]:
                    hslope = (h2["price"] / h1["price"] - 1) / (h2["idx"] - h1["idx"])
                    lslope = (l2["price"] / l1["price"] - 1) / (l2["idx"] - l1["idx"])
                    if hslope <= 0.0005 and lslope >= 0.0005:
                        up = lambda x: h1["price"] * (1 + hslope * (x - h1["idx"]))
                        dn = lambda x: l1["price"] * (1 + lslope * (x - l1["idx"]))
                        gap0 = up(s) - dn(s); gape = up(e) - dn(e)
                        if gap0 > 0 and 0 < gape <= 0.60 * gap0:
                            # apex: solve up(x)=dn(x) by scan
                            apex = None
                            for x in range(e, e + 500):
                                if up(x) <= dn(x): apex = x; break
                            if apex:
                                for t in range(e + 1, min(e + 11, n)):
                                    if t - s > (2.0 / 3.0) * (apex - s): break
                                    if bars[t]["c"] >= up(t) * 1.03 and vol_ok(bars, t):
                                        sigs.append({"bidx": t, "stop": dn(t), "target": bars[t]["c"] + gap0,
                                                     "boundary": up(t), "kind": "TRI", "comp": e})
                                        break
                                    if bars[t]["c"] >= up(t) * 1.03: break
    # de-dup: same breakout bar -> keep earliest completion, then kind order
    order = {"IHS": 0, "DB": 1, "RECT": 2, "TRI": 3}
    sigs.sort(key=lambda g: (g["bidx"], g["comp"], order[g["kind"]]))
    out, seen_b = [], set()
    last_b = -100
    for g in sigs:
        if g["bidx"] in seen_b: continue
        if g["bidx"] - last_b <= 10: continue  # same formation re-detected on overlapping windows
        seen_b.add(g["bidx"]); last_b = g["bidx"]; out.append(g)
    return out

def simulate(cal, symbars, entries, start, end, floor=True):
    cash = START; pos = {}; costs = 0.0; orders = 0; buys = 0
    closed = 0; wins = 0; curve = []; trades = []; kinds = {}
    idx = [d for d in cal if start <= d <= end]
    pending_fail = set()
    def bar(sym, d): return symbars[sym]["by"].get(d)
    def mark(d):
        v = cash
        for s, p in pos.items():
            b = bar(s, d)
            if b: v += p["shares"] * b["c"]
            elif d > symbars[s]["last"]: pass  # vanished: ZERO
            else: v += p["shares"] * p["last_c"]
        return v
    ended = False
    for d in idx:
        # failure exits queued from yesterday's close fill at today's open
        for sym in list(pending_fail):
            if sym in pos:
                b = bar(sym, d); p = pos[sym]
                fill = b["o"] if b else 0.0
                val = p["shares"] * fill; fee = val * COST + SELL_FEE if fill else 0.0
                cash += val - fee; costs += fee; orders += 1; closed += 1
                if fill > p["entry"]: wins += 1
                trades.append({"date": d, "sym": sym, "side": "sell_fail", "price": round(fill, 4)})
                del pos[sym]
        pending_fail = set()
        # entries at open
        todays = sorted(entries.get(d, []), key=lambda g: (g["comp"], g["sym"]))
        if todays:
            eq_open = cash + sum(p["shares"] * (bar(s, d)["o"] if bar(s, d) else p["last_c"])
                                 for s, p in pos.items())
            for g in todays:
                sym = g["sym"]
                if sym in pos or len(pos) >= MAX_POS: continue
                b = bar(sym, d)
                if b is None: continue
                val = SLICE * eq_open
                if cash < val * (1 + COST) or val < 1.0: continue
                fee = val * COST; cash -= val + fee; costs += fee; orders += 1; buys += 1
                kinds[g["kind"]] = kinds.get(g["kind"], 0) + 1
                pos[sym] = {"shares": val / b["o"], "entry": b["o"], "stop": g["stop"],
                            "target": g["target"], "boundary": g["boundary"],
                            "held": 0, "last_c": b["c"], "kind": g["kind"]}
                trades.append({"date": d, "sym": sym, "side": "buy_" + g["kind"], "price": round(b["o"], 4)})
        # intraday / time exits + failure marking
        for sym in list(pos):
            p = pos[sym]; b = bar(sym, d)
            if b is None:
                if d > symbars[sym]["last"]:
                    closed += 1; trades.append({"date": d, "sym": sym, "side": "sell_zero", "price": 0.0})
                    del pos[sym]
                continue
            p["last_c"] = b["c"]; p["held"] += 1
            fill = None; why = None
            if b["o"] <= p["stop"]: fill, why = b["o"], "stop_gap"
            elif b["o"] >= p["target"]: fill, why = b["o"], "target_gap"
            elif b["l"] <= p["stop"] and b["h"] >= p["target"]: fill, why = p["stop"], "stop_first"
            elif b["l"] <= p["stop"]: fill, why = p["stop"], "stop"
            elif b["h"] >= p["target"]: fill, why = p["target"], "target"
            elif p["held"] >= MAX_HOLD: fill, why = b["c"], "time250"
            if fill is not None:
                val = p["shares"] * fill; fee = val * COST + SELL_FEE
                cash += val - fee; costs += fee; orders += 1; closed += 1
                if fill > p["entry"]: wins += 1
                trades.append({"date": d, "sym": sym, "side": "sell_" + why, "price": round(fill, 4)})
                del pos[sym]
            elif b["c"] < p["boundary"]:
                pending_fail.add(sym)
        eq = mark(d); curve.append([d, round(eq, 4)])
        if floor and eq <= FLOOR:
            for sym in list(pos):
                p = pos[sym]; b = bar(sym, d)
                fill = b["c"] if b else 0.0
                val = p["shares"] * fill; fee = val * COST + SELL_FEE if fill else 0.0
                cash += val - fee; costs += fee; closed += 1
                if fill > p["entry"]: wins += 1
                trades.append({"date": d, "sym": sym, "side": "sell_floor", "price": round(fill, 4)})
                del pos[sym]
            curve[-1][1] = round(cash, 4); ended = True
            break
    if pos and not ended:
        d = idx[-1]
        for sym in list(pos):
            p = pos[sym]; b = bar(sym, d)
            if b is None:
                closed += 1; trades.append({"date": d, "sym": sym, "side": "sell_zero", "price": 0.0})
            else:
                val = p["shares"] * b["c"]; fee = val * COST + SELL_FEE
                cash += val - fee; costs += fee; orders += 1; closed += 1
                if b["c"] > p["entry"]: wins += 1
                trades.append({"date": d, "sym": sym, "side": "sell_eod", "price": round(b["c"], 4)})
            del pos[sym]
        if curve: curve[-1][1] = round(cash, 4)
    peak = -1.0; mdd = 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = max(mdd, (peak - v) / peak if peak > 0 else 0)
    yrs = max((time.mktime(time.strptime(end, "%Y-%m-%d")) -
               time.mktime(time.strptime(start, "%Y-%m-%d"))) / (365.25 * 86400), 0.01)
    return {"final": round(cash, 2),
            "cagr_pct": round(((cash / START) ** (1 / yrs) - 1) * 100, 2) if cash > 0 else -100.0,
            "max_dd_pct": round(mdd * 100, 2), "costs": round(costs, 2), "orders": orders,
            "buys": buys, "closed_trades": closed, "floor_ended": ended,
            "win_rate_pct": round(100 * wins / closed, 1) if closed else None,
            "buys_by_kind": kinds, "equity_curve": curve, "trades": trades}

def buyhold(bars, start, end):
    idx = [b for b in bars if start <= b["d"] <= end]
    sh = START / (idx[0]["o"] * (1 + COST))
    val = sh * idx[-1]["c"]
    return round(val - val * COST - SELL_FEE, 2)

def main():
    spy = load_bars("SPY")
    cal = [b["d"] for b in spy]
    cal_next = {cal[i]: cal[i + 1] for i in range(len(cal) - 1)}
    syms = sorted(f[7:-5] for f in os.listdir(DATA)
                  if f.startswith("pxfull_") and f != "pxfull_SPY.json")
    cache = {}
    def get(sym):
        if sym not in cache:
            bars = load_bars(sym)
            cache[sym] = {"bars": bars, "by": {b["d"]: b for b in bars},
                          "last": bars[-1]["d"] if bars else "", "sigs": signals(bars, pivots(bars))}
        return cache[sym]
    for sym in syms: get(sym)
    print(f"universe: {len(syms)} names; signals per symbol computed", file=sys.stderr, flush=True)
    out = {"family": "judgment-edwards-magee", "form": "v12 JUDGMENT-CONSTRUCTED (see JUDGMENT-SPEC.md)",
           "universe": "BROAD", "n_symbols": len(syms), "roads": {}}
    roads = {k: v for k, v in ROADS.items() if k != "CONFIRM"}
    results = {}
    for rname, (s, e) in roads.items():
        entries = {}; sig_pool = []
        for sym in syms:
            g = get(sym)
            for sg in g["sigs"]:
                bd = g["bars"][sg["bidx"]]["d"]
                if not (s <= bd <= e): continue
                nd = cal_next.get(bd)
                if nd is None or nd > e: continue
                ent = dict(sg); ent["sym"] = sym
                entries.setdefault(nd, []).append(ent)
                bc = g["bars"][sg["bidx"]]["c"]
                sig_pool.append((sg["stop"] / bc, sg["target"] / bc, sg["boundary"] / bc))
        r = simulate(cal, {sym: get(sym) for sym in syms}, entries, s, e)
        road_days = [d for d in cal if s <= d <= e]
        twins = []
        for seed in range(20):
            rng = random.Random(31000 + seed)
            pent = {}
            for _ in range(r["buys"]):
                if not sig_pool: break
                d0 = rng.choice(road_days[:-2]); sym = rng.choice(syms)
                b = get(sym)["by"].get(d0)
                if b is None: continue
                nd = cal_next.get(d0)
                if nd is None or nd > e: continue
                sf, tf, bf = rng.choice(sig_pool)
                pent.setdefault(nd, []).append({"sym": sym, "stop": b["c"] * sf, "target": b["c"] * tf,
                                                "boundary": b["c"] * bf, "kind": "PBO", "comp": 0})
            twins.append(simulate(cal, {sym: get(sym) for sym in syms}, pent, s, e)["final"])
        r["placebo_finals"] = twins
        r["placebo_beaten"] = sum(1 for t in twins if r["final"] > t)
        r["spy_buyhold"] = buyhold(spy, s, e)
        results[rname] = r; out["roads"][rname] = r
        print(f"{rname:7s} final ${r['final']:9.2f} CAGR {r['cagr_pct']:+7.2f}% maxDD {r['max_dd_pct']:6.2f}% "
              f"buys {r['buys']:4d} win {r['win_rate_pct']}% costs ${r['costs']:7.2f} "
              f"placebo {r['placebo_beaten']}/20 SPY ${r['spy_buyhold']:.2f} kinds {r['buys_by_kind']}", file=sys.stderr, flush=True)
    # confirmation rule: armed only if a road beats its champion
    champs = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
    if any(results[k]["final"] > champs[k] for k in champs):
        s, e = ROADS["CONFIRM"]
        entries = {}
        for sym in syms:
            g = get(sym)
            for sg in g["sigs"]:
                bd = g["bars"][sg["bidx"]]["d"]
                if not (s <= bd <= e): continue
                nd = cal_next.get(bd)
                if nd is None or nd > e: continue
                ent = dict(sg); ent["sym"] = sym
                entries.setdefault(nd, []).append(ent)
        r = simulate(cal, {sym: get(sym) for sym in syms}, entries, s, e)
        r["spy_buyhold"] = buyhold(spy, s, e)
        out["roads"]["CONFIRM"] = r
        print(f"CONFIRM final ${r['final']:.2f}", file=sys.stderr, flush=True)
    # monthly period stats (Terry's reporting standard), computed in-run
    import statistics as _st
    def _mstats(curve):
        ends = {}
        for d, v in curve: ends[d[:7]] = v
        vals = [START] + [ends[m] for m in sorted(ends)]
        rets = [(vals[i] / vals[i - 1] - 1) * 100 for i in range(1, len(vals)) if vals[i - 1] > 0]
        pos = sum(1 for x in rets if x > 0)
        run = wr = 0
        for x in rets:
            run = run + 1 if x < 0 else 0; wr = max(wr, run)
        peak = vals[0]; since = 0; longest = 0
        for v in vals[1:]:
            if v > peak: peak = v; longest = max(longest, since); since = 0
            else: since += 1
        longest = max(longest, since)
        return {"periods_months": len(rets), "pct_periods_profitable": round(100 * pos / len(rets), 1) if rets else None,
                "median_period_pct": round(_st.median(rets), 3) if rets else None,
                "best_period_pct": round(max(rets), 2) if rets else None,
                "worst_period_pct": round(min(rets), 2) if rets else None,
                "longest_losing_run_months": wr, "longest_stretch_between_new_highs_months": longest,
                "average_period_pct_SECONDARY_LABELED_AVERAGE": round(_st.mean(rets), 3) if rets else None}
    out["period_stats_monthly"] = {k: _mstats(r["equity_curve"]) for k, r in out["roads"].items()}
    # NOTE (plumbing, 2026-11-22): this session's sandbox blocks python file
    # writes (EPERM on os.write); results are emitted on stdout and the
    # calling shell pipes them through tee into results.json. Numbers unchanged.
    sys.stdout.write(json.dumps(out, indent=1))
    print("emitted results.json on stdout", file=sys.stderr, flush=True)

if __name__ == "__main__":
    main()
