#!/usr/bin/env python3
"""
PRE-FOMC ANNOUNCEMENT DRIFT — Lucca & Moench (NY Fed Staff Report 512,
2011; Journal of Finance 2015). Terry's AI stock app. Simulation only.

THE SPEC (firm-reverse-engineering.md §4.4, FROZEN — implemented exactly
as written; no alternative exit, no parameter, nothing tuned):

  Universe: SPY only. Events: scheduled FOMC meetings only, dates from
  the Federal Reserve's published historical meeting calendars (free),
  2016-11-21 -> 2026-11-20. Emergency meetings excluded in advance.

  Rule (Lucca & Moench, frozen): buy SPY at the CLOSE of the trading day
  before the announcement day; sell at the CLOSE of the announcement
  day. This is the daily-bar approximation of their 24-hour window; the
  contamination (the position is still held for the post-14:00 hours)
  is stated in the report, and no alternative exit is run — one shot,
  no spec-shopping.

  Portfolio: $100, fully invested only inside event windows, cash
  otherwise.

  Costs/floor: program standard on both legs (0.10% of trade value per
  side + $0.01 per sell order); plain -15% floor ($85) on the daily
  close. A 2x-cost stress is reported alongside.

  Judging: continuous 2019-01-01 -> 2026-11-20 and validation
  2023-01-01 -> 2026-11-20. Design-period events (2016-2018) are
  reported as context/count only. Report total pot result, per-event
  mean return, and the share of SPY's total window return the strategy
  captures per day invested.

  Placebo: 20 seeds of pseudo-calendars — the same number of events per
  year, each real date shifted by a random +5 to +25 trading days (no
  overlap with real windows). Gate: validation net return above the
  95th percentile of the placebo distribution AND positive net of 2x
  costs on the continuous window. (The audit's standing promotion bar
  also requires beating SPY buy-hold on validation; both are reported
  and the verdict applies both.)

FORCED READINGS (stated here and in the report, before results):
  1. The 2020-03-17/18 meeting was SCHEDULED on the Fed's published
     calendar but was cancelled after the emergency actions of Mar 3
     and Mar 15; no policy announcement was made on Mar 18. It is
     therefore NOT an event. The Mar 3 and Mar 15, 2020 unscheduled
     emergency announcements are excluded by the spec's
     scheduled-meetings-only rule. Net effect: 2020 contributes 7
     events, not 8.
  2. "Announcement day" = the second day of each scheduled two-day
     meeting (the day the statement is released). All scheduled
     meetings in range are two-day meetings.
  3. Placebo construction: a pseudo-calendar is built per judging
     window. Each real event keeps its source-year slot (a December
     event shifted into January still counts as that December year's
     event — this is what "same number of events per year" is read to
     mean). A candidate shift is redrawn until the pseudo event's
     [entry, announcement] window (a) ends on or before the window's
     last trading day, (b) overlaps no real FOMC event window anywhere
     in 2016-2026, and (c) overlaps no already-placed pseudo window in
     the same seed (the pot can only hold one position at a time).
     Seeds are 1..20, drawn with Python's random.Random(seed),
     processing events chronologically.
  4. "Days invested" = the number of event windows (each is exactly
     one close-to-close trading interval). The capture metrics are
     reported three ways so the spec's phrase is fully answered:
     raw capture (strategy net return / SPY net return), capture per
     invested day, and strategy return per invested day.
  5. Prices are the program's SPY cache (Yahoo chart API via the
     champion engine's cache in backtests/v4/data): closes are
     adjclose (split/dividend-adjusted, total-return basis), opens
     scaled by adjclose/close — the identical construction to
     value-momentum-plainfloor.py. The strategy trades at closes, so
     only closes enter its fills; opens are used only by the SPY
     buy-hold control and a floor liquidation, per program convention.

Data sources (Federal Reserve, free):
  - Meeting calendars 2021-2026: "Meeting calendars and information",
    https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm?os=___
  - Historical materials 2016-2020:
    https://www.federalreserve.gov/monetarypolicy/fomchistorical2016.htm
    https://www.federalreserve.gov/monetarypolicy/fomchistorical2017.htm
    https://www.federalreserve.gov/monetarypolicy/fomchistorical2018.htm
    https://www.federalreserve.gov/monetarypolicy/fomchistorical2019.htm
    https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm
  Announcement dates below are the second (statement) day of each
  scheduled meeting as listed on those calendars.
"""
import json, math, os, random, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
SPY_CACHE = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/data/px_SPY.json")

