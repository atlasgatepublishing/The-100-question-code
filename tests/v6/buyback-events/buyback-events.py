#!/usr/bin/env python3
"""
BUYBACK-ANNOUNCEMENT EVENTS (census queue #8) vs the promoted champion.

Family as published: Ikenberry, Lakonishok & Vermaelen (1995) and
successors — open-market repurchase AUTHORIZATION announcements are
followed by positive abnormal drift (~12% over 4 years in the original,
concentrated in value names). One clean shot, no tuning.

SPEC (stated in advance):
  event   = a top-30 pond company announcing a NEW share-repurchase
            authorization (new program, stated-amount increase, or new
            time-bounded authorization) in an SEC Form 8-K.
  entry   = next trading day's open after the 8-K filing date (the
            filing date is the public date; never backdated to a board
            date — see the flagged PFE/XOM cases in the report).
  hold    = 12 months; exit at the open of the first trading day on or
            after entry + 12 calendar months.
  pot     = each event gets an equal 1/5 slice of pot value at entry
            (pot value marked at that day's open, after that day's
            exits, before that day's entries); max 5 concurrent
            positions; a 6th event while full is skipped and logged;
            an event for a ticker already held is skipped for the pot
            (still counted in the standalone stats); proceeds return
            to cash at exit; plain -15% floor ($85 on $100) checked at
            the daily close, liquidation at the next open on breach
            (champion convention); window-end liquidation at the
            final close; program costs 0.10%/side + $0.01 per sell.
  windows = FULL 2019-01-02..2026-11-20 and VALIDATION
            2023-01-03..2026-11-20 (announcements filed inside the
            window only), plus calendar-year folds 2020..2026.
  placebo = the same audited events with announcement dates shifted
            +6 calendar months, identical mechanics (defined here,
            before results).

DETECTION (see buyback-events.md for the full audit trail):
  All 4,786 Form 8-Ks filed by the 30 pond CIKs 2016-11-21..2026-11-20
  were enumerated via the EDGAR submissions API (efts.sec.gov
  full-text search is 403-blocked from this network); exhibit/press
  documents were downloaded from Archives and text-searched
  (1,242 filings mention repurchase/buyback). A rule classifier
  produced 132 candidates; every candidate was manually audited
  against the filing text, yielding the 91 events frozen below.
  RELIABILITY FINDING: the 8-K channel is structurally incomplete —
  MSFT (3 authorizations), Mastercard (Dec announcements) and IBM
  (2 additions) announce by standalone press release only and have
  ZERO events in any 8-K; WFC's $30B (2023) and $40B (2025)
  announcements are likewise press-release-only. The traded list is
  therefore the 8-K-VISIBLE subset, and results are graded as such.

Prices/benchmarks reuse the champion engine
(backtests/v4/value-momentum-plainfloor.py) and its caches read-only.
Replication of the champion's published numbers is asserted first.
Simulation only.
"""

import importlib.util
import json
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
CHAMP_PATH = os.path.join(HERE, "..", "..", "v4",
                          "value-momentum-plainfloor.py")

START_CASH = 100.0
FLOOR = 85.0
MAX_POS = 5
HOLD_MONTHS = 12

