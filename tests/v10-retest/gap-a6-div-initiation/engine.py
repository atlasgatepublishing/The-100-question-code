#!/usr/bin/env python3
"""
DIVIDEND-INITIATION DRIFT (Michaely, Thaler & Womack 1995) — gap test
A-6 from research/v7-completeness/missing-families.md (Table A).
Terry's AI stock app. Simulation only. NO parameter tuning: the frozen
spec below is run ONCE, as written, and judged against the promoted
champion's published numbers.

THE FAMILY AS PUBLISHED: Michaely, Thaler & Womack, "Price Reactions
to Dividend Initiations and Omissions: Overreaction or Drift?"
(Journal of Finance 50(2), 1995): firms that INITIATE a regular cash
dividend earn ~+3.4% around the announcement and then drift ~+7.5%
market-adjusted over the following 12 months. (Omissions drift ~-11%
— a short/avoid leg a long-only account cannot use as a position; it
is logged as an exclusion note below, never traded.)

THE FROZEN SPEC (missing-families.md, Table A, item A-6, verbatim in
substance): Event = a pond name announcing its first regular cash
dividend (or first in >= 5 years), dated from the announcement filing;
enter next trading day; hold 12 months; equal weight across
concurrent events (cap 5); cash otherwise. Pond = the champion's
honest top-30 as of Nov 2016. $100 pot, program costs (0.10%/side +
$0.01/sell), plain -15% floor, windows continuous 2019-01-02 ->
2026-11-20 and validation 2023-01-03 -> 2026-11-20, judged vs SPY
($313.62 / $187.77) and the champion ($544.47 / $288.05); placebo =
same event dates with random pond names, 20 seeds.

FORCED READINGS (stated here, before any result):
  R1 ENTRY PRICE: entry at the CLOSE of the next trading day after
     the announcement date — the spin-off precedent (queue #6, the
     spec's own governing precedent) enters at the close of the first
     session in which the event is fully public. Both announcements
     were after-close earnings releases, so the next session is the
     first full public session and its close is the conservative end
     of it. Consequence, accepted in advance: MTW's +3.4%
     announcement return is deliberately NOT captured; the pot buys
     only the 12-month drift, which is the claim under test.
  R2 SIZING: "equal weight across concurrent events (cap 5)" is run
     with the spin-off slicing rule verbatim — each entry is funded
     with 1/5 of the pot's marked value at that day's closes before
     the trade (at most five positions by construction; unfilled
     fifths stay in cash; if cash is short, existing positions are
     sold pro-rata by value at that close to raise it, sell costs
     apply). Buy value = min(target, cash / 1.001); buy cost 0.10%.
  R3 WINDOW MEMBERSHIP: a pot takes the events whose ENTRY date falls
     inside its window; both pots start flat in cash (champion
     chassis). Both qualifying entries (Feb/Apr 2024) fall inside
     BOTH windows, so the two pots place identical trades and are
     expected to finish identically — the continuous window adds
     only idle-cash years. Stated in advance, not discovered after.
  R4 EXIT: at the close of the first trading day on or after the
     12-month anniversary of entry, or at the window-end close if
     the anniversary is later (spin-off convention). Sell cost
     0.10% + $0.01. Window end liquidates any open position at the
     final close (champion SELL-END convention).
  R5 FLOOR: plain -15% ($85.00) on the whole pot, champion mechanics
     — a close at/below $85 liquidates everything at the next trading
     day's open and ends the run.
  R6 PLACEBO: for each seed 1..20, each event's name is replaced by a
     pond name drawn uniformly WITHOUT replacement (within the seed)
     from the 28 pond names that had no initiation event — identical
     entry/exit dates, slicing, costs and floor. The placebo answers:
     did the initiation pick the right stock, or would any pond stock
     bought on the same dates have done the same?
  R7 PRICE TAPE: the program's dividend-adjusted closes (Yahoo
     adjclose, the champion engine's exact bar construction) — a
     total-return tape, so the initiated dividend itself is inside
     the held name's price path, not credited as separate cash. This
     is the house convention for the champion and the spin-off test,
     and it makes the SPY comparison apples-to-apples.
  R8 "REGULAR" AND THE 5-YEAR GAP: "regular" = a declared recurring
     cash-dividend program (both qualifying filings state a quarterly
     program going forward). A one-off special dividend would not
     qualify; no pond name's first in-window payment was a special.
     The >=5-year gap is measured ex-date to ex-date on the payment
     tape (announcement-to-announcement gives the same ruling for
     the one near-miss, DIS: ~3.99 years either way).

THE EVENT CENSUS (verified before any price was read for trading):
Method: the complete dividend payment tape (Yahoo dividend events,
2005-01-01 -> 2026-11-20, cached in ./data) for all 30 pond names —
an initiation that pays MUST appear on the tape as a first ex-date,
either first-ever or after a >=5-year silence, so the tape is the
complete candidate list by construction; EDGAR then dates and
confirms each candidate from the issuer's own filing. (EDGAR
full-text search returned HTTP 403 from this environment; the census
does not depend on it — the same standard the spin-off census
stated: the census rests on the underlying records read directly,
not on mention counts.)
  - QUALIFYING (2):
    * META — first dividend EVER. Tape: no dividend from its 2012
      IPO through 2023; first ex-date 2024-02-21 ($0.50). Filing:
      8-K filed 2024-02-01 (accession 0001326801-24-000010), Ex-99.1
      headline "Meta Reports Fourth Quarter and Full Year 2023
      Results; Initiates Quarterly Dividend" — "declared a cash
      dividend of $0.50 per share... payable on March 26, 2024 to
      stockholders of record as of... February 22, 2024. We intend
      to pay a cash dividend on a quarterly basis going forward."
      Announcement 2024-02-01 -> entry 2024-02-02 (close).
    * GOOGL — first dividend EVER. Tape: no dividend from its 2004
      IPO through 2023; first ex-date 2024-06-10 ($0.20). Filing:
      8-K filed 2024-04-25 (accession 0001652044-24-000047), Ex-99.1
      "Dividend Program: Alphabet's Board of Directors today
      approved the initiation of a cash dividend program, and
      declared a cash dividend of $0.20 per share that will be paid
      on June 17, 2024, to stockholders of record as of June 10,
      2024... The company intends to pay quarterly cash dividends
      in the future." Announcement 2024-04-25 -> entry 2024-04-26.
  - NEAR-MISS, EXCLUDED BY THE SPEC'S OWN THRESHOLD (1):
    * DIS — resumption, but the silence was 3.99 years, not >= 5.
      Tape: semi-annual payer through ex-date 2019-12-13 ($0.88),
      suspended in 2020, first post-suspension ex-date 2023-12-08
      ($0.30) — a 3.99-year gap. Filing confirmation: DIS 10-Q
      filed 2024-02-07 — "On November 30, 2023, the Board of
      Directors declared a cash dividend of $0.30 per share...
      paid in January 2024 to shareholders of record as of
      December 11, 2023." Under the frozen ">= 5 years" line this
      is NOT an event. No result was consulted; the line excludes it.
  - OMISSION NOTE (logged, not traded, per spec): INTC's tape stops
    after ex-date 2024-08-07 — a suspension. MTW's omission leg is
    the family's short/avoid side; a long-only pot cannot hold it
    as a position, and the ranked pot never held INTC.
  - NO EVENT: AMZN, BRK-B, NFLX never paid a dividend in the tape
    (2005-2026; for META/GOOGL-style completeness: none ever).
    The remaining 24 pond names were already regular payers before
    the census window opened (2016-11-21) and paid continuously
    through it — the largest in-window ex-date gap among them is
    0.34 years (GE's quarterly cadence), so none can be a
    "first in >= 5 years" event.
  Event count honesty: TWO qualifying events in ten years on this
  pond, both in the validation era, none in 2016-2022. The family
  is graded on exactly that supply — no more, no less.

Data: Yahoo dividend tapes + EDGAR filings (census; cached in
./data) + the champion engine's price caches (v4, read-only) for
prices. Champion inputs reused read-only from the v4 caches.
"""
import calendar
import importlib.util
import json
import os
import random
import time
import urllib.request
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
CENSUS_WINDOW = ("2016-11-21", "2026-11-20")
HOLD_MONTHS = 12

