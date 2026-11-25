#!/usr/bin/env python3
"""
V13 BEST-RULES — N-PV3 "RIDING THE METAORDER" under CLAUDE-DESIGNED rules.
Simulation only. Spec frozen in BEST-RULES-SPEC.md BEFORE this run.

MY RULES (vs the published v8 form):
  - VR-5 over trailing 21 daily returns (published: 63).
  - Entry gate: VR >= 1.10 AND 21-day total return >= 0 (published:
    rank-only top-5 with a 63-day sign gate).
  - Weekly checks (first trading day of ISO week; signal = prior trading
    day's close; trades at the check day's open). NO full rotation.
  - Exit at a check when the footprint is gone: VR < 1.00 or 21-day
    return < 0. Hold band: held names with VR in [1.00, 1.10) are kept.
  - Up to 5 holdings; entries fill empty slots only, 20% of pre-trade
    equity-at-open per entry; continuing holdings never rebalanced.
  - NO pot floor (published: plain -15%).
  - Universe: honest top-30 pond (Nov 2016), unchanged.
Costs: 0.10%/side + $0.01 per sell order. Cash earns nothing.
End-of-window mark at final close (house convention).

Placebos: 20 seeds/road — identical engine, gates, exits and band;
empty slots filled with RANDOM qualifying names instead of top-VR.

Data: shared read-only long-run pxfull caches
(~/workspace/stock-app/backtests/v7/long-hold/data/pxfull_<T>.json),
GOOGL from the v10 folder's slug-local pxfull_GOOGL.json. Bars built
exactly as the champion/v8 engines build them: open scaled by
adjclose/close, close = adjclose. SPY calendar is the master calendar.
Integrity: SPY buy-hold net must reproduce $822.94 / $367.80 / $313.62 /
$187.77 on LONG / DECADE / CONT / VAL.
"""
import bisect
import json
import math
import os
import random
from datetime import datetime, date

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH = os.path.join(BT, "v7", "long-hold", "data")
GOOGL_PATH = os.path.join(BT, "v10-retest", "novel-pv3-metaorder",
                          "pxfull_GOOGL.json")

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
BENCH = "SPY"
COST_RATE = 0.001
SELL_FEE = 0.01
POT = 100.0
N_RET = 21            # VR window (returns)
LAG = 5               # VR-5
VR_ENTER = 1.10       # presence threshold
VR_KEEP = 1.00        # footprint-gone exit line (band [1.00, 1.10) kept)
MAX_POS = 5
TARGET = 0.20         # of pre-trade equity at entry

