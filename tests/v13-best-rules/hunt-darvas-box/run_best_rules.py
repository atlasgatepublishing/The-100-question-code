#!/usr/bin/env python3
"""V13 BEST-RULES RUN — hunt-darvas-box (MECHANICAL Darvas box).
Frozen spec: BEST-RULES-SPEC.md in this folder. Summary of MY rules:
- Box exactly as published: upper rail H confirmed after 3 consecutive days
  failing to touch/exceed the high; lower rail L likewise. Daily bars.
- Entry: intraday break above H (fill H*1.001, or open on gap-through),
  candidate within 5% of cache-history high, SPY > 200d gate. NO volume
  gate (dropped per spec). NO pyramid/pilot adds (dropped per spec).
- Stop: just below the broken box's LOWER rail (L*0.999); trails up to just
  below each newly completed box's lower rail while held, never down.
  Exit fill: stop level intraday, or open on a gap through.
- Basket: max 3 concurrent, target = equity/3 per entry, pond order on
  same-day competition. No pot floor. Costs 0.10%/side + $0.01/sell. $100.
- Box void on close below L or 126 trading days without breakout.
Data (read-only): backtests/v7/long-hold/data/pxfull_<T>.json (Yahoo chart
payloads, full OHLCV 2008->2026-11-20). GOOGL served by pxfull_GOOG.json.
Placebos: 20 seeds/road, per-asset entry counts matched, median hold,
identical basket/costs.
"""
import json, os, random, statistics, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "..", "v7", "long-hold", "data")
POND = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG","V","WMT","HD","BAC",
        "CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]
COST, SELL_FEE, MAXPOS = 0.001, 0.01, 3
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
PUBLISHED = {"LONG": 278.21, "DECADE": 202.49, "CONT": 133.85, "VAL": 121.44}  # v12 basket-5
SPY_PROG = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}