START_CASH = 100.0
FLOOR = 85.0                    # plain -15% floor on the $100 pot
COST_RATE = 0.0010              # 0.10% of trade value per side
SELL_FEE = 0.01                 # $0.01 per sell order
PLACEBO_SEEDS = list(range(1, 21))

EVENT_RANGE = ("2016-11-21", "2026-11-20")
WINDOWS = {
    "continuous": ("2019-01-01", "2026-11-20"),
    "validation": ("2023-01-01", "2026-11-20"),
}
REFERENCES = {
    "continuous": {"champion_vm": 544.47, "spy_buyhold": 313.62},
    "validation": {"champion_vm": 288.05, "spy_buyhold": 187.77},
}

# Scheduled FOMC announcement days (statement day = day 2 of each
# scheduled meeting), transcribed from the Federal Reserve's published
# calendars listed in the header. 2020 has 7: the scheduled Mar 17-18
# meeting was cancelled (see forced reading 1). 2016 and 2026 are
# partial years under the 2016-11-21 -> 2026-11-20 event range.
FOMC_ANNOUNCEMENTS = [
    # 2016 (in range only)
    "2016-12-14",
    # 2017
    "2017-02-01", "2017-03-15", "2017-05-03", "2017-06-14",
    "2017-07-26", "2017-09-20", "2017-11-01", "2017-12-13",
    # 2018
    "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13",
    "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19",
    # 2019
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19",
    "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
    # 2020 (Mar 17-18 scheduled meeting cancelled — not an event)
    "2020-01-29", "2020-04-29", "2020-06-10", "2020-07-29",
    "2020-09-16", "2020-11-05", "2020-12-16",
    # 2021
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
    "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    # 2023
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    # 2026 (in range only; Dec 9 announcement is past 2026-11-20)
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28",
]


# ------------------------------------------------------------------ data
def load_spy_bars():
    """Program construction (champion engine): close = adjclose;
    open scaled by adjclose/close. Returns list of {d, o, c}."""
    with open(SPY_CACHE, "rb") as f:
        j = json.loads(f.read())
    res = j["chart"]["result"][0]
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
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


BARS = load_spy_bars()
DATES = [b["d"] for b in BARS]
IDX = {d: i for i, d in enumerate(DATES)}
BAR = {b["d"]: b for b in BARS}


def _pct(sorted_vals, q):
    """Percentile, linear interpolation (champion engine's method)."""
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


