#!/usr/bin/env python3
"""
GAP TEST A-7 — STOCK-SPLIT ANNOUNCEMENT DRIFT (Ikenberry, Rankine &
Stice 1996) — Terry's AI stock app. Simulation only. NO parameter
tuning: the frozen spec from research/v7-completeness/missing-families.md
(Table A, item A-7) is run ONCE, as written, and judged against the
promoted champion's published numbers.

THE FAMILY AS PUBLISHED: Ikenberry, Rankine & Stice, "What Do Stock
Splits Really Signal?", Journal of Financial and Quantitative Analysis
31(3), 357-375 (1996); confirmed by Desai & Jain (1997), Journal of
Business: firms announcing forward stock splits of 2-for-1 or larger
earn ~+3.4% around the announcement and ~+7.9% excess return over the
following year — the market underreacts to the signal the split sends.

THE FROZEN SPEC (missing-families.md, Table A, A-7): event form, same
portfolio rules as A-6 (dividend-initiation drift), which itself adopts
the spin-off precedent (queue #6) for event mechanics:
  - Event = a pond name announcing a forward split >= 2-for-1, dated
    from the announcement filing (EDGAR 8-K / press release).
  - Enter the next trading day after the announcement; hold 12 months;
    equal weight across concurrent events (cap 5); cash otherwise.

FORCED READINGS (stated here, before any result):
  1. ENTRY PRICE: the spec says "enter next day" without naming open
     or close. The program's one completed event-form precedent
     (spin-offs, queue #6) enters at a CLOSE, so entry is at the close
     of the first trading day strictly after the announcement date.
     This forfeits the announcement-day and entry-day moves — the
     conservative reading, and the program's standing event convention.
  2. SLICING: per the spin-off precedent, each entry is funded with
     1/5 of the pot's value marked at that day's closes before the
     trade (at most five concurrent positions by construction; the
     cap never binds here — maximum concurrency is 2). If cash is
     short of the target, existing positions are sold pro-rata by
     value at that day's close to raise it (sell costs apply).
  3. EXIT: at the close of the first trading day on or after the
     12-month anniversary of entry, or at the window-end close if the
     anniversary falls later (no ranked or placebo hold reaches the
     window end here — the last, NFLX, exits 2026-11-02).
  4. WINDOW MEMBERSHIP: an event belongs to a window if its
     ANNOUNCEMENT date falls inside the window. A pot cannot enter a
     trade whose entry day precedes its own start, and entering
     mid-hold at the window open would not be the published event
     trade. (This excludes GOOGL from the validation pot: announced
     2022-02-01, its hold overlaps Jan-Feb 2023 but began in 2022.)
  5. ANNOUNCEMENT DATE = the date the split was publicly announced,
     as dated in the filing itself (press-release date / 8-K event
     date), which for WMT (press release dated Jan 30, 2024, 8-K
     filed Jan 31) is one day earlier than the EDGAR filing stamp.
     All five announcements were made after the close or on the
     filing date; the entry rule (next trading day's close) is
     unaffected by intraday timing.
  6. PLACEBO: for each seed 1..20, each event keeps its own entry and
     exit dates and slicing, but the name bought is a uniform random
     draw from the other 29 pond names (seeded RNG). Positions are
     keyed by event, so a seed may hold two slices of one name.

EVENT CENSUS (built before any price was read for grading):
  Method: (a) mechanical sweep of the split events recorded in the
  program's cached Yahoo chart payloads (fetched with events=div,split)
  for all 30 pond names, full cached range 2017-06 -> 2026-11; (b)
  every candidate's announcement verified in its EDGAR 8-K / press
  release exhibit (text pulled and quoted in the report).
  Result: exactly FIVE forward splits >= 2-for-1 by pond names with
  announcements in 2019-01-02 -> 2026-11-20 — AAPL 4:1 (announced
  2020-07-30), GOOGL 20:1 (2022-02-01), AMZN 20:1 (2022-03-09),
  WMT 3:1 (2024-01-30), NFLX 10:1 (2025-10-30). The sweep also shows
  ZERO pond splits effective anywhere in 2017-06 -> 2019-12, so no
  pre-window straggler exists. Fractional Yahoo "split" records
  (PFE 1054:1000, T 1324:1000, IBM 1046:1000, MMM 1196:1000, GE
  104:100 / 1281:1000 / 1253:1000) are spin-off distribution
  adjustments, not split announcements, and GE's 1:8 (2021-08-02) is
  a REVERSE split — all excluded by the >= 2-for-1 forward definition,
  by category, before any result.

CHASSIS (program standard): $100 pot, costs 0.10%/side + $0.01/sell,
plain -15% floor ($85; close at/below -> liquidate at next open, run
ends), windows CONTINUOUS 2019-01-02 -> 2026-11-20 and VALIDATION
2023-01-03 -> 2026-11-20. Judged vs SPY (published nets $313.62 /
$187.77) and the champion (value + momentum: $544.47 / $288.05),
both replication-checked in-run before any variant number is taken.
"""
import importlib.util
import json
import os
import random
import time
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
FULL = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")

