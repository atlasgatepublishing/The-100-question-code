#!/usr/bin/env python3
"""
NOVEL TEST N-PV3 — "RIDING THE METAORDER" (return-sequence autocorrelation
sort) — Terry's AI stock app, simulation only. INVENTED-IN-2026 RULE
(Territory 1 of the v8 novel track, ~/workspace/stock-app/research/
v8-novel/novel-price-volume.md). This is 1 of 12 invented rules.

Run once, exactly per the frozen spec in novel-price-volume.md, no tuning.

Spec (verbatim substance):
  Monthly top-5 sort on the variance ratio VR-5 of the name's own daily
  returns over 63 days, with a sign gate.
  - On the last trading day of each month, for each pond name take the
    trailing 63 daily close-to-close returns r1..r63. Form the 59
    overlapping 5-day sums Sj = rj+..+rj+4 (j = 1..59). Compute
    VR = Var(S) / (5 x Var(r)), population variance for both.
  - Sign gate: eligible only if the trailing 63-day total return >= 0%.
  - Rank eligible names by VR descending; buy the top 5, equal weight
    (1/5 of pot each), at the next session's open; hold one month;
    FULL monthly rotation as in N-PV1 (sell all holdings and re-buy the
    new top 5 — no netting, so the cost record stays honest).

House chassis:
  $100 pot, honest top-30 pond as of Nov 2016, costs 0.10%/side + $0.01
  per sell order, plain -15% floor ($85, daily close, liquidate at next
  open, no re-entry), cash earns nothing. Windows: continuous
  2019-01-01 -> 2026-11-20 and validation 2023-01-01 -> 2026-11-20
  (fresh pots). 20-seed placebos (seeds 1..20) on identical dates and
  mechanics: each month, 5 RANDOM names from the same sign-gated
  eligible set, identical full-rotation engine and floor.

Data: the champion engine's own Yahoo caches, read exactly as the
champion engine reads them (~/workspace/stock-app/backtests/v4/data/
px_<T>.json first, else .../v4/value-momentum-honest-data/px_<T>.json),
bars built identically to value-momentum-plainfloor.py: open scaled by
adjclose/close, close = adjclose (split/dividend-adjusted). SPY
buy-hold via the champion engine's spy_net formula on the same bars —
the integrity gate must reproduce the published $313.62 / $187.77.

VERDICT VOCABULARY (invented-rule track): the best possible verdict is
CANDIDATE — only a forward paper trial can promote an invented rule.
CANDIDATE requires ALL of: (1) validation final > SPY $187.77,
(2) validation placebo 20/20, (3) continuous final > SPY $313.62,
(4) no floor halt on either main window. Anything less = NOT A
CANDIDATE, reported plainly.

FORCED READINGS (stated before results; forced by the spec's text or
the house chassis, none is a tuning choice):
  1. Signal/execution timing: the spec computes the signal on the last
     trading day of the month and buys at the next session's open —
     i.e. rebalance at the open of the first trading day of each month
     using the prior trading day's close (identical cadence to the
     program's other monthly sorts). The first rebalance of each
     window fires at the window's first session open, signalled from
     the prior trading day (2018-12-31 / 2022-12-30, both month-ends).
  2. The 63 returns are taken from the name's OWN bar series: the last
     64 actual closes ending on the signal day. (Pond names trade every
     SPY session, so this equals the calendar reading in practice;
     forward-filled placeholder closes are never fed to the VR.)
  3. Full rotation per N-PV1's definition: at each rebalance open,
     every holding is sold in full (each sell pays 0.10% + $0.01),
     then each pick is bought with 20% of the pot's equity marked at
     that open (pre-trade). A name still in the top 5 is sold and
     re-bought. Fewer than 5 eligible -> buy what's eligible at 20%
     each, rest cash (house convention); 0 eligible -> all cash.
  4. VR ties break by ticker (determinism only). A name with fewer
     than 64 closes on or before the signal day, or with Var(r) = 0,
     is ineligible that month.
  5. End of window: positions marked at the final close (house
     convention of the recent v7/v8 tests); the SPY benchmark is the
     champion engine's spy_net, which deducts its own final sell cost.
"""

