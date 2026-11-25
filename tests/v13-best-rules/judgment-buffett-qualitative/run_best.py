#!/usr/bin/env python3
"""
V13 BEST-RULES — Buffett Qualitative / Moat (JUDGMENT-CONSTRUCTED).
Frozen per BEST-RULES-SPEC.md. Chassis: persistence holding — keep any held
name that still passes the gates, never rebalance/trim; sell only on gate
failure; fill vacancies from highest-ranked non-held passers with available
cash split equally among the fills only.
Reads ONLY the v12 caches (read-only): eval_cache.json + price_cache.json.
Writes only inside this folder -> results.json (equity curves included).
"""
import json, os, sys, math, random, statistics, bisect
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V12 = os.path.expanduser(
    "~/workspace/stock-app/backtests/v12-completions/judgment-buffett-qualitative")

START_CASH = 100.0
BUY_COST, SELL_COST, SELL_FEE = 0.001, 0.001, 0.01
N_HOLD = 5
ROADS = [("LONG", "2010-01-04", "2026-11-20"),
         ("DECADE", "2016-11-21", "2026-11-20"),
         ("CONT", "2019-01-02", "2026-11-20"),
         ("VAL", "2023-01-03", "2026-11-20")]
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}


class Book:
    def __init__(self, prices):
        self.dates = prices["SPY"]["dates"]
        self.data = prices
        self.idx = {t: {d: i for i, d in enumerate(p["dates"])}
                    for t, p in prices.items()}

    def bar(self, t, d):
        p = self.data.get(t)
        if not p:
            return None
        i = self.idx[t].get(d)
        return (p["o"][i], p["c"][i]) if i is not None else None

    def close_le(self, t, d):
        p = self.data.get(t)
        if not p:
            return None
        i = bisect.bisect_right(p["dates"], d) - 1
        return p["c"][i] if i >= 0 else None

    def last_date(self, t):
        p = self.data.get(t)
        return p["dates"][-1] if p and p["dates"] else None


def simulate(book, evals, start, end, placebo_rng=None):
    """Persistence chassis. Returns dict with final/costs/trades/curve/pools."""
    cash = START_CASH
    positions = {}          # ticker -> shares
    trades, total_costs = [], 0.0
    curve, pools = [], []
    days = [d for d in book.dates if start <= d <= end]
    form_set = {d for d in days if d in evals}
    pending = None          # (sells:set, buys:list) to execute at today's open
    floor_breach = None

    def close_val(t, d):
        ld = book.last_date(t)
        if ld is None or d > ld:
            return 0.0
        c = book.close_le(t, d)
        return c if c else 0.0

    def pclose(d):
        return cash + sum(sh * close_val(t, d) for t, sh in positions.items())

    def execute(d, sells, buys):
        nonlocal cash, total_costs
        # sells first (full exits), at open; vanished names are already 0
        for t in list(sells):
            if t not in positions:
                continue
            ld = book.last_date(t)
            if ld is not None and d > ld:
                del positions[t]  # tape ended: valued zero, nothing to sell
                continue
            b = book.bar(t, d)
            if not b:
                continue
            val = positions[t] * b[0]
            c = val * SELL_COST + SELL_FEE
            cash += val - c
            total_costs += c
            trades.append((d, t, "SELL", round(positions[t], 6), b[0],
                           round(val, 2), round(c, 2)))
            del positions[t]
        if buys:
            per = cash / len(buys)
            for t in buys:
                b = book.bar(t, d)
                if not b or b[0] <= 0:
                    continue
                bv = min(per, cash / 1.001)
                if bv <= 0.005:
                    continue
                sh = bv / b[0]
                c = bv * BUY_COST
                cash -= bv + c
                total_costs += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", round(sh, 6), b[0],
                               round(bv, 2), round(c, 2)))

    for d in days:
        if pending is not None:
            execute(d, pending[0], pending[1])
            pending = None
        if d in form_set:
            ranked = evals[d]["ranked"]
            elig = set(ranked)
            sells = {t for t in positions if t not in elig}
            held_ok = [t for t in positions if t in elig]
            n_vac = N_HOLD - len(held_ok)
            buys = []
            if n_vac > 0:
                cands = [t for t in ranked if t not in positions]
                if placebo_rng is not None:
                    buys = placebo_rng.sample(cands, min(n_vac, len(cands))) \
                        if cands else []
                else:
                    buys = cands[:n_vac]
            pools.append({"date": d, "eligible": evals[d]["eligible"],
                          "held_kept": held_ok, "sells": sorted(sells),
                          "buys": buys, "fails": evals[d]["fails"],
                          "waived_margin": evals[d]["waived"]})
            if sells or buys:
                pending = (sells, buys)
        v = pclose(d)
        curve.append((d, round(v, 4)))
        if floor_breach is None and v <= 85.0:
            floor_breach = d
    last = days[-1]
    for t in list(positions):
        c_ = close_val(t, last)
        if c_ > 0:
            val = positions[t] * c_
            cst = val * SELL_COST + SELL_FEE
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", round(positions[t], 6), c_,
                           round(val, 2), round(cst, 2)))
        del positions[t]
    return {"final": round(cash, 2), "costs": round(total_costs, 2),
            "trades": trades, "curve": curve, "pools": pools,
            "floor_breach_diagnostic": floor_breach}