# ------------------------------------------------------------- event census
# (ticker, ratio, announcement date, effective date per Yahoo split
#  record, filing basis). All verified from EDGAR before prices were read.
EVENTS = [
    {"ticker": "AAPL", "ratio": "4-for-1", "announced": "2020-07-30",
     "effective": "2020-08-31",
     "basis": "AAPL 8-K filed 2020-07-30 (acc. 0000320193-20-000060), "
              "Ex-99.1 Q3 FY2020 press release: 'The Board of Directors "
              "has also approved a four-for-one stock split... trading "
              "will begin on a split-adjusted basis on August 31, 2020.'"},
    {"ticker": "GOOGL", "ratio": "20-for-1", "announced": "2022-02-01",
     "effective": "2022-07-18",
     "basis": "Alphabet 8-K filed 2022-02-01 (acc. 0001652044-22-000015), "
              "Ex-99.1 Q4 2021 press release: 'Alphabet today announced "
              "that the Board of Directors had approved and declared a "
              "20-for-one stock split... in the form of a one-time "
              "special stock dividend.'"},
    {"ticker": "AMZN", "ratio": "20-for-1", "announced": "2022-03-09",
     "effective": "2022-06-06",
     "basis": "AMZN 8-K filed 2022-03-09 (acc. 0001018724-22-000009), "
              "Item 8.01: 'On March 9, 2022, the Board of Directors of "
              "Amazon.com, Inc. approved a 20-for-1 split of the "
              "Company's common stock... Trading is expected to begin "
              "on a split-adjusted basis on June 6, 2022.'"},
    {"ticker": "WMT", "ratio": "3-for-1", "announced": "2024-01-30",
     "effective": "2024-02-26",
     "basis": "WMT 8-K filed 2024-01-31 (acc. 0000104169-24-000004), "
              "Ex-99.1 press release dated Jan. 30, 2024: 'Walmart "
              "Announces 3-for-1 Stock Split... it will conduct a split "
              "of its outstanding shares of common stock at a ratio "
              "of 3:1.'"},
    {"ticker": "NFLX", "ratio": "10-for-1", "announced": "2025-10-30",
     "effective": "2025-11-17",
     "basis": "NFLX 8-K filed 2025-10-30 (acc. 0001065280-25-000407), "
              "Ex-99.1: 'Netflix Announces Ten-For-One Stock Split... "
              "its Board of Directors has approved a ten-for-one "
              "forward stock split of the Company's common stock.'"},
]

EXCLUDED = [
    {"ticker": "GE", "ratio": "1-for-8", "date": "2021-08-02",
     "why": "REVERSE split — the published event is a forward split "
            ">= 2-for-1."},
    {"ticker": "PFE/T/IBM/MMM/GE", "ratio": "fractional (e.g. 1054:1000)",
     "date": "2020-11-17 / 2022-04-11 / 2021-11-04 / 2024-04-01 / "
             "2019-02-26, 2023-01-04, 2024-04-02",
     "why": "Yahoo records spin-off distributions (VTRS, WBD, KD, "
            "SOLV, GEHC, GEV and a 2019 GE adjustment) as fractional "
            "'splits'. No split was announced; these are the spin-off "
            "family's events (queue #6), not A-7's."},
]


