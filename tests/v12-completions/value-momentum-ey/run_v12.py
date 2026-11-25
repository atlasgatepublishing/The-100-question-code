#!/usr/bin/env python3
"""
v12 COMPLETIONS — value-momentum-ey, CONSTRUCTED broad form.
Simulation only. See CONSTRUCTION-SPEC.md (frozen before this run).

Mechanics are the house/v10 engine's, widened to the broad seed:
  - Signal: E/P = trailing annual as-filed NetIncomeLoss(2)/ProfitLoss(1)
    (fiscal-year facts only, 300-400d) / (as-filed shares x price), shares
    chain dei(3) > CommonStockSharesOutstanding(2) > WeightedAvgBasic(1);
    facts filed strictly before formation, 548-day freshness gate;
    momentum 12-1 on adjclose bars; score = avg percentile(E/P, momentum);
    negative E/P ranks at the bottom, never excluded.
  - Portfolio: top QUINTILE of the scored pool, equal weight (CONSTRUCTED
    long-only top form); pool < 50 names -> cash that period.
  - Cadences: v10 uniform definitions; rebalance executes next trading
    day's open (adj-scaled open, house bar construction).
  - Costs: 0.10%/side + $0.01 per sell order. $100 start.
  - Protection: v9 plain -15% floor checked every close; first halt ->
    liquidate next open, 90 calendar days cash, restart at next regular
    cadence date under episode-2 -15% floor; second halt ends the run.
  - Vanished -> ZERO: a held name with no bar for >10 consecutive trading
    days (SPY calendar) is written to zero and removed.
  - Placebos: 20 seeds; twin samples the same pick count from the same
    scored pool at each formation.

Usage:
  run_v12.py grid                       # DECADE, all 7 cadences
  run_v12.py confirm <cadence> [...]    # LONG/CONT/VAL for given cadences
"""
import bisect
import json
import math
import os
import random
import sys
import time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CELLS = os.path.join(HERE, "cells")
CONF = os.path.join(HERE, "confirmation")
os.makedirs(CELLS, exist_ok=True)
os.makedirs(CONF, exist_ok=True)

START_CASH = 100.0
PLACEBO_SEEDS = list(range(1, 21))
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
ROADS = {
    "LONG": ("2010-01-04", "2026-11-20"),
    "DECADE": ("2016-11-21", "2026-11-20"),
    "CONT": ("2019-01-02", "2026-11-20"),
    "VAL": ("2023-01-03", "2026-11-20"),
}
STALE_DAYS = 10  # vanished -> zero threshold (trading days)

# ------------------------------------------------------------ data loading
def load_seed():
    d = json.load(open(os.path.join(DATA, "tradable_universe.json")))
    trad = {int(k): v for k, v in d["tradable"].items()}
    cik2tick = {cik: v["ticker"] for cik, v in trad.items()}
    tick2cik = {}
    for cik, t in cik2tick.items():
        tick2cik.setdefault(t, cik)
    return cik2tick, tick2cik


def concept_rows(bundle, tax, concept):
    resp = bundle.get(f"{tax}:{concept}")
    if not resp or "units" not in resp:
        return []
    units = resp["units"]
    key = "USD" if "USD" in units else ("shares" if "shares" in units
                                        else list(units)[0])
    rows = []
    for e in units[key]:
        if "filed" not in e or "val" not in e:
            continue
        rows.append(e)
    return rows


def income_rows(bundle):
    rows = []
    for concept, prio in (("NetIncomeLoss", 2), ("ProfitLoss", 1)):
        for e in concept_rows(bundle, "us-gaap", concept):
            if "start" not in e or "end" not in e:
                continue
            sy, sm, sd = int(e["start"][:4]), int(e["start"][5:7]), int(e["start"][8:10])
            ey_, em, ed = int(e["end"][:4]), int(e["end"][5:7]), int(e["end"][8:10])
            dur = date(ey_, em, ed).toordinal() - date(sy, sm, sd).toordinal()
            if 300 <= dur <= 400:
                rows.append((e["filed"], e["end"], float(e["val"]), prio))
    return rows


