#!/usr/bin/env python3
"""
SPIN-OFFS (Cusatis, Miles & Woolridge 1993) — Terry's AI stock app.
Simulation only. NO parameter tuning: the spec below is run ONCE, as
described, and judged against the promoted champion's published numbers.

THE FAMILY AS PUBLISHED: Cusatis, Miles & Woolridge, "Restructuring
through spinoffs: The stock market evidence" (Journal of Financial
Economics, 1993): firms spun off from parents outperformed the market
over the three years after distribution, and parents did too; the
effect was strongest in the second and third years and concentrated in
spin-offs later taken over. McConnell & Ovtchinnikov (2004) broadly
confirmed positive long-run drift for spin-off children. The published
event: a PRO-RATA distribution of a separately listed child's shares to
ALL of the parent's shareholders (including Reverse-Morris-Trust
merger-spins, where parent holders receive listed child shares pro
rata). Elective split-off exchanges, IPO carve-outs with no
distribution, and outright sales are NOT the published event and are
excluded below, by definition, before any results.

THE POND ADAPTATION (this test): whenever a company in the champion's
honest point-in-time top-30 universe (as of Nov 2016) — or its
successor — completes such a distribution during
2016-11-21 -> 2026-11-20, the pot buys the CHILD. Events were
identified from SEC filings only (parent completion 8-Ks + the child's
Form 10 registration), never from memory; the census is in the report
(spinoffs.md) and in the EVENTS / EXCLUDED tables below.

EVENT CENSUS RESULT (verified from EDGAR before any price was read):
SIX qualifying distributions — PFE->VTRS (2020-11-16), IBM->KD
(2021-11-03), T->WBD (closing 2022-04-08), GE->GEHC (2023-01-03),
MMM->SOLV (2024-04-01), GE->GEV (2024-04-02). Five are testable.
T->WBD is NOT testable: Warner Bros. Discovery was acquired by
Skydance and delisted on 2026-10-06 (its own 8-K), after which Yahoo
purged its entire price history — the live series and both program
caches return a one-bar stub (2026-10-05), Nasdaq's API answers
"Symbol not exists", Stooq is behind the JS bot-wall the program
already knows as manual-only, and no Tiingo/Alpaca key exists in this
environment. WBD stays in the census as a qualifying event and is
excluded from the portfolio for a DATA reason only — the same
documented treatment vm-broad gave Yahoo-purged UTX/WBA/CELG/RAI.
No WBD return figure was seen before this decision (none exists).

THE SLICING RULE (stated in advance, exactly as run):
  - Pot: $100 cash at 2016-11-21. Cash earns nothing (program rule).
  - ENTRY: at the close of the child's first REGULAR-WAY trading
    session (when-issued bars, which Yahoo includes for KD/GEHC/GEV/
    SOLV, are never used; VTRS's pre-distribution bars are Mylan
    backfill and are never used — each child's series is truncated to
    its entry date in the run book).
  - SIZE: each entry is funded with 1/5 of the pot's value marked at
    that day's closes BEFORE the entry trade (the pot holds at most 5
    spin-off positions by construction; unfilled fifths stay in cash).
    If cash is short of the target, existing positions are sold
    pro-rata by value at that day's close to raise it (sell costs
    apply). Buy value = min(target, cash / 1.001); buy cost 0.10%.
  - EXIT: at the close of the first trading day on or after the
    36-month anniversary of entry (Cusatis's horizon), or at the
    window-end close (2026-11-20) if the anniversary is later.
    Sell cost 0.10% of value + $0.01 per order (program costs).
  - FLOOR: plain -15% ($85.00) on the whole pot, champion mechanics —
    a close at/below $85 liquidates everything at the next trading
    day's open and ends the run.
  - Window end: any remaining positions are liquidated at the final
    close with sell costs (the champion's SELL-END convention).

COMPARISONS REPORTED: (a) SPY net over the identical census window
2016-11-21 -> 2026-11-20, program cost formula, on a long SPY series
fetched with the engine's own Yahoo method — the formula+series are
cross-checked on the champion's FULL window, where they must
reproduce the published $313.62; (b) the champion's published FULL
$544.47 / VALIDATION $288.05 (replication-checked in-run, below) —
the spinoff pot held only cash until Nov 2020, so its final is
identical whether the window is opened in 2016 or at the champion's
2019 start; (c) a per-event table: each child standalone ($100 in at
the entry close, out at the exit close, program costs) vs SPY over
the identical dates with identical treatment.

Data: SEC EDGAR (census; submissions + filing texts cached in
./spinoffs-data) + Yahoo Finance chart API prices (split/dividend
adjusted, the champion engine's exact bar construction), cached in
./spinoffs-data. Champion inputs reused read-only from the v4 caches.
"""
import calendar
import importlib.util
import json
import os
import time
import urllib.request
from datetime import date as _date

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
DATA = os.path.join(HERE, "spinoffs-data")
os.makedirs(DATA, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
WINDOW = ("2016-11-21", "2026-11-20")
FULL = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")

# ------------------------------------------------------------- event census
# (parent, child, distribution date, first regular-way session = entry,
#  filing basis). All dates verified from the filings cited in
#  spinoffs.md before any price was read.
EVENTS = [
    {"parent": "PFE", "child": "VTRS", "distribution": "2020-11-16",
     "entry": "2020-11-17", "testable": True,
     "basis": "PFE 8-K filed 2020-11-16 (Ex-99.1: completed the spin-off of "
              "Upjohn combined with Mylan to form Viatris; 'Viatris will "
              "begin trading tomorrow, November 17, 2020'); Viatris 10-12G "
              "filed 2019-10-25; PFE item-2.01 8-K filed 2020-11-20."},
    {"parent": "IBM", "child": "KD", "distribution": "2021-11-03",
     "entry": "2021-11-04", "testable": True,
     "basis": "IBM 8-K filed 2021-11-04 (item 2.01: 'On November 3, 2021, "
              "IBM completed ... distribution to holders of IBM's common "
              "stock of 80.1% of Kyndryl ... in a tax free spin-off'); "
              "Kyndryl Form 10 (DRS) filed from 2021-06-22."},
    {"parent": "T", "child": "WBD", "distribution": "2022-04-08",
     "entry": "2022-04-11", "testable": False,
     "basis": "T 8-K filed 2022-04-11 (items 2.01/3.02/7.01/8.01: pro rata "
              "dividend of Spinco stock; AT&T holders received 0.241917 "
              "shares of WBD per AT&T share). UNTESTABLE: WBD acquired by "
              "Skydance, delisted 2026-10-06 (WBD 8-K filed 2026-10-06); "
              "Yahoo purged the price history (live series and both "
              "program caches = one-bar stub), Nasdaq API 'Symbol not "
              "exists', Stooq behind its JS bot-wall, no Tiingo/Alpaca "
              "key in the environment."},
    {"parent": "GE", "child": "GEHC", "distribution": "2023-01-03",
     "entry": "2023-01-04", "testable": True,
     "basis": "GE 8-K filed 2023-01-04 (pro-rata distribution of ~80.1% of "
              "GE HealthCare; Ex-99.1: one GEHC share per three GE shares; "
              "'On January 4, 2023, GE HealthCare's common stock began "
              "trading on Nasdaq'); GEHC Form 10 (DRS) filed from "
              "2022-07-29."},
    {"parent": "MMM", "child": "SOLV", "distribution": "2024-04-01",
     "entry": "2024-04-01", "testable": True,
     "basis": "MMM 8-K filed 2024-04-04 (item 2.01: 'On April 1, 2024, 3M "
              "completed the separation ... through the pro rata "
              "distribution of 80.1% of Solventum'); Solventum Form 10 "
              "(DRS) filed from 2023-02-14."},
    {"parent": "GE", "child": "GEV", "distribution": "2024-04-02",
     "entry": "2024-04-02", "testable": True,
     "basis": "GE 8-K filed 2024-04-02 (item 2.01: 'pro rata distribution "
              "of all of the outstanding shares of GE Vernova'; 'On April "
              "2, 2024, GE Vernova's common stock began trading on the "
              "NYSE'); GE Vernova Form 10 (DRS) filed from 2023-10-27."},
]

EXCLUDED = [
    {"parent": "JNJ", "child": "KVUE", "what": "Kenvue: IPO (May 2023) "
     "followed by a split-off EXCHANGE OFFER completed 2023-08-23 (JNJ "
     "8-K item 2.01 filed 2023-08-25). Elective exchange by tendering "
     "holders only — not a pro-rata distribution. Excluded by definition."},
    {"parent": "INTC", "child": "MBLY", "what": "Mobileye: IPO carve-out "
     "(Oct 2022; MBLY DRS/S-1 from 2022-03-02). Intel retained ~88%; no "
     "shares were distributed to INTC holders. Excluded by definition."},
    {"parent": "PFE", "child": "HLN", "what": "Haleon was demerged by GSK "
     "(Jul 2022); Pfizer held a minority stake and distributed nothing to "
     "PFE holders (it later sold shares in market offerings). Not a PFE "
     "distribution. Excluded."},
    {"parent": "T", "child": "DirecTV", "what": "Contributed to a TPG "
     "joint venture (2021) and later sold; never separately listed, never "
     "distributed. Excluded."},
    {"parent": "GE", "child": "BHGE", "what": "Baker Hughes: GE sold down "
     "its stake in secondary offerings (GE item-2.01 8-K filed 2019-09-20 "
     "reports completed SALES). A sale, not a distribution. Excluded."},
    {"parent": "PG", "child": "Coty", "what": "Split-off closed "
     "2016-10-03 — before the census window opens (2016-11-21), and an "
     "elective split-off in any case. Excluded."},
    {"parent": "WBD", "child": "(successor check)", "what": "WBD "
     "announced a separation in June 2025; it was never completed — WBD "
     "was instead acquired by Skydance (merger agreement 2026-02-27, "
     "closed 2026-10-06 per WBD's 8-K). No successor event."},
]


# ------------------------------------------------------------------ prices
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


def get_prices_local(ticker, p1, p2="2026-11-21"):
    """The champion engine's bar construction, verbatim, with a local
    cache (the v4 caches are read-only and Yahoo has purged WBD)."""
    path = os.path.join(DATA, f"px_{ticker}.json")
    t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    j = json.loads(_fetch(url, path, headers={"User-Agent": "Mozilla/5.0"}))
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


def add_months(dstr, months):
    y, m, d = int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])
    m2 = m + months
    y += (m2 - 1) // 12
    m = (m2 - 1) % 12 + 1
    # clamp day to month length
    mdays = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
             31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    d = min(d, mdays)
    return f"{y:04d}-{m:02d}-{d:02d}"