# ---------------------------------------------------------------- events
# Audited 8-K-visible authorization events: (ticker, 8-K filing date,
# amount note). FLAG = board acted earlier; date used is the first
# 8-K public disclosure (never backdated).
EVENTS = [
    ("HD",  "2017-02-21", "$15B program"),
    ("VZ",  "2017-03-03", "reauthorization (no $ amount)"),
    ("V",   "2017-04-20", "$5B program"),
    ("INTC", "2017-04-27", "+$10B"),
    ("AAPL", "2017-05-02", "program to $210B total"),
    ("BAC", "2017-06-28", "$12B program"),
    ("JPM", "2017-06-28", "$19.4B program"),
    ("WMT", "2017-10-10", "$20B program"),
    ("BAC", "2017-12-05", "~$0.9B offset authorization"),
    ("PFE", "2018-01-30", "$10B program (FLAG: board Dec 2017; first 8-K disclosure here)"),
    ("GOOGL", "2018-02-01", "+$8.3B"),
    ("V",   "2018-02-01", "$7.5B program"),
    ("PEP", "2018-02-13", "$15B program"),
    ("CSCO", "2018-02-14", "+$25B"),
    ("META", "2018-04-25", "+$9B"),
    ("AAPL", "2018-05-01", "+$100B"),
    ("BAC", "2018-06-28", "$20.6B program"),
    ("JPM", "2018-06-28", "$20.7B program"),
    ("INTC", "2018-11-15", "+$15B"),
    ("JNJ", "2018-12-17", "$5B program"),
    ("META", "2018-12-07", "+$9B"),
    ("PFE", "2019-01-29", "$10B program (FLAG: board Dec 2018; first 8-K disclosure here)"),
    ("V",   "2019-01-30", "$8.5B program"),
    ("CVX", "2019-02-01", "$25B program"),
    ("CSCO", "2019-02-13", "+$15B"),
    ("BAC", "2019-02-07", "$0.6B offset authorization"),
    ("HD",  "2019-02-26", "$15B program"),
    ("AAPL", "2019-04-30", "+$75B"),
    ("JPM", "2019-06-27", "$29.4B program"),
    ("BAC", "2019-06-27", "$30.9B program"),
    ("GOOGL", "2019-07-25", "$25B program"),
    ("INTC", "2019-10-24", "+$20B"),
    ("VZ",  "2020-02-06", "reauthorization (no $ amount)"),
    ("META", "2020-01-29", "+$10B"),
    ("V",   "2020-01-30", "$9.5B program"),
    ("AAPL", "2020-04-30", "+$50B"),
    ("AAPL", "2021-04-28", "+$90B"),
    ("GOOGL", "2020-07-30", "$28B program"),
    ("JPM", "2020-12-18", "$30B program"),
    ("WFC", "2021-01-15", "+500M shares authorized"),
    ("META", "2021-01-27", "+$25B"),
    ("V",   "2021-01-28", "$8B program"),
    ("WMT", "2021-02-18", "$20B program"),
    ("NFLX", "2021-04-20", "$5B program"),
    ("BAC", "2021-01-19", "$2.9B authorization"),
    ("BAC", "2021-04-15", "$25B program"),
    ("GOOGL", "2021-04-27", "$50B program"),
    ("META", "2021-10-25", "+$50B"),
    ("XOM", "2021-10-29", "$10B program (from 2022)"),
    ("V",   "2021-12-15", "$12B program"),
    ("PEP", "2022-02-10", "$10B program"),
    ("CSCO", "2022-02-16", "+$15B"),
    ("AMZN", "2022-03-09", "$10B program"),
    ("JPM", "2022-04-13", "$30B program"),
    ("GE",  "2022-04-26", "$3B program"),
    ("GOOGL", "2022-04-26", "$70B program"),
    ("AAPL", "2022-04-28", "+$90B"),
    ("XOM", "2022-04-29", "increase; program total $30B through 2023"),
    ("JNJ", "2022-09-14", "$5B program"),
    ("V",   "2022-10-25", "$12B program"),
    ("WMT", "2022-11-15", "$20B program"),
    ("CVX", "2023-01-27", "$75B program"),
    ("XOM", "2023-01-31", "program increase (FLAG: Dec 2022 corporate plan; first 8-K disclosure here)"),
    ("META", "2023-02-01", "+$40B"),
    ("GOOGL", "2023-04-25", "$70B program"),
    ("AAPL", "2023-05-04", "+$90B"),
    ("HD",  "2023-08-15", "$15B program"),
    ("NFLX", "2023-10-18", "+$10B"),
    ("V",   "2023-10-24", "$25B program"),
    ("DIS", "2024-02-07", "new authorization; FY24 purchases targeted at $3B"),
    ("META", "2024-02-01", "+$50B"),
    ("GE",  "2024-03-07", "$15B program"),
    ("GOOGL", "2024-04-25", "$70B program"),
    ("AAPL", "2024-05-02", "+$110B"),
    ("JPM", "2024-06-28", "$30B program"),
    ("BAC", "2024-07-24", "$25B program"),
    ("T",   "2024-12-03", "$10B program"),
    ("NFLX", "2025-01-21", "+$15B"),
    ("CSCO", "2025-02-12", "+$15B"),
    ("GOOGL", "2025-04-24", "$70B program"),
    ("V",   "2025-04-29", "$30B program"),
    ("AAPL", "2025-05-01", "+$100B"),
    ("JPM", "2025-07-01", "$50B program"),
    ("BAC", "2025-07-23", "$40B program"),
    ("PEP", "2026-02-03", "$10B program"),
    ("WMT", "2026-02-19", "$30B program"),
    ("VZ",  "2026-01-30", "$25B program"),
    ("NFLX", "2026-04-23", "+$25B"),
    ("V",   "2026-04-28", "$20B program"),
    ("AAPL", "2026-04-30", "+$100B"),
    ("JPM", "2026-06-24", "$50B program"),
]