def load_bars(t):
    fn = "GOOG" if t == "GOOGL" else t
    d = json.load(open(os.path.join(DATA, f"pxfull_{fn}.json")))
    r = d["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    bars = []
    for ts, o, h, l, c, v in zip(r["timestamp"], q["open"], q["high"], q["low"], q["close"], q["volume"]):
        if c is None: continue
        dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")
        bars.append({"d": dt, "o": o, "h": h, "l": l, "c": c, "v": v or 0})
    return bars

def sma(vals, n):
    out = [None] * len(vals); s = 0.0
    for i, x in enumerate(vals):
        s += x
        if i >= n: s -= vals[i - n]
        if i >= n - 1: out[i] = s / n
    return out

def darvas_trades(bars, gate):
    """Box state machine (published) with MY stop: below the broken box's
    lower rail; trails to below each new completed box's lower rail."""
    n = len(bars)
    H_ = [b["h"] for b in bars]; L_ = [b["l"] for b in bars]; C = [b["c"] for b in bars]
    trades = []
    phase = "seek_top"; H = None; cnt = 0; L = None; box_done_i = None; ath = 0.0
    stop = None; in_pos = False; cur = None
    i = 0
    while i < n:
        ath = max(ath, H_[i])
        if not in_pos:
            if phase == "seek_top":
                if H is None or H_[i] > H: H = H_[i]; cnt = 0
                elif H_[i] < H:
                    cnt += 1
                    if cnt == 3: phase = "seek_bot"; L = None; cnt = 0
            elif phase == "seek_bot":
                if L is None or L_[i] < L: L = L_[i]; cnt = 0
                elif L_[i] > L:
                    cnt += 1
                    if cnt == 3: phase = "watch"; box_done_i = i
                if H_[i] > H: phase = "seek_top"; H = H_[i]; cnt = 0
            elif phase == "watch":
                if C[i] < L or i - box_done_i > 126:
                    phase = "seek_top"; H = H_[i]; cnt = 0
                elif H_[i] > H * 1.001:
                    if gate[i] and H >= 0.95 * ath:
                        cur = {"entry_i": i, "entry_px": H * 1.001, "entry_d": bars[i]["d"]}
                        stop = L * 0.999; in_pos = True
                        phase = "seek_top"; H = None; cnt = 0; L = None
        else:
            if phase == "seek_top":
                if H is None or H_[i] > H: H = H_[i]; cnt = 0
                elif H_[i] < H:
                    cnt += 1
                    if cnt == 3: phase = "seek_bot"; L = None; cnt = 0
            elif phase == "seek_bot":
                if L is None or L_[i] < L: L = L_[i]; cnt = 0
                elif L_[i] > L:
                    cnt += 1
                    if cnt == 3:
                        stop = max(stop, L * 0.999); phase = "seek_top"; H = None; cnt = 0
                if H_[i] > (H or 0): phase = "seek_top"; H = H_[i]; cnt = 0
            if L_[i] < stop:
                fill = bars[i]["o"] if bars[i]["o"] < stop else stop
                cur.update({"exit_i": i, "exit_px": fill, "exit_d": bars[i]["d"]})
                trades.append(cur); cur = None; in_pos = False
                phase = "seek_top"; H = None; cnt = 0; L = None
        i += 1
    if cur is not None:
        cur.update({"exit_i": n - 1, "exit_px": C[n - 1], "exit_d": bars[n - 1]["d"], "eod": True})
        trades.append(cur)
    return trades

def run_basket(bars_by, trades_by, start, end):
    cal = [b["d"] for b in bars_by["SPY"] if start <= b["d"] <= end]
    close_by = {t: {b["d"]: b["c"] for b in bars_by[t]} for t in bars_by}
    last_px = {}
    entries, exits = {}, {}
    n_trades = 0
    for t in POND:
        for tr in trades_by.get(t, []):
            if not (start <= tr["entry_d"] <= end): continue
            n_trades += 1
            entries.setdefault(tr["entry_d"], []).append((POND.index(t), t, tr))
            if tr["exit_d"] <= end and not tr.get("eod"):
                exits.setdefault(tr["exit_d"], []).append((t, tr))
    for d in entries: entries[d].sort()
    cash, lots, curve, costs, orders = 100.0, {}, [], 0.0, 0
    prev_eq = 100.0
    closed_pnls = []
    for d in cal:
        for t, tr in exits.get(d, []):
            if t in lots:
                sh, basis = lots.pop(t)
                val = sh * tr["exit_px"]; fee = COST * val + SELL_FEE
                cash += val - fee; costs += fee; orders += 1
                closed_pnls.append(val - fee - basis)
        for _o, t, tr in entries.get(d, []):
            if t in lots or len(lots) >= MAXPOS: continue
            tgt = prev_eq / MAXPOS
            val = min(tgt, cash / (1 + COST))
            if val < 1.0: continue
            fee = COST * val; cash -= val + fee; costs += fee; orders += 1
            lots[t] = (val / tr["entry_px"], val + fee)
        eq = cash
        for t, (sh, _b) in lots.items():
            if d in close_by[t]: last_px[t] = close_by[t][d]
            eq += sh * last_px.get(t, 0.0)
        curve.append({"d": d, "eq": round(eq, 4)})
        prev_eq = eq
    final = curve[-1]["eq"] if curve else 100.0
    pk, maxdd = 100.0, 0.0
    for pt in curve:
        pk = max(pk, pt["eq"]); maxdd = max(maxdd, (pk - pt["eq"]) / pk * 100 if pk else 0.0)
    wins = [p for p in closed_pnls if p > 0]
    exp = {"closed_trades_in_road": len(closed_pnls),
           "win_rate_pct": round(100 * len(wins) / len(closed_pnls), 1) if closed_pnls else None,
           "expectancy_per_closed_trade": round(statistics.mean(closed_pnls), 2) if closed_pnls else None,
           "open_positions_end": len(lots)}
    return {"final": round(final, 2), "max_dd_pct": round(maxdd, 2), "costs": round(costs, 2),
            "orders": orders, "entries_taken": n_trades, "expectancy": exp,
            "periods": period_stats(curve), "curve": curve}

def period_stats(curve):
    month_end, prev_m = {}, None
    for pt in curve:
        month_end[pt["d"][:7]] = pt["eq"]
    keys = sorted(month_end); rets = []; last = 100.0
    for k in keys:
        rets.append(month_end[k] / last - 1); last = month_end[k]
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    pkv, since, longest = 100.0, 0, 0
    for pt in curve:
        if pt["eq"] >= pkv: pkv, since = pt["eq"], 0
        else: since += 1; longest = max(longest, since)
    return {"n_months": len(rets),
            "median_month_pct": round(statistics.median(rets) * 100, 2) if rets else None,
            "share_positive_pct": round(100 * sum(1 for r in rets if r > 0) / len(rets), 1) if rets else None,
            "best_month_pct": round(max(rets) * 100, 2) if rets else None,
            "worst_month_pct": round(min(rets) * 100, 2) if rets else None,
            "longest_losing_streak_months": streak,
            "longest_days_between_new_highs": longest,
            "mean_month_pct_secondary": round(statistics.mean(rets) * 100, 2) if rets else None}

def spy_buyhold(bars, start, end):
    seg = [b for b in bars if start <= b["d"] <= end]
    if len(seg) < 2: return None
    sh = (100.0 / (1 + COST)) / seg[0]["o"]
    net = sh * seg[-1]["c"]; net -= COST * net + SELL_FEE
    return round(net, 2)

def main():
    bars_by = {t: load_bars(t) for t in POND}
    spy = load_bars("SPY"); bars_by["SPY"] = spy
    spy_c = [b["c"] for b in spy]; s200 = sma(spy_c, 200)
    gate_by_date = {spy[i]["d"]: (1 if s200[i] and spy_c[i] > s200[i] else 0) for i in range(len(spy))}
    trades_by = {}
    for t in POND:
        gate = [gate_by_date.get(b["d"], 0) for b in bars_by[t]]
        trades_by[t] = darvas_trades(bars_by[t], gate)
    total = sum(len(v) for v in trades_by.values())
    out = {"family": "hunt-darvas-box", "program": "v13-best-rules",
           "form": "MY RULES: published 3-day box, intraday breakout entry, NO volume gate, NO pyramid, stop below broken box lower rail trailing to new boxes' lower rails, max-3 equal slots, SPY>200d gate, ATH-5% leg, no floor",
           "costs": "0.10% of notional per side + $0.01 per sell order",
           "total_trades_pond_full_history": total, "roads": {}}
    beat = []
    for name, (s, e) in ROADS.items():
        r = run_basket(bars_by, trades_by, s, e)
        # placebos: matched per-asset entry counts, median hold of real in-road trades
        holds = []
        for t in POND:
            for tr in trades_by[t]:
                if s <= tr["entry_d"] <= e: holds.append(tr["exit_i"] - tr["entry_i"])
        med_hold = int(statistics.median(holds)) if holds else 10
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed * 7 + hash(name) % 997)
            ptr = {}
            for t in POND:
                bars = bars_by[t]
                didx = [i for i, b in enumerate(bars) if s <= b["d"] <= e]
                k = sum(1 for tr in trades_by[t] if s <= tr["entry_d"] <= e)
                pool = didx[: max(0, len(didx) - med_hold - 1)]
                ents = sorted(rng.sample(pool, min(k, len(pool)))) if k and pool else []
                ptr[t] = [{"entry_i": i, "entry_px": bars[i]["c"], "entry_d": bars[i]["d"],
                           "exit_i": i + med_hold, "exit_px": bars[i + med_hold]["c"],
                           "exit_d": bars[i + med_hold]["d"]} for i in ents]
            finals.append(run_basket(bars_by, ptr, s, e)["final"])
        beaten = sum(1 for f in finals if r["final"] > f)
        out["roads"][name] = {"window": [s, e], "final": r["final"], "max_dd_pct": r["max_dd_pct"],
            "costs": r["costs"], "orders": r["orders"], "entries_generated": r["entries_taken"],
            "expectancy": r["expectancy"], "periods": r["periods"],
            "placebo_beaten": f"{beaten}/20", "placebo_median": round(statistics.median(finals), 2),
            "placebo_finals": finals, "spy_price_only_net": spy_buyhold(spy, s, e),
            "spy_program_ref": SPY_PROG[name], "champion_vm": CHAMPION[name],
            "published_mechanical_basket5": PUBLISHED[name], "curve": r["curve"]}
        print(f"{name:7s} final ${r['final']:8.2f} dd {r['max_dd_pct']:5.1f}% costs ${r['costs']:6.2f} "
              f"orders {r['orders']:4d} placebo {beaten}/20 med ${statistics.median(finals):.2f} | "
              f"pub ${PUBLISHED[name]} SPYprog ${SPY_PROG[name]} champ ${CHAMPION[name]}", flush=True)
        if r["final"] > CHAMPION[name]: beat.append(name)
    if beat:
        out["confirmation"] = {}
        for cname, (s, e) in {"CONF_A": ("2017-01-03", "2020-12-31"), "CONF_B": ("2021-01-04", "2024-12-31")}.items():
            r = run_basket(bars_by, trades_by, s, e)
            out["confirmation"][cname] = {"window": [s, e], "final": r["final"], "max_dd_pct": r["max_dd_pct"],
                                          "spy_price_only_net": spy_buyhold(spy, s, e)}
            print(cname, "final", r["final"], "SPY(price)", spy_buyhold(spy, s, e), flush=True)
        for name in beat:
            s, e = ROADS[name]
            mid = "2023-01-02" if name == "LONG" else ("2021-11-22" if name == "DECADE" else None)
            if mid:
                h1 = run_basket(bars_by, trades_by, s, mid)
                h2 = run_basket(bars_by, trades_by, mid, e)
                out["confirmation"][name + "_halves"] = {"first_half_final": h1["final"], "second_half_final": h2["final"]}
                print(name, "halves:", h1["final"], h2["final"], flush=True)
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("saved results.json; champion beats:", beat or "none")

if __name__ == "__main__":
    main()