# ---------------------------------------------------------------- engine
def simulate(announcement_dates, start, end, cost_mult=1.0, floor_on=True,
             label=""):
    """One $100 pot. For each announcement date: buy at the close of
    the prior trading day, sell at the close of the announcement day.
    Cash otherwise. Plain floor on the daily close (program
    convention: a close at/below $85 liquidates at the next open and
    ends the run; if the pot is already in cash it simply ends)."""
    rate = COST_RATE * cost_mult
    fee = SELL_FEE * cost_mult
    days = [d for d in DATES if start <= d <= end]
    if not days:
        return None
    day_set = set(days)
    events = []
    for a in announcement_dates:
        if a not in IDX:
            raise ValueError(f"announcement date {a} not a trading day")
        ei = IDX[a] - 1
        events.append({"announcement": a, "entry": DATES[ei]})
    entry_map = {e["entry"]: e for e in events}
    exit_map = {e["announcement"]: e for e in events}

    cash = START_CASH
    shares = 0.0
    holding = None            # event dict being held
    total_costs = 0.0
    trades = []
    event_rows = []
    curve = []
    halted = None
    halt_info = None

    for di, d in enumerate(days):
        # --- buy at today's close if today is an entry day
        if d in entry_map and holding is None and shares == 0.0:
            e = entry_map[d]
            px = BAR[d]["c"]
            buy_val = cash / (1.0 + rate)
            buy_cost = buy_val * rate
            shares = buy_val / px
            cash = 0.0
            total_costs += buy_cost
            holding = dict(e)
            holding.update({"entry_close": px, "pre_cash": buy_val + buy_cost,
                            "buy_value": buy_val, "buy_cost": buy_cost,
                            "shares": shares})
            trades.append((d, "BUY", round(buy_val, 2), round(buy_cost, 4)))
        # --- mark to today's close
        value = cash + (shares * BAR[d]["c"] if shares else 0.0)
        # --- sell at today's close if today is the announcement day
        if d in exit_map and holding is not None:
            px = BAR[d]["c"]
            proceeds = shares * px
            sell_cost = proceeds * rate + fee
            cash = proceeds - sell_cost
            total_costs += sell_cost
            trades.append((d, "SELL", round(proceeds, 2), round(sell_cost, 4)))
            gross = px / holding["entry_close"] - 1.0
            event_rows.append({
                "announcement": d,
                "entry": holding["entry"],
                "entry_close": round(holding["entry_close"], 4),
                "exit_close": round(px, 4),
                "gross_return_pct": round(gross * 100, 4),
                "pre_cash": round(holding["pre_cash"], 2),
                "post_cash": round(cash, 2),
                "net_return_pct": round((cash / holding["pre_cash"] - 1.0) * 100, 4),
                "buy_cost": round(holding["buy_cost"], 4),
                "sell_cost": round(sell_cost, 4),
            })
            shares = 0.0
            holding = None
            value = cash
        curve.append((d, value))
        # --- plain floor on the daily close
        if floor_on and value <= FLOOR and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(value, 2),
                         "floor_in_effect": FLOOR}
            if shares:
                nd = days[di + 1]
                val = shares * BAR[nd]["o"]
                c = val * rate + fee
                cash = val - c
                total_costs += c
                trades.append((nd, "SELL-HALT", round(val, 2), round(c, 4)))
                shares = 0.0
                holding = None
            return _result(label, cash, total_costs, trades, event_rows,
                           curve, halted, halt_info,
                           days[di + 1] if shares == 0.0 and di + 1 < len(days) else d)
    # end of window: liquidate any residual holding at the final close
    if shares:
        last = days[-1]
        px = BAR[last]["c"]
        val = shares * px
        c = val * rate + fee
        cash = val - c
        total_costs += c
        trades.append((last, "SELL-END", round(val, 2), round(c, 4)))
        shares = 0.0
        holding = None
    return _result(label, cash, total_costs, trades, event_rows, curve,
                   halted, halt_info, days[-1])


def _result(label, cash, total_costs, trades, event_rows, curve, halted,
            halt_info, end_date):
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    worst_d, worst_v = min(curve, key=lambda kv: kv[1]) if curve else (None, None)
    gross = [r["gross_return_pct"] for r in event_rows]
    net = [r["net_return_pct"] for r in event_rows]
    return {
        "label": label,
        "final": round(cash, 2),
        "return_pct": round(cash / START_CASH * 100 - 100, 2),
        "total_costs": round(total_costs, 2),
        "n_trades": len(trades),
        "trades": trades,
        "n_events": len(event_rows),
        "events": event_rows,
        "mean_event_gross_pct": round(sum(gross) / len(gross), 4) if gross else None,
        "mean_event_net_pct": round(sum(net) / len(net), 4) if net else None,
        "median_event_gross_pct": round(_pct(sorted(gross), 0.5), 4) if gross else None,
        "positive_events": sum(1 for g in gross if g > 0),
        "max_drawdown_pct": round(maxdd * 100, 2),
        "max_drawdown_date": maxdd_d,
        "worst_close": round(worst_v, 2) if worst_v is not None else None,
        "worst_close_date": worst_d,
        "halted": halted,
        "halt_info": halt_info,
        "end": end_date,
    }


def spy_buyhold(start, end):
    """Champion engine's spy_net, verbatim mechanics: buy at the first
    open (cash/1.001), sell at the final close, program costs."""
    days = [d for d in DATES if start <= d <= end]
    first, last = days[0], days[-1]
    o = BAR[first]["o"]
    sh = (START_CASH / 1.001) / o
    buy_cost = START_CASH - sh * o
    val = sh * BAR[last]["c"]
    sell_cost = val * 0.001 + 0.01
    return {"final": round(val - sell_cost, 2),
            "return_pct": round((val - sell_cost) / START_CASH * 100 - 100, 2),
            "total_costs": round(buy_cost + sell_cost, 2),
            "trading_days": len(days)}