# ------------------------------------------------------------- event census
# (name, announcement date (EDGAR filing date), basis). Entry/exit are
# derived mechanically: entry = close of the next trading day after
# the announcement; exit = close of the first trading day on/after
# entry + 12 months.
EVENTS = [
    {"name": "META", "announce": "2024-02-01",
     "basis": "First dividend ever (tape: none 2012 IPO -> 2023; first "
              "ex-date 2024-02-21, $0.50). META 8-K filed 2024-02-01 "
              "(acc. 0001326801-24-000010), Ex-99.1: 'Initiates "
              "Quarterly Dividend' — $0.50 declared, payable 2024-03-26, "
              "record 2024-02-22, 'intend to pay a cash dividend on a "
              "quarterly basis going forward.'"},
    {"name": "GOOGL", "announce": "2024-04-25",
     "basis": "First dividend ever (tape: none 2004 IPO -> 2023; first "
              "ex-date 2024-06-10, $0.20). Alphabet 8-K filed "
              "2024-04-25 (acc. 0001652044-24-000047), Ex-99.1: 'Board "
              "of Directors today approved the initiation of a cash "
              "dividend program' — $0.20 declared, payable 2024-06-17, "
              "record 2024-06-10, 'intends to pay quarterly cash "
              "dividends in the future.'"},
]