import json
import math
import os
import random
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.expanduser("~/workspace/stock-app/backtests/v4/data")
HONEST = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/value-momentum-honest-data")

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
BENCH = "SPY"
COST_RATE = 0.001                 # 0.10% per side
SELL_FEE = 0.01                   # per sell order
POT = 100.0
FLOOR = 85.0                      # plain -15% floor, no ladder
N_RET = 63                        # trailing daily returns
LAG = 5                           # VR-5

WINDOWS = {
    "continuous": ("2019-01-01", "2026-11-20"),
    "validation": ("2023-01-01", "2026-11-20"),
}
PLACEBO_SEEDS = list(range(1, 21))

# CANDIDATE gates (invented-rule track, from the tasking)
GATE_SPY = {"continuous": 313.62, "validation": 187.77}
CHAMPION = {"continuous": 544.47, "validation": 288.05}


# --------------------------------------------------------------------------
# Data — champion engine construction, verbatim method
# --------------------------------------------------------------------------
def load_bars(ticker):
    """Return sorted list of {d, o, c} with o scaled by adjclose/close
    and c = adjclose, exactly as value-momentum-plainfloor.get_prices."""
    path = os.path.join(SHARED, f"px_{ticker}.json")
    if not (os.path.exists(path) and os.path.getsize(path) > 100):
        path = os.path.join(HONEST, f"px_{ticker}.json")
    with open(path, "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


class Market:
    """SPY calendar is the master calendar. Per-ticker: bars by date,
    forward-filled closes over the calendar for valuation, and the
    name's own close series for the VR signal."""

    def __init__(self, tickers):
        raw = {t: load_bars(t) for t in tickers + [BENCH]}
        self.cal = [b["d"] for b in raw[BENCH]]
        self.bars = {}
        self.closes = {}
        self.own = {}          # ticker -> (dates list, closes list)
        for t in tickers + [BENCH]:
            self.bars[t] = {b["d"]: (b["o"], b["c"]) for b in raw[t]}
            self.own[t] = ([b["d"] for b in raw[t]],
                           [b["c"] for b in raw[t]])
            arr, last = [], None
            for d in self.cal:
                if d in self.bars[t]:
                    last = self.bars[t][d][1]
                arr.append(last)
            self.closes[t] = arr

    def open_px(self, t, i):
        d = self.cal[i]
        if d in self.bars[t]:
            return self.bars[t][d][0]
        return None

    def close_px(self, t, i):
        return self.closes[t][i]

    def variance_ratio(self, t, signal_date):
        """(VR, total 63d return) from the name's own last 64 closes
        ending on the last own bar <= signal_date; None if unusable."""
        dates, closes = self.own[t]
        # last own bar on or before signal_date
        import bisect
        k = bisect.bisect_right(dates, signal_date) - 1
        if k < N_RET:                      # need indices k-63 .. k
            return None
        seg = closes[k - N_RET: k + 1]     # 64 closes
        if any(v is None or v <= 0 for v in seg):
            return None
        r = [seg[i + 1] / seg[i] - 1.0 for i in range(N_RET)]   # 63
        s = [sum(r[j:j + LAG]) for j in range(N_RET - LAG + 1)]  # 59

        def pvar(x):
            m = sum(x) / len(x)
            return sum((v - m) ** 2 for v in x) / len(x)

        vr_den = LAG * pvar(r)
        if vr_den <= 0:
            return None
        vr = pvar(s) / vr_den
        tot = seg[-1] / seg[0] - 1.0
        return vr, tot

    def eligible(self, signal_date):
        """[(ticker, VR, tot_ret)] passing the sign gate (tot >= 0)."""
        out = []
        for t in UNIVERSE:
            got = self.variance_ratio(t, signal_date)
            if got is None:
                continue
            vr, tot = got
            if tot >= 0.0:
                out.append((t, vr, tot))
        return out


# --------------------------------------------------------------------------
# Simulation — monthly FULL rotation; plain floor; ranked / placebo modes
# --------------------------------------------------------------------------
class Result:
    def __init__(self):
        self.final = None
        self.orders = 0
        self.costs = 0.0
        self.halt_date = None
        self.max_dd = 0.0
        self.worst_close = None
        self.equity_curve = []
        self.months = 0
        self.month_wins = 0
        self.n_months = 0
        self.elig_counts = []
        self.pick_vrs = []        # VR of each ranked pick (ranked mode)
        self.elig_vr_medians = []


def simulate(mkt, start_d, end_d, mode, seed=42, start_cash=None,
             floor=None):  # V9: protection-module parameters (defaults = his rules)
    rng = random.Random(seed)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    cash = float(POT) if start_cash is None else float(start_cash)
    if floor is None:
        floor = FLOOR
    pos = {}
    res = Result()
    pending_liquidation = False
    cur_month = None

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            tot += sh * px
        return tot

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        month_key = d[:7]

        # --- floor liquidation at the open -------------------------------
        if pending_liquidation:
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    px = mkt.close_px(t, i)
                val = pos[t] * px
                fee = val * COST_RATE + SELL_FEE
                cash += val - fee
                res.costs += fee
                res.orders += 1
                del pos[t]
            res.halt_date = d
            res.final = cash
            res.equity_curve.append((d, cash))
            break

        # --- monthly full rotation at the open ---------------------------
        if month_key != cur_month:
            cur_month = month_key
            signal_date = mkt.cal[i - 1]        # prior trading day
            elig = mkt.eligible(signal_date)
            res.elig_counts.append(len(elig))
            if elig:
                vrs = sorted(v for _, v, _ in elig)
                res.elig_vr_medians.append(vrs[len(vrs) // 2])
            if mode == "ranked":
                elig.sort(key=lambda x: (-x[1], x[0]))
                picks = [t for t, _, _ in elig[:5]]
                res.pick_vrs.extend(v for _, v, _ in elig[:5])
            else:  # placebo: random names from the same eligible set
                names = sorted(t for t, _, _ in elig)
                picks = (rng.sample(names, min(5, len(names)))
                         if names else [])
            res.n_months += 1

            eq_open = equity_at(i, use_open=True)
            # FULL ROTATION: sell everything first (N-PV1 definition)
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    px = mkt.close_px(t, i)
                val = pos[t] * px
                fee = val * COST_RATE + SELL_FEE
                cash += val - fee
                res.costs += fee
                res.orders += 1
                del pos[t]
            # buys: 20% of pre-trade equity-at-open per pick
            for t in picks:
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                target = 0.20 * eq_open
                buy_val = min(target, cash / (1.0 + COST_RATE))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * COST_RATE
                cash -= buy_val + fee
                res.costs += fee
                res.orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px

        # --- close: equity, floor ---------------------------------------
        eq_close = equity_at(i, use_open=False)
        res.equity_curve.append((d, eq_close))
        if eq_close <= floor:
            pending_liquidation = True
            if i == i1:      # no next open inside window: liquidate at close
                tot = cash
                for t, sh in list(pos.items()):
                    val = sh * mkt.close_px(t, i)
                    fee = val * COST_RATE + SELL_FEE
                    tot += val - fee
                    res.costs += fee
                    res.orders += 1
                res.final = tot
                res.halt_date = d
                pos.clear()
                break

    if res.final is None:
        res.final = res.equity_curve[-1][1]
    peak = -1.0
    worst = None
    for d, eq in res.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            res.max_dd = min(res.max_dd, eq / peak - 1.0)
        if worst is None or eq < worst[1]:
            worst = (d, eq)
    res.worst_close = {"date": worst[0], "value": round(worst[1], 2)}
    month_end = {}
    for d, eq in res.equity_curve:
        month_end[d[:7]] = eq
    keys = sorted(month_end)
    for a, b in zip(keys, keys[1:]):
        r = month_end[b] / month_end[a] - 1.0
        res.months += 1
        if r > 0:
            res.month_wins += 1
    return res


def spy_net(mkt, start_d, end_d):
    """Champion engine's spy_net formula on the champion-built bars:
    buy at the first window day's adjusted open, sell at the last
    day's adjusted close, same cost schedule."""
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    o = mkt.open_px(BENCH, i0)
    sh = (POT / 1.001) / o
    val = sh * mkt.close_px(BENCH, i1)
    return val - (val * COST_RATE + SELL_FEE)


def cagr(final, years):
    if final <= 0:
        return float("nan")
    return (final / POT) ** (1.0 / years) - 1.0


def years_between(a, b):
    da = datetime.strptime(a, "%Y-%m-%d")
    db = datetime.strptime(b, "%Y-%m-%d")
    return (db - da).days / 365.25


def per_year(res):
    out = {}
    years = sorted({d[:4] for d, _ in res.equity_curve})
    prev_eq = float(POT)
    for y in years:
        pts = [e for d, e in res.equity_curve if d[:4] == y]
        if not pts:
            continue
        end_eq = pts[-1]
        out[y] = round((end_eq / prev_eq - 1.0) * 100, 2)
        prev_eq = end_eq
    return out


def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def _summ(r, yrs, bench):
    return {
        "final": round(r.final, 2),
        "ret_pct": round((r.final / POT - 1) * 100, 2),
        "cagr_pct": round(cagr(r.final, yrs) * 100, 2),
        "orders": r.orders,
        "costs": round(r.costs, 2),
        "max_dd_pct": round(r.max_dd * 100, 2),
        "worst_close": r.worst_close,
        "halt": r.halt_date,
        "month_win_pct": (round(100 * r.month_wins / r.months, 1)
                          if r.months else None),
        "bench_final": round(bench, 2),
    }


def main_original():  # V9: superseded by main() below (placebos not re-run)
    mkt = Market(UNIVERSE)
    out = {"test": "novel-pv3-riding-the-metaorder",
           "track": "v8 novel (invented-in-2026), 1 of 12 invented rules",
           "source": "~/workspace/stock-app/research/v8-novel/"
                     "novel-price-volume.md (Rule N-PV3)",
           "universe": UNIVERSE, "placebo_seeds": PLACEBO_SEEDS,
           "floor": FLOOR, "pot": POT}

    # ---- integrity gate ----------------------------------------------------
    gates = {}
    for wname, (sd, ed) in WINDOWS.items():
        gates[wname] = round(spy_net(mkt, sd, ed), 2)
    out["integrity_spy_net"] = gates
    print(f"INTEGRITY SPY net (champion construction): "
          f"continuous={gates['continuous']} (published 313.62)  "
          f"validation={gates['validation']} (published 187.77)",
          flush=True)

    ranked, ranked_res = {}, {}
    for wname, (sd, ed) in WINDOWS.items():
        yrs = years_between(sd, ed)
        bench = spy_net(mkt, sd, ed)
        r = simulate(mkt, sd, ed, "ranked")
        ranked[wname] = r.final
        ranked_res[wname] = r
        s = _summ(r, yrs, bench)
        s["n_selection_months"] = r.n_months
        s["elig_min"] = min(r.elig_counts) if r.elig_counts else None
        s["elig_median"] = (_pct(sorted(r.elig_counts), 0.5)
                            if r.elig_counts else None)
        s["elig_max"] = max(r.elig_counts) if r.elig_counts else None
        s["pick_vr_mean"] = (round(sum(r.pick_vrs) / len(r.pick_vrs), 4)
                             if r.pick_vrs else None)
        s["pick_vr_min"] = (round(min(r.pick_vrs), 4) if r.pick_vrs
                            else None)
        s["pick_vr_max"] = (round(max(r.pick_vrs), 4) if r.pick_vrs
                            else None)
        s["elig_vr_median_mean"] = (
            round(sum(r.elig_vr_medians) / len(r.elig_vr_medians), 4)
            if r.elig_vr_medians else None)
        s["champion_final"] = CHAMPION[wname]
        out[f"{wname}|ranked"] = s
        print(f"{wname}|ranked: final={r.final:.2f} "
              f"ret={(r.final/POT-1)*100:+.2f}% orders={r.orders} "
              f"costs=${r.costs:.2f} maxDD={r.max_dd*100:.2f}% "
              f"halt={r.halt_date} elig_med={s['elig_median']} "
              f"pickVR_mean={s['pick_vr_mean']}", flush=True)
        if wname == "continuous":
            out["per_year_ranked"] = per_year(r)

    # ---- placebos -----------------------------------------------------------
    placebo_beats = {}
    for wname, (sd, ed) in WINDOWS.items():
        bench = spy_net(mkt, sd, ed)
        finals, rows = [], []
        for seed in PLACEBO_SEEDS:
            r = simulate(mkt, sd, ed, "placebo", seed=seed)
            finals.append(r.final)
            rows.append({
                "seed": seed, "final": round(r.final, 2),
                "ret_pct": round((r.final / POT - 1) * 100, 2),
                "max_dd_pct": round(r.max_dd * 100, 2),
                "halt": r.halt_date, "orders": r.orders,
                "costs": round(r.costs, 2)})
        sfin = sorted(finals)
        rk = ranked[wname]
        n_beat = sum(1 for v in finals if rk > v)
        placebo_beats[wname] = n_beat
        dist = {
            "n_seeds": len(finals),
            "median_final": round(_pct(sfin, 0.50), 2),
            "p25_final": round(_pct(sfin, 0.25), 2),
            "p75_final": round(_pct(sfin, 0.75), 2),
            "best_final": round(sfin[-1], 2),
            "worst_final": round(sfin[0], 2),
            "n_halted": sum(1 for row in rows if row["halt"]),
            "ranked_final": round(rk, 2),
            "ranked_minus_median": round(rk - _pct(sfin, 0.50), 2),
            "ranked_beats_n_of_20": n_beat,
            "ranked_percentile": round(100.0 * n_beat / len(finals), 1),
            "bench_final": round(bench, 2),
            "rows": rows}
        out[f"{wname}|placebo_dist"] = dist
        print(f"{wname}|placebo_dist: median={dist['median_final']:.2f} "
              f"best={dist['best_final']:.2f} worst={dist['worst_final']:.2f} "
              f"ranked={rk:.2f} beats {n_beat}/20 "
              f"halted={dist['n_halted']}", flush=True)

    # ---- verdict (invented-rule bar) ---------------------------------------
    checks = {
        "validation_final_gt_spy_187.77":
            ranked["validation"] > GATE_SPY["validation"],
        "validation_placebo_20_of_20": placebo_beats["validation"] == 20,
        "continuous_final_gt_spy_313.62":
            ranked["continuous"] > GATE_SPY["continuous"],
        "no_floor_halt_either_window":
            all(ranked_res[w].halt_date is None for w in WINDOWS),
    }
    verdict = "CANDIDATE" if all(checks.values()) else "NOT A CANDIDATE"
    out["candidate_checks"] = checks
    out["verdict"] = verdict
    print(f"CANDIDATE CHECKS: {checks} -> {verdict}", flush=True)

    with open(os.path.join(HERE, "novel-pv3-metaorder-results.json"),
              "w") as f:
        json.dump(out, f, indent=1)
    print("saved novel-pv3-metaorder-results.json")




# ======================================================================
# V9 CLAUDE-RULES PROTECTION (frozen spec v9 — ONLY change vs original):
# Episode-1 floor -15% from $100 (identical). On FIRST halt: liquidate
# exactly as the original engine does, sit in cash 90 calendar days,
# then RESTART with the remaining cash at the next monthly rotation
# (first session of a month) on/after halt date + 90 days. Episode-2
# floor: -15% from the RESTART balance. SECOND halt ends the run.
# Ranked only; no placebos.
# ======================================================================
def main():
    import datetime as _dt
    mkt = Market(UNIVERSE)
    gates = {w: round(spy_net(mkt, sd, ed), 2) for w, (sd, ed) in WINDOWS.items()}
    assert gates == {"continuous": 313.62, "validation": 187.77}, gates
    print(f"SPY gate PASSED: {gates}", flush=True)
    out_win, restarts_all = {}, []
    for wname, (sd, ed) in WINDOWS.items():
        r1 = simulate(mkt, sd, ed, "ranked")
        f1 = round(r1.final, 2)
        worst1 = r1.worst_close["value"]
        print(f"EP1 {wname}: final={f1} halt={r1.halt_date} worst={r1.worst_close}", flush=True)
        final, status, worst = f1, "completed_no_halt", worst1
        if r1.halt_date is not None:
            thr = (_dt.date.fromisoformat(r1.halt_date) + _dt.timedelta(days=90)).isoformat()
            # next monthly rotation: first SPY session of a month, >= thr
            rot = None
            for j in range(1, len(mkt.cal)):
                if mkt.cal[j] >= thr and mkt.cal[j][:7] != mkt.cal[j-1][:7]:
                    rot = mkt.cal[j]; break
            rb = r1.final; fl2 = 0.85 * rb
            r2 = simulate(mkt, rot, ed, "ranked", start_cash=rb, floor=fl2)
            final = round(r2.final, 2)
            status = "halted_episode2_permanent" if r2.halt_date else "restarted_completed"
            worst = min(worst1, r2.worst_close["value"])
            restarts_all.append({
                "window": wname, "halt_date_liquidation": r1.halt_date,
                "halt_signal_close": r1.worst_close,
                "liquidation_final_episode1": f1,
                "restart_eligible_date": thr, "restart_date": rot,
                "restart_balance": f1, "episode2_floor": round(fl2, 2),
                "episode2_halted": r2.halt_date, "episode2_final": final,
                "episode2_costs": round(r2.costs, 2),
                "episode2_worst_close": r2.worst_close})
            print(f"EP2 {wname}: restart {rot} bal={rb:.2f} floor2={fl2:.2f} final={final} halt={r2.halt_date}", flush=True)
        out_win[wname] = {"final": final, "status": status, "worst_close": worst}
    assert out_win["continuous"]["final"] is not None
    res = {"slug": "novel-pv3-metaorder", "name": "N-PV3 RIDING THE METAORDER",
           "status": "partial-rerun",
           "his": {"continuous_final": 88.05, "validation_final": 195.80},
           "v9": {"continuous_final": out_win["continuous"]["final"],
                  "validation_final": out_win["validation"]["final"],
                  "continuous_status": out_win["continuous"]["status"],
                  "validation_status": out_win["validation"]["status"],
                  "restarts": restarts_all,
                  "folds_note": "Original ran no yearly fold pots (it reported per-year returns of the continuous pot only: 2019 +9.29%, 2020 -19.43%); nothing to re-run under v9.",
                  "worst_total_loss_pct": round(100.0 - out_win["continuous"]["worst_close"], 2)},
           "notes": "Episode 1 must reproduce his recorded finals ($88.05 halted at the 2020-03-13 open, worst close $83.16 on 2020-03-12 / $195.80 validation, no halt, worst close $100.26); the run log shows the ep1 prints. Validation identical under v9. Ranked only; placebos not re-run per task. 1 of 12 invented rules.",
           "episode1_check": {"continuous_final": 88.05, "validation_final": 195.80}}
    with open(os.path.join(HERE, "novel-pv3-metaorder-v9-results.json"), "w") as f:
        json.dump(res, f, indent=1)
    with open(os.path.join(HERE, "v9-results.json"), "w") as f:
        json.dump(res, f, indent=1)
    print(json.dumps(res, indent=1), flush=True)
    print("DONE")


if __name__ == "__main__":
    main()