# Verified authorization announcements that never appear in any 8-K
# (press-release-only channel) — census completeness record, NOT traded.
KNOWN_MISSED = [
    ("MSFT", "2019-09-18", "$40B program — press release only; no Sep 2019 8-K carries it (verified: the month's only 8-K exhibit is a board-nomination release; program confirmed in MSFT 10-Q)"),
    ("MSFT", "2021-09-14", "$60B program — press release only; no 8-K"),
    ("MSFT", "2024-09-16", "$60B program — press release only; no Sep 2024 8-K at all"),
    ("IBM",  "2017-10-31", "+$3B — Business Wire dividend release only; confirmed in IBM 2017 10-K footnote; never in an 8-K"),
    ("IBM",  "2018-10-30", "+$4B — Business Wire dividend release only; confirmed in IBM 2018 10-K footnote; never in an 8-K"),
    ("MA",   "2023-12-05", "new program (~$11B as reported) — December announcements are press-release-only; Dec 2023's only 8-K is a bylaws filing with no exhibit"),
    ("MA",   "2024-12-10", "new program (~$12B as reported) — press release only; no Dec 2024 8-K exists"),
    ("WFC",  "2023-07-25", "$30B program — press release only; the 2023-07-25 8-K is a debt-offering filing"),
    ("WFC",  "2025-04-29", "$40B program — press release only; absent from WFC's April 2025 8-Ks"),
    ("BRK-B", "2018-07-17", "policy amendment (no $ amount) — announced by press release and an 8-K was filed, but with no stated amount it fails the stated event definition; census-listed, not traded"),
]


def add_months(ds, months):
    y, m, d = int(ds[:4]), int(ds[5:7]), int(ds[8:10])
    m2 = m + months
    y += (m2 - 1) // 12
    m2 = (m2 - 1) % 12 + 1
    # clamp day to month length
    if m2 == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m2 + 1, 1)
    last_day = (nxt - date(y, m2, 1)).days
    return date(y, m2, min(d, last_day)).isoformat()


