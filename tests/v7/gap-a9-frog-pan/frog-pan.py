#!/usr/bin/env python3
"""
GAP TEST A-9 — FROG-IN-THE-PAN MOMENTUM (Da, Gurun & Warachka 2014) —
Terry's AI stock app, simulation only.

One clean shot, exactly per the frozen spec in
~/workspace/stock-app/research/v7-completeness/missing-families.md
(Table A, item A-9). Run once, no tuning.

Spec (verbatim substance):
  Monthly. Among pond names with positive 12-1 momentum, compute the
  information-discreteness score from daily bars over the same window:
      ID = sign(formation return) x (% down days - % up days)
  Hold the 5 lowest-ID names, equal weight. The trial's question, stated
  in advance by the spec: does path shape add anything over the promoted
  momentum basket (same pond, same dates)? Judge against the basket
  first, SPY second.

House chassis:
  $100 pot, honest top-30 pond as of Nov 2016 (identical list to the
  promoted momentum basket), costs 0.10%/side + $0.01 per sell order,
  plain -15% floor ($85, daily close, liquidate at next open, no
  re-entry), cash earns nothing. Windows: continuous 2019-01-01 ->
  2026-11-20 and validation 2023-01-01 -> 2026-11-20 (fresh pots).
  20-seed placebos (seeds 1..20) on the same dates and mechanics:
  each month, 5 RANDOM names from the same eligible set (positive
  12-1 momentum), identical engine and floor.

Mechanics shared with the promoted basket engine
(~/workspace/stock-app/backtests/v4/momentum-basket-honest.py):
  selection on the first trading day of each month, signals from the
  PRIOR trading day's close, rebalance at the selection day's OPEN to
  20%-of-equity targets; names that drop out are sold in full; fewer
  than 5 eligible -> hold what's eligible at 20% each, rest cash.
  The basket benchmark is re-run inside this script on IDENTICAL dates
  and the identical plain-floor chassis so the comparison is exact.

Data: the basket's own cache, read-only —
  ~/workspace/stock-app/backtests/v4/momentum-basket-honest-data/
  (Yahoo daily bars, split-adjusted opens/closes, 2015-01-01 ->
  2026-11-20; SPY calendar is the master calendar; closes forward-filled
  for valuation, exactly as in the basket engine.)

Benchmark basis (disclosed): the strategy and the basket run on the
basket cache's split-adjusted bars — the identical basis on which the
basket's published $439.45 / $208.27 were produced (this script's
identical-dates basket re-run reproduces the published validation
$208.27 to the cent, and its continuous figure matches the program's
recorded plain-floor basket number). The SPY buy-hold benchmark,
however, is the program's canonical figure, computed from the shared
dividend-adjusted (adjclose) SPY series in
~/workspace/stock-app/backtests/v4/data/px_SPY.json using the champion
engine's own spy_net formula — it reproduces the published
$313.62 / $187.77 to the cent. (On the basket cache's split-only bars
SPY nets $279.86 / $179.10 — the difference is SPY's dividends, which
the pond stocks' split-only bars likewise omit from every pot in this
test, basket and frog alike; the frog-vs-basket comparison, the spec's
primary judgment, is on one identical basis.)

FORCED READINGS (stated before results; forced by the spec's text or by
the house chassis, none is a tuning choice):
  1. Formation window = the 12-1 window itself: closes at signal-day
     indices [j-252 .. j-21]; the formation return is the 12-1 momentum,
     c[j-21]/c[j-252] - 1. Daily returns are the 231 close-to-close
     returns inside that span. % up / % down days use ALL 231 days as
     the denominator; zero-return days (incl. forward-filled non-trading
     days for a name) count in neither numerator, per DGW's "% of days"
     definition.
  2. Eligibility is the spec's own words: positive 12-1 momentum ONLY.
     The spec states no 200-day-average trend gate for A-9 (that gate
     belongs to the basket's rule), so none is applied to the frog pot
     or to its placebo eligible set. The basket benchmark keeps its own
     published gate.
  3. Since every eligible name has positive formation return, sign = +1
     throughout and ID = %down - %up; lowest ID = the most continuously
     rising path. Ties in ID break by higher 12-1 momentum, then ticker
     (determinism only).
  4. End of window: positions are marked at the final close (house
     convention in the recent v7 tests: no forced end-liquidation fee
     beyond the SPY-net convention, which is computed with the same
     cost schedule by spy_net()).
"""

import json
import math
import os
import random
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/momentum-basket-honest-data")

UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
BENCH = "SPY"
COST_RATE = 0.001                 # 0.10% per side
SELL_FEE = 0.01                   # per sell order
POT = 100.0
FLOOR = 85.0                      # plain -15% floor, no ladder

