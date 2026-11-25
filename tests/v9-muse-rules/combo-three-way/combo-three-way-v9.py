#!/usr/bin/env python3
"""
THE THREE-WAY COMBINATION UNDER CLAUDE'S RULES (v9) — Terry's AI stock
app. Simulation only.

TERRY'S REQUEST (2026-11-21): put the three biggest strategies
together in ONE pot — the champion (value+momentum), Lazy Prices, and
N-F3 "Paying in Stock" — and run it under BOTH rule sets. This script
is the CLAUDE-RULES twin; the his-rules twin (plain floor, halt = dead)
runs in parallel in backtests/v8/combo-three-way/ with the identical
construction. The ONLY difference between the twins is the protection
module (run_combo_v9 below).

CONSTRUCTION (identical to the twin; extends the program's combo
precedent — combo-vm-nf3's position-level sleeve machinery — to three
sleeves):
  - ONE $100 pot, three equal sleeves. Each sleeve is its own sub-pot
    (own cash, own positions) running its parent EXACTLY as
    promoted/frozen:
      VM  — value+momentum (backtests/v4/value-momentum-plainfloor.py:
            book-to-market + 12-1 momentum percentile-average rank,
            quarterly top-5, equal weight).
      LZ  — Lazy Prices (backtests/v7/gap-a5-lazy-prices/lazy-prices.py:
            whole-document 10-K cosine similarity vs prior year,
            quarterly top-5 least-changed, equal weight).
      NF3 — N-F3 "Paying in Stock" (research/v8-novel/novel-filings.md;
            engine backtests/v8/novel-f3-paying-in-stock/: TTM
            ShareBasedCompensation / TTM revenue, ACCEL vs same quarter
            a year earlier, rank ascending, quarterly top-5, equal
            weight).
  - Shared quarterly schedule: first trading day of Jan/Apr/Jul/Oct,
    selection at the close, execution at the next open — champion
    mechanics in every sleeve. All three parents trade on the
    champion's PriceBook (verified: the Lazy loader's bars are
    byte-identical to the champion's on all 31 tickers, same caches).
  - Sleeve weights reset to equal thirds at EACH quarterly selection
    date: each sleeve's rebalance budget is one third of the combined
    pot's selection-day close. At the next open each sleeve first sells
    toward its targets (champion mechanics); cash the overweight
    sleeves raised above their budgets then moves to the underweight
    sleeves (same-pot transfers — the market trades are the sleeves'
    own rebalance sells/buys, each charged at the program schedule);
    then each sleeve buys toward its targets.
  - Costs: 0.10% of trade value per side + $0.01 per sell order,
    charged inside each sleeve exactly as in the parent engines.

PROTECTION — CLAUDE-RULES PROTECTION SPEC v9 (frozen; the ONLY
difference from the twin):
  - Episode 1: floor = -15% from the $100 start ($85.00) on the
    COMBINED pot. A close at/below the floor liquidates everything at
    the next open (champion semantics), exactly as under Terry's rule.
  - On FIRST halt: the pot sits in cash 90 calendar days after the
    liquidation date, then RESTARTS the whole combined pot with the
    remaining cash at the next quarterly selection date, under an
    episode-2 floor of -15% from the RESTART balance. Sleeves restart
    at equal thirds of the remaining cash.
  - On SECOND halt: the run ends permanently.
  - If halt + 90 days runs past the window/fold end (no quarterly
    selection date remains in-window), the run ends in cash.
  - The same spec applies inside the yearly folds.

WINDOWS: continuous 2019-01-02 -> 2026-11-20 and validation
2023-01-03 -> 2026-11-20, $100 pots.
PLACEBOS: 20 seeds (1..20); at each selection date each sleeve draws
5 random names from ITS OWN eligible pool (draw order VM, LZ, NF3),
identical dates/mechanics/resets, and the SAME v9 protection — one
random.Random(seed) per run, carried across a restart (no reseed),
mirroring the v9 single-strategy precedent.
FOLDS vs SPY: fresh $100 combo pots for each calendar year 2020-2026
under v9; the his-rules combo fold finals are computed alongside as a
reference column. SPY buy-hold net over the identical spans.

PRE-REGISTERED ADOPTION BAR (the same bar as the twin, stated before
the run): the combination must beat ALL THREE parents on BOTH windows
— V+M $544.47 / $288.05, Lazy Prices $504.34 / $324.12, N-F3
$505.43 / $289.53. Anything less is dilution, reported plainly. Because
one parent is an invented-in-2026 rule, even a full pass would be
CANDIDATE-grade only: only the forward paper trial can adopt it.
Program prior, stated in advance: every combination tested so far
diluted its better parent (winners' blend, grand combination,
V+M+trend, V+M x Lazy, V+M x N-F3).

INTEGRITY (run first, abort on failure): all three parent engines are
imported verbatim and re-run standalone at $100 under the plain floor
before any combo number is taken; their finals must reproduce the
published his-rules figures — V+M $544.47 / $288.05, Lazy Prices
$504.34 / $324.12, N-F3 $505.43 / $289.53, SPY net $313.62 / $187.77.
Signal scores are memoized per selection date (the score at a date
cannot depend on which run asks for it).

Run once, no tuning. No parameter was invented: sleeve construction,
reset cadence and cost schedule come from the combo precedent; the
protection module is the frozen v9 spec exactly as implemented in the
v9 single-strategy re-runs (see v9-muse-rules/value-momentum/).
"""
import importlib.util
import json
import math
import os
import random
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
V7LZ = os.path.expanduser("~/workspace/stock-app/backtests/v7/gap-a5-lazy-prices")
V8 = os.path.expanduser("~/workspace/stock-app/backtests/v8")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