def spy_net(book, start, end):
    days = [d for d in book.dates if start <= d <= end]
    o = book.bar("SPY", days[0])[0]
    sh = (START_CASH / 1.001) / o
    val = sh * book.close_le("SPY", days[-1])
    return round(val - (val * 0.001 + 0.01), 2)


def period_stats(curve, freq):
    ends = {}
    for d, v in curve:
        ends[d[:4] if freq == "A" else d[:7]] = v
    keys = sorted(ends)
    vals = [START_CASH] + [ends[k] for k in keys]
    rets = [(vals[i] / vals[i - 1] - 1) * 100 for i in range(1, len(vals))
            if vals[i - 1] > 0]
    if not rets:
        return None
    pos = sum(1 for r in rets if r > 0)
    run = worst = 0
    for r in rets:
        run = run + 1 if r < 0 else 0
        worst = max(worst, run)
    peak, since, longest = vals[0], 0, 0
    for v in vals[1:]:
        if v > peak:
            peak, longest, since = v, max(longest, since), 0
        else:
            since += 1
    longest = max(longest, since)
    return {"periods": len(rets),
            "pct_periods_profitable": round(100 * pos / len(rets), 1),
            "median_period_pct": round(statistics.median(rets), 3),
            "best_period_pct": round(max(rets), 2),
            "worst_period_pct": round(min(rets), 2),
            "longest_losing_run_periods": worst,
            "longest_stretch_between_new_highs_periods": longest,
            "average_period_pct_SECONDARY_LABELED_AVERAGE":
                round(statistics.mean(rets), 3)}


def max_dd(curve):
    peak, mdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    return round(mdd * 100, 2)


def run_window(book, evals, start, end):
    """Strategy + SPY + 20 placebos for one window. Returns summary dict."""
    r = simulate(book, evals, start, end)
    spy = spy_net(book, start, end)
    finals = []
    for seed in range(1, 21):
        rng = random.Random(1000 + seed)
        rp = simulate(book, evals, start, end, placebo_rng=rng)
        finals.append(round(rp["final"], 2))
    sfin = sorted(finals)
    return {"strategy": r, "spy_net": spy,
            "placebo_finals": finals,
            "placebo_median": round(statistics.median(sfin), 2),
            "placebo_best": sfin[-1], "placebo_worst": sfin[0],
            "beats_n_of_20": sum(1 for v in finals if r["final"] > v)}


