#!/usr/bin/env python3
"""
THE GREAT RETEST (v10) — re-fomc-drift (Pre-FOMC Announcement Drift, RE #4).

INTEGRITY (done separately, see integrity_run.log / integrity-results.json):
the unmodified original v7 engine (integrity_original.py in this folder,
byte copy of backtests/v7/re-fomc-drift/re-fomc-drift.py) reproduced the
published finals to the cent on the v4 SPY cache:
  CONT 2019-01-01->2026-11-20 (62 events) $93.00, floor never fired
  VAL  2023-01-01->2026-11-20 (31 events) $90.26, floor never fired
  SPY gates $313.62 / $187.77; 2x-cost stress $84.00 / $84.61 (noted).

SWEEP (SPEC uniform event-strategy definition):
  ROAD: DECADE 2016-11-21 -> 2026-11-20, $100/cell.
  Event rules stay exactly as published: buy SPY at the close of the
  trading day before each scheduled FOMC announcement (79 events in the
  decade range; the cancelled 2020-03-18 meeting is not an event, the
  Mar 3/15 2020 emergency announcements are excluded — same census as
  the original). CADENCE governs only the position review / exit-check
  rhythm: the scheduled exit (announcement-day close) executes at the
  close of the FIRST cadence date on/after the announcement day (if no
  cadence date remains in the window, at the final day's close), and
  the floor is checked only on cadence dates. Daily cadence is
  therefore the original form. Where capital is tied up in a still-open
  position, a later event's entry is skipped for lack of cash (counted
  as skipped_no_cash) — the mechanical consequence of a slower exit
  rhythm, not a rule change.
  Cadence dates (SPEC): daily = every trading day; weekly = first
  trading day of each ISO week; biweekly = first trading day of every
  second ISO week (starting with the window's first week); monthly =
  first trading day of each month; quarterly = first trading day of
  each calendar quarter; semiannual = first trading day of each
  half-year; annual = first trading day of each year.
  v9 protections: plain -15% floor from the episode's starting balance,
  NO ladder. First halt (on a cadence-date close): liquidate any holding
  at that close (program costs), sit in cash 90 calendar days, restart
  at the next event entry on/after the sit expires, with an episode-2
  floor of -15% from the restart balance. Second halt ends the run.
  Costs: program conventions — 0.10% of trade value per side +
  $0.01 per sell order, identical to the original engine.

DATA: the original v4 SPY cache starts 2017-06-01 and cannot cover the
first four decade events (2016-12-14 .. 2017-05-03). The decade runs
therefore use the program's v2 SPY payload
(backtests/v2/data/SPY.json, Yahoo chart API, 2015-06-01 -> 2026-11-20,
read-only), closes = adjclose (total-return basis), opens scaled by
adjclose/close — the identical construction. Verified before use: that
payload reproduces SPY buy-hold to the cent on all three windows
(DECADE $367.80, CONT $313.62, VAL $187.77) AND the strategy finals
CONT $93.00 / VAL $90.26 through this sweep engine at daily cadence
(cross-check printed by this script). No data was patched.

PLACEBOS (the original v7 design, unchanged): per seed 1..20, each real
announcement is shifted by a random +5..+25 trading days (random.Random
(seed), chronological), redrawn until the pseudo window ends by the
window's last trading day and overlaps no real FOMC window (2016-2026)
and no already-placed pseudo window in the seed. Twins run through the
same cadence engine, same costs, same v9 chassis.
"""
import bisect, json, math, os, random, time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SPY_FULL = os.path.expanduser("~/workspace/stock-app/backtests/v2/data/SPY.json")