def shares_rows(bundle):
    rows = []
    for tax, concept, prio in (
            ("dei", "EntityCommonStockSharesOutstanding", 3),
            ("us-gaap", "CommonStockSharesOutstanding", 2),
            ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", 1)):
        for e in concept_rows(bundle, tax, concept):
            rows.append((e["filed"], e.get("end", ""), float(e["val"]), prio))
    return rows


class PitChain:
    """Same fast path as the v10 engine (proven identical there)."""

    def __init__(self, rows):
        self.rows = [r for _, r in sorted(
            enumerate(rows),
            key=lambda p: (p[1][0], p[1][3], p[1][1], -p[0]))]
        self.fileds = [r[0] for r in self.rows]

    def value(self, asof, max_age_days=548):
        i = bisect.bisect_left(self.fileds, asof) - 1
        if i < 0:
            return None
        filed, end, val, prio = self.rows[i]
        ay, am, ad = int(asof[:4]), int(asof[5:7]), int(asof[8:10])
        fy, fm, fd = int(filed[:4]), int(filed[5:7]), int(filed[8:10])
        if date(fy, fm, fd).toordinal() < date(ay, am, ad).toordinal() - max_age_days:
            return None
        return (filed, end, val)


def bars_adj(payload):
    """Bars as compact (date, open, close) tuples — same construction as
    the house engine (open scaled by adjclose/close; close = adjclose)."""
    res = payload["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append((d, (o * ratio if o else a), a))
    bars.sort(key=lambda b: b[0])
    return bars


class PriceBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.idx = {t: {b[0]: (b[1], b[2]) for b in bl}
                    for t, bl in bars_by_ticker.items()}
        self._dl = {t: [b[0] for b in bl] for t, bl in bars_by_ticker.items()}
        self._cl = {t: [b[2] for b in bl] for t, bl in bars_by_ticker.items()}
        self.calendar = self._dl.get("SPY", [])

    def bar(self, t, d):
        oc = self.idx.get(t, {}).get(d)
        if oc is None:
            return None
        return {"o": oc[0], "c": oc[1]}

    def close_on_or_before(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return None
        i = bisect.bisect_right(dl, d) - 1
        return self._cl[t][i] if i >= 0 else None

    def last_bar_idx(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return -1
        return bisect.bisect_right(dl, d) - 1

    def cal_idx(self, d):
        return bisect.bisect_right(self.calendar, d) - 1


# ---------------------------------------------------------------- scoring
def percentile_ranks(values):
    items = sorted(values.items(), key=lambda kv: kv[1])
    n = len(items)
    if n == 1:
        return {items[0][0]: 0.5}
    return {t: i / (n - 1) for i, (t, _) in enumerate(items)}


class Scorer:
    def __init__(self, pb, tickers, income_chains, shares_chains):
        self.pb = pb
        self.tickers = tickers
        self.inc = income_chains
        self.shr = shares_chains
        self.memo = {}

    def scores(self, d):
        if d in self.memo:
            return self.memo[d]
        pb = self.pb
        scores = {}
        for t in self.tickers:
            ni = self.inc[t].value(d)
            if ni is None:
                continue
            so = self.shr[t].value(d)
            if so is None or so[2] <= 0:
                continue
            dl = pb._dl.get(t)
            if not dl:
                continue
            i = bisect.bisect_right(dl, d) - 1
            if i < 252:
                continue
            px = pb._cl[t][i]
            if px <= 0:
                continue
            mcap = so[2] * px
            if mcap <= 0:
                continue
            ey = ni[2] / mcap
            mom = pb._cl[t][i - 21] / pb._cl[t][i - 252] - 1.0
            scores[t] = (ey, mom)
        self.memo[d] = scores
        return scores

    def picks(self, d, placebo_rng=None):
        scores = self.scores(d)
        if len(scores) < 50:
            return [], scores
        n_pick = max(1, len(scores) // 5)
        if placebo_rng is not None:
            return placebo_rng.sample(sorted(scores), n_pick), scores
        vr = percentile_ranks({t: v[0] for t, v in scores.items()})
        mr = percentile_ranks({t: v[1] for t, v in scores.items()})
        combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
        return sorted(combined, key=lambda t: -combined[t])[:n_pick], scores


# ---------------------------------------------------------------- cadence
def cadence_dates(days, cadence):
    if cadence == "daily":
        return list(days)
    out, seen = [], set()
    if cadence == "weekly":
        for d in days:
            iso = date.fromisoformat(d).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                out.append(d)
        return out
    if cadence == "biweekly":
        weeks = []
        for d in days:
            iso = date.fromisoformat(d).isocalendar()
            key = (iso[0], iso[1])
            if key not in seen:
                seen.add(key)
                weeks.append((key, d))
        return [d for i, (_, d) in enumerate(weeks) if i % 2 == 0]
    if cadence == "monthly":
        keyf = lambda d: (d[:4], d[5:7])  # noqa: E731
    elif cadence == "quarterly":
        keyf = lambda d: (d[:4], (int(d[5:7]) - 1) // 3)  # noqa: E731
    elif cadence == "semiannual":
        keyf = lambda d: (d[:4], (int(d[5:7]) - 1) // 6)  # noqa: E731
    elif cadence == "annual":
        keyf = lambda d: d[:4]  # noqa: E731
    else:
        raise ValueError(cadence)
    for d in days:
        key = keyf(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


# ----------------------------------------------------------------- engine
def run_one(pb, scorer, start, end, start_cash, floor, cadence, placebo_rng=None):
    cash = start_cash
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    pools = []
    curve = []
    zeroed = []
    days = [d for d in pb.calendar if start <= d <= end]
    if not days:
        return None
    sel_set = set(cadence_dates(days, cadence))
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def apply_zero_rule(d):
        gi = pb.cal_idx(d)
        for t in list(positions):
            li = pb.last_bar_idx(t, d)
            if li < 0:
                zeroed.append((d, t, "no-bars-ever"))
                del positions[t]
                continue
            last_d = pb._dl[t][li]
            lgi = pb.cal_idx(last_d)
            if gi - lgi > STALE_DAYS:
                zeroed.append((d, t, f"tape ended {last_d}"))
                del positions[t]

    def execute_rebalance(d, targets):
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        for t in list(positions):
            if t not in opens:
                continue
            cur_val = positions[t] * opens[t]
            tgt = targets.get(t, 0.0)
            if cur_val > tgt + 0.005:
                sell_val = cur_val - tgt
                sh = sell_val / opens[t]
                c = sell_val * 0.001 + 0.01
                cash += sell_val - c
                cost += c
                positions[t] -= sh
                trades.append((d, t, "SELL", sh, opens[t], sell_val, c))
                if positions[t] < 1e-9:
                    del positions[t]
        for t, tgt in targets.items():
            if t not in opens:
                continue
            cur_val = positions.get(t, 0.0) * opens[t]
            buy_val = tgt - cur_val
            if buy_val > 0.005:
                buy_val = min(buy_val, cash / 1.001)
                if buy_val <= 0.005:
                    continue
                sh = buy_val / opens[t]
                c = buy_val * 0.001
                cash -= buy_val + c
                cost += c
                positions[t] = positions.get(t, 0.0) + sh
                trades.append((d, t, "BUY", sh, opens[t], buy_val, c))
        total_costs += cost
        return cost

    for di, d in enumerate(days):
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        apply_zero_rule(d)
        if d in sel_set:
            picks, scores = scorer.picks(d, placebo_rng=placebo_rng)
            if picks:
                pools.append((d, len(scores), list(picks)))
                pv = portfolio_close(d)
                each = pv / len(picks)
                pending = {t: each for t in picks}
            else:
                pools.append((d, len(scores), []))
                pending = {}
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            nd = days[di + 1]
            apply_zero_rule(nd)
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
                else:
                    zeroed.append((nd, t, "no bar at halt liquidation"))
            positions = {}
            curve.append((nd, cash))
            return {"final": cash, "costs": total_costs, "trades": trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "pools": pools, "curve": curve, "zeroed": zeroed}
    last = days[-1]
    apply_zero_rule(last)
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    if curve and curve[-1][0] == last:
        curve[-1] = (last, cash)
    return {"final": cash, "costs": total_costs, "trades": trades,
            "halted": None, "end": last, "halt_info": None,
            "pools": pools, "curve": curve, "zeroed": zeroed}


def run_v9(pb, scorer, start, end, cadence, placebo_seed=None):
    rng = random.Random(placebo_seed) if placebo_seed is not None else None
    episodes = []
    ep1 = run_one(pb, scorer, start, end, START_CASH, 0.85 * START_CASH,
                  cadence, placebo_rng=rng)
    episodes.append(ep1)
    restart = None
    if ep1 is not None and ep1["halted"]:
        halt_d = date.fromisoformat(ep1["halted"])
        elig = (halt_d + timedelta(days=90)).isoformat()
        if elig <= end:
            ep2 = run_one(pb, scorer, elig, end, ep1["final"],
                          0.85 * ep1["final"], cadence, placebo_rng=rng)
            if ep2 is not None:
                episodes.append(ep2)
                first_sel = ep2["pools"][0][0] if ep2["pools"] else None
                restart = {"halt_date": ep1["halted"], "eligibility": elig,
                           "restart_balance": round(ep1["final"], 2),
                           "episode2_floor": round(0.85 * ep1["final"], 2),
                           "episode2_first_selection": first_sel}
    last = episodes[-1]
    curve = list(episodes[0]["curve"])
    if len(episodes) > 1:
        trading_days = [d for d in pb.calendar if start <= d <= end]
        gap = [d for d in trading_days
               if episodes[0]["end"] < d < episodes[1]["curve"][0][0]]
        curve += [(d, episodes[0]["final"]) for d in gap]
        curve += list(episodes[1]["curve"])
    halts = []
    for i, ep in enumerate(episodes):
        if ep["halted"]:
            halts.append({"episode": i + 1, "signal_date": ep["halted"],
                          "signal_close": ep["halt_info"]["signal_close"] if ep.get("halt_info") else None,
                          "floor_in_effect": ep["halt_info"]["floor_in_effect"] if ep.get("halt_info") else None,
                          "liquidation_date": ep["end"],
                          "proceeds": round(ep["final"], 2)})
    return {"final": last["final"],
            "costs": sum(ep["costs"] for ep in episodes),
            "orders": sum(len(ep["trades"]) for ep in episodes),
            "trades": [tr for ep in episodes for tr in ep["trades"]],
            "halts": halts, "restart": restart,
            "second_halt": bool(len(episodes) > 1 and episodes[1]["halted"]),
            "curve": curve,
            "zeroed": [z for ep in episodes for z in ep["zeroed"]],
            "pools": [p for ep in episodes for p in ep["pools"]]}


def curve_stats(curve):
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    return round(maxdd * 100, 2)


def spy_net(pb, start, end, start_cash=START_CASH):
    days = [d for d in pb.calendar if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost


# --------------------------------------------------------------------- main
def build_world():
    cik2tick, tick2cik = load_seed()
    income_chains, shares_chains = {}, {}
    tickers = []
    for cik, t in sorted(cik2tick.items(), key=lambda kv: kv[1]):
        p = os.path.join(DATA, f"concepts_{cik:010d}.json")
        if not os.path.exists(p):
            continue
        bundle = json.load(open(p))
        income_chains[t] = PitChain(income_rows(bundle))
        shares_chains[t] = PitChain(shares_rows(bundle))
        tickers.append(t)
    bars = {}
    missing_px = []
    for t in tickers + ["SPY"]:
        p = os.path.join(DATA, f"pxfull_{t}.json")
        if not os.path.exists(p):
            missing_px.append(t)
            continue
        try:
            bars[t] = bars_adj(json.load(open(p)))
        except Exception:
            missing_px.append(t)
    tickers = [t for t in tickers if t in bars]
    pb = PriceBook(bars)
    scorer = Scorer(pb, tickers, income_chains, shares_chains)
    print(f"world: {len(tickers)} tickers with prices+facts; "
          f"missing price payloads: {len(missing_px)} {missing_px[:20]}",
          flush=True)
    return pb, scorer, tickers, missing_px


def run_cell(pb, scorer, road, cadence, with_placebos=True):
    start, end = ROADS[road]
    ranked = run_v9(pb, scorer, start, end, cadence)
    placebo_finals = []
    if with_placebos:
        for seed in PLACEBO_SEEDS:
            twin = run_v9(pb, scorer, start, end, cadence, placebo_seed=seed)
            placebo_finals.append(round(twin["final"], 2))
    n_beat = sum(1 for v in placebo_finals if ranked["final"] > v)
    sfin = sorted(placebo_finals)
    med = None
    if sfin:
        med = sfin[len(sfin) // 2] if len(sfin) % 2 == 1 else \
            (sfin[len(sfin) // 2 - 1] + sfin[len(sfin) // 2]) / 2.0
    yrs = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    spy_final, _ = spy_net(pb, start, end)
    cell = {
        "road": road, "cadence": cadence,
        "window": {"start": start, "end": end},
        "final": round(ranked["final"], 2),
        "cagr_pct": round(((ranked["final"] / START_CASH) ** (1.0 / yrs) - 1.0) * 100, 2) if ranked["final"] > 0 else -100.0,
        "max_dd_pct": curve_stats(ranked["curve"]),
        "halts": ranked["halts"], "restart": ranked["restart"],
        "second_halt": ranked["second_halt"],
        "costs": round(ranked["costs"], 2), "orders": ranked["orders"],
        "spy_final": round(spy_final, 2),
        "placebo_beaten": n_beat if with_placebos else None,
        "placebo_median": round(med, 2) if med is not None else None,
        "placebo_finals": placebo_finals,
        "zeroed_events": [[d, t, why] for d, t, why in ranked["zeroed"]],
        "n_zeroed": len(ranked["zeroed"]),
        "pool_sizes_first_last": [ranked["pools"][0][1], ranked["pools"][-1][1]] if ranked["pools"] else None,
        "trades": [[d, t, side, round(sh, 6), round(px, 4), round(val, 2), round(c, 4)]
                   for (d, t, side, sh, px, val, c) in ranked["trades"]],
        "equity_curve": [[d, round(v, 4)] for d, v in ranked["curve"]],
    }
    return cell


def main():
    t0 = time.time()
    mode = sys.argv[1]
    pb, scorer, tickers, missing_px = build_world()
    if mode == "grid":
        summary = {}
        for cadence in CADENCES:
            cell = run_cell(pb, scorer, "DECADE", cadence)
            with open(os.path.join(CELLS, f"{cadence}.json"), "w") as f:
                json.dump(cell, f, indent=1)
            summary[cadence] = {k: cell[k] for k in
                                ("final", "cagr_pct", "max_dd_pct", "costs",
                                 "orders", "spy_final", "placebo_beaten",
                                 "placebo_median", "n_zeroed")}
            summary[cadence]["halts"] = len(cell["halts"])
            print(f"== DECADE {cadence}: final=${cell['final']:,.2f} "
                  f"spy=${cell['spy_final']:,.2f} cagr={cell['cagr_pct']}% "
                  f"maxdd={cell['max_dd_pct']}% costs=${cell['costs']:,.2f} "
                  f"orders={cell['orders']} halts={len(cell['halts'])} "
                  f"placebo {cell['placebo_beaten']}/20 "
                  f"(med ${cell['placebo_median']}) zeroed={cell['n_zeroed']}",
                  flush=True)
        json.dump(summary, open(os.path.join(HERE, "grid_summary.json"), "w"), indent=1)
    elif mode == "confirm":
        for cadence in sys.argv[2:]:
            for road in ("LONG", "CONT", "VAL"):
                cell = run_cell(pb, scorer, road, cadence)
                with open(os.path.join(CONF, f"{road.lower()}-{cadence}.json"), "w") as f:
                    json.dump(cell, f, indent=1)
                print(f"== {road} {cadence}: final=${cell['final']:,.2f} "
                      f"spy=${cell['spy_final']:,.2f} cagr={cell['cagr_pct']}% "
                      f"maxdd={cell['max_dd_pct']}% costs=${cell['costs']:,.2f} "
                      f"orders={cell['orders']} halts={len(cell['halts'])} "
                      f"placebo {cell['placebo_beaten']}/20 "
                      f"(med ${cell['placebo_median']}) zeroed={cell['n_zeroed']}",
                      flush=True)
    print(f"DONE {mode} in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