# ------------------------------------------------------------- the strategy
def run_spinoffs(pb, events, start, end, start_cash=START_CASH,
                 floor0=FLOOR0, label=""):
    """Event pot per the slicing rule in the header. pb must contain SPY
    (calendar spine) and every testable child, bars truncated to >= the
    child's entry date."""
    cash = start_cash
    positions = {}          # child -> shares
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    # --- V9 PROTECTION MODULE (CLAUDE-RULES v9, the ONLY change): ---
    # episode 1 floor = floor0 (-15% of start). On FIRST halt: liquidate
    # exactly as below, sit in cash 90 calendar days, then event entries
    # resume (next spin-off event on/after the resume date) with
    # episode-2 floor = -15% of the restart balance. On SECOND halt:
    # original return (run ends permanently).
    floor = floor0
    v9_episode = 1
    v9_resume = None
    restarts = []
    curve = []
    days = [d for d in pb.dates if start <= d <= end]
    day_set = set(days)

    entries = {ev["entry"]: ev for ev in events if ev["testable"]}
    exits = {}
    for ev in events:
        if not ev["testable"]:
            continue
        anniv = add_months(ev["entry"], 36)
        xd = next((d for d in days if d >= anniv), None)
        exits[ev["child"]] = xd if xd is not None else end
    exit_days = {}
    for child, xd in exits.items():
        exit_days.setdefault(xd, []).append(child)

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
            # liquidate everything at today's open (next available open
            # per child), champion mechanics
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
            if v9_episode == 1:
                import datetime as _dt
                v9_episode = 2
                v9_resume = (_dt.date.fromisoformat(days[di - 1])
                             + _dt.timedelta(days=90)).isoformat()
                restarts.append({"halt_date": days[di - 1],
                                 "liquidation_date": d,
                                 "restart_balance": round(cash, 2),
                                 "resume_on_or_after": v9_resume,
                                 "episode2_floor": round(0.85 * cash, 2)})
                floor = 0.85 * cash
                pending_halt = False
                halt_info = None
            else:
                halted = d
                return {"label": label, "final": cash, "costs": total_costs,
                        "trades": trades, "halted": days[di - 1],
                        "halt_info": halt_info, "restarts": restarts,
                        "curve": curve, "exits": exits}
        # scheduled exits first (close), then entries (close)
        for child in exit_days.get(d, []):
            if child not in positions:
                continue
            px = close_of(child, d)
            val = positions[child] * px
            c = val * 0.001 + 0.01
            cash += val - c
            total_costs += c
            trades.append((d, child, "SELL-EXIT", positions[child], px,
                           val, c))
            del positions[child]
        if d in entries and (v9_resume is None or d >= v9_resume):
            ev = entries[d]
            child = ev["child"]
            marked = pot_close(d)
            target = marked / 5.0
            if cash < target * 1.001 and positions:
                # sell pro-rata slices at today's close to raise the cash
                need = target * 1.001 - cash
                tot_val = sum(positions[t] * close_of(t, d)
                              for t in positions)
                for t in list(positions):
                    if need <= 0:
                        break
                    px = close_of(t, d)
                    cur = positions[t] * px
                    sell_val = min(cur, need * (cur / tot_val) * 1.02)
                    sell_val = min(sell_val, cur)
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
            px = close_of(child, d)
            buy_val = min(target, cash / 1.001)
            if buy_val > 0.005 and px:
                sh = buy_val / px
                c = buy_val * 0.001
                cash -= buy_val + c
                total_costs += c
                positions[child] = positions.get(child, 0.0) + sh
                trades.append((d, child, "BUY", sh, px, buy_val, c))
        v = pot_close(d)
        curve.append((d, v))
        if v <= floor and di < len(days) - 1:
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            pending_halt = True
    # window end: liquidate at final close (champion SELL-END convention)
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
            "restarts": restarts,
            "curve": curve, "exits": exits}