START_CASH = 100.0
COST_RATE = 0.0010
SELL_FEE = 0.01
DECADE = ("2016-11-21", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# Scheduled FOMC announcement days — identical census to the original
# engine (Federal Reserve published calendars; 2020 Mar 17-18 meeting
# cancelled -> not an event; emergency meetings excluded).
FOMC_ANNOUNCEMENTS = [
    "2016-12-14",
    "2017-02-01", "2017-03-15", "2017-05-03", "2017-06-14",
    "2017-07-26", "2017-09-20", "2017-11-01", "2017-12-13",
    "2018-01-31", "2018-03-21", "2018-05-02", "2018-06-13",
    "2018-08-01", "2018-09-26", "2018-11-08", "2018-12-19",
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19",
    "2019-07-31", "2019-09-18", "2019-10-30", "2019-12-11",
    "2020-01-29", "2020-04-29", "2020-06-10", "2020-07-29",
    "2020-09-16", "2020-11-05", "2020-12-16",
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16",
    "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15",
    "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17",
    "2026-07-29", "2026-09-16", "2026-10-28",
]


def load_bars(path):
    with open(path, "rb") as f:
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


BARS = load_bars(SPY_FULL)
DATES = [b["d"] for b in BARS]
IDX = {d: i for i, d in enumerate(DATES)}
BAR = {b["d"]: b for b in BARS}


def spy_buyhold(start, end):
    days = [d for d in DATES if start <= d <= end]
    first, last = days[0], days[-1]
    o = BAR[first]["o"]
    sh = (START_CASH / 1.001) / o
    buy_cost = START_CASH - sh * o
    val = sh * BAR[last]["c"]
    sell_cost = val * 0.001 + 0.01
    return round(val - sell_cost, 2)


def cadence_dates(cad, days):
    if cad == "daily":
        return set(days)
    out, seen = [], set()
    for d in days:
        y, m = int(d[:4]), int(d[5:7])
        iso = date.fromisoformat(d).isocalendar()
        if cad == "weekly":
            key = (iso[0], iso[1])
        elif cad == "monthly":
            key = (y, m)
        elif cad == "quarterly":
            key = (y, (m - 1) // 3)
        elif cad == "semiannual":
            key = (y, (m - 1) // 6)
        elif cad == "annual":
            key = (y,)
        else:
            key = None
        if key not in seen:
            seen.add(key)
            out.append(d)
    if cad == "biweekly":
        wk, seenw = [], set()
        for d in days:
            iso = date.fromisoformat(d).isocalendar()
            key = (iso[0], iso[1])
            if key not in seenw:
                seenw.add(key)
                wk.append(d)
        out = wk[::2]
    return set(out)


def run_cell(announcements, cad, start, end):
    """One $100 pot under the cadence exit rhythm + v9 protections."""
    days = [d for d in DATES if start <= d <= end]
    day_set = set(days)
    cads = cadence_dates(cad, days)
    cad_sorted = sorted(cads)

    def exit_date(ann):
        i = bisect.bisect_left(cad_sorted, ann)
        return cad_sorted[i] if i < len(cad_sorted) else days[-1]

    # event plan: entry day (trading day before announcement) -> exit day
    plan = {}
    for a in announcements:
        if a not in IDX or a not in day_set:
            continue
        entry = DATES[IDX[a] - 1]
        if entry not in day_set:
            continue
        plan.setdefault(entry, []).append(
            {"announcement": a, "entry": entry, "exit": exit_date(a)})
    exits_by_day = {}
    all_events = [e for v in plan.values() for e in v]
    for e in all_events:
        exits_by_day.setdefault(e["exit"], []).append(e)

    cash = START_CASH
    shares = 0.0
    holding = None
    total_costs = 0.0
    orders = 0
    trades = []
    event_rows = []
    curve = []
    halts = []               # [{date, episode, close_value, floor}]
    restart_info = None
    episode = 1
    ep_start_cash = START_CASH
    floor = 0.85 * ep_start_cash
    eligible_from = None     # date string; in 90-day sit when set
    ended = False
    skipped_no_cash = 0
    skipped_sit = 0

    def sell_all(d, px, tag):
        nonlocal cash, shares, holding, total_costs, orders
        proceeds = shares * px
        cost = proceeds * COST_RATE + SELL_FEE
        cash = proceeds - cost
        total_costs += cost
        orders += 1
        trades.append([d, tag, round(proceeds, 2), round(cost, 4)])
        shares = 0.0
        holding = None
        return cost

    for d in days:
        if not ended:
            # 1) exits due today (cadence dates by construction)
            for e in list(exits_by_day.get(d, [])):
                if holding is not None and holding["announcement"] == e["announcement"]:
                    px = BAR[d]["c"]
                    pre = holding["pre_cash"]
                    entry_close = holding["entry_close"]
                    sell_all(d, px, "SELL")
                    gross = px / entry_close - 1.0
                    event_rows.append({
                        "announcement": e["announcement"],
                        "entry": e["entry"],
                        "scheduled_exit": e["announcement"],
                        "actual_exit": d,
                        "entry_close": round(entry_close, 4),
                        "gross_return_pct": round(gross * 100, 4),
                        "net_return_pct": round((cash / pre - 1.0) * 100, 4),
                        "pre_cash": round(pre, 2),
                        "post_cash": round(cash, 2),
                    })
            # 2) entries at today's close (event rule, not cadence-gated)
            for e in plan.get(d, []):
                if eligible_from is not None and d < eligible_from:
                    skipped_sit += 1
                    continue
                if shares > 0 or holding is not None:
                    skipped_no_cash += 1
                    continue
                if eligible_from is not None and episode == 1:
                    pass  # handled below at first actual entry
                if eligible_from is not None:
                    # restart takes effect at this entry
                    episode = 2
                    ep_start_cash = cash
                    floor = 0.85 * ep_start_cash
                    restart_info = {"date": d, "restart_cash": round(cash, 2),
                                    "episode2_floor": round(floor, 2),
                                    "event_announcement": e["announcement"]}
                    eligible_from = None
                px = BAR[d]["c"]
                buy_val = cash / (1.0 + COST_RATE)
                buy_cost = buy_val * COST_RATE
                shares = buy_val / px
                cash = 0.0
                total_costs += buy_cost
                orders += 1
                trades.append([d, "BUY", round(buy_val, 2), round(buy_cost, 4)])
                holding = {"announcement": e["announcement"], "entry": d,
                           "exit": e["exit"], "entry_close": px,
                           "pre_cash": buy_val + buy_cost}
                # fill entry_close on the event row when it completes
                e["_entry_close"] = px
            # fix event rows' entry_close from the plan records
            # (rows were appended in step 1 before _entry_close existed
            #  for that event in this loop's scope — patch from plan)
        value = cash + (shares * BAR[d]["c"] if shares else 0.0)
        # 3) floor check — cadence dates only
        if not ended and eligible_from is None and d in cads and value <= floor:
            halts.append({"date": d, "episode": episode,
                          "close_value": round(value, 2),
                          "floor": round(floor, 2)})
            if shares:
                sell_all(d, BAR[d]["c"], "SELL-HALT")
                value = cash
            if episode >= 2:
                ended = True
            else:
                eligible_from = (date.fromisoformat(d) + timedelta(days=90)).isoformat()
        curve.append([d, round(value if not (shares == 0.0) else cash, 2)])
    # end of window: liquidate any residual holding at the final close
    if shares:
        sell_all(days[-1], BAR[days[-1]]["c"], "SELL-END")
        curve[-1] = [days[-1], round(cash, 2)]
    # patch entry_close into event rows from plan records
    ec = {}
    for v in plan.values():
        for e in v:
            if "_entry_close" in e:
                ec[e["announcement"]] = e["_entry_close"]
    for r in event_rows:
        r["entry_close"] = round(ec[r["announcement"]], 4) if r["announcement"] in ec else None
        r.pop("entry_close_tmp", None)

    peak, maxdd = -1.0, 0.0
    for _d, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    years = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    final = round(cash, 2)
    gross = [r["gross_return_pct"] for r in event_rows]
    net = [r["net_return_pct"] for r in event_rows]
    return {
        "final": final,
        "cagr_pct": round(((final / START_CASH) ** (1.0 / years) - 1.0) * 100, 2) if final > 0 else -100.0,
        "max_dd_pct": round(maxdd * 100, 2),
        "costs": round(total_costs, 2),
        "orders": orders,
        "trades": trades,
        "halts": halts,
        "n_events_scheduled": len(all_events),
        "n_events_traded": len(event_rows),
        "skipped_no_cash": skipped_no_cash,
        "skipped_sit": skipped_sit,
        "restart": restart_info,
        "events": event_rows,
        "mean_event_gross_pct": round(sum(gross) / len(gross), 4) if gross else None,
        "mean_event_net_pct": round(sum(net) / len(net), 4) if net else None,
        # the instrument IS SPY, so SPY's return over each entry->exit
        # span equals the event's gross return by construction; the net
        # excess vs holding SPY over the same span is exactly the cost
        # drag (net - gross).
        "mean_net_excess_vs_spy_same_span_pct": round(
            sum(n - g for n, g in zip(net, gross)) / len(net), 4) if net else None,
        "equity_curve": curve,
    }


def holding_entry_close(e):
    return e.get("_entry_close", 0.0)


# --------------------------------------------------------------- placebo
REAL_WINDOWS = [(IDX[a] - 1, IDX[a]) for a in FOMC_ANNOUNCEMENTS if a in IDX]


def _overlaps(a_lo, a_hi, b_lo, b_hi):
    return a_lo <= b_hi and b_lo <= a_hi


def build_pseudo_calendar(real_dates, start, end, seed):
    rng = random.Random(seed)
    end_idx = max(IDX[d] for d in DATES if start <= d <= end)
    placed, pseudo = [], []
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
            raise RuntimeError(f"could not place pseudo event for {a} (seed {seed})")
    return sorted(pseudo)


def main():
    start, end = DECADE
    spy_dec = spy_buyhold(start, end)
    spy_cont = spy_buyhold("2019-01-02", "2026-11-20")
    spy_val = spy_buyhold("2023-01-03", "2026-11-20")
    print(f"SPY gates (full-span payload): DECADE=${spy_dec} CONT=${spy_cont} VAL=${spy_val}", flush=True)
    assert spy_dec == 367.80 and spy_cont == 313.62 and spy_val == 187.77, "SPY gate failed"

    # cross-check: daily cadence mechanics on CONT/VAL windows must
    # reproduce the original finals through this engine (original form
    # = plain floor, no restart needed since floor never fired there;
    # this engine's cadence-date floor at daily = daily floor).
    for name, (ws, we), pub in [("CONT", ("2019-01-01", "2026-11-20"), 93.00),
                                ("VAL", ("2023-01-01", "2026-11-20"), 90.26)]:
        evs = [a for a in FOMC_ANNOUNCEMENTS if ws <= a <= we]
        r = run_cell(evs, "daily", ws, we)
        print(f"CROSSCHECK {name}: daily-cadence final=${r['final']} published=${pub} "
              f"events={r['n_events_traded']} halts={r['halts']}", flush=True)
        assert r["final"] == pub, f"{name} cross-check FAILED"

    real_decade = [a for a in FOMC_ANNOUNCEMENTS if start <= a <= end]
    print(f"DECADE events: {len(real_decade)}", flush=True)

    cells_summary = {}
    for cad in CADENCES:
        r = run_cell(real_decade, cad, start, end)
        # placebos: original shifted-calendar twins, same cadence engine
        twin_finals, twin_rows = [], []
        for seed in range(1, 21):
            pseudo = build_pseudo_calendar(real_decade, start, end, seed)
            tr = run_cell(pseudo, cad, start, end)
            twin_finals.append(tr["final"])
            twin_rows.append({"seed": seed, "final": tr["final"],
                              "halts": [h["date"] for h in tr["halts"]],
                              "restart": bool(tr["restart"]),
                              "announcements": pseudo})
        beaten = sum(1 for f in twin_finals if f < r["final"])
        cell = {
            "cadence": cad,
            "window": [start, end],
            "final": r["final"],
            "cagr_pct": r["cagr_pct"],
            "max_dd_pct": r["max_dd_pct"],
            "costs": r["costs"],
            "orders": r["orders"],
            "halts": r["halts"],
            "restart": r["restart"],
            "second_halt": len(r["halts"]) >= 2,
            "n_events_scheduled": r["n_events_scheduled"],
            "n_events_traded": r["n_events_traded"],
            "skipped_no_cash": r["skipped_no_cash"],
            "skipped_sit": r["skipped_sit"],
            "mean_event_gross_pct": r["mean_event_gross_pct"],
            "mean_event_net_pct": r["mean_event_net_pct"],
            "mean_net_excess_vs_spy_same_span_pct": r["mean_net_excess_vs_spy_same_span_pct"],
            "events": r["events"],
            "trades": r["trades"],
            "equity_curve": r["equity_curve"],
            "placebo_beaten": beaten,
            "placebo_twin_finals": twin_finals,
            "placebo_twins": twin_rows,
            "placebo_note": ("original v7 shifted-calendar twins: each real announcement "
                             "shifted +5..+25 trading days (seeds 1-20, redrawn to avoid "
                             "real/pseudo window overlap), same cadence exit rhythm, "
                             "costs and v9 chassis"),
        }
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell, f, indent=1)
        cells_summary[cad] = {
            "final": r["final"], "cagr_pct": r["cagr_pct"],
            "max_dd_pct": r["max_dd_pct"], "halts": len(r["halts"]),
            "restart": bool(r["restart"]), "second_halt": len(r["halts"]) >= 2,
            "costs": r["costs"], "orders": r["orders"],
            "placebo_beaten": beaten,
            "placebo_note": cell["placebo_note"],
        }
        print(f"{cad}: final=${r['final']} CAGR={r['cagr_pct']}% DD={r['max_dd_pct']}% "
              f"costs=${r['costs']} orders={r['orders']} halts={r['halts']} "
              f"restart={r['restart']} traded={r['n_events_traded']}/{r['n_events_scheduled']} "
              f"skip_cash={r['skipped_no_cash']} skip_sit={r['skipped_sit']} "
              f"mean_net/event={r['mean_event_net_pct']}% placebo_beaten={beaten}/20",
              flush=True)

    money = [c for c in CADENCES
             if cells_summary[c]["final"] > spy_dec and cells_summary[c]["placebo_beaten"] > 10]
    results = {
        "slug": "re-fomc-drift",
        "area": "Event strategies / timers, allocators & overlays (W8): calendar-event — pre-FOMC announcement drift (Lucca & Moench), SPY only, event-to-event with capital deployed exactly per the published rule",
        "native_cadence": "event-driven",
        "original_cadence_foreign": False,
        "cadence_note": ("Native form is event-driven with exit at the announcement-day close "
                         "(= daily review rhythm). The original program test ran that native "
                         "form — not foreign. Sweep: event entries stay exactly as published "
                         "at every cadence; cadence governs only the review/exit rhythm "
                         "(scheduled exit executes at the first cadence date on/after the "
                         "announcement day; floor checked on cadence dates only)."),
        "integrity": {
            "status": "reproduced",
            "original_finals": {"continuous": 93.00, "validation": 90.26,
                                "spy_gate": {"continuous": 313.62, "validation": 187.77},
                                "stress_2x_costs": {"continuous": 84.00, "validation": 84.61}},
            "reproduced_finals": {"continuous": 93.00, "validation": 90.26,
                                   "spy_gate": {"continuous": 313.62, "validation": 187.77},
                                   "stress_2x_costs": {"continuous": 84.00, "validation": 84.61}},
            "notes": ("Unmodified original v7 engine run in this folder (integrity_original.py, "
                      "integrity_run.log, integrity-results.json): CONT $93.00 / VAL $90.26 to "
                      "the cent, floor never fired (worst closes $92.79 / $90.05, no-floor "
                      "finals identical), placebos beaten 11/20 CONT and 3/20 VAL, 2x-cost "
                      "stress finals $84.00 (halted 2026-06-17) / $84.61 (halted 2026-09-16) "
                      "— stress is a sensitivity check, not the verdict run. Sweep engine "
                      "cross-check at daily cadence on the full-span payload also reproduces "
                      "CONT $93.00 / VAL $90.26 exactly."),
        },
        "data_note": ("Original v4 SPY cache starts 2017-06-01 and cannot cover the first four "
                      "decade events (2016-12-14, 2017-02-01, 2017-03-15, 2017-05-03). Decade "
                      "runs use the program's v2 SPY payload (backtests/v2/data/SPY.json, "
                      "Yahoo chart API, 2015-06-01->2026-11-20, read-only), same adjclose "
                      "construction; it reproduces SPY buy-hold to the cent on DECADE "
                      "($367.80), CONT ($313.62) and VAL ($187.77) and the strategy finals "
                      "CONT/VAL. No data patched; no events invented or backfilled — all 79 "
                      "scheduled announcements in the decade range are in the original census."),
        "decade_spy_final": spy_dec,
        "decade_window": [start, end],
        "cells": cells_summary,
        "money_cadences": money,
        "verdict_area": "NO GROUND" if not money else "REAL BUT SMALL",
        "verdict_change": ("none — the original program verdict (NOT PROMOTED / tested and "
                           "failed) stands at every cadence" if not money else
                           "see RESULTS.md"),
    }
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1)
    print(f"MONEY CADENCES: {money}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