# --------------------------------------------------------------- placebo
# Real event windows (entry index, announcement index) across the full
# event range — pseudo windows may not overlap any of them.
REAL_WINDOWS = [(IDX[a] - 1, IDX[a]) for a in FOMC_ANNOUNCEMENTS
                if a in IDX]


def _overlaps(a_lo, a_hi, b_lo, b_hi):
    return a_lo <= b_hi and b_lo <= a_hi


def build_pseudo_calendar(real_dates, start, end, seed):
    """Shift each real announcement by +5..+25 trading days (redrawn
    until valid — see forced reading 3). Returns announcement dates."""
    rng = random.Random(seed)
    end_idx = max(IDX[d] for d in DATES if start <= d <= end)
    placed = []               # (entry_idx, ann_idx)
    pseudo = []
    for a in real_dates:
        ai = IDX[a]
        for _attempt in range(10000):
            shift = rng.randint(5, 25)
            nai = ai + shift
            nei = nai - 1
            if nai > end_idx:
                continue
            if any(_overlaps(nei, nai, lo, hi) for lo, hi in REAL_WINDOWS):
                continue
            if any(_overlaps(nei, nai, lo, hi) for lo, hi in placed):
                continue
            placed.append((nei, nai))
            pseudo.append(DATES[nai])
            break
        else:
            raise RuntimeError(f"could not place pseudo event for {a} "
                               f"(seed {seed})")
    return sorted(pseudo)


def placebo_block(real_dates, start, end):
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        pseudo = build_pseudo_calendar(real_dates, start, end, seed)
        r = simulate(pseudo, start, end, cost_mult=1.0, floor_on=True,
                     label=f"PLACEBO {seed}")
        finals.append(r["final"])
        rows.append({"seed": seed, "final": r["final"],
                     "return_pct": r["return_pct"],
                     "halted": r["halted"], "n_events": r["n_events"],
                     "announcements": pseudo})
    srt = sorted(finals)
    return {
        "seeds": len(finals),
        "finals": [round(f, 2) for f in finals],
        "median": round(_pct(srt, 0.50), 2),
        "q1": round(_pct(srt, 0.25), 2),
        "q3": round(_pct(srt, 0.75), 2),
        "p95": round(_pct(srt, 0.95), 2),
        "best": round(srt[-1], 2),
        "worst": round(srt[0], 2),
        "mean": round(sum(finals) / len(finals), 2),
        "halted_count": sum(1 for r in rows if r["halted"]),
        "rows": rows,
    }