def add_months(dstr, months):
    y, m, d = int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])
    m2 = m + months
    y += (m2 - 1) // 12
    m = (m2 - 1) % 12 + 1
    # clamp day to month length
    if m == 12:
        nxt = _date(y + 1, 1, 1)
    else:
        nxt = _date(y, m + 1, 1)
    last_day = (nxt - _date(y, m, 1)).days
    return _date(y, m, min(d, last_day)).isoformat()


def build_champion_inputs():
    ciks = E.get_ciks()
    overrides = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = overrides.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributable"
                         "ToNoncontrollingInterest", prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding",
                         prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding",
                         prio=2) +
            E.pit_series(facts, "us-gaap",
                         "WeightedAverageNumberOfSharesOutstandingBasic",
                         prio=1))
        time.sleep(0.05)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return E.PriceBook(bars), equity_rows, shares_rows


def schedule_events(pb, events, start, end):
    """Attach entry/exit trading days for events announced in-window."""
    days = [d for d in pb.dates if start <= d <= end]
    out = []
    for ev in events:
        if not (start <= ev["announced"] <= end):
            continue
        entry = next((d for d in days if d > ev["announced"]), None)
        anniv = add_months(entry, 12)
        exit_d = next((d for d in days if d >= anniv), None)
        out.append({**ev, "entry": entry,
                    "exit": exit_d if exit_d is not None else end})
    return out


def run_event_pot(pb, sched, start, end, names, label=""):
    """Event pot per the slicing rule in the header. `sched` is the
    scheduled event list; `names[i]` is the ticker bought for event i
    (the event's own name for the ranked run, a random pond name for a
    placebo seed). Positions are keyed by event index."""
    cash = START_CASH
    positions = {}          # event idx -> (ticker, shares)
    trades = []
    total_costs = 0.0
    halt_info = None
    curve = []
    days = [d for d in pb.dates if start <= d <= end]

    entries = {}
    for i, ev in enumerate(sched):
        entries.setdefault(ev["entry"], []).append(i)
    exit_days = {}
    for i, ev in enumerate(sched):
        exit_days.setdefault(ev["exit"], []).append(i)

    def close_of(t, d):
        return pb.close_on_or_before(t, d)

    def pot_close(d):
        v = cash
        for t, sh in positions.values():
            c = close_of(t, d)
            if c:
                v += sh * c
        return v

    pending_halt = False
    for di, d in enumerate(days):
        if pending_halt:
            for i in list(positions):
                t, sh = positions[i]
                nd, o = pb.next_open(t, days[di - 1])
                if o is None:
                    continue
                val = sh * o
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((nd, t, "SELL-HALT", sh, o, val, c))
                del positions[i]
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": days[di - 1],
                    "halt_info": halt_info, "curve": curve}
        # scheduled exits first (close), then entries (close)
        for i in exit_days.get(d, []):
            if i not in positions:
                continue
            t, sh = positions[i]
            px = close_of(t, d)
            val = sh * px
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((d, t, "SELL-EXIT", sh, px, val, c))
            del positions[i]
        for i in entries.get(d, []):
            t = names[i]
            marked = pot_close(d)
            target = marked / 5.0
            if cash < target * 1.001 and positions:
                need = target * 1.001 - cash
                tot_val = sum(sh * close_of(tt, d)
                              for tt, sh in positions.values())
                for j in list(positions):
                    if need <= 0:
                        break
                    tt, sh = positions[j]
                    px = close_of(tt, d)
                    cur = sh * px
                    sell_val = min(cur, need * (cur / tot_val) * 1.02)
                    if sell_val <= 0.005:
                        continue
                    ssh = sell_val / px
                    c = sell_val * 0.001 + 0.01
                    cash += sell_val - c
                    total_costs += c
                    trades.append((d, tt, "SELL-FUND", ssh, px, sell_val, c))
                    if sh - ssh < 1e-9:
                        del positions[j]
                    else:
                        positions[j] = (tt, sh - ssh)
                    need -= sell_val
            px = close_of(t, d)
            buy_val = min(target, cash / 1.001)
            if buy_val > 0.005 and px:
                sh = buy_val / px
                c = buy_val * 0.001
                cash -= buy_val + c
                total_costs += c
                if i in positions:  # cannot happen (one entry per event)
                    tt, old = positions[i]
                    positions[i] = (tt, old + sh)
                else:
                    positions[i] = (t, sh)
                trades.append((d, t, "BUY", sh, px, buy_val, c))
        v = pot_close(d)
        curve.append((d, v))
        if v <= FLOOR0 and di < len(days) - 1:
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": FLOOR0}
            pending_halt = True
    # window end: liquidate at final close (program SELL-END convention)
    last = days[-1]
    for i in list(positions):
        t, sh = positions[i]
        px = close_of(t, last)
        if px:
            val = sh * px
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((last, t, "SELL-END", sh, px, val, c))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "halt_info": None,
            "curve": curve}