NEAR_MISSES = [
    {"name": "DIS", "what": "Resumption after suspension, gap 3.99 "
     "years < the spec's >= 5 years. Tape: last pre-suspension ex-date "
     "2019-12-13 ($0.88 semi-annual); first post-suspension ex-date "
     "2023-12-08 ($0.30). DIS 10-Q filed 2024-02-07: board declared "
     "$0.30 on 2023-11-30, record 2023-12-11, paid Jan 2024. Excluded "
     "by the frozen threshold; no result consulted."},
    {"name": "INTC", "what": "OMISSION note (logged, not traded): tape "
     "stops after ex-date 2024-08-07 — a suspension. MTW's omission "
     "drift is a short/avoid leg; a long-only pot cannot hold it."},
    {"name": "AMZN/BRK-B/NFLX", "what": "Never paid any dividend on "
     "the 2005-2026 tape. No initiation occurred."},
    {"name": "24 continuous payers", "what": "AAPL MSFT JPM XOM JNJ PG "
     "V WMT HD BAC CVX PFE VZ T INTC CSCO GE IBM MMM UNH MA KO PEP "
     "WFC: regular payers before 2016-11-21, paid continuously "
     "through the window; largest in-window ex-date gap 0.34y (GE). "
     "None can be a first-ever or first-in->=5-years event."},
]