# ------------------------------------------------------------------ main
def main():
    out = {
        "test": "Pre-FOMC announcement drift (Lucca & Moench 2011/2015)",
        "spec_source": "research/v7-completeness/firm-reverse-engineering.md §4.4 (frozen)",
        "simulation_only": True,
        "chassis": {"start_cash": START_CASH, "floor": FLOOR,
                    "cost_rate_per_side": COST_RATE, "sell_fee": SELL_FEE},
        "event_range": list(EVENT_RANGE),
        "fomc_announcements": FOMC_ANNOUNCEMENTS,
        "event_counts": {},
        "forced_readings": [
            "2020-03-18 excluded: the scheduled Mar 17-18, 2020 meeting was cancelled and made no announcement; Mar 3 / Mar 15, 2020 emergency announcements excluded as unscheduled.",
            "Announcement day = second (statement) day of each scheduled two-day meeting.",
            "Placebo: pseudo events keep their source-year slot; shifts redrawn until the pseudo window ends by the window's last trading day and overlaps no real FOMC window (2016-2026) and no already-placed pseudo window in the seed.",
            "Days invested = number of event windows (one close-to-close trading interval each).",
        ],
    }

    # Event census by period (design period = context/count only).
    design = [a for a in FOMC_ANNOUNCEMENTS if a < "2019-01-01"]
    out["event_counts"] = {
        "all_in_range": len(FOMC_ANNOUNCEMENTS),
        "design_2016_2018_context_only": len(design),
        "design_dates": design,
        "by_year": {y: sum(1 for a in FOMC_ANNOUNCEMENTS if a.startswith(y))
                    for y in sorted({a[:4] for a in FOMC_ANNOUNCEMENTS})},
    }
    print(f"EVENTS: total={len(FOMC_ANNOUNCEMENTS)} design={len(design)} "
          f"by_year={out['event_counts']['by_year']}", flush=True)

    for name, (ws, we) in WINDOWS.items():
        real = [a for a in FOMC_ANNOUNCEMENTS if ws <= a <= we]
        spy = spy_buyhold(ws, we)
        ref = REFERENCES[name]["spy_buyhold"]
        integrity_ok = abs(spy["final"] - ref) < 0.005
        print(f"INTEGRITY {name}: SPY buy-hold=${spy['final']:,.2f} "
              f"published=${ref:,.2f} match={integrity_ok}", flush=True)
        if not integrity_ok:
            raise SystemExit("SPY buy-hold does not reproduce the "
                             "published program figure — results untrusted")

        strat = simulate(real, ws, we, cost_mult=1.0, floor_on=True,
                         label=f"{name} FOMC")
        strat2x = simulate(real, ws, we, cost_mult=2.0, floor_on=True,
                           label=f"{name} FOMC 2x-cost")
        strat_nf = simulate(real, ws, we, cost_mult=1.0, floor_on=False,
                            label=f"{name} FOMC no-floor")
        pl = placebo_block(real, ws, we)
        srt = sorted(pl["finals"])
        beaten = sum(1 for f in pl["finals"] if f < strat["final"])
        ties = sum(1 for f in pl["finals"] if f == strat["final"])
        pctile = 100.0 * (beaten + 0.5 * ties) / len(pl["finals"])
        capture = (strat["return_pct"] / spy["return_pct"] * 100
                   if spy["return_pct"] else None)
        block = {
            "window": [ws, we],
            "reference": REFERENCES[name],
            "integrity_spy_buyhold_match": integrity_ok,
            "n_events": len(real),
            "event_dates": real,
            "strategy": strat,
            "strategy_2x_costs": {"final": strat2x["final"],
                                  "return_pct": strat2x["return_pct"],
                                  "total_costs": strat2x["total_costs"],
                                  "halted": strat2x["halted"]},
            "strategy_no_floor_final": strat_nf["final"],
            "spy_buyhold": spy,
            "capture": {
                "spy_net_return_pct": spy["return_pct"],
                "strategy_net_return_pct": strat["return_pct"],
                "raw_capture_pct_of_spy_return": round(capture, 2) if capture is not None else None,
                "days_invested_event_windows": strat["n_events"],
                "capture_pct_per_invested_day": round(capture / strat["n_events"], 4) if capture is not None and strat["n_events"] else None,
                "strategy_return_pct_per_invested_day": round(strat["return_pct"] / strat["n_events"], 4) if strat["n_events"] else None,
                "spy_trading_days_in_window": spy["trading_days"],
            },
            "placebo": pl,
            "placebo_p95_final": pl["p95"],
            "strategy_placebo_percentile_empirical": round(pctile, 1),
            "strategy_seeds_beaten": beaten,
        }
        out[name] = block
        print(f"{name.upper()}: FOMC final=${strat['final']:,.2f} "
              f"({strat['return_pct']:+.2f}%) events={strat['n_events']} "
              f"mean_event_gross={strat['mean_event_gross_pct']}% "
              f"costs=${strat['total_costs']} halted={strat['halted']} | "
              f"SPY=${spy['final']:,.2f} | 2x-cost final=${strat2x['final']:,.2f}",
              flush=True)
        print(f"   PLACEBO {name}: median=${pl['median']:,.2f} "
              f"p95=${pl['p95']:,.2f} best=${pl['best']:,.2f} "
              f"worst=${pl['worst']:,.2f} halted={pl['halted_count']}/20 | "
              f"strategy beat {beaten}/20 ({pctile:.1f}th pct empirical)",
              flush=True)

    # Pre-registered gate (§4.4 + the audit's standing promotion bar).
    v = out["validation"]
    c = out["continuous"]
    gate = {
        "validation_net_return_above_placebo_p95": v["strategy"]["final"] > v["placebo_p95_final"],
        "validation_beats_spy_buyhold": v["strategy"]["final"] > v["spy_buyhold"]["final"],
        "continuous_positive_net_of_2x_costs": c["strategy_2x_costs"]["final"] > START_CASH,
    }
    gate["promoted"] = all(gate.values())
    out["promotion_gate"] = gate
    print(f"GATE: {gate}", flush=True)

    with open(os.path.join(HERE, "re-fomc-drift-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
