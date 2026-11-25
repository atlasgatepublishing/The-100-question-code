#!/usr/bin/env python3
"""v13 BEST RULES — Fitschen Aberration (CONSTRUCTED), frozen in BEST-RULES-SPEC.md.
Signal UNCHANGED from v12 construction: SMA(20) +/- 2.0 x pop SD(20);
entry on close above upper band; exit on close below SMA(20); long-only.
MY translation: portfolio breadth — signal run on all 153 non-SPY pond
names, up to 10 concurrent equal slots (10% of equity at entry), ranked
same-day by breakout strength, center-line exits only, NO pot floor.
Daily, decide at close, execute next open. Costs 0.10%/side + $0.01/sell.
Placebos: per-name circular shift of the in/out target series (20 seeds).
Confirmation (frozen in spec) runs only if a road beats champion V+M.
Implementation note: numpy calendar-aligned arrays + precomputed daily
events (the first pure-Python version was too slow and was replaced
before producing any number — plumbing only, no spec element changed)."""
import json, os, glob, time, statistics, math
import numpy as np

START = 100.0
COST = 0.001; SELL_FEE = 0.01
MAX_SLOTS = 10; SLOT_FRAC = 0.10; MIN_CASH_FRAC = 0.05
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PXDIR = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
HERE = os.path.dirname(os.path.abspath(__file__))


def load_pxfull(ticker):
    p = os.path.join(PXDIR, f"pxfull_{ticker}.json")
    j = json.load(open(p))
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


def signal_series(closes):
    n = len(closes); targets = np.zeros(n, dtype=bool); strengths = np.zeros(n)
    pos = False
    for i in range(n):
        if i >= 19:
            win = closes[i - 19:i + 1]
            sma = win.mean()
            upper = sma + 2.0 * win.std()  # population SD
            strengths[i] = closes[i] / upper - 1.0 if upper > 0 else 0.0
            if not pos and closes[i] > upper:
                pos = True
            elif pos and closes[i] < sma:
                pos = False
        targets[i] = pos
    return targets, strengths


def period_stats(curve):
    if not curve:
        return None
    vals, last = [], None
    for d, v in curve:
        k = d[:7]
        if k != last:
            vals.append(v); last = k
        else:
            vals[-1] = v
    series = [START] + vals
    if len(series) < 2:
        return None
    rets = [(series[i] / series[i - 1] - 1.0) * 100.0 if series[i - 1] > 0 else 0.0
            for i in range(1, len(series))]
    posc = sum(1 for r in rets if r > 0)
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
    return {"periods": len(rets), "pct_positive": round(100.0 * posc / len(rets), 1),
            "median_pct": round(statistics.median(rets), 3),
            "mean_pct_secondary_average_only": round(statistics.mean(rets), 3),
            "best_pct": round(max(rets), 2), "worst_pct": round(min(rets), 2),
            "longest_losing_streak": worst, "longest_between_highs_periods": longest}