def standalone(pb, ticker, entry, exit_d, start_cash=START_CASH):
    """$100 in at the entry close, out at the exit close, program costs.
    Used for each event name AND for SPY over the identical dates."""
    pe = pb.close_on_or_before(ticker, entry)
    px = pb.close_on_or_before(ticker, exit_d)
    buy_val = start_cash / 1.001
    buy_cost = start_cash - buy_val
    sh = buy_val / pe
    val = sh * px
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost, pe, px


def curve_stats(curve):
    worst = min(v for _, v in curve)
    peak, maxdd = curve[0][1], 0.0
    for _, v in curve:
        peak = max(peak, v)
        maxdd = min(maxdd, v / peak - 1.0)
    invested_days = 0
    return {"worst_close": round(worst, 2),
            "worst_close_above_floor": round(worst - FLOOR0, 2),
            "max_drawdown_pct": round(maxdd * 100, 2)}


def summarize(r):
    return {"final": round(r["final"], 2),
            "return_pct": round((r["final"] / START_CASH - 1) * 100, 2),
            "costs": round(r["costs"], 2),
            "n_trades": len(r["trades"]),
            "halted": r["halted"],
            "halt_info": r["halt_info"],
            **curve_stats(r["curve"])}


def main():
    out = {"strategy": "GAP A-7 STOCK-SPLIT ANNOUNCEMENT DRIFT "
                       "(Ikenberry, Rankine & Stice 1996): buy pond "
                       "names announcing forward splits >= 2-for-1 at "
                       "the close of the next trading day after the "
                       "announcement, 1/5-of-pot slices (cap 5 "
                       "concurrent), hold 12 months, plain -15% floor, "
                       "$100",
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0,
           "windows": {"FULL": FULL, "VALIDATION": VAL},
           "events": EVENTS, "excluded": EXCLUDED}

    # ---- (0) replication check: champion engine, published numbers
    pb, equity_rows, shares_rows = build_champion_inputs()
    rep = {}
    for tag, (ws, we), published in (("FULL", FULL, 544.47),
                                     ("VALIDATION", VAL, 288.05)):
        rb = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                       FLOOR0, LADDER, label=f"REPLICATION {tag}",
                       quiet=True)
        rep[tag] = {"final": round(rb["final"], 2), "published": published,
                    "match": round(rb["final"], 2) == published,
                    "halted": rb["halted"]}
        print(f"REPLICATION {tag}: champion=${rb['final']:,.2f} "
              f"published=${published:,.2f} match={rep[tag]['match']}",
              flush=True)
        if not rep[tag]["match"]:
            raise SystemExit("REPLICATION FAILED — variant numbers "
                             "untrusted")
    spy = {}
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        spy[tag] = round(s, 2)
    print(f"CONTROL SPY: FULL=${spy['FULL']:,.2f} (published $313.62) | "
          f"VALIDATION=${spy['VALIDATION']:,.2f} (published $187.77)",
          flush=True)
    out["replication_champion"] = rep
    out["spy_net"] = spy

    # ---- (1) ranked pots + placebos, both windows
    results = {}
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        sched = schedule_events(pb, EVENTS, ws, we)
        print(f"\n{tag}: {len(sched)} events in window", flush=True)
        for ev in sched:
            print(f"  {ev['ticker']} {ev['ratio']} announced "
                  f"{ev['announced']} -> entry {ev['entry']} @ "
                  f"${pb.close_on_or_before(ev['ticker'], ev['entry']):,.2f}"
                  f" -> exit {ev['exit']} @ "
                  f"${pb.close_on_or_before(ev['ticker'], ev['exit']):,.2f}",
                  flush=True)
        names = [ev["ticker"] for ev in sched]
        r = run_event_pot(pb, sched, ws, we, names, label=f"A7 {tag}")
        print(f"RANKED {tag}: final=${r['final']:,.2f} "
              f"costs=${r['costs']:,.2f} trades={len(r['trades'])} "
              f"halted={r['halted']}", flush=True)

        placebo_finals = []
        placebo_detail = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            pnames = [rng.choice([t for t in UNIVERSE
                                  if t != ev["ticker"]])
                      for ev in sched]
            pr = run_event_pot(pb, sched, ws, we, pnames,
                               label=f"A7 {tag} placebo {seed}")
            placebo_finals.append(round(pr["final"], 2))
            placebo_detail.append({"seed": seed, "names": pnames,
                                   "final": round(pr["final"], 2),
                                   "halted": pr["halted"]})
        sf = sorted(placebo_finals)
        med = (sf[9] + sf[10]) / 2 if len(sf) == 20 else sf[len(sf) // 2]
        beaten = sum(1 for f in placebo_finals if round(r["final"], 2) > f)
        print(f"PLACEBO {tag}: median=${med:,.2f} min=${sf[0]:,.2f} "
              f"max=${sf[-1]:,.2f} | ranked beats {beaten}/20", flush=True)

        # per-event standalone table (event name vs SPY, identical dates)
        standalone_rows = []
        for ev in sched:
            net, cst, pe, px = standalone(pb, ev["ticker"], ev["entry"],
                                          ev["exit"])
            snet, scst, spe, spx = standalone(pb, "SPY", ev["entry"],
                                              ev["exit"])
            standalone_rows.append(
                {"ticker": ev["ticker"], "ratio": ev["ratio"],
                 "announced": ev["announced"], "entry": ev["entry"],
                 "exit": ev["exit"], "entry_px": round(pe, 2),
                 "exit_px": round(px, 2), "net": round(net, 2),
                 "spy_net": round(snet, 2), "beat_spy": net > snet})
            print(f"  STANDALONE {ev['ticker']}: ${net:,.2f} vs SPY "
                  f"${snet:,.2f} -> {'BEAT' if net > snet else 'LOST'}",
                  flush=True)

        results[tag] = {
            "window": [ws, we], "n_events": len(sched),
            "schedule": [{"ticker": ev["ticker"], "ratio": ev["ratio"],
                          "announced": ev["announced"],
                          "effective": ev["effective"],
                          "entry": ev["entry"], "exit": ev["exit"]}
                         for ev in sched],
            "ranked": summarize(r),
            "ranked_trades": [
                {"date": d, "ticker": t, "side": s,
                 "shares": round(sh, 6), "px": round(px, 4),
                 "value": round(v, 2), "cost": round(c, 2)}
                for d, t, s, sh, px, v, c in r["trades"]],
            "placebo": {"finals": placebo_finals,
                        "median": round(med, 2), "min": sf[0],
                        "max": sf[-1], "ranked_beats": beaten,
                        "detail": placebo_detail},
            "standalone": standalone_rows,
            "spy_net": spy[tag],
            "champion_published": 544.47 if tag == "FULL" else 288.05}
    out["results"] = results

    with open(os.path.join(HERE, "gap-a7-split-drift-results.json"),
              "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("\nDONE", flush=True)


if __name__ == "__main__":
    main()