ROADS = {
    "LONG":   ("2010-01-01", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT":   ("2019-01-01", "2026-11-20"),
    "VAL":    ("2023-01-01", "2026-11-20"),
}
CONFIRM_WINDOWS = {   # Terry's confirmation rule: different years
    "LONG-H1-2010-2018": ("2010-01-01", "2018-12-31"),
    "LONG-H2-2019-2026": ("2019-01-01", "2026-11-20"),
}
SPY_REF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
CHAMPION = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
PUBLISHED = {"LONG": 763.09, "DECADE": 319.77, "CONT": 88.05, "VAL": 195.80}
PLACEBO_SEEDS = list(range(1, 21))


# --------------------------------------------------------------------------
# Data — champion engine construction on the pxfull caches
# --------------------------------------------------------------------------
def load_bars(ticker):
    if ticker == "GOOGL":
        path = GOOGL_PATH
    else:
        path = os.path.join(LH, f"pxfull_{ticker}.json")
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
    def __init__(self, tickers):
        raw = {t: load_bars(t) for t in tickers + [BENCH]}
        self.cal = [b["d"] for b in raw[BENCH]]
        self.bars = {}
        self.closes = {}
        self.own = {}
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
        self._stat_cache = {}

    def open_px(self, t, i):
        d = self.cal[i]
        if d in self.bars[t]:
            return self.bars[t][d][0]
        return None

    def close_px(self, t, i):
        return self.closes[t][i]

    def stats(self, t, signal_date):
        """(VR-5 over 21 returns, 21d total return) from the name's own
        last 22 closes ending on the last own bar <= signal_date."""
        key = (t, signal_date)
        if key in self._stat_cache:
            return self._stat_cache[key]
        dates, closes = self.own[t]
        k = bisect.bisect_right(dates, signal_date) - 1
        out = None
        if k >= N_RET:
            seg = closes[k - N_RET: k + 1]          # 22 closes
            if all(v is not None and v > 0 for v in seg):
                r = [seg[i + 1] / seg[i] - 1.0 for i in range(N_RET)]
                s = [sum(r[j:j + LAG]) for j in range(N_RET - LAG + 1)]

                def pvar(x):
                    m = sum(x) / len(x)
                    return sum((v - m) ** 2 for v in x) / len(x)

                den = LAG * pvar(r)
                if den > 0:
                    out = (pvar(s) / den, seg[-1] / seg[0] - 1.0)
        self._stat_cache[key] = out
        return out


# --------------------------------------------------------------------------
# Simulation — weekly checks, footprint exit + band, no rotation, no floor
# --------------------------------------------------------------------------
class Result:
    def __init__(self):
        self.final = None
        self.orders = 0
        self.entries = 0
        self.exits = 0
        self.checks = 0
        self.costs = 0.0
        self.max_dd = 0.0
        self.worst_close = None
        self.equity_curve = []
        self.elig_counts = []
        self.pick_vrs = []
        self.holdings_sum = 0
        self.holdings_days = 0


def simulate(mkt, start_d, end_d, mode, seed=42):
    rng = random.Random(seed)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    cash = float(POT)
    pos = {}
    res = Result()

    # check dates: first trading day of each ISO week in window; the
    # window's first session is always a check date.
    check_idx = set()
    seen_wk = set()
    for i in range(i0, i1 + 1):
        key = date.fromisoformat(mkt.cal[i]).isocalendar()[:2]
        if key not in seen_wk:
            seen_wk.add(key)
            check_idx.add(i)
    check_idx.add(i0)

    def equity_at(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.open_px(t, i) if use_open else mkt.close_px(t, i)
            if px is None:
                px = mkt.close_px(t, i)
            if px is not None:
                tot += sh * px
        return tot

    for i in range(i0, i1 + 1):
        d = mkt.cal[i]
        if i in check_idx and i > 0:
            res.checks += 1
            signal_date = mkt.cal[i - 1]
            stats = {}
            for t in UNIVERSE:
                st = mkt.stats(t, signal_date)
                if st is not None:
                    stats[t] = st
            qualifiers = [t for t, (vr, tot) in stats.items()
                          if vr >= VR_ENTER and tot >= 0.0]
            res.elig_counts.append(len(qualifiers))

            eq_open = equity_at(i, use_open=True)

            # --- exits: footprint gone (VR < 1.00) or sign flipped ----
            for t in list(pos):
                st = stats.get(t)
                if st is None or st[0] < VR_KEEP or st[1] < 0.0:
                    px = mkt.open_px(t, i)
                    if px is None:
                        px = mkt.close_px(t, i)
                    val = pos[t] * px
                    fee = val * COST_RATE + SELL_FEE
                    cash += val - fee
                    res.costs += fee
                    res.orders += 1
                    res.exits += 1
                    del pos[t]

            # --- entries: fill empty slots only -----------------------
            slots = MAX_POS - len(pos)
            if slots > 0:
                cands = [t for t in qualifiers if t not in pos]
                if mode == "ranked":
                    cands.sort(key=lambda t: (-stats[t][0], t))
                else:  # placebo: random order, same gates/exits/band
                    rng.shuffle(cands)
                for t in cands[:slots]:
                    px = mkt.open_px(t, i)
                    if px is None:
                        continue
                    target = TARGET * eq_open
                    buy_val = min(target, cash / (1.0 + COST_RATE))
                    if buy_val <= 0.01:
                        continue
                    fee = buy_val * COST_RATE
                    cash -= buy_val + fee
                    res.costs += fee
                    res.orders += 1
                    res.entries += 1
                    if mode == "ranked":
                        res.pick_vrs.append(stats[t][0])
                    pos[t] = pos.get(t, 0.0) + buy_val / px

        eq_close = equity_at(i, use_open=False)
        res.equity_curve.append((d, eq_close))
        res.holdings_sum += len(pos)
        res.holdings_days += 1

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
    return res


def spy_net(mkt, start_d, end_d):
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    o = mkt.open_px(BENCH, i0)
    sh = (POT / 1.001) / o
    val = sh * mkt.close_px(BENCH, i1)
    return val - (val * COST_RATE + SELL_FEE)


# --------------------------------------------------------------------------
# Reporting helpers
# --------------------------------------------------------------------------
def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    p = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(p)), int(math.ceil(p))
    if lo == hi:
        return sorted_vals[lo]
    f = p - lo
    return sorted_vals[lo] * (1 - f) + sorted_vals[hi] * f


def period_distribution(curve):
    """Monthly-period distribution from a daily equity curve."""
    month_end = {}
    for d, eq in curve:
        month_end[d[:7]] = eq
    keys = sorted(month_end)
    rets = []
    prev = POT
    for k in keys:
        rets.append(month_end[k] / prev - 1.0)
        prev = month_end[k]
    srt = sorted(rets)
    pos_share = (sum(1 for r in rets if r > 0) / len(rets) * 100
                 if rets else None)
    # longest losing streak (months with return < 0)
    streak = best_streak = 0
    for r in rets:
        streak = streak + 1 if r < 0 else 0
        best_streak = max(best_streak, streak)
    # longest stretch between new highs (calendar days, daily curve)
    peak = -1.0
    peak_date = None
    longest = 0
    for d, eq in curve:
        if eq >= peak:
            if peak_date is not None:
                dd_days = (datetime.strptime(d, "%Y-%m-%d")
                           - datetime.strptime(peak_date, "%Y-%m-%d")).days
                longest = max(longest, dd_days)
            peak = eq
            peak_date = d
    if peak_date is not None and curve:
        dd_days = (datetime.strptime(curve[-1][0], "%Y-%m-%d")
                   - datetime.strptime(peak_date, "%Y-%m-%d")).days
        longest = max(longest, dd_days)
    return {
        "n_months": len(rets),
        "median_month_pct": round(_pct(srt, 0.5) * 100, 2) if rets else None,
        "share_months_positive_pct": round(pos_share, 1) if rets else None,
        "best_month_pct": round(max(rets) * 100, 2) if rets else None,
        "worst_month_pct": round(min(rets) * 100, 2) if rets else None,
        "mean_month_pct_SECONDARY": round(sum(rets) / len(rets) * 100, 2)
        if rets else None,
        "longest_losing_streak_months": best_streak,
        "longest_stretch_between_new_highs_days": longest,
    }


def years_between(a, b):
    da = datetime.strptime(a, "%Y-%m-%d")
    db = datetime.strptime(b, "%Y-%m-%d")
    return (db - da).days / 365.25


def run_window(mkt, name, sd, ed, with_placebos=True):
    yrs = years_between(sd, ed)
    bench = spy_net(mkt, sd, ed)
    r = simulate(mkt, sd, ed, "ranked")
    out = {
        "window": [sd, ed],
        "final": round(r.final, 2),
        "ret_pct": round((r.final / POT - 1) * 100, 2),
        "cagr_pct": round(((r.final / POT) ** (1.0 / yrs) - 1) * 100, 2)
        if r.final > 0 else None,
        "max_dd_pct": round(r.max_dd * 100, 2),
        "worst_close": r.worst_close,
        "orders": r.orders, "entries": r.entries, "exits": r.exits,
        "checks": r.checks, "costs": round(r.costs, 2),
        "avg_holdings": round(r.holdings_sum / r.holdings_days, 2)
        if r.holdings_days else None,
        "qualifiers_median": (_pct(sorted(r.elig_counts), 0.5)
                              if r.elig_counts else None),
        "qualifiers_min": min(r.elig_counts) if r.elig_counts else None,
        "qualifiers_max": max(r.elig_counts) if r.elig_counts else None,
        "pick_vr_mean": (round(sum(r.pick_vrs) / len(r.pick_vrs), 3)
                         if r.pick_vrs else None),
        "spy_final": round(bench, 2),
        "period_distribution": period_distribution(r.equity_curve),
        "equity_curve": [[d, round(e, 4)] for d, e in r.equity_curve],
    }
    print(f"{name}|ranked: final={r.final:.2f} "
          f"ret={(r.final/POT-1)*100:+.2f}% maxDD={r.max_dd*100:.2f}% "
          f"orders={r.orders} entries={r.entries} exits={r.exits} "
          f"costs=${r.costs:.2f} avgHold={out['avg_holdings']} "
          f"qualMed={out['qualifiers_median']} SPY={bench:.2f}", flush=True)
    if with_placebos:
        finals, rows = [], []
        for seed in PLACEBO_SEEDS:
            pr = simulate(mkt, sd, ed, "placebo", seed=seed)
            finals.append(pr.final)
            rows.append({"seed": seed, "final": round(pr.final, 2),
                         "max_dd_pct": round(pr.max_dd * 100, 2),
                         "orders": pr.orders,
                         "costs": round(pr.costs, 2)})
        sfin = sorted(finals)
        n_beat = sum(1 for v in finals if r.final > v)
        out["placebo"] = {
            "n_seeds": len(finals),
            "median_final": round(_pct(sfin, 0.5), 2),
            "p25_final": round(_pct(sfin, 0.25), 2),
            "p75_final": round(_pct(sfin, 0.75), 2),
            "best_final": round(sfin[-1], 2),
            "worst_final": round(sfin[0], 2),
            "ranked_beats_n_of_20": n_beat,
            "ranked_minus_median": round(r.final - _pct(sfin, 0.5), 2),
            "rows": rows,
        }
        print(f"{name}|placebo: median={_pct(sfin,0.5):.2f} "
              f"best={sfin[-1]:.2f} worst={sfin[0]:.2f} "
              f"ranked beats {n_beat}/20", flush=True)
    return out


def main():
    print("loading market...", flush=True)
    mkt = Market(UNIVERSE)
    out = {"test": "v13-best-rules novel-pv3-metaorder",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "universe": UNIVERSE, "pot": POT,
           "rules": {"n_ret": N_RET, "lag": LAG, "vr_enter": VR_ENTER,
                     "vr_keep": VR_KEEP, "max_pos": MAX_POS,
                     "target": TARGET, "floor": None,
                     "cadence": "weekly checks, footprint exit + band"},
           "placebo_seeds": PLACEBO_SEEDS}

    # integrity gate
    gates = {w: round(spy_net(mkt, sd, ed), 2)
             for w, (sd, ed) in ROADS.items()}
    out["integrity_spy_net"] = gates
    out["integrity_spy_ref"] = SPY_REF
    print(f"INTEGRITY SPY net: {gates} (refs {SPY_REF})", flush=True)

    for wname, (sd, ed) in ROADS.items():
        out[wname] = run_window(mkt, wname, sd, ed)
        out[wname]["champion_vm"] = CHAMPION[wname]
        out[wname]["published_form"] = PUBLISHED[wname]

    # confirmation windows (different years) — always run, used by the
    # verdict only if a road beats the champion
    conf = {}
    for wname, (sd, ed) in CONFIRM_WINDOWS.items():
        conf[wname] = run_window(mkt, wname, sd, ed)
    out["confirmation_windows"] = conf

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved results.json", flush=True)


if __name__ == "__main__":
    main()