# ------------------------------------------------------------------ census
def _fetch(url, path, headers=None, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(
                url, headers=headers or {"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            with open(path, "wb") as f:
                f.write(blob)
            return blob
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")


def dividend_tape(ticker):
    """Full dividend ex-date tape (Yahoo events), 2005 -> 2026."""
    path = os.path.join(DATA, f"div_{ticker}.json")
    t1 = calendar.timegm(time.strptime("2005-01-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2026-11-21", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1mo&events=div,split")
    j = json.loads(_fetch(url, path, headers={"User-Agent": "Mozilla/5.0"}))
    res = j["chart"]["result"][0]
    divs = (res.get("events") or {}).get("dividends") or {}
    rows = sorted((time.strftime("%Y-%m-%d", time.gmtime(v["date"])),
                   v["amount"]) for v in divs.values())
    return rows


def _ord(dstr):
    return _date(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()


def run_census():
    """Recompute the census from the tapes and ASSERT it reproduces the
    verified result: exactly {META, GOOGL} qualify; DIS's gap < 5y."""
    table = {}
    qualifying = []
    for t in UNIVERSE:
        rows = dividend_tape(t)
        if not rows:
            table[t] = {"n_payments": 0, "status": "never paid"}
            continue
        first, last = rows[0], rows[-1]
        max_gap_inwin = None
        for i in range(1, len(rows)):
            if CENSUS_WINDOW[0] <= rows[i][0] <= CENSUS_WINDOW[1]:
                gap = (_ord(rows[i][0]) - _ord(rows[i - 1][0])) / 365.25
                if max_gap_inwin is None or gap > max_gap_inwin[0]:
                    max_gap_inwin = (round(gap, 2), rows[i - 1][0],
                                     rows[i][0])
        is_first_ever_inwin = CENSUS_WINDOW[0] <= first[0] <= CENSUS_WINDOW[1]
        is_resumption = (max_gap_inwin is not None
                         and max_gap_inwin[0] >= 5.0)
        status = "payer"
        if is_first_ever_inwin:
            status = "FIRST-EVER in window"
            qualifying.append(t)
        elif is_resumption:
            status = "RESUMPTION after >=5y in window"
            qualifying.append(t)
        table[t] = {"n_payments": len(rows), "first_ex": first[0],
                    "first_amt": first[1], "last_ex": last[0],
                    "max_gap_ending_in_window": max_gap_inwin,
                    "status": status}
        print(f"CENSUS {t}: n={len(rows)} first={first[0]} "
              f"last={last[0]} maxgap-inwin={max_gap_inwin} "
              f"status={status}", flush=True)
    assert sorted(qualifying) == ["GOOGL", "META"], \
        f"census mismatch: {qualifying}"
    dis_gap = table["DIS"]["max_gap_ending_in_window"][0]
    assert dis_gap < 5.0, f"DIS gap {dis_gap} would qualify!"
    print(f"CENSUS ASSERTED: qualifying={sorted(qualifying)}; "
          f"DIS gap={dis_gap}y < 5y (excluded)", flush=True)
    return table


# ------------------------------------------------------------------ engine
def add_months(dstr, months):
    y, m, d = int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])
    m2 = m + months
    y += (m2 - 1) // 12
    m = (m2 - 1) % 12 + 1
    mdays = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0))
             else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    d = min(d, mdays)
    return f"{y:04d}-{m:02d}-{d:02d}"


def derive_schedule(pb, events):
    """entry = first trading day strictly after the announcement;
    exit = first trading day on/after entry + HOLD_MONTHS."""
    out = []
    for ev in events:
        entry = next(d for d in pb.dates if d > ev["announce"])
        anniv = add_months(entry, HOLD_MONTHS)
        exit_d = next((d for d in pb.dates if d >= anniv), None)
        out.append({**ev, "entry": entry, "exit": exit_d})
    return out


def run_event_pot(pb, sched, start, end, start_cash=START_CASH,
                  floor0=FLOOR0, label=""):
    """Event pot per forced readings R1-R5. sched entries carry the
    (possibly placebo-substituted) name plus entry/exit dates."""
    cash = start_cash
    positions = {}          # name -> shares
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    days = [d for d in pb.dates if start <= d <= end]

    entries = {}
    for ev in sched:
        if start <= ev["entry"] <= end:
            entries.setdefault(ev["entry"], []).append(ev)
    exit_days = {}
    for ev in sched:
        if ev["exit"] is not None and start <= ev["exit"] <= end:
            exit_days.setdefault(ev["exit"], []).append(ev["name"])

    def close_of(t, d):
        return pb.close_on_or_before(t, d)

    def pot_close(d):
        v = cash
        for t, sh in positions.items():
            c = close_of(t, d)
            if c:
                v += sh * c
        return v

    pending_halt = False
    for di, d in enumerate(days):
        if pending_halt:
            for t in list(positions):
                nd, o = pb.next_open(t, days[di - 1])
                if o is None:
                    continue
                val = positions[t] * o
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((nd, t, "SELL-HALT", positions[t], o, val, c))
                del positions[t]
            halted = days[di - 1]
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted,
                    "halt_info": halt_info, "curve": curve}
        for name in exit_days.get(d, []):
            if name not in positions:
                continue
            px = close_of(name, d)
            val = positions[name] * px
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((d, name, "SELL-EXIT", positions[name], px,
                           val, c))
            del positions[name]
        for ev in entries.get(d, []):
            name = ev["name"]
            marked = pot_close(d)
            target = marked / 5.0
            if cash < target * 1.001 and positions:
                need = target * 1.001 - cash
                tot_val = sum(positions[t] * close_of(t, d)
                              for t in positions)
                for t in list(positions):
                    if need <= 0:
                        break
                    px = close_of(t, d)
                    cur = positions[t] * px
                    sell_val = min(cur, need * (cur / tot_val) * 1.02)
                    if sell_val <= 0.005:
                        continue
                    sh = sell_val / px
                    c = sell_val * 0.001 + 0.01
                    cash += sell_val - c
                    total_costs += c
                    positions[t] -= sh
                    trades.append((d, t, "SELL-FUND", sh, px, sell_val, c))
                    if positions[t] < 1e-9:
                        del positions[t]
                    need -= sell_val
            px = close_of(name, d)
            buy_val = min(target, cash / 1.001)
            if buy_val > 0.005 and px:
                sh = buy_val / px
                c = buy_val * 0.001
                cash -= buy_val + c
                total_costs += c
                positions[name] = positions.get(name, 0.0) + sh
                trades.append((d, name, "BUY", sh, px, buy_val, c))
        v = pot_close(d)
        curve.append((d, v))
        if v <= floor0 and di < len(days) - 1:
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor0}
            pending_halt = True
    last = days[-1]
    for t in list(positions):
        px = close_of(t, last)
        if px:
            val = positions[t] * px
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((last, t, "SELL-END", positions[t], px, val, c))
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