def standalone(pb, ticker, entry, exit_d, start_cash=START_CASH):
    """$100 in at the entry close, out at the exit close, program costs.
    Used for each child AND for SPY over the identical dates."""
    pe = pb.close_on_or_before(ticker, entry)
    px = pb.close_on_or_before(ticker, exit_d)
    buy_val = start_cash / 1.001
    buy_cost = start_cash - buy_val
    sh = buy_val / pe
    val = sh * px
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost, pe, px


def spy_net_closes(pb, start, end, start_cash=START_CASH):
    """Program SPY formula (buy at first open, sell at last close, same
    costs as E.spy_net) on an arbitrary price book."""
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    val = sh * pb.close_on_or_before("SPY", last)
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost


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
    out = {"strategy": "SPIN-OFFS (Cusatis, Miles & Woolridge 1993): buy "
                       "the distributed child at the first regular-way "
                       "close, 1/5-of-pot slices, hold 36 months, plain "
                       "-15% floor, $100",
           "universe_parents": UNIVERSE, "pot": START_CASH,
           "floor": FLOOR0, "window": WINDOW,
           "events": EVENTS, "excluded_near_misses": EXCLUDED}

    # ---- (0) replication check: champion engine, published numbers
    pb_c, equity_rows, shares_rows = build_champion_inputs()
    rep = {}
    for tag, (ws, we), published in (("FULL", FULL, 544.47),
                                     ("VALIDATION", VAL, 288.05)):
        rb = E.run_pot(pb_c, equity_rows, shares_rows, ws, we, START_CASH,
                       FLOOR0, LADDER, label=f"REPLICATION {tag}", quiet=True)
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
        s, _ = E.spy_net(pb_c, ws, we, START_CASH)
        spy_c[tag] = round(s, 2)
    print(f"CONTROL SPY (champion book): FULL=${spy_c['FULL']:,.2f} "
          f"VALIDATION=${spy_c['VALIDATION']:,.2f}", flush=True)
    out["replication_champion"] = rep
    out["spy_champion_book"] = spy_c

    # ---- prices for the event pot (SPY long series + testable children)
    bars = {"SPY": get_prices_local("SPY", "2016-11-01")}
    fetch_from = {"VTRS": "2020-09-01", "KD": "2021-08-01",
                  "GEHC": "2022-10-01", "SOLV": "2024-01-01",
                  "GEV": "2024-01-01"}
    for ev in EVENTS:
        if not ev["testable"]:
            continue
        child = ev["child"]
        raw = get_prices_local(child, fetch_from[child])
        bars[child] = [b for b in raw if b["d"] >= ev["entry"]]
        print(f"{child}: series from {raw[0]['d']} (raw), truncated to "
              f"{bars[child][0]['d']}..{bars[child][-1]['d']} "
              f"({len(bars[child])} bars)", flush=True)
    pb = E.PriceBook(bars)

    # SPY formula/series control on the champion's FULL window
    s_full, _ = spy_net_closes(pb, FULL[0], FULL[1])
    s_win, _ = spy_net_closes(pb, WINDOW[0], WINDOW[1])
    print(f"SPY (long local series): FULL control=${s_full:,.2f} "
          f"(published $313.62) | census window=${s_win:,.2f}", flush=True)
    out["spy_long_series"] = {
        "full_control": round(s_full, 2), "published_full": 313.62,
        "census_window_net": round(s_win, 2)}

    # ---- (1) the event portfolio
    r = run_spinoffs(pb, EVENTS, WINDOW[0], WINDOW[1], label="SPINOFFS")
    st = curve_stats(r["curve"])
    print(f"SPINOFF POT: final=${r['final']:,.2f} "
          f"({(r['final'] / START_CASH - 1) * 100:+.2f}%) costs="
          f"${r['costs']:,.2f} orders={len(r['trades'])} "
          f"halted={r['halted']} maxDD={st['max_drawdown_pct']}%", flush=True)
    out["portfolio"] = {
        "final": round(r["final"], 2),
        "ret_pct": round((r["final"] / START_CASH - 1) * 100, 2),
        "costs": round(r["costs"], 2), "orders": len(r["trades"]),
        "halted": r["halted"], "halt_info": r["halt_info"],
        "restarts": r["restarts"],
        "spy_census_window": round(s_win, 2),
        "champion_full": rep["FULL"]["final"],
        "champion_validation": rep["VALIDATION"]["final"],
        "trades": [(d, t, s_, round(sh, 6), round(p, 4), round(v, 2),
                    round(c, 2)) for d, t, s_, sh, p, v, c in r["trades"]],
        **st}

    # ---- (2) per-event table: child standalone vs SPY, identical dates
    rows = []
    for ev in EVENTS:
        if not ev["testable"]:
            rows.append({**{k: ev[k] for k in ("parent", "child",
                                               "distribution", "entry")},
                         "testable": False,
                         "note": "price series purged (see census)"})
            continue
        xd = r["exits"][ev["child"]]
        cf, cc, pe, px = standalone(pb, ev["child"], ev["entry"], xd)
        sf, sc, spe, spx = standalone(pb, "SPY", ev["entry"], xd)
        rows.append({**{k: ev[k] for k in ("parent", "child",
                                           "distribution", "entry")},
                     "testable": True, "exit": xd,
                     "entry_close": round(pe, 4), "exit_close": round(px, 4),
                     "child_net_final": round(cf, 2),
                     "child_net_ret_pct": round((cf / 100 - 1) * 100, 2),
                     "spy_net_final": round(sf, 2),
                     "spy_net_ret_pct": round((sf / 100 - 1) * 100, 2),
                     "beat_spy": cf > sf})
        print(f"EVENT {ev['parent']}->{ev['child']}: in {ev['entry']} "
              f"@ {pe:.2f} -> out {xd} @ {px:.2f} | child ${cf:,.2f} "
              f"({(cf / 100 - 1) * 100:+.2f}%) vs SPY ${sf:,.2f} "
              f"({(sf / 100 - 1) * 100:+.2f}%) beat={cf > sf}", flush=True)
    out["event_table"] = rows
    testable = [x for x in rows if x["testable"]]
    out["events_beat_spy"] = sum(1 for x in testable if x["beat_spy"])
    out["events_testable"] = len(testable)

    with open(os.path.join(HERE, "spinoffs-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