champ = _load("champ", os.path.join(V4, "value-momentum-plainfloor.py"))
lz = _load("lz", os.path.join(V7LZ, "lazy-prices.py"))
nf3 = _load("nf3", os.path.join(
    V8, "novel-f3-paying-in-stock", "novel-f3-paying-in-stock.py"))

UNIVERSE = champ.UNIVERSE
PLACEBO_SEEDS = list(range(1, 21))
POT = 100.0
PUBLISHED = {
    "VM": {"FULL": 544.47, "VALIDATION": 288.05},
    "LZ": {"FULL": 504.34, "VALIDATION": 324.12},
    "NF3": {"FULL": 505.43, "VALIDATION": 289.53},
    "SPY": {"FULL": 313.62, "VALIDATION": 187.77},
}
WINDOWS = [("FULL", "2019-01-02", "2026-11-20"),
           ("VALIDATION", "2023-01-03", "2026-11-20")]


# ------------------------------------------------------------- scoring
class Scorer:
    """Memoized per-date scores for all three sleeves."""

    def __init__(self, pb, equity_rows, shares_rows, facts_by_ticker,
                 signals):
        self.pb = pb
        self.equity_rows = equity_rows
        self.shares_rows = shares_rows
        self.facts = facts_by_ticker
        self.signals = signals
        self.pos_idx = {t: {b["d"]: i for i, b in enumerate(pb.bars[t])}
                        for t in pb.bars}
        self._vm = {}
        self._lz = {}
        self._nf3 = {}
        self.nf3_stats = {"direct": 0, "derived": 0}

    def vm(self, d):
        """(pool_dict ticker->(bm, mom), ranked picks) — champion block
        copied verbatim from value-momentum-plainfloor.run_pot (via
        combo-vm-nf3's Scorer)."""
        if d in self._vm:
            return self._vm[d]
        pb = self.pb
        scores = {}
        for t in UNIVERSE:
            be = champ.pit_value(self.equity_rows.get(t, []), d)
            so = champ.pit_value(self.shares_rows.get(t, []), d)
            px = pb.close_on_or_before(t, d)
            if be is None or so is None or px is None or so[2] <= 0 \
                    or be[2] is None:
                continue
            mcap = so[2] * px
            if mcap <= 0:
                continue
            bm = be[2] / mcap
            bl = pb.bars.get(t, [])
            didx = self.pos_idx.get(t, {}).get(d)
            if didx is None or didx < 253:
                continue
            mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
            scores[t] = (bm, mom)
        picks = []
        if len(scores) >= 5:
            vr = champ.percentile_ranks({t: v[0] for t, v in scores.items()})
            mr = champ.percentile_ranks({t: v[1] for t, v in scores.items()})
            combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
            picks = sorted(combined, key=lambda t: -combined[t])[:5]
        out = (scores, picks)
        self._vm[d] = out
        return out

    def lz(self, d):
        """(pool_dict ticker->similarity, ranked picks) — Lazy Prices
        scoring copied verbatim from lazy-prices.run_pot: most recent
        similarity with acceptance date strictly before d; top-5 by
        similarity descending."""
        if d in self._lz:
            return self._lz[d]
        scores = {}
        for t in UNIVERSE:
            sig = lz.latest_signal(self.signals.get(t, []), d)
            if sig is not None:
                scores[t] = sig[1]
        picks = []
        if len(scores) >= 5:
            picks = sorted(scores, key=lambda t: -scores[t])[:5]
        out = (scores, picks)
        self._lz[d] = out
        return out

    def nf3(self, d):
        """(pool_dict ticker->ACCEL, ranked picks) — N-F3 signal via the
        frozen module's own signal_at (via combo-vm-nf3's Scorer)."""
        if d in self._nf3:
            return self._nf3[d]
        scores = {}
        for t in UNIVERSE:
            a = nf3.signal_at(self.facts[t], d, self.nf3_stats)
            if a is not None:
                scores[t] = a
        picks = []
        if len(scores) >= 5:
            picks = sorted(scores, key=lambda t: (scores[t], t))[:5]
        out = (scores, picks)
        self._nf3[d] = out
        return out