def main():
    with open(os.path.join(V12, "eval_cache.json")) as f:
        ec = json.load(f)
    evals = ec["formations"]
    with open(os.path.join(V12, "price_cache.json")) as f:
        prices = json.load(f)
    book = Book(prices)
    out = {"label": "JUDGMENT-CONSTRUCTED — Buffett qualitative/moat, "
                    "V13 best-rules (persistence chassis)",
           "form": "JUDGMENT-CONSTRUCTED",
           "N": N_HOLD, "load_failures": ec["load_failures"], "roads": {}}
    for rname, ws, we in ROADS:
        w = run_window(book, evals, ws, we)
        r = w["strategy"]
        road = {"final": r["final"], "costs": r["costs"],
                "orders": len(r["trades"]),
                "max_drawdown_pct": max_dd(r["curve"]),
                "floor_breach_diagnostic": r["floor_breach_diagnostic"],
                "spy_net": w["spy_net"], "champion_VM": CHAMP[rname],
                "pools": r["pools"], "curve": r["curve"],
                "trades": r["trades"],
                "placebos": {"seeds": 20, "finals": w["placebo_finals"],
                             "median": w["placebo_median"],
                             "best": w["placebo_best"],
                             "worst": w["placebo_worst"],
                             "strategy_beats_n_of_20": w["beats_n_of_20"]},
                "period_stats": {
                    "annual_native_tempo": period_stats(r["curve"], "A"),
                    "monthly_secondary": period_stats(r["curve"], "M")}}
        out["roads"][rname] = road
        print(f"{rname}: final=${r['final']:,.2f} costs=${r['costs']:.2f} "
              f"orders={len(r['trades'])} maxDD={max_dd(r['curve'])}% "
              f"spy=${w['spy_net']} champ=${CHAMP[rname]} "
              f"placebo med=${w['placebo_median']:,.2f} "
              f"beats {w['beats_n_of_20']}/20", flush=True)
        # ---- confirmation (frozen bars in BEST-RULES-SPEC rule 12) ----
        if r["final"] > CHAMP[rname]:
            print(f"{rname}: BEATS CHAMPION — running frozen confirmation",
                  flush=True)
            days = [d for d in book.dates if ws <= d <= we]
            mid = days[len(days) // 2]
            conf = {"triggered": True, "midpoint": mid, "halves": {},
                    "yearly_folds": {}}
            halves = [("H1", ws, mid), ("H2", next(
                d for d in days if d > mid), we)]
            conf["halves_pass"] = True
            for hn, hs, he in halves:
                hw = run_window(book, evals, hs, he)
                ok = (hw["strategy"]["final"] > hw["spy_net"] and
                      hw["strategy"]["final"] > hw["placebo_median"])
                conf["halves"][hn] = {
                    "window": [hs, he], "final": hw["strategy"]["final"],
                    "spy_net": hw["spy_net"],
                    "placebo_median": hw["placebo_median"], "pass": ok}
                conf["halves_pass"] = conf["halves_pass"] and ok
                print(f"  {hn} {hs}..{he}: final=${hw['strategy']['final']} "
                      f"spy=${hw['spy_net']} pmed=${hw['placebo_median']} "
                      f"pass={ok}", flush=True)
            forms = sorted(d for d in evals if ws <= d <= we)
            n_spy = n_pl = 0
            for fd in forms:
                fw = run_window(book, evals, fd, we)
                s_ok = fw["strategy"]["final"] > fw["spy_net"]
                p_ok = fw["strategy"]["final"] > fw["placebo_median"]
                n_spy += s_ok
                n_pl += p_ok
                conf["yearly_folds"][fd] = {
                    "final": fw["strategy"]["final"],
                    "spy_net": fw["spy_net"],
                    "placebo_median": fw["placebo_median"],
                    "beats_spy": s_ok, "beats_placebo_median": p_ok}
                print(f"  fold {fd}: final=${fw['strategy']['final']} "
                      f"spy=${fw['spy_net']} pmed=${fw['placebo_median']}",
                      flush=True)
            nf = len(forms)
            conf["folds_pass"] = (n_spy > nf / 2 and n_pl > nf / 2)
            conf["confirmed"] = bool(conf["halves_pass"] and
                                     conf["folds_pass"])
            road["confirmation"] = conf
            print(f"  folds: beats SPY {n_spy}/{nf}, placebo median "
                  f"{n_pl}/{nf} -> confirmed={conf['confirmed']}", flush=True)
        else:
            road["confirmation"] = {"triggered": False}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE — results.json written", flush=True)


if __name__ == "__main__":
    main()