class Pond:
    """Calendar-aligned arrays. cal: list of dates (SPY calendar).
    For each tick: opens/closes (nan where no bar), targets, strengths."""

    def __init__(self):
        spy = load_pxfull("SPY")
        self.spy = spy
        self.cal = [b["d"] for b in spy]
        self.cidx = {d: i for i, d in enumerate(self.cal)}
        self.ticks = []
        self.O = {}; self.C = {}; self.T = {}; self.S = {}
        ticks = sorted(os.path.basename(p)[7:-5]
                       for p in glob.glob(os.path.join(PXDIR, "pxfull_*.json")))
        for t in ticks:
            if t == "SPY":
                continue
            bars = load_pxfull(t)
            if len(bars) < 60:
                continue
            n = len(self.cal)
            O = np.full(n, np.nan); C = np.full(n, np.nan)
            idxs = []
            for b in bars:
                i = self.cidx.get(b["d"])
                if i is not None:
                    O[i] = b["o"]; C[i] = b["c"]; idxs.append(i)
            closes_own = np.array([b["c"] for b in bars])
            tg, st = signal_series(closes_own)
            T = np.zeros(n, dtype=bool); S = np.zeros(n)
            for k, i in enumerate(idxs):
                T[i] = tg[k]; S[i] = st[k]
            self.ticks.append(t); self.O[t] = O; self.C[t] = C
            self.T[t] = T; self.S[t] = S

    def events(self, i0, i1, seed=None):
        """Per-day events for window [i0, i1): dict day_offset -> (buy_candidates, sells)
        derived from target transitions. Buys: (tick, strength) unsorted.
        Sells: tick list (only meaningful if held; engine checks)."""
        rng = np.random.default_rng(seed) if seed is not None else None
        buys = {}; sells = {}
        for t in self.ticks:
            tg = self.T[t][i0:i1].copy()
            if rng is not None:
                if tg.any() and len(tg) > 1:
                    k = int(rng.integers(1, len(tg)))
                    tg = np.roll(tg, k)
                prev0 = False
            else:
                prev0 = bool(self.T[t][i0 - 1]) if i0 > 0 else False
            prev = np.empty(len(tg), dtype=bool)
            prev[0] = prev0; prev[1:] = tg[:-1]
            up = tg & ~prev; dn = ~tg & prev
            st = self.S[t][i0:i1]
            for j in np.nonzero(up)[0]:
                buys.setdefault(int(j), []).append((t, float(st[j])))
            for j in np.nonzero(dn)[0]:
                sells.setdefault(int(j), []).append(t)
        for j in buys:
            buys[j].sort(key=lambda x: (-x[1], x[0]))
        return buys, sells

    def run(self, start, end, seed=None):
        i0 = next(i for i, d in enumerate(self.cal) if d >= start)
        i1 = max(i for i, d in enumerate(self.cal) if d <= end) + 1
        buys, sells = self.events(i0, i1, seed)
        cash = START; positions = {}
        costs = 0.0; trades = []; closed = []
        pending_buys = []; pending_sells = []
        last_close = {}
        days_invested = 0; curve = []
        for j in range(i1 - i0):
            gi = i0 + j; d = self.cal[gi]
            for t in list(pending_sells):
                if t in positions and not np.isnan(self.O[t][gi]):
                    pos = positions.pop(t); o = float(self.O[t][gi])
                    val = pos[0] * o; fee = val * COST + SELL_FEE
                    cash += val - fee; costs += fee
                    trades.append([d, "SELL", t, round(o, 4), round(val, 2), round(fee, 2)])
                    closed.append(val - fee - pos[1])
            pending_sells = []
            if pending_buys:
                eq_open = cash
                for t, pos in positions.items():
                    px = self.O[t][gi] if not np.isnan(self.O[t][gi]) else last_close.get(t, 0.0)
                    eq_open += pos[0] * float(px)
                for t, _s in pending_buys:
                    if len(positions) >= MAX_SLOTS or t in positions:
                        continue
                    if np.isnan(self.O[t][gi]):
                        continue
                    if cash < MIN_CASH_FRAC * eq_open:
                        continue
                    notional = min(SLOT_FRAC * eq_open, cash)
                    if notional <= 0:
                        continue
                    bv = notional / (1 + COST); fee = bv * COST
                    o = float(self.O[t][gi]); shares = bv / o
                    cash -= bv + fee
                    positions[t] = (shares, bv + fee)
                    costs += fee
                    trades.append([d, "BUY", t, round(o, 4), round(bv, 2), round(fee, 2)])
                pending_buys = []
            eq = cash
            for t, pos in positions.items():
                if not np.isnan(self.C[t][gi]):
                    last_close[t] = float(self.C[t][gi])
                eq += pos[0] * last_close.get(t, 0.0)
            if positions:
                days_invested += 1
            curve.append([d, round(eq, 4)])
            if j in sells:
                pending_sells = [t for t in sells[j] if t in positions]
            if j in buys:
                pending_buys = buys[j]
        last_d = self.cal[i1 - 1]
        for t in list(positions):
            pos = positions.pop(t); px = last_close.get(t, 0.0)
            val = pos[0] * px; fee = val * COST + SELL_FEE
            cash += val - fee; costs += fee
            trades.append([last_d, "SELL-END", t, round(px, 4), round(val, 2), round(fee, 2)])
            closed.append(val - fee - pos[1])
        if curve:
            curve[-1] = [last_d, round(cash, 4)]
        peak, maxdd = -1.0, 0.0
        for _, v in curve:
            peak = max(peak, v)
            if peak > 0:
                maxdd = max(maxdd, (peak - v) / peak)
        wins = [c for c in closed if c > 0]; losses = [c for c in closed if c <= 0]
        return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
                "costs": round(costs, 2), "orders": len(trades), "trades": trades,
                "invested_pct_days_any_position": round(100.0 * days_invested / max(1, (i1 - i0)), 1),
                "equity_curve": curve, "period_stats": period_stats(curve),
                "closed_trades": len(closed),
                "win_rate_pct": round(100.0 * len(wins) / len(closed), 1) if closed else None,
                "avg_win": round(statistics.mean(wins), 2) if wins else None,
                "avg_loss": round(statistics.mean(losses), 2) if losses else None,
                "expectancy_per_trade": round(statistics.mean(closed), 2) if closed else None}