# ------------------------------------------------------------- sleeves
class Sleeve:
    def __init__(self, name, cash):
        self.name = name
        self.cash = cash
        self.positions = {}
        self.trades = []
        self.costs = 0.0
        self.pending = None      # (targets dict, budget)
        self.curve = []

    def close_value(self, pb, d):
        v = self.cash
        for t, sh in self.positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def open_value(self, pb, d):
        v = self.cash
        for t, sh in self.positions.items():
            b = pb.bar(t, d)
            if b:
                v += sh * b["o"]
        return v


def sleeve_sells(pb, s, d, targets):
    """Champion sell phase: trim/sell positions toward target values at
    the open of day d. Copied verbatim from combo-vm-nf3."""
    opens = {}
    for t in set(list(s.positions) + list(targets)):
        b = pb.bar(t, d)
        if b:
            opens[t] = b["o"]
    for t in list(s.positions):
        if t not in opens:
            continue
        cur_val = s.positions[t] * opens[t]
        tgt = targets.get(t, 0.0)
        if cur_val > tgt + 0.005:
            sell_val = cur_val - tgt
            sh = sell_val / opens[t]
            c = sell_val * 0.001 + 0.01
            s.cash += sell_val - c
            s.costs += c
            s.positions[t] -= sh
            s.trades.append((d, s.name, "SELL", sh, opens[t], sell_val, c))
            if s.positions[t] < 1e-9:
                del s.positions[t]
    return opens


def sleeve_buys(pb, s, d, targets, opens):
    """Champion buy phase: buy toward target values, capped by cash.
    Copied verbatim from combo-vm-nf3."""
    for t, tgt in targets.items():
        if t not in opens:
            continue
        cur_val = s.positions.get(t, 0.0) * opens[t]
        buy_val = tgt - cur_val
        if buy_val > 0.005:
            buy_val = min(buy_val, s.cash / 1.001)
            if buy_val <= 0.005:
                continue
            sh = buy_val / opens[t]
            c = buy_val * 0.001
            s.cash -= buy_val + c
            s.costs += c
            s.positions[t] = s.positions.get(t, 0.0) + sh
            s.trades.append((d, s.name, "BUY", sh, opens[t], buy_val, c))