WINDOWS = {
    "continuous": ("2019-01-01", "2026-11-20"),
    "validation": ("2023-01-01", "2026-11-20"),
}
PLACEBO_SEEDS = list(range(1, 21))


# --------------------------------------------------------------------------
# Data (identical construction to the basket engine)
# --------------------------------------------------------------------------
def load(ticker):
    with open(os.path.join(CACHE, f"{ticker}.json")) as f:
        return json.load(f)


class Market:
    """SPY calendar is the master calendar; per-ticker bars keyed by date."""

    def __init__(self, tickers):
        self.bars = {}
        self.closes = {}
        spy = load(BENCH)
        self.cal = [r["d"] for r in spy]
        raw = {BENCH: spy}
        for t in tickers:
            raw[t] = load(t)
        for t in tickers + [BENCH]:
            self.bars[t] = {r["d"]: (r["o"], r["c"]) for r in raw[t]}
            arr, last = [], None
            for d in self.cal:
                if d in self.bars[t]:
                    last = self.bars[t][d][1]
                arr.append(last)          # forward-fill closes for valuation
            self.closes[t] = arr

    def open_px(self, t, i):
        d = self.cal[i]
        if d in self.bars[t]:
            return self.bars[t][d][0]
        return None

    def close_px(self, t, i):
        return self.closes[t][i]

    def sma(self, t, i, n):
        if i + 1 < n:
            return None
        seg = self.closes[t][i - n + 1: i + 1]
        if any(v is None for v in seg):
            return None
        return sum(seg) / n

    def momentum_12_1(self, t, i):
        """12-1 momentum at index i: c[i-21]/c[i-252]-1."""
        if i - 252 < 0:
            return None
        a, b = self.closes[t][i - 252], self.closes[t][i - 21]
        if a is None or b is None or a <= 0:
            return None
        return b / a - 1.0

    def info_discreteness(self, t, i):
        """DGW ID over the 12-1 formation window ending at index i.

        Formation return = 12-1 momentum. Daily returns are the
        close-to-close returns at indices [i-251 .. i-21] (231 returns
        spanning closes [i-252 .. i-21]).
        ID = sign(formation return) x (% down days - % up days).
        """
        mom = self.momentum_12_1(t, i)
        if mom is None:
            return None
        seg = self.closes[t][i - 252: i - 21 + 1]     # 232 closes
        if any(v is None or v <= 0 for v in seg):
            return None
        up = down = 0
        for k in range(1, len(seg)):
            r = seg[k] / seg[k - 1] - 1.0
            if r > 0:
                up += 1
            elif r < 0:
                down += 1
        total = len(seg) - 1                          # 231 days
        sign = 1.0 if mom > 0 else (-1.0 if mom < 0 else 0.0)
        return sign * (down / total - up / total)


# --------------------------------------------------------------------------
# Simulation (basket engine mechanics; plain floor; three modes)
#   mode 'frog'    : A-9 ranked — 5 lowest ID among positive-momentum names
#   mode 'basket'  : promoted basket — 200d gate, top-5 by 12-1 momentum
#   mode 'placebo' : 5 random names from the frog eligible set
# --------------------------------------------------------------------------
class Result:
    def __init__(self):
        self.final = None
        self.orders = 0
        self.costs = 0.0
        self.halt_date = None
        self.max_dd = 0.0
        self.equity_curve = []
        self.sel_total = 0
        self.sel_wins = 0
        self.months = 0
        self.month_wins = 0
        self.n_months = 0            # selection months executed
        self.elig_counts = []        # eligible-set size per selection
        self.pick_overlap = 0        # frog only: picks also in basket top-5