def load_champion():
    spec = importlib.util.spec_from_file_location("champ", CHAMP_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Cal:
    """Trading calendar + price access on top of the champion PriceBook."""

    def __init__(self, pb):
        self.pb = pb
        self.days = sorted(b["d"] for b in pb.bars["SPY"])
        self.dayset = set(self.days)

    def first_day_after(self, ds):
        for d in self.days:
            if d > ds:
                return d
        return None

    def first_day_on_or_after(self, ds):
        for d in self.days:
            if d >= ds:
                return d
        return None

    def open_on(self, t, d):
        b = self.pb.bar(t, d)
        return b["o"] if b else None

    def close_on_or_before(self, t, d):
        return self.pb.close_on_or_before(t, d)


def standalone(cal, ticker, filing_date):
    """$100 hypothetical, next-open entry, 12-month hold, program costs.
    Returns dict or None if no price coverage at entry."""
    entry = cal.first_day_after(filing_date)
    if entry is None:
        return None
    o = cal.open_on(ticker, entry)
    if o is None:
        return None
    sh = (100.0 / 1.001) / o
    exit_target = add_months(entry, HOLD_MONTHS)
    exit_day = cal.first_day_on_or_after(exit_target)
    truncated = False
    if exit_day is None:
        exit_day = cal.days[-1]
        truncated = True
        xp = cal.close_on_or_before(ticker, exit_day)
    else:
        xp = cal.open_on(ticker, exit_day)
        if xp is None:
            xp = cal.close_on_or_before(ticker, exit_day)
    val = sh * xp
    net = val - (val * 0.001 + 0.01)
    # SPY over the identical span, identical mechanics
    so = cal.open_on("SPY", entry)
    ssh = (100.0 / 1.001) / so
    sxp = (cal.open_on("SPY", exit_day) if not truncated
           else cal.close_on_or_before("SPY", exit_day))
    sval = ssh * sxp
    snet = sval - (sval * 0.001 + 0.01)
    return {"ticker": ticker, "filing": filing_date, "entry": entry,
            "exit": exit_day, "net": round(net, 2),
            "ret_pct": round(net - 100.0, 2),
            "spy_net": round(snet, 2), "spy_ret_pct": round(snet - 100.0, 2),
            "excess_pct": round(net - snet, 2), "truncated": truncated}


def run_event_pot(cal, events, start, end, label):
    """events: list of (ticker, filing_date, note) — only events with
    filing_date in [start, end] are eligible. Returns result dict."""
    days = [d for d in cal.days if start <= d <= end]
    if not days:
        return None
    by_entry = {}
    eligible = []
    for tk, fd, note in events:
        if not (start <= fd <= end):
            continue
        entry = cal.first_day_after(fd)
        if entry is None or entry > end:
            continue
        by_entry.setdefault(entry, []).append((tk, fd, note))
        eligible.append((tk, fd))
    cash = START_CASH
    positions = []  # dicts: ticker, shares, exit_day, entry, filing
    trades = []
    skipped = []
    total_costs = 0.0
    halted = None
    curve = []

    def close_value(d):
        v = cash
        for p in positions:
            c = cal.close_on_or_before(p["ticker"], d)
            if c:
                v += p["shares"] * c
        return v

    for di, d in enumerate(days):
        # 1) exits at today's open
        for p in list(positions):
            if p["exit_day"] == d:
                xp = cal.open_on(p["ticker"], d)
                if xp is None:
                    xp = cal.close_on_or_before(p["ticker"], d)
                val = p["shares"] * xp
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((d, p["ticker"], "SELL-EXIT", round(p["shares"], 4),
                               xp, round(val, 2), round(c, 2)))
                positions.remove(p)
        # 2) entries at today's open
        for tk, fd, note in by_entry.get(d, []):
            if any(p["ticker"] == tk for p in positions):
                skipped.append({"date": fd, "ticker": tk,
                                "reason": "already held"})
                continue
            if len(positions) >= MAX_POS:
                skipped.append({"date": fd, "ticker": tk,
                                "reason": "pot full (5 positions)"})
                continue
            o = cal.open_on(tk, d)
            if o is None:
                skipped.append({"date": fd, "ticker": tk,
                                "reason": "no price bar"})
                continue
            pv = cash
            for p in positions:
                po = cal.open_on(p["ticker"], d)
                if po:
                    pv += p["shares"] * po
            slice_val = pv / MAX_POS
            buy_val = min(slice_val, cash / 1.001)
            if buy_val <= 0.005:
                skipped.append({"date": fd, "ticker": tk,
                                "reason": "insufficient cash"})
                continue
            sh = buy_val / o
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            exit_day = cal.first_day_on_or_after(add_months(d, HOLD_MONTHS))
            if exit_day is None:
                exit_day = days[-1]
            positions.append({"ticker": tk, "shares": sh,
                              "exit_day": exit_day, "entry": d,
                              "filing": fd})
            trades.append((d, tk, "BUY", round(sh, 4), o,
                           round(buy_val, 2), round(c, 2)))
        # 3) close mark + floor
        v = close_value(d)
        curve.append((d, v))
        if v <= FLOOR and di < len(days) - 1:
            halted = d
            nd = days[di + 1]
            for p in list(positions):
                xp = cal.open_on(p["ticker"], nd)
                if xp is None:
                    xp = cal.close_on_or_before(p["ticker"], nd)
                val = p["shares"] * xp
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((nd, p["ticker"], "SELL-HALT",
                               round(p["shares"], 4), xp, round(val, 2),
                               round(c, 2)))
            positions = []
            return {"label": label, "final": round(cash, 2),
                    "costs": round(total_costs, 2), "halted": halted,
                    "trades": trades, "skipped": skipped,
                    "events_eligible": len(eligible), "curve": curve}
    # window end: liquidate at final close
    last = days[-1]
    for p in list(positions):
        xp = cal.close_on_or_before(p["ticker"], last)
        val = p["shares"] * xp
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((last, p["ticker"], "SELL-END", round(p["shares"], 4),
                       xp, round(val, 2), round(c, 2)))
    positions = []
    return {"label": label, "final": round(cash, 2),
            "costs": round(total_costs, 2), "halted": None,
            "trades": trades, "skipped": skipped,
            "events_eligible": len(eligible), "curve": curve}


def summarize(rows):
    rows = [r for r in rows if r]
    if not rows:
        return {}
    rets = sorted(r["ret_pct"] for r in rows)
    exc = sorted(r["excess_pct"] for r in rows)
    n = len(rows)
    med = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
    mede = exc[n // 2] if n % 2 else (exc[n // 2 - 1] + exc[n // 2]) / 2
    return {"n": n,
            "mean_ret_pct": round(sum(rets) / n, 2),
            "median_ret_pct": round(med, 2),
            "mean_excess_vs_spy_pct": round(sum(exc) / n, 2),
            "median_excess_vs_spy_pct": round(mede, 2),
            "share_beating_spy": round(sum(1 for e in exc if e > 0) / n, 3),
            "share_positive": round(sum(1 for r in rets if r > 0) / n, 3)}


def main():
    champ = load_champion()
    # ---- replication check (mandatory, to the cent) -------------------
    ciks = champ.get_ciks()
    equity_rows, shares_rows = {}, {}
    for t in champ.UNIVERSE:
        cik = {"XOM": 34088}.get(t, ciks[t][0])
        facts = champ.get_companyfacts(cik)
        equity_rows[t] = (
            champ.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            champ.pit_series(facts, "us-gaap",
                             "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                             prio=1))
        shares_rows[t] = (
            champ.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            champ.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            champ.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    bars = {}
    for t in champ.UNIVERSE + ["SPY"]:
        bars[t] = champ.get_prices(t)
    pb = champ.PriceBook(bars)
    rep = {}
    for wname, ws, we in (("FULL", "2019-01-02", "2026-11-20"),
                          ("VALIDATION", "2023-01-03", "2026-11-20")):
        r = champ.run_pot(pb, equity_rows, shares_rows, ws, we, 100.0, 85.0,
                          [], label=f"REPLICATION {wname}", quiet=True)
        s, _ = champ.spy_net(pb, ws, we, 100.0)
        rep[wname] = {"pot": round(r["final"], 2), "spy": round(s, 2)}
        print(f"replication {wname}: pot=${r['final']:,.2f} spy=${s:,.2f}",
              flush=True)
    assert rep["FULL"]["pot"] == 544.47 and rep["FULL"]["spy"] == 313.62, rep
    assert rep["VALIDATION"]["pot"] == 288.05 and rep["VALIDATION"]["spy"] == 187.77, rep
    print("REPLICATION OK: champion $544.47 / $288.05, SPY $313.62 / $187.77",
          flush=True)

    cal = Cal(pb)
    events = sorted(EVENTS, key=lambda e: e[1])
    placebo_events = sorted(
        [(tk, add_months(fd, 6), note) for tk, fd, note in EVENTS],
        key=lambda e: e[1])

    out = {"replication": rep,
           "detection": {
               "filings_scanned_8k": 4786,
               "filings_mentioning_repurchase": 1242,
               "classifier_candidates": 132,
               "audited_events_traded": len(events),
               "tickers_with_events": len({t for t, _, _ in events}),
               "known_missed_press_release_only": KNOWN_MISSED},
           "events": [{"ticker": t, "filing_date": d, "note": n}
                      for t, d, n in events]}

    # ---- standalone per-event stats -----------------------------------
    sa = [standalone(cal, t, d) for t, d, _ in events]
    sa_full = [r for r in sa if r and not r["truncated"]]
    out["standalone_real"] = {"all": summarize(sa),
                              "completed_holds_only": summarize(sa_full),
                              "rows": sa}
    sap = [standalone(cal, t, d) for t, d, _ in placebo_events]
    sap_full = [r for r in sap if r and not r["truncated"]]
    out["standalone_placebo"] = {"all": summarize(sap),
                                 "completed_holds_only": summarize(sap_full),
                                 "rows": sap}
    print("standalone real:", out["standalone_real"]["completed_holds_only"],
          flush=True)
    print("standalone placebo:",
          out["standalone_placebo"]["completed_holds_only"], flush=True)

    # ---- pots ----------------------------------------------------------
    windows = [("FULL", "2019-01-02", "2026-11-20"),
               ("VALIDATION", "2023-01-03", "2026-11-20")]
    out["pots"] = {}
    for wname, ws, we in windows:
        s, _ = champ.spy_net(pb, ws, we, 100.0)
        for tag, evs in (("real", events), ("placebo", placebo_events)):
            r = run_event_pot(cal, evs, ws, we, f"{wname} {tag}")
            worst = min(r["curve"], key=lambda kv: kv[1]) if r["curve"] else None
            out["pots"][f"{wname}_{tag}"] = {
                "final": r["final"], "costs": r["costs"],
                "halted": r["halted"], "spy_net": round(s, 2),
                "events_eligible": r["events_eligible"],
                "trades": r["trades"], "skipped": r["skipped"],
                "worst_close": round(worst[1], 2) if worst else None,
                "worst_close_date": worst[0] if worst else None}
            print(f"pot {wname} {tag}: final=${r['final']:,.2f} "
                  f"spy=${s:,.2f} halted={r['halted']} "
                  f"eligible={r['events_eligible']} "
                  f"skipped={len(r['skipped'])}", flush=True)

    # ---- folds ----------------------------------------------------------
    out["folds"] = {}
    for y in range(2020, 2027):
        ws = f"{y}-01-01"
        we = "2026-11-20" if y == 2026 else f"{y}-12-31"
        s, _ = champ.spy_net(pb, ws, we, 100.0)
        row = {"spy_net": round(s, 2)}
        for tag, evs in (("real", events), ("placebo", placebo_events)):
            r = run_event_pot(cal, evs, ws, we, f"FOLD {y} {tag}")
            row[tag] = {"final": r["final"], "halted": r["halted"],
                        "events_eligible": r["events_eligible"],
                        "skipped": len(r["skipped"])}
        out["folds"][str(y)] = row
        print(f"fold {y}: real=${row['real']['final']:,.2f} "
              f"placebo=${row['placebo']['final']:,.2f} spy=${s:,.2f}",
              flush=True)

    with open(os.path.join(HERE, "buyback-events-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