# ------------------------------------------------------------- combo
def run_combo(pb, scorer, start, end, start_cash=100.0, floor0=85.0,
              placebo_rng=None, label="", quiet=True):
    """One combined pot under a SINGLE plain floor (the his-rules
    mechanics; run_combo_v9 wraps this with the v9 restart rule).
    Three sleeves, equal-thirds budgets, quarterly resets via same-pot
    cash transfers after the sell phase — combo-vm-nf3's construction
    generalized from two sleeves to three."""
    sleeves = [Sleeve("VM", start_cash / 3.0),
               Sleeve("LZ", start_cash / 3.0),
               Sleeve("NF3", start_cash / 3.0)]
    by_name = {s.name: s for s in sleeves}
    sel_dates = champ.quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    curve = []
    pools = []
    transfers = []
    halted = None
    halt_info = None

    def combined_close(d):
        return sum(s.close_value(pb, d) for s in sleeves)

    def liquidate(d, tag):
        # Champion semantics: SELL-HALT sells at the next open, only
        # names with a bar that day; SELL-END sells every position at
        # the final close. Positions are cleared either way.
        for s in sleeves:
            for t in list(s.positions):
                if tag == "SELL-HALT":
                    b = pb.bar(t, d)
                    px = b["o"] if b else None
                else:
                    px = pb.close_on_or_before(t, d)
                if px:
                    val = s.positions[t] * px
                    c = val * 0.001 + 0.01
                    s.cash += val - c
                    s.costs += c
                    s.trades.append((d, s.name, tag, s.positions[t],
                                     px, val, c))
            s.positions = {}

    for di, d in enumerate(days):
        # --- execute pending rebalances at today's open
        if any(s.pending is not None for s in sleeves):
            opens_by_sleeve = {}
            budgets = {}
            for s in sleeves:
                if s.pending is not None:
                    targets, budget = s.pending
                    opens_by_sleeve[s.name] = sleeve_sells(pb, s, d, targets)
                    budgets[s.name] = budget
            # --- equal-thirds reset: move the overweight sleeves'
            # surplus cash (raised by their sells, above their budgets
            # at today's open prices) to the underweight sleeves,
            # pro-rata to surpluses given and deficits owed.
            vals = {s.name: s.open_value(pb, d) for s in sleeves}
            excess = {n: vals[n] - budgets.get(n, vals[n]) for n in vals}
            give_cap = {}
            need = {}
            for s in sleeves:
                n = s.name
                give_cap[n] = min(excess[n], s.cash) if excess[n] > 0.005 else 0.0
                need[n] = -excess[n] if excess[n] < -0.005 else 0.0
            total_give = sum(give_cap.values())
            total_need = sum(need.values())
            moved = min(total_give, total_need)
            if moved > 0.005 and total_give > 0 and total_need > 0:
                gives = {n: moved * give_cap[n] / total_give
                         for n in give_cap if give_cap[n] > 0}
                recvs = {n: moved * need[n] / total_need
                         for n in need if need[n] > 0}
                for n, amt in gives.items():
                    by_name[n].cash -= amt
                for n, amt in recvs.items():
                    by_name[n].cash += amt
                transfers.append({"date": d,
                                  "from": {n: round(a, 2)
                                           for n, a in gives.items()},
                                  "to": {n: round(a, 2)
                                         for n, a in recvs.items()},
                                  "moved": round(moved, 2)})
            for s in sleeves:
                if s.pending is not None:
                    targets, _ = s.pending
                    sleeve_buys(pb, s, d, targets,
                                opens_by_sleeve[s.name])
                    s.pending = None
        # --- selection day: score all three sleeves, set third budgets
        if d in sel_set:
            vm_pool, vm_picks = scorer.vm(d)
            lz_pool, lz_picks = scorer.lz(d)
            f3_pool, f3_picks = scorer.nf3(d)
            if placebo_rng is not None:
                if len(vm_pool) >= 5:
                    vm_picks = placebo_rng.sample(sorted(vm_pool), 5)
                if len(lz_pool) >= 5:
                    lz_picks = placebo_rng.sample(sorted(lz_pool), 5)
                if len(f3_pool) >= 5:
                    f3_picks = placebo_rng.sample(sorted(f3_pool), 5)
            combined = combined_close(d)
            budget = combined / 3.0
            for s, pool, picks in (("VM", vm_pool, vm_picks),
                                   ("LZ", lz_pool, lz_picks),
                                   ("NF3", f3_pool, f3_picks)):
                if len(pool) >= 5:
                    by_name[s].pending = ({t: budget / 5.0 for t in picks},
                                          budget)
            pools.append((d, len(vm_pool), list(vm_picks),
                          len(lz_pool), list(lz_picks),
                          len(f3_pool), list(f3_picks),
                          round(combined, 2)))
            if not quiet:
                print(f"  [{label}] {d} VM pool={len(vm_pool)} "
                      f"picks={vm_picks} | LZ pool={len(lz_pool)} "
                      f"picks={lz_picks} | NF3 pool={len(f3_pool)} "
                      f"picks={f3_picks} | pot=${combined:,.2f}",
                      flush=True)
        # --- end of day: combined curve + the ONE floor
        v = combined_close(d)
        curve.append((d, v))
        for s in sleeves:
            s.curve.append((d, s.close_value(pb, d)))
        if v <= floor0 and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor0}
            nd = days[di + 1]
            liquidate(nd, "SELL-HALT")
            final = sum(s.cash for s in sleeves)
            return {"label": label, "final": final,
                    "costs": sum(s.costs for s in sleeves),
                    "trades": [tr for s in sleeves for tr in s.trades],
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "pools": pools, "curve": curve, "transfers": transfers,
                    "sleeve_finals": {s.name: s.cash for s in sleeves},
                    "sleeve_curves": {s.name: s.curve for s in sleeves}}
    last = days[-1]
    liquidate(last, "SELL-END")
    final = sum(s.cash for s in sleeves)
    return {"label": label, "final": final,
            "costs": sum(s.costs for s in sleeves),
            "trades": [tr for s in sleeves for tr in s.trades],
            "halted": None, "end": last, "halt_info": None,
            "pools": pools, "curve": curve, "transfers": transfers,
            "sleeve_finals": {s.name: s.cash for s in sleeves},
            "sleeve_curves": {s.name: s.curve for s in sleeves}}