def simulate(mkt, start_d, end_d, mode, seed=42, basket_picks_by_month=None):
    rng = random.Random(seed)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    cash = float(POT)
    pos = {}
    res = Result()
    pending_liquidation = False
    mark_px = {}
    cur_month = None
    my_picks_by_month = {}

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
                if t in mark_px:
                    res.sel_total += 1
                    if px > mark_px[t]:
                        res.sel_wins += 1
                del pos[t]
            mark_px.clear()
            res.halt_date = d
            res.final = cash
            res.equity_curve.append((d, cash))
            break

        # --- monthly selection / rebalance at the open -------------------
        if month_key != cur_month and i > 0:
            cur_month = month_key
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is not None and t in mark_px:
                    res.sel_total += 1
                    if px > mark_px[t]:
                        res.sel_wins += 1
            j = i - 1                       # signal day = prior trading day

            if mode == "basket":
                elig = []
                for t in UNIVERSE:
                    sma200 = mkt.sma(t, j, 200)
                    c = mkt.close_px(t, j)
                    if sma200 is None or c is None or c <= sma200:
                        continue
                    mom = mkt.momentum_12_1(t, j)
                    if mom is None:
                        continue
                    elig.append((t, mom))
                elig.sort(key=lambda x: -x[1])
                picks = [t for t, _ in elig[:5]]
            else:
                # frog eligible set: positive 12-1 momentum (spec verbatim)
                elig = []
                for t in UNIVERSE:
                    mom = mkt.momentum_12_1(t, j)
                    if mom is None or mom <= 0:
                        continue
                    idv = mkt.info_discreteness(t, j)
                    if idv is None:
                        continue
                    elig.append((t, mom, idv))
                res.elig_counts.append(len(elig))
                if mode == "frog":
                    elig.sort(key=lambda x: (x[2], -x[1], x[0]))
                    picks = [t for t, _, _ in elig[:5]]
                else:  # placebo: random 5 of the same eligible set
                    names = sorted(t for t, _, _ in elig)
                    picks = (rng.sample(names, min(5, len(names)))
                             if names else [])
            res.n_months += 1
            my_picks_by_month[month_key] = list(picks)
            if mode == "frog" and basket_picks_by_month is not None:
                bp = set(basket_picks_by_month.get(month_key, []))
                res.pick_overlap += len(set(picks) & bp)

            eq_open = equity_at(i, use_open=True)
            target_val = {t: 0.20 * eq_open for t in picks}

            # sells first: names not picked, then trims
            for t in list(pos):
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos[t] * px
                want = target_val.get(t, 0.0)
                if cur_val > want + 0.01:
                    sell_val = cur_val - want
                    sh = sell_val / px
                    fee = sell_val * COST_RATE + SELL_FEE
                    cash += sell_val - fee
                    res.costs += fee
                    res.orders += 1
                    pos[t] -= sh
                    if want <= 0.0 or pos[t] * px < 0.01:
                        del pos[t]
            # buys
            for t in picks:
                px = mkt.open_px(t, i)
                if px is None:
                    continue
                cur_val = pos.get(t, 0.0) * px
                deficit = target_val[t] - cur_val
                if deficit <= 0.01:
                    continue
                buy_val = min(deficit, cash / (1.0 + COST_RATE))
                if buy_val <= 0.01:
                    continue
                fee = buy_val * COST_RATE
                cash -= buy_val + fee
                res.costs += fee
                res.orders += 1
                pos[t] = pos.get(t, 0.0) + buy_val / px
            mark_px = {}
            for t in pos:
                px = mkt.open_px(t, i)
                if px is not None:
                    mark_px[t] = px

        # --- close: equity, floor ---------------------------------------
        eq_close = equity_at(i, use_open=False)
        res.equity_curve.append((d, eq_close))
        if eq_close <= FLOOR:
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
    for d, eq in res.equity_curve:
        peak = max(peak, eq)
        if peak > 0:
            res.max_dd = min(res.max_dd, eq / peak - 1.0)
    month_end = {}
    for d, eq in res.equity_curve:
        month_end[d[:7]] = eq
    keys = sorted(month_end)
    for a, b in zip(keys, keys[1:]):
        r = month_end[b] / month_end[a] - 1.0
        res.months += 1
        if r > 0:
            res.month_wins += 1
    return res, my_picks_by_month


def spy_net(mkt, start_d, end_d):
    """Basket-cache (split-adjusted only) SPY net — kept for disclosure;
    NOT the headline benchmark (see spy_net_canonical)."""
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= start_d)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= end_d)
    buy_px = mkt.open_px(BENCH, i0)
    sell_px = mkt.close_px(BENCH, i1)
    sh = (POT * (1 - COST_RATE)) / buy_px
    return sh * sell_px * (1 - COST_RATE) - SELL_FEE


SHARED = os.path.expanduser("~/workspace/stock-app/backtests/v4/data")


