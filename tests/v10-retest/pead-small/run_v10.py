#!/usr/bin/env python3
"""
PEAD-SMALL — v10 GREAT RETEST cadence sweep (simulation only).

Strategy (frozen, as published in v4 / re-run in v9): post-earnings drift in
small/mid caps. EDGAR 8-K Item 2.02 filing; filing-day excess return vs SPY
>= +5%; point-in-time screens on filing day (close $5-$60, 63d ADV > $5M,
Corwin-Schultz spread proxy <= 1.5%); buy next trading day's open; hold 40
trading days; -8% intraday stop; SPY-below-200DMA regime exit; max 3
concurrent; one entry per name per 63 trading days; costs 0.35%/side +
$0.01/sell order (the engine's own cost code, unchanged).

INTEGRITY (done before this sweep, outputs in this folder):
  engine_v4_original.py (his ladder rules) -> integrity_v4_output.json
    design $100 $91.16; validation $100 $99.88, ladder halt 2024-11-18,
    26 entries; SPY validation $179.10; placebo seed42 $100 $84.12.
  engine_v9.py (plain -15% floor) -> integrity_v9_output.json
    design identical $91.16; validation $100 $119.00, no halt, 56 entries.
  Both reproduced the published finals to the cent.

SWEEP (SPEC v10, THE CADENCE SWEEP): DECADE road, $100, program costs,
v9 protections (plain -15% floor, 90-day cash sit, episode-2 floor -15%
from restart balance, second halt ends run).

CADENCE TREATMENT for this EVENT-DRIVEN strategy (per SPEC): the event
rule stays exactly as published — screens and entries fire on the filing
event (buy next trading day's open) at EVERY cadence. Cadence governs
only the position review / exit rhythm: the -8% stop check, the 40-day
hold-end check, the SPY regime check, and the -15% floor check are
evaluated ONLY on cadence review dates (daily = every trading day;
weekly = first trading day of each week; biweekly = first trading day of
every second week, anchored on the first calendar week of the run;
monthly/quarterly/semi-annual/annual = first trading day of the
month/quarter/half-year/year). A pending regime or floor exit set at a
review close executes at the NEXT review date's open. Daily review is
therefore exactly the original engine's rhythm (verified below against
the plain v9 Sim on the same window). Equity is still marked to market
daily for the curve / drawdown (measurement only, no trading effect).

ROAD NOTE: the published data channel starts at EDGAR events from
2018-12-01 and Yahoo bars from 2018-01-01 (the original design window
was 2019-2022). The DECADE calendar therefore runs 2018-01-02 ->
2026-11-20 with the first possible signal in Jan 2019 — the longest
honest sub-window of the decade this channel supports, documented per
SPEC. SPY decade reference $367.80 is the SPEC dividend-adjusted figure
for the full 2016-11-21 start; the in-plumbing price-only SPY final on
the traded sub-window is also recorded per cell.

PLACEBOS: the original v4 seed design (pead-small-placebo-seeds.py):
entries sampled from the pool of screened NON-earnings 8-K filing dates
of the same companies, sample size max(6x target, target) sorted by date,
max_entries = the real run's entry count at that cadence, identical
machinery. Seeds 1-20 per cadence, $100 pot, v9 protections, same
cadence review rhythm as the real run.
"""
import importlib.util, json, math, os, random, statistics, sys
from datetime import date, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("engine_v9",
                                              os.path.join(BASE, "engine_v9.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

WS, WE = date(2016, 11, 21), date(2026, 11, 20)
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]
START = 100.0


def review_dates(cal, cadence):
    """Set of review dates per the SPEC's uniform cadence definition."""
    if cadence == "daily":
        return set(cal)
    out = set()
    if cadence == "weekly":
        prev = None
        for d in cal:
            wk = d.isocalendar()[:2]
            if wk != prev:
                out.add(d)
                prev = wk
    elif cadence == "biweekly":
        # anchor: Monday of the week containing the first calendar day
        anchor = cal[0] - timedelta(days=cal[0].weekday())
        prev = None
        for d in cal:
            wk = d.isocalendar()[:2]
            if wk != prev:
                prev = wk
                monday = d - timedelta(days=d.weekday())
                if ((monday - anchor).days // 7) % 2 == 0:
                    out.add(d)
    elif cadence in ("monthly", "quarterly", "semiannual", "annual"):
        prev = None
        for d in cal:
            if cadence == "monthly":
                key = (d.year, d.month)
            elif cadence == "quarterly":
                key = (d.year, (d.month - 1) // 3)
            elif cadence == "semiannual":
                key = (d.year, (d.month - 1) // 6)
            else:
                key = (d.year,)
            if key != prev:
                out.add(d)
                prev = key
    else:
        raise ValueError(cadence)
    return out


class CadenceSim(mod.Sim):
    """v9 Sim with exit/floor checks gated to cadence review dates.

    Entries (the event rule) are NOT gated. At daily cadence this is the
    v9 engine's run() line for line.
    """

    def __init__(self, *a, cadence="daily", review=None, **kw):
        super().__init__(*a, **kw)
        self.cadence = cadence
        self.review = review if review is not None else set(self.cal)
        self.equity = []

    def run(self, signals):
        sig_by_day = {}
        for s in signals:
            sig_by_day.setdefault(s["buy_date"], []).append(s)
        for d in self.cal:
            gi = mod.GLOBAL_IDX[d]
            is_rev = d in self.review
            if is_rev and self.pending_liquidation:
                for pos in list(self.positions):
                    self.sell(pos, self.bars[pos["ticker"]][d]["open"], "floor", d)
                self.pending_liquidation = False
                self.v9_halts.append({"date": d.isoformat(),
                                      "balance": round(self.cash, 2),
                                      "episode": self.episode})
                if self.episode >= 2:
                    self.halted = True
                    self.halt_date = d
                    break
                self.restart_not_before = d + timedelta(days=90)
                self.episode = 2
                self.floor = 0.85 * self.cash
                continue
            if is_rev and self.pending_regime_exit:
                for pos in list(self.positions):
                    self.sell(pos, self.bars[pos["ticker"]][d]["open"], "regime", d)
                self.pending_regime_exit = False
            if is_rev:
                for pos in list(self.positions):
                    bar = self.bars[pos["ticker"]][d]
                    if bar["low"] <= pos["stop_price"]:
                        px = bar["open"] if bar["open"] < pos["stop_price"] else pos["stop_price"]
                        self.sell(pos, px, "stop", d)
            if (self.restart_not_before is not None and not self._restart_logged
                    and d >= self.restart_not_before):
                self.v9_restarts.append({"date": d.isoformat(),
                                         "balance": round(self.cash, 2),
                                         "episode2_floor": round(self.floor, 2)})
                self._restart_logged = True
            if not self.halted and not (self.restart_not_before is not None
                                        and d < self.restart_not_before):
                for s in sig_by_day.get(d, []):
                    if self.max_entries is not None and self.entries >= self.max_entries:
                        break
                    t = s["ticker"]
                    if len(self.positions) >= mod.MAX_POS:
                        continue
                    if any(p["ticker"] == t for p in self.positions):
                        continue
                    if gi - self.last_entry_idx.get(t, -10**9) < mod.COOLDOWN:
                        continue
                    slots = mod.MAX_POS - len(self.positions)
                    spend = self.cash / slots
                    if spend < 2.0:
                        continue
                    px = self.bars[t][d]["open"]
                    if px is None or px <= 0:
                        continue
                    shares = spend / (px * (1 + mod.BUY_COST))
                    cost = spend - shares * px
                    self.cash -= spend
                    self.total_costs += cost
                    self.positions.append({
                        "ticker": t, "shares": shares, "entry_price": px,
                        "entry_date": d, "entry_gidx": gi,
                        "cost_basis": spend, "stop_price": px * (1 - mod.STOP_PCT)})
                    self.entries += 1
                    self.last_entry_idx[t] = gi
            if is_rev:
                for pos in list(self.positions):
                    if gi - pos["entry_gidx"] >= mod.HOLD_DAYS - 1:
                        self.sell(pos, self.bars[pos["ticker"]][d]["close"],
                                  "hold_end", d)
                ma = self.spy_ma.get(d)
                if self.positions and ma is not None and self.spy_close[d] < ma:
                    self.pending_regime_exit = True
            value = self.cash + sum(
                p["shares"] * self.bars[p["ticker"]][d]["close"]
                for p in self.positions)
            self.equity.append((d, value))
            if is_rev and value <= self.floor:
                self.pending_liquidation = True
        if not self.halted and self.positions:
            d = self.cal[-1]
            for pos in list(self.positions):
                self.sell(pos, self.bars[pos["ticker"]][d]["close"], "window_end", d)
            if self.equity and self.equity[-1][0] == d:
                self.equity[-1] = (d, self.cash)
        return self


def max_dd(equity, start):
    peak, mdd = start, 0.0
    for _, v in equity:
        peak = max(peak, v)
        mdd = max(mdd, (peak - v) / peak * 100 if peak > 0 else 0.0)
    return round(mdd, 2)


def event_stats(sim, spy_bars):
    """Per-event net return and net excess vs SPY over the same hold."""
    nets, excs = [], []
    for t in sim.trades:
        nets.append(t["pnl_pct"])
        e, x = t["entry_date"], t["exit_date"]
        if e in spy_bars and x in spy_bars and spy_bars[e]["close"]:
            spy_r = (spy_bars[x]["close"] / spy_bars[e]["close"] - 1) * 100
            excs.append(t["pnl_pct"] - spy_r)
    f = lambda v: round(statistics.mean(v), 2) if v else None
    m = lambda v: round(statistics.median(v), 2) if v else None
    wins = sum(1 for t in sim.trades if t["pnl"] > 0)
    return {
        "signals_traded": sim.entries,
        "round_trips": len(sim.trades),
        "win_rate_pct": round(wins / len(sim.trades) * 100, 1) if sim.trades else None,
        "per_event_mean_net_pct": f(nets),
        "per_event_median_net_pct": m(nets),
        "per_event_mean_net_excess_vs_spy_pct": f(excs),
        "per_event_median_net_excess_vs_spy_pct": m(excs),
        "exit_reasons": {r: sum(1 for t in sim.trades if t["reason"] == r)
                         for r in ("stop", "hold_end", "regime", "floor",
                                   "window_end")},
    }


def main():
    print("Loading data (read-only v4 cache)...", file=sys.stderr)
    ciks = mod.get_ciks()
    earnings, nonearn, stats = mod.get_events(ciks)
    bars = {t: mod.get_bars(t) for t in mod.SEEDS + ["SPY"]}
    spy = bars["SPY"]
    mod.ALL_DAYS = sorted(spy.keys())
    mod.GLOBAL_IDX = {d: i for i, d in enumerate(mod.ALL_DAYS)}
    spy_close = {d: spy[d]["close"] for d in mod.ALL_DAYS}
    closes = [spy[d]["close"] for d in mod.ALL_DAYS]
    spy_ma = {d: (sum(closes[i - 199:i + 1]) / 200 if i >= 199 else None)
              for i, d in enumerate(mod.ALL_DAYS)}
    screener = mod.Screener(bars)

    cal = [d for d in mod.ALL_DAYS if WS <= d <= WE]
    diag = {}
    sigs = mod.build_signals(earnings, bars, spy, screener, WS, WE, diag)
    pool = mod.build_placebo_pool(nonearn, bars, screener, WS, WE)
    spy_sub = mod.spy_benchmark(cal, spy, 100)
    years = (cal[-1] - cal[0]).days / 365.25
    print(f"cal {cal[0]}..{cal[-1]} ({len(cal)}d); signals {len(sigs)}; "
          f"placebo pool {len(pool)}; SPY sub-window net ${spy_sub}; diag {diag}",
          file=sys.stderr)

    # sanity: daily CadenceSim must equal the plain v9 Sim on this window
    plain = mod.Sim(cal, bars, spy_close, spy_ma, START, 85.0, []).run(sigs)
    daily_rev = review_dates(cal, "daily")
    chk = CadenceSim(cal, bars, spy_close, spy_ma, START, 85.0, [],
                     cadence="daily", review=daily_rev).run(sigs)
    assert abs(plain.cash - chk.cash) < 0.005, (plain.cash, chk.cash)
    print(f"sanity: plain v9 Sim ${plain.cash:.2f} == daily CadenceSim "
          f"${chk.cash:.2f}", file=sys.stderr)

    cells, results_cells = {}, {}
    for cad in CADENCES:
        rev = review_dates(cal, cad)
        sim = CadenceSim(cal, bars, spy_close, spy_ma, START, 85.0, [],
                         cadence=cad, review=rev).run(sigs)
        es = event_stats(sim, spy)
        target = sim.entries
        twins = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            sampled = rng.sample(pool, min(len(pool), max(target * 6, target)))
            sampled.sort(key=lambda s: s["buy_date"])
            ps = CadenceSim(cal, bars, spy_close, spy_ma, START, 85.0, [],
                            cadence=cad, review=rev,
                            max_entries=target).run(sampled)
            twins.append(round(ps.cash, 2))
        beaten = sum(1 for f in twins if f < round(sim.cash, 2))
        final = round(sim.cash, 2)
        cell = {
            "slug": "pead-small", "cadence": cad,
            "cadence_treatment": ("event entries as published (next-open after "
                                  "qualifying filing); stop / 40-day hold-end / "
                                  "SPY-regime / -15% floor checks only on "
                                  f"{cad} review dates; pending regime/floor "
                                  "exits execute at the next review date's open"),
            "window": [str(cal[0]), str(cal[-1])],
            "window_note": ("SPEC DECADE is 2016-11-21..2026-11-20; the "
                            "published data channel (EDGAR events from "
                            "2018-12-01, Yahoo bars from 2018-01-01) starts "
                            "the traded calendar 2018-01-02, first signals "
                            "Jan 2019 — longest honest sub-window, per SPEC"),
            "start": START, "final": final,
            "cagr_pct": round(((final / START) ** (1 / years) - 1) * 100, 2),
            "max_dd_pct": max_dd(sim.equity, START),
            "costs": round(sim.total_costs, 2),
            "orders": sim.entries + len(sim.trades),
            "entries": sim.entries,
            "halts": sim.v9_halts, "restarts": sim.v9_restarts,
            "restart": bool(sim.v9_restarts),
            "second_halt": bool(sim.halted),
            "halted_end": sim.halted,
            "event_stats": es,
            "spy_subwindow_price_only_net_final": spy_sub,
            "placebo_beaten": f"{beaten}/20",
            "placebo_twin_finals": twins,
            "placebo_note": ("Original v4 seed design: screened non-earnings "
                             "8-K dates of the same companies, sample "
                             "max(6x target, target), max_entries = real "
                             "entries at this cadence, seeds 1-20, v9 "
                             "protections, same cadence rhythm"),
            "equity_curve": [[d.isoformat(), round(v, 2)] for d, v in sim.equity],
            "trades": [{**t, "entry_date": t["entry_date"].isoformat(),
                        "exit_date": t["exit_date"].isoformat(),
                        "pnl": round(t["pnl"], 2),
                        "pnl_pct": round(t["pnl_pct"], 2),
                        "entry_price": round(t["entry_price"], 2),
                        "exit_price": round(t["exit_price"], 2)}
                       for t in sim.trades],
        }
        with open(os.path.join(BASE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells[cad] = cell
        results_cells[cad] = {
            "final": final, "cagr_pct": cell["cagr_pct"],
            "max_dd_pct": cell["max_dd_pct"],
            "halts": len(sim.v9_halts), "restart": bool(sim.v9_restarts),
            "second_halt": bool(sim.halted),
            "costs": cell["costs"], "orders": cell["orders"],
            "placebo_beaten": f"{beaten}/20",
            "placebo_note": cell["placebo_note"],
            "signals_traded": es["signals_traded"],
            "per_event_mean_net_excess_vs_spy_pct":
                es["per_event_mean_net_excess_vs_spy_pct"],
            "per_event_median_net_excess_vs_spy_pct":
                es["per_event_median_net_excess_vs_spy_pct"],
        }
        print(f"{cad}: final ${final} CAGR {cell['cagr_pct']}% DD "
              f"{cell['max_dd_pct']}% entries {sim.entries} costs "
              f"${cell['costs']} halts {len(sim.v9_halts)} placebo "
              f"{beaten}/20 meanExcess {es['per_event_mean_net_excess_vs_spy_pct']}%",
              file=sys.stderr)

    # Money cadence (program bar): beats SPY AND beats >=19/20 placebo
    # twins (the champion's own 19-of-20 significance standard in this
    # program). Annual nominally beat SPY and 15/20 twins but its twin
    # distribution is centered near SPY itself (median $333.87, 5/20 twins
    # above the real run) — the no-review ride, not the signal; recorded
    # under nominal_money_cadences in the verdict patch, not credited.
    money = [c for c in CADENCES
             if cells[c]["final"] > 367.80
             and int(cells[c]["placebo_beaten"].split("/")[0]) >= 19]
    out = {
        "slug": "pead-small",
        "area": ("Earnings-event drift in small/mid caps (SPEC W9): event-to-"
                 "event PEAD where the literature says the drift survives; "
                 "decade cadence sweep on the DECADE road (traded sub-window "
                 "2018-01-02..2026-11-20, data channel limit)"),
        "area_source": "SPEC.md W9 batch + THE CADENCE SWEEP (2026-11-21 ~22:09)",
        "native_cadence": "event-driven",
        "cadence": "event-driven",
        "original_cadence_foreign": {
            "foreign": False,
            "note": ("Original program test ran the published event-driven "
                     "form with daily exit/floor checks — its native cadence; "
                     "no foreign cadence was forced. The sweep's non-daily "
                     "cells are the foreign tempos being probed."),
        },
        "native_change": ("none — original form was native. v10 adds: the "
                          "7-cadence exit-rhythm sweep on the DECADE road and "
                          "20-seed placebos per cadence (original ran 5 seeds, "
                          "validation only)"),
        "integrity": {
            "status": "reproduced",
            "original_finals": {
                "design_100_his": 91.16, "design_100_v9": 91.16,
                "validation_100_his": 99.88, "validation_100_v9": 119.00,
                "validation_50_his": 49.82, "validation_50_v9": 59.19,
                "spy_validation_100": 179.10,
            },
            "reproduced_finals": {
                "design_100_his": 91.16, "design_100_v9": 91.16,
                "validation_100_his": 99.88, "validation_100_v9": 119.00,
                "validation_50_his": 49.82, "validation_50_v9": 59.19,
                "spy_validation_100": 179.10,
            },
            "note": ("engine_v4_original.py (his ladder rules) and engine_v9.py "
                     "(plain -15% floor) re-run in this folder on the original "
                     "windows reproduced every published final to the cent: "
                     "design identical under both rule sets ($45.39/$91.16); "
                     "validation his-rules $49.82/$99.88 with the ladder halt "
                     "on 2024-11-18 after 26 entries; v9 $59.19/$119.00, no "
                     "halt, all 56 entries; SPY validation $89.54/$179.10; "
                     "v4 placebo seed 42 $84.12 on $100 also reproduced. "
                     "Outputs: integrity_v4_output.json / "
                     "integrity_v9_output.json. Daily-cadence CadenceSim "
                     "additionally matched the plain v9 Sim to the cent on "
                     "the decade window before sweep numbers were taken."),
        },
        "decade_spy_final": 367.80,
        "spy": {"DECADE": 367.80,
                "DECADE_subwindow_price_only_net_in_plumbing": spy_sub,
                "VAL_original_engine": 179.10},
        "champion_decade_final": 65.89,
        "champion_note": ("Champion (value+momentum) DECADE final $65.89 after "
                          "two halts (lazy-quarterly test) — its crown rests on "
                          "the 2010 and 2019 roads, per SPEC; printed here "
                          "because pead-small's decade cells are compared "
                          "against it in RESULTS.md"),
        "cells": results_cells,
        "money_cadences": money,
        "verdict_area": "NO GROUND",
        "verdict_change": ("Unchanged. The family was FAILED/CLOSED in v4 and "
                           "stayed closed in v9; the decade cadence sweep "
                           "confirms it on its own ground at every exit rhythm. "
                           "Median per-event net excess vs SPY is negative at "
                           "all seven cadences. The one nominal SPY-beater "
                           "(annual) is a placebo-shared artifact of never "
                           "reviewing positions — see RESULTS.md."),
    }
    with open(os.path.join(BASE, "results.json"), "w") as f:
        json.dump(out, f, indent=1)
    print("money_cadences:", money)


if __name__ == "__main__":
    main()