# ============================================================ V9 MODULE
# The ONLY difference from the twin: run_combo_v9 wraps run_combo
# (unchanged above) with the CLAUDE-RULES PROTECTION SPEC v9, exactly
# as run_pot_v9 wraps run_pot in the v9 single-strategy re-runs.
def run_combo_v9(pb, scorer, start, end, start_cash=100.0,
                 placebo_rng=None, label="", quiet=True):
    """One window under CLAUDE-RULES PROTECTION SPEC v9.
    Episode 1: run_combo with floor = 85% of start_cash.
    On first halt: cash sits 90 calendar days after the liquidation
    date; episode 2 starts at the next quarterly selection date on or
    after liquidation+90d, with floor = 85% of the restart cash.
    On second halt (or no in-window selection date left): run ends."""
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_combo(pb, scorer, start, end, start_cash, floor1,
                   placebo_rng=placebo_rng, label=label + " EP1",
                   quiet=quiet)
    out = {"final": r1["final"], "costs": r1["costs"],
           "trades": r1["trades"], "curve": list(r1["curve"]),
           "halted": r1["halted"], "halt_info": r1["halt_info"],
           "restarts": [], "second_halt": None, "episodes": 1,
           "transfers": r1["transfers"], "pools": r1["pools"],
           "sleeve_finals_ep1": r1["sleeve_finals"],
           "sleeve_finals": r1["sleeve_finals"]}
    if r1["halted"] is None:
        return out
    # first halt: r1["end"] is the liquidation (next-open) date
    liq_date = r1["end"]
    cash = r1["final"]
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _date(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in champ.quarter_selection_dates(pb, start, end):
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _date(cy, cm, cd).toordinal() >= day90:
            restart = cand
            break
    # cash-flat curve segment between liquidation and restart/end
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq_date < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        out["curve"].append((end, cash))
        return out
    floor2 = round(0.85 * cash, 2)
    out["restarts"].append({"halt_signal_date": r1["halted"],
                            "liquidation_date": liq_date,
                            "halt_signal_close": r1["halt_info"]["signal_close"],
                            "restart_date": restart,
                            "restart_balance": round(cash, 2),
                            "episode2_floor": floor2})
    r2 = run_combo(pb, scorer, restart, end, cash, floor2,
                   placebo_rng=placebo_rng, label=label + " EP2",
                   quiet=quiet)
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["trades"] += r2["trades"]
    out["curve"] += list(r2["curve"])
    out["transfers"] += r2["transfers"]
    out["pools"] += r2["pools"]
    out["sleeve_finals"] = r2["sleeve_finals"]
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out


# ------------------------------------------------------------- helpers
def diagnostics(curve, floor0):
    """Copied from combo-vm-nf3 (reporting only)."""
    worst_d, worst_v = min(curve, key=lambda kv: kv[1])
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = (d, v)
    covid = [(d, v) for d, v in curve if "2020-02-01" <= d <= "2020-04-30"]
    covid_worst = min(covid, key=lambda kv: kv[1]) if covid else None
    return {"worst_close": round(worst_v, 2), "worst_close_date": worst_d,
            "floor": floor0,
            "worst_close_above_floor": round(worst_v - floor0, 2),
            "max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "covid_worst_close": round(covid_worst[1], 2) if covid_worst else None,
            "covid_worst_date": covid_worst[0] if covid_worst else None,
            "year_end_closes": {y: {"date": dd, "close": round(vv, 2)}
                                for y, (dd, vv) in sorted(year_end.items())}}


def monthly_returns(curve):
    month_last = {}
    for d, v in curve:
        month_last[d[:7]] = v
    months = sorted(month_last)
    out = {}
    for a, b in zip(months, months[1:]):
        out[b] = month_last[b] / month_last[a] - 1.0
    return out


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    return cov / math.sqrt(vx * vy)


def pct(sorted_vals, q):
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


def worst_from_start(r, start_cash):
    """Lowest equity point (daily closes + final cash) vs the start —
    the v9 precedent's worst-loss measure."""
    vals = [v for _, v in r["curve"]] + [r["final"]]
    return min(vals) if vals else start_cash


# ----------------------------------------------------------------- main
def main():
    import time
    ciks = champ.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}  # champion engine's parent-CIK fix
    facts_by_ticker = {}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = champ.get_companyfacts(cik)
        facts_by_ticker[t] = facts
        equity_rows[t] = (
            champ.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            champ.pit_series(facts, "us-gaap",
                             "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                             prio=1))
        shares_rows[t] = (
            champ.pit_series(facts, "dei",
                             "EntityCommonStockSharesOutstanding", prio=3) +
            champ.pit_series(facts, "us-gaap",
                             "CommonStockSharesOutstanding", prio=2) +
            champ.pit_series(facts, "us-gaap",
                             "WeightedAverageNumberOfSharesOutstandingBasic",
                             prio=1))
        print(f"{t}: facts loaded (CIK {cik})", flush=True)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = champ.get_prices(t)
        print(f"{t}: {len(bars[t])} bars "
              f"{bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    pb = champ.PriceBook(bars)

    print("building Lazy Prices signals (cached corpus)...", flush=True)
    signals, census = lz.build_signals()
    bars_lz = {}
    for t in UNIVERSE + ["SPY"]:
        bars_lz[t] = lz.get_prices(t)
    pb_lz = lz.PriceBook(bars_lz)
    for wname, ws, we in WINDOWS:
        sd_champ = champ.quarter_selection_dates(pb, ws, we)
        sd_lz = lz.quarter_selection_dates(pb_lz, ws, we)
        assert sd_champ == sd_lz, \
            f"selection dates diverge on {wname}: {sd_champ} vs {sd_lz}"
    print("selection dates identical across champion/Lazy books",
          flush=True)

    # ---- integrity: parents standalone, imported engines, verbatim,
    # plain -15% floor (his rules), must reproduce published finals
    checks = {}
    parents = {}
    for wname, ws, we in WINDOWS:
        vm100 = champ.run_pot(pb, equity_rows, shares_rows, ws, we,
                              100.0, 85.0, [], label=f"{wname} VM parent",
                              quiet=True)
        lz100 = lz.run_pot(pb_lz, signals, ws, we)
        stats = {"direct": 0, "derived": 0}
        f3_100 = nf3.run_pot(pb, facts_by_ticker, ws, we, 100.0, 85.0,
                             label=f"{wname} NF3 parent", stats=stats)
        s, _ = champ.spy_net(pb, ws, we, 100.0)
        got = {"VM": vm100["final"], "LZ": lz100["final"],
               "NF3": f3_100["final"], "SPY": s}
        for k, v in got.items():
            want = PUBLISHED[k][wname]
            print(f"CHECK {k} {wname} $100: ${v:.2f} "
                  f"(published ${want})", flush=True)
            assert abs(v - want) < 0.05, \
                f"INTEGRITY FAIL {k} {wname}: got {v:.2f}, want {want}"
            checks[f"{k}_{wname}"] = round(v, 2)
        parents[wname] = {
            "VM": {"final": round(vm100["final"], 2),
                   "costs": round(vm100["costs"], 2),
                   "orders": len(vm100["trades"]),
                   "halted": vm100["halted"],
                   "diag": diagnostics(vm100["curve"], 85.0)},
            "LZ": {"final": round(lz100["final"], 2),
                   "costs": round(lz100["costs"], 2),
                   "orders": len(lz100["trades"]),
                   "halted": lz100["halted"],
                   "diag": diagnostics(lz100["curve"], 85.0)},
            "NF3": {"final": round(f3_100["final"], 2),
                    "costs": round(f3_100["costs"], 2),
                    "orders": len(f3_100["trades"]),
                    "halted": f3_100["halted"],
                    "diag": diagnostics(f3_100["curve"], 85.0)},
            "SPY": round(s, 2),
        }
        print(f"== PARENTS {wname}: VM=${vm100['final']:,.2f} "
              f"LZ=${lz100['final']:,.2f} NF3=${f3_100['final']:,.2f} "
              f"SPY=${s:,.2f}", flush=True)
    print("integrity checks passed", flush=True)

    scorer = Scorer(pb, equity_rows, shares_rows, facts_by_ticker,
                    signals)

    # ---- static mix diagnostic: parents standalone at $100/3, floors
    # off — what the three engines sum to with NO resets and NO floor
    third = POT / 3.0
    static_mix = {}
    static_curves = {}
    for wname, ws, we in WINDOWS:
        vm_t = champ.run_pot(pb, equity_rows, shares_rows, ws, we,
                             third, -1e18, [], label=f"{wname} VM third",
                             quiet=True)
        lz_t = lz.run_pot(pb_lz, signals, ws, we, start_cash=third,
                          floor0=-1e18)
        st = {"direct": 0, "derived": 0}
        f3_t = nf3.run_pot(pb, facts_by_ticker, ws, we, third, -1e18,
                           label=f"{wname} NF3 third", stats=st)
        static_mix[wname] = {
            "VM_third": round(vm_t["final"], 2),
            "LZ_third": round(lz_t["final"], 2),
            "NF3_third": round(f3_t["final"], 2),
            "sum": round(vm_t["final"] + lz_t["final"] + f3_t["final"], 2)}
        static_curves[wname] = {"VM": vm_t["curve"], "LZ": lz_t["curve"],
                                "NF3": f3_t["curve"]}
        print(f"== STATIC MIX {wname}: VM=${vm_t['final']:,.2f} "
              f"LZ=${lz_t['final']:,.2f} NF3=${f3_t['final']:,.2f} "
              f"sum=${vm_t['final'] + lz_t['final'] + f3_t['final']:,.2f}",
              flush=True)

    # ---- sleeve correlations (standalone thirds, monthly returns)
    corr = {}
    for wname in static_curves:
        m = {k: monthly_returns(c) for k, c in static_curves[wname].items()}
        corr[wname] = {}
        for a, b in (("VM", "LZ"), ("VM", "NF3"), ("LZ", "NF3")):
            common = sorted(set(m[a]) & set(m[b]))
            corr[wname][f"{a}-{b}"] = {
                "r": pearson([m[a][x] for x in common],
                             [m[b][x] for x in common]),
                "months": len(common)}

    # ---- the combo: ranked under v9 + his-rules reference + placebos
    out = {"test": "THREE-WAY COMBO (V+M x Lazy Prices x N-F3), equal "
                   "thirds, quarterly reset, one combined floor — "
                   "CLAUDE-RULES PROTECTION SPEC v9",
           "protection_v9": "episode-1 floor -15% from the $100 start "
                            "on the combined pot; on first halt "
                            "liquidate, 90 calendar days cash, restart "
                            "the whole pot at the next quarterly "
                            "selection date with the remaining cash; "
                            "episode-2 floor -15% from the restart "
                            "balance; second halt ends the run",
           "bar": "beat ALL THREE parents on BOTH windows "
                  "(VM $544.47/$288.05; LZ $504.34/$324.12; "
                  "NF3 $505.43/$289.53)",
           "integrity_checks": checks,
           "parents_recomputed": parents,
           "static_mix": static_mix,
           "sleeve_monthly_correlation": corr,
           "universe": UNIVERSE,
           "lazy_census": census}
    for wname, ws, we in WINDOWS:
        s, _ = champ.spy_net(pb, ws, we, 100.0)
        r = run_combo_v9(pb, scorer, ws, we, POT,
                         label=f"{wname} COMBO-V9")
        diag = diagnostics(r["curve"], 85.0)
        worst_eq = worst_from_start(r, POT)
        rh = run_combo(pb, scorer, ws, we, POT, 85.0,
                       label=f"{wname} COMBO-HIS")
        placebo_rows = []
        placebo_finals = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            pr = run_combo_v9(pb, scorer, ws, we, POT, placebo_rng=rng,
                              label=f"{wname} COMBO-V9 PLACEBO s{seed}")
            placebo_rows.append({
                "seed": seed, "final": round(pr["final"], 2),
                "halted_first": pr["halted"],
                "restarts": pr["restarts"],
                "second_halt": pr["second_halt"],
                "episodes": pr["episodes"],
                "costs": round(pr["costs"], 2)})
            placebo_finals.append(round(pr["final"], 2))
            print(f"  placebo v9 seed {seed}: ${pr['final']:,.2f} "
                  f"halt1={pr['halted']} "
                  f"restart={len(pr['restarts'])} "
                  f"halt2={bool(pr['second_halt'])}", flush=True)
        sf = sorted(placebo_finals)
        placebo_median = round(pct(sf, 0.5), 2)
        beaten = sum(1 for x in placebo_finals if r["final"] > x)
        beats_parents = {k: r["final"] > PUBLISHED[k][wname]
                         for k in ("VM", "LZ", "NF3")}
        out[wname] = {
            "final": round(r["final"], 2), "costs": round(r["costs"], 2),
            "orders": len(r["trades"]), "halted_first": r["halted"],
            "halt_info": r["halt_info"], "restarts": r["restarts"],
            "second_halt": r["second_halt"], "episodes": r["episodes"],
            "spy_net": round(s, 2), "diag": diag,
            "worst_equity_from_100": round(worst_eq, 2),
            "worst_total_loss_from_100": round(POT - worst_eq, 2),
            "sleeve_finals": r["sleeve_finals"],
            "transfers": r["transfers"],
            "n_transfers": len(r["transfers"]),
            "total_moved": round(sum(t["moved"]
                                     for t in r["transfers"]), 2),
            "beats_parents": beats_parents,
            "beats_all_parents": all(beats_parents.values()),
            "his_rules_reference": {
                "final": round(rh["final"], 2),
                "costs": round(rh["costs"], 2),
                "orders": len(rh["trades"]), "halted": rh["halted"],
                "halt_info": rh["halt_info"],
                "worst_equity_from_100": round(worst_from_start(rh, POT), 2),
                "sleeve_finals": rh["sleeve_finals"],
                "n_transfers": len(rh["transfers"])},
            "placebo_finals": placebo_finals,
            "placebo_rows": placebo_rows,
            "placebo_median": placebo_median,
            "placebo_beaten": beaten,
            "placebo_first_halts": sum(1 for x in placebo_rows
                                       if x["halted_first"]),
            "placebo_second_halts": sum(1 for x in placebo_rows
                                        if x["second_halt"]),
            "pools": r["pools"],
        }
        print(f"== {wname} COMBO-V9 final=${r['final']:,.2f} "
              f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
              f"halt1={r['halted']} restarts={len(r['restarts'])} "
              f"halt2={bool(r['second_halt'])} | SPY=${s:,.2f} | "
              f"his-rules combo=${rh['final']:,.2f} "
              f"halted={rh['halted']} | placebo median="
              f"${placebo_median:,.2f} beaten={beaten}/20", flush=True)
        print(f"   worst equity ${worst_eq:,.2f} (worst total loss "
              f"${POT - worst_eq:,.2f}) | maxDD {diag['max_drawdown_pct']}% "
              f"| transfers={len(r['transfers'])} moved="
              f"${sum(t['moved'] for t in r['transfers']):,.2f}",
              flush=True)

    # ---- yearly folds vs SPY (v9; his-rules combo alongside)
    folds = []
    prod_v9 = 1.0
    prod_his = 1.0
    prod_spy = 1.0
    wins = 0
    for yr in range(2020, 2027):
        fs = f"{yr}-01-01"
        fe = "2026-11-20" if yr == 2026 else f"{yr}-12-31"
        fr = run_combo_v9(pb, scorer, fs, fe, POT,
                          label=f"FOLD {yr} V9")
        fh = run_combo(pb, scorer, fs, fe, POT, 85.0,
                       label=f"FOLD {yr} HIS")
        fs_spy, _ = champ.spy_net(pb, fs, fe, POT)
        win = fr["final"] > fs_spy
        wins += 1 if win else 0
        prod_v9 *= fr["final"] / POT
        prod_his *= fh["final"] / POT
        prod_spy *= fs_spy / POT
        folds.append({"year": yr, "start": fs, "end": fe,
                      "combo_v9_final": round(fr["final"], 2),
                      "combo_his_final": round(fh["final"], 2),
                      "spy_final": round(fs_spy, 2),
                      "win_v9_vs_spy": win,
                      "halted_first": fr["halted"],
                      "restarts": fr["restarts"],
                      "second_halt": fr["second_halt"],
                      "episodes": fr["episodes"],
                      "his_halted": fh["halted"],
                      "worst_equity_v9": round(worst_from_start(fr, POT), 2),
                      "costs_v9": round(fr["costs"], 2)})
        print(f"== FOLD {yr}: combo-v9=${fr['final']:,.2f} "
              f"combo-his=${fh['final']:,.2f} SPY=${fs_spy:,.2f} "
              f"win={win} halt1={fr['halted']} "
              f"restarts={len(fr['restarts'])} "
              f"halt2={bool(fr['second_halt'])}", flush=True)
    out["folds"] = {"per_year": folds, "wins_vs_spy": wins,
                    "combo_v9_fold_compounded": round(POT * prod_v9, 2),
                    "combo_his_fold_compounded": round(POT * prod_his, 2),
                    "spy_fold_compounded": round(POT * prod_spy, 2)}
    out["nf3_quarter_values"] = scorer.nf3_stats

    verdict = (out["FULL"]["beats_all_parents"]
               and out["VALIDATION"]["beats_all_parents"])
    out["verdict"] = ("ADOPT (CANDIDATE-grade) — beats all three parents "
                      "on both windows under Claude's rules"
                      if verdict else
                      "NOT ADOPTED — dilution under Claude's rules "
                      "(fails the pre-registered bar: must beat ALL "
                      "THREE parents on BOTH windows)")
    print(f"\nVERDICT: {out['verdict']}", flush=True)

    with open(os.path.join(HERE, "combo-three-way-v9-results.json"),
              "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("saved combo-three-way-v9-results.json")


if __name__ == "__main__":
    main()