def load_spy_canonical():
    """Dividend-adjusted SPY bars from the shared v4 cache, built exactly
    as the champion engine builds them (open scaled by adjclose/close,
    close = adjclose). Returns {date: (open_adj, close_adj)} + calendar."""
    with open(os.path.join(SHARED, "px_SPY.json"), "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = {}
    for i, t in enumerate(ts):
        d = datetime.utcfromtimestamp(t).strftime("%Y-%m-%d")
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars[d] = ((o * ratio) if o else a, a)
    return bars


SPY_CANON = load_spy_canonical()


def spy_net_canonical(start_d, end_d):
    """The program's canonical SPY buy-hold net (champion engine formula):
    buy at the first window day's adjusted open, sell at the last day's
    adjusted close, same cost schedule."""
    days = sorted(d for d in SPY_CANON if start_d <= d <= end_d)
    first, last = days[0], days[-1]
    o = SPY_CANON[first][0]
    sh = (POT / 1.001) / o
    val = sh * SPY_CANON[last][1]
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
        "halt": r.halt_date,
        "sel_win_pct": (round(100 * r.sel_wins / r.sel_total, 1)
                        if r.sel_total else None),
        "sel_n": r.sel_total,
        "month_win_pct": (round(100 * r.month_wins / r.months, 1)
                          if r.months else None),
        "bench_final": round(bench, 2),
    }


def main():
    mkt = Market(UNIVERSE)
    out = {"test": "gap-a9-frog-in-the-pan",
           "source": "Da, Gurun & Warachka (2014), RFS 27(7)",
           "universe": UNIVERSE, "placebo_seeds": PLACEBO_SEEDS,
           "floor": FLOOR, "pot": POT}

    # ---- integrity gates -------------------------------------------------
    gates, gates_cache = {}, {}
    for wname, (sd, ed) in WINDOWS.items():
        gates[wname] = round(spy_net_canonical(sd, ed), 2)
        gates_cache[wname] = round(spy_net(mkt, sd, ed), 2)
    out["integrity_spy_net_canonical"] = gates
    out["integrity_spy_net_basket_cache"] = gates_cache
    print(f"INTEGRITY SPY net (canonical adjclose): "
          f"continuous={gates['continuous']} (published 313.62)  "
          f"validation={gates['validation']} (published 187.77); "
          f"basket-cache basis: {gates_cache}", flush=True)

    ranked_final = {}
    basket_picks = {}
    for wname, (sd, ed) in WINDOWS.items():
        yrs = years_between(sd, ed)
        bench = spy_net_canonical(sd, ed)

        # basket benchmark on identical dates / chassis first (for picks)
        rb, bpicks = simulate(mkt, sd, ed, "basket")
        basket_picks[wname] = bpicks
        out[f"{wname}|basket_same_dates"] = _summ(rb, yrs, bench)
        print(f"{wname}|basket: final={rb.final:.2f} "
              f"ret={(rb.final/POT-1)*100:+.2f}% orders={rb.orders} "
              f"costs=${rb.costs:.2f} maxDD={rb.max_dd*100:.2f}% "
              f"halt={rb.halt_date}", flush=True)

        r, _ = simulate(mkt, sd, ed, "frog",
                        basket_picks_by_month=bpicks)
        ranked_final[wname] = r.final
        s = _summ(r, yrs, bench)
        s["n_selection_months"] = r.n_months
        s["elig_min"] = min(r.elig_counts) if r.elig_counts else None
        s["elig_median"] = (_pct(sorted(r.elig_counts), 0.5)
                            if r.elig_counts else None)
        s["elig_max"] = max(r.elig_counts) if r.elig_counts else None
        s["pick_overlap_with_basket"] = r.pick_overlap
        s["pick_slots"] = 5 * r.n_months
        out[f"{wname}|frog"] = s
        print(f"{wname}|frog: final={r.final:.2f} "
              f"ret={(r.final/POT-1)*100:+.2f}% orders={r.orders} "
              f"costs=${r.costs:.2f} maxDD={r.max_dd*100:.2f}% "
              f"halt={r.halt_date} overlap={r.pick_overlap}/"
              f"{5*r.n_months} elig_med={s['elig_median']}", flush=True)

        # per-year for the continuous window
        if wname == "continuous":
            out["per_year_frog"] = per_year(r)
            out["per_year_basket_same_dates"] = per_year(rb)

    # ---- placebos ---------------------------------------------------------
    for wname, (sd, ed) in WINDOWS.items():
        yrs = years_between(sd, ed)
        bench = spy_net_canonical(sd, ed)
        finals, rows = [], []
        for seed in PLACEBO_SEEDS:
            r, _ = simulate(mkt, sd, ed, "placebo", seed=seed)
            finals.append(r.final)
            rows.append({
                "seed": seed, "final": round(r.final, 2),
                "ret_pct": round((r.final / POT - 1) * 100, 2),
                "max_dd_pct": round(r.max_dd * 100, 2),
                "halt": r.halt_date, "orders": r.orders,
                "costs": round(r.costs, 2)})
        sfin = sorted(finals)
        rk = ranked_final[wname]
        n_beat = sum(1 for v in finals if rk > v)
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

    with open(os.path.join(HERE, "frog-pan-results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("saved frog-pan-results.json")


if __name__ == "__main__":
    main()