def curve_stats(curve, start_cash=START_CASH):
    peak, maxdd, maxdd_d, worst, worst_d = -1.0, 0.0, None, 1e18, None
    for d, v in curve:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
        if v < worst:
            worst, worst_d = v, d
    year_end = {}
    for d, v in curve:
        year_end[d[:4]] = round(v, 2)
    return {"max_drawdown_pct": round(maxdd * 100, 2),
            "max_drawdown_date": maxdd_d,
            "worst_close": round(worst, 2), "worst_close_date": worst_d,
            "year_end_closes": year_end}


# --------------------------------------------------------------------- main
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


def main():
    out = {"strategy": "DIVIDEND-INITIATION DRIFT (Michaely, Thaler & "
                       "Womack 1995) — gap test A-6: buy pond names "
                       "announcing a first regular dividend (or first "
                       "in >=5y) at the next session's close, 1/5-of-pot "
                       "slices (cap 5), hold 12 months, plain -15% "
                       "floor, $100",
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0,
           "windows": {"FULL": FULL, "VALIDATION": VAL},
           "events": EVENTS, "near_misses": NEAR_MISSES}

    # ---- (0) the census, recomputed from the tapes and asserted
    out["census"] = run_census()

    # ---- (1) replication check: champion engine, published numbers
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
            raise SystemExit("REPLICATION FAILED — variant numbers untrusted")
    spy_c = {}
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        spy_c[tag] = round(s, 2)
    print(f"CONTROL SPY (champion book): FULL=${spy_c['FULL']:,.2f} "
          f"VALIDATION=${spy_c['VALIDATION']:,.2f}", flush=True)
    out["replication_champion"] = rep
    out["spy_champion_book"] = spy_c

    # ---- (2) schedule derived mechanically from the announcements
    sched = derive_schedule(pb, EVENTS)
    for ev in sched:
        print(f"EVENT {ev['name']}: announced {ev['announce']} -> entry "
              f"{ev['entry']} (close) -> exit {ev['exit']} (close)",
              flush=True)
    out["schedule"] = [{k: ev[k] for k in ("name", "announce", "entry",
                                           "exit")} for ev in sched]

    # ---- (3) ranked pots, both windows
    ranked = {}
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        r = run_event_pot(pb, sched, ws, we, label=f"DIV-INIT {tag}")
        st = curve_stats(r["curve"])
        ranked[tag] = r
        print(f"RANKED {tag}: final=${r['final']:,.2f} "
              f"({(r['final'] / START_CASH - 1) * 100:+.2f}%) costs="
              f"${r['costs']:,.2f} orders={len(r['trades'])} "
              f"halted={r['halted']} maxDD={st['max_drawdown_pct']}% "
              f"SPY=${spy_c[tag]:,.2f} champion=${rep[tag]['final']:,.2f}",
              flush=True)
        out[f"ranked_{tag}"] = {
            "final": round(r["final"], 2),
            "ret_pct": round((r["final"] / START_CASH - 1) * 100, 2),
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "halted": r["halted"], "halt_info": r["halt_info"],
            "spy": spy_c[tag], "champion": rep[tag]["final"],
            "trades": [(d, t, s_, round(sh, 6), round(p, 4), round(v, 2),
                        round(cc, 2))
                       for d, t, s_, sh, p, v, cc in r["trades"]],
            **st}

    # ---- (4) placebo: same dates, random non-initiator pond names
    pool = [t for t in UNIVERSE if t not in {ev["name"] for ev in EVENTS}]
    placebo = {}
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        finals = []
        detail = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            picks = rng.sample(pool, len(sched))
            psched = [{**ev, "name": pick}
                      for ev, pick in zip(sched, picks)]
            r = run_event_pot(pb, psched, ws, we,
                              label=f"PLACEBO {tag} s{seed}")
            finals.append(round(r["final"], 2))
            detail.append({"seed": seed, "picks": picks,
                           "final": round(r["final"], 2),
                           "halted": r["halted"]})
        finals_sorted = sorted(finals)
        median = (finals_sorted[9] + finals_sorted[10]) / 2
        beat = sum(1 for f in finals if ranked[tag]["final"] > f)
        placebo[tag] = {"finals": finals_sorted, "median": round(median, 2),
                        "min": finals_sorted[0], "max": finals_sorted[-1],
                        "ranked_beats": beat, "detail": detail}
        print(f"PLACEBO {tag}: median=${median:,.2f} min="
              f"${finals_sorted[0]:,.2f} max=${finals_sorted[-1]:,.2f} | "
              f"ranked ${ranked[tag]['final']:,.2f} beats {beat}/20",
              flush=True)
    out["placebo"] = placebo

    # ---- (5) per-event table: event name standalone vs SPY, same dates
    rows = []
    for ev in sched:
        cf, cc, pe, px = standalone(pb, ev["name"], ev["entry"], ev["exit"])
        sf, sc, spe, spx = standalone(pb, "SPY", ev["entry"], ev["exit"])
        rows.append({"name": ev["name"], "announce": ev["announce"],
                     "entry": ev["entry"], "exit": ev["exit"],
                     "entry_close": round(pe, 4),
                     "exit_close": round(px, 4),
                     "name_net_final": round(cf, 2),
                     "name_net_ret_pct": round((cf / 100 - 1) * 100, 2),
                     "spy_net_final": round(sf, 2),
                     "spy_net_ret_pct": round((sf / 100 - 1) * 100, 2),
                     "beat_spy": cf > sf})
        print(f"EVENT {ev['name']}: in {ev['entry']} @ {pe:.2f} -> out "
              f"{ev['exit']} @ {px:.2f} | name ${cf:,.2f} "
              f"({(cf / 100 - 1) * 100:+.2f}%) vs SPY ${sf:,.2f} "
              f"({(sf / 100 - 1) * 100:+.2f}%) beat={cf > sf}", flush=True)
    out["event_table"] = rows
    out["events_beat_spy"] = sum(1 for x in rows if x["beat_spy"])
    out["events_total"] = len(rows)

    with open(os.path.join(HERE, "gap-a6-div-initiation-results.json"),
              "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