def buy_hold(bars, start, end):
    days = [b for b in bars if start <= b["d"] <= end]
    if not days:
        return None
    o = days[0]["o"]; sh = (START / (1 + COST)) / o
    curve = [[b["d"], round(sh * b["c"], 4)] for b in days]
    val = sh * days[-1]["c"]; final = val - (val * COST + SELL_FEE)
    curve[-1] = [days[-1]["d"], round(final, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(final, 2), "max_dd_pct": round(maxdd * 100, 2), "equity_curve": curve}


def spy_timer(bars, start, end):
    closes = np.array([b["c"] for b in bars])
    targets, _ = signal_series(closes)
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    desired = bool(targets[idx[0] - 1]) if idx and idx[0] > 0 else False
    cash, shares, costs = START, 0.0, 0.0
    pending = desired if desired else None
    curve = []
    for i in idx:
        b = bars[i]
        if pending is not None:
            if pending and shares == 0.0:
                bv = cash / (1 + COST); fee = bv * COST
                shares = bv / b["o"]; cash -= bv + fee; costs += fee
            elif not pending and shares > 0:
                val = shares * b["o"]; fee = val * COST + SELL_FEE
                cash += val - fee; costs += fee; shares = 0.0
            pending = None
        if bool(targets[i]) != (shares > 0):
            pending = bool(targets[i])
        curve.append([b["d"], round(cash + shares * b["c"], 4)])
    if shares > 0:
        last = bars[idx[-1]]; val = shares * last["c"]; fee = val * COST + SELL_FEE
        cash += val - fee; costs += fee; shares = 0.0
        curve[-1] = [last["d"], round(cash, 4)]
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return {"final": round(cash, 2), "max_dd_pct": round(maxdd * 100, 2),
            "costs": round(costs, 2), "equity_curve": curve}


def main():
    pond = Pond()
    print(f"pond: {len(pond.ticks)} names, calendar {pond.cal[0]} -> {pond.cal[-1]}")
    out = {"family": "hunt-fitschen-aberration (Fitschen Aberration — CONSTRUCTED)",
           "form": "v13 best rules: frozen SMA20 +/-2SD band-break / center-line exit signal, portfolio breadth 10 equal slots over the pond, no floor",
           "pond_names": len(pond.ticks),
           "costs": "stocks 0.10%/side + $0.01 sell fee", "roads": {}, "confirmation": {}}
    for name, (s, e) in ROADS.items():
        r = pond.run(s, e)
        bh = buy_hold(pond.spy, s, e)
        st_ref = spy_timer(pond.spy, s, e)
        finals = [pond.run(s, e, seed=seed)["final"] for seed in range(1, 21)]
        rec = {"my_rules": r, "spy_hold_same_plumbing": {"final": bh["final"], "max_dd_pct": bh["max_dd_pct"]},
               "spy_program_ref": SPYREF[name], "champion_vm": CHAMP[name],
               "published_form_spy_timer_same_plumbing": {"final": st_ref["final"], "max_dd_pct": st_ref["max_dd_pct"], "costs": st_ref["costs"]},
               "placebo": {"seed_finals": finals, "median": round(statistics.median(finals), 2),
                           "beaten_of_20": sum(1 for p in finals if r["final"] > p),
                           "design": "per-name circular shift of in/out target series within the road (20 seeds); same slots/ranking/sizing/costs"}}
        out["roads"][name] = rec
        print(f"{name}: mine ${r['final']} (DD {r['max_dd_pct']}%, costs ${r['costs']}, orders {r['orders']}, "
              f"closed {r['closed_trades']}, placebos {rec['placebo']['beaten_of_20']}/20) | "
              f"SPYtimer ${st_ref['final']} | SPYhold ${bh['final']} | champ ${CHAMP[name]}", flush=True)
        if r["final"] > CHAMP[name]:
            print(f"  {name} BEATS CHAMPION — running frozen confirmation", flush=True)
            conf = {"yearly_folds": {}}
            my_years, spy_years = [], []
            for y in range(int(s[:4]), int(e[:4]) + 1):
                ys, ye = max(s, f"{y}-01-01"), min(e, f"{y}-12-31")
                if ys > ye:
                    continue
                ry = pond.run(ys, ye); sy = buy_hold(pond.spy, ys, ye)
                if ry and sy:
                    conf["yearly_folds"][str(y)] = {"mine": ry["final"], "spy": sy["final"]}
                    my_years.append(ry["final"]); spy_years.append(sy["final"])
            conf["yearly_summary"] = {
                "median_mine": round(statistics.median(my_years), 2),
                "median_spy": round(statistics.median(spy_years), 2),
                "share_positive_pct": round(100.0 * sum(1 for v in my_years if v > 100) / len(my_years), 1),
                "pass": bool(statistics.median(my_years) > 100 and
                             sum(1 for v in my_years if v > 100) / len(my_years) >= 0.55 and
                             statistics.median(my_years) > statistics.median(spy_years))}
            win_dates = [d for d in pond.cal if s <= d <= e]
            mid = win_dates[len(win_dates) // 2]
            hres = []
            for hs, he in ((s, mid), (mid, e)):
                rh = pond.run(hs, he); sh2 = buy_hold(pond.spy, hs, he)
                hres.append({"window": [hs, he], "mine": rh["final"], "spy": sh2["final"],
                             "pass": bool(rh["final"] > 100 and rh["final"] > sh2["final"])})
            conf["half_windows"] = {"halves": hres, "pass": all(h["pass"] for h in hres)}
            conf["confirmed"] = bool(conf["yearly_summary"]["pass"] and conf["half_windows"]["pass"])
            out["confirmation"][name] = conf
            print("  confirmation:", json.dumps(conf)[:800], flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("DONE")


if __name__ == "__main__":
    main()
