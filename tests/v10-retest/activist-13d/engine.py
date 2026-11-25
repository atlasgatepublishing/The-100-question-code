#!/usr/bin/env python3
"""
13D ACTIVIST EVENTS (Brav, Jiang, Partnoy & Thomas 2008) — Terry's AI
stock app. Simulation only. NO parameter tuning: the spec below is run
ONCE, as described, and judged against the promoted champion's
published numbers.

THE FAMILY AS PUBLISHED: when an investor crosses 5% of a company with
active intent, they must file Schedule 13D. Brav, Jiang, Partnoy &
Thomas (2008, Journal of Finance, "Hedge Fund Activism, Corporate
Governance, and Firm Performance") and the successor literature find
the TARGET earns positive abnormal returns around and after the
filing — roughly +6-7% announcement-window abnormal return in BJPT,
with drift thereafter. The public, tradable event is the FILING (the
filer may cross 5% up to 10 calendar days before filing under the
rules in force for most of the window; the crossing itself is not
public information and is never used here).

THE SPEC FOR THIS POND (stated in advance, run once):
  - Event census: every INITIAL Schedule 13D (form type exactly
    "SC 13D" — amendments "SC 13D/A" are NOT new events) whose SUBJECT
    company is one of the champion's honest point-in-time top-30 as of
    Nov 2016, with EDGAR acceptance datetime from 2016-11-21 through
    2026-11-20. Discovery: EDGAR's own subject-company filing index
    (browse-edgar, the index behind the EDGAR company pages), then
    every candidate verified TWICE: against its filing header (subject
    CIK must equal the target's CIK; acceptance datetime read from the
    header, ET) AND against the Schedule 13D cover in the filing
    document itself (the issuer named before "(Name of Issuer)").
    The document check exists because EDGAR headers can be mis-keyed:
    accession 0000104169-22-000040's header names Walmart as its own
    subject, but the document is Walmart's 13D on Symbotic Inc. (the
    corrected twin, -000043, keys it properly) — where header and
    document disagree, the document decides and the disagreement is
    logged. Two more census traps handled: Disney's subject filings
    before Mar 2019 sit under its predecessor CIK 1001039 (the current
    ticker mapping gives 1744489), so DIS is queried under both; and
    the banks'/strategics' company files are full of 13Ds they filed
    on OTHER companies (closed-end funds, portfolio stakes) — those
    are filer-side filings, rejected on subject, never counted.
    A second, independent discovery pass (EDGAR full-text search by
    issuer name + entity CIK, run as an audit) reproduced the same
    candidate accession sets as the subject index for every name
    except the Disney predecessor filing, which it caught — the two
    methods together bound the census. All initial 13Ds count — the
    13D form IS the active-intent filing (passive holders file 13G);
    no sub-filtering by filer type, which would be tuning.
  - Entry: the first trading-day OPEN strictly after the filing's
    acceptance timestamp (a filing accepted before 09:30 ET enters
    that day's open; after the open, the next trading day's open).
  - Hold: 12 months per position; exit at the open of the first
    trading day on/after the 12-month anniversary of entry.
  - Portfolio: $100 pot. Each event invests one fifth of the pot's
    market value (measured at the entry open) — max 5 concurrent
    lots; an event arriving while 5 lots are open is SKIPPED and
    logged. Exits at a given open execute before entries at that open.
  - Costs: 0.10% of trade value per side + $0.01 per sell order
    (the program standard).
  - Protection: PLAIN -15% floor only ($85 on the $100 pot, no
    ladder). Close at/below floor -> liquidate everything at next
    open, run ends.
  - Windows (the program's): CONTINUOUS 2019-01-02 -> 2026-11-20 and
    VALIDATION 2023-01-03 -> 2026-11-20. A window's pot takes only
    events FILED inside that window; a position still open at the
    window's end is liquidated at the final close (the champion's
    SELL-END convention) and marked truncated.
  - Per-event returns (census table): a standalone $20 slice per
    event (the pot's starting slice size), entry open -> exit open
    12 months later, same costs; SPY bought/sold over the identical
    span with the identical cost treatment alongside. Events whose
    12 months run past the price data (filed after ~Nov 2025) are
    marked truncated at the 2026-11-20 close.
  - Placebo: the same targets with entries shifted +6 months (entry
    = first open after acceptance datetime + 6 calendar months),
    same 12-month hold and portfolio rules — run for a window only
    if that window holds >= 4 events.

HONESTY RULE (from the task): if the whole census holds fewer than
~4 qualifying events, the family is graded UNTESTABLE-ON-THIS-POND —
the census is delivered as the evidence and no portfolio verdict is
manufactured from 1-2 events. The pond is NOT widened.

Runs:
  (0) REPLICATION CHECK — the imported champion engine must reproduce
      the published $544.47 (continuous) and $288.05 (validation) and
      SPY $313.62 / $187.77 to the cent before any variant number is
      taken.
  (1) EVENT CENSUS 2016-11-21 -> 2026-11-20 with per-event returns.
  (2) EVENT POT on both windows (+ date-shifted placebo where the
      count supports one).

Judged against the champion (published): validation $288.05 |
continuous $544.47 | SPY net $187.77 validation / $313.62 continuous
(recomputed in-run as control).

Data: EDGAR (browse-edgar subject index + filing headers, cached in
./data) for the census; Yahoo Finance chart API prices (same
split/dividend-adjusted method as the champion) fetched long
(2016-06-01 -> 2026-11-21) into ./data for the event engine, because
the champion's own price cache starts 2017-06-01 and 2016-17 events
need 2016 prices. The replication check uses the champion's caches
verbatim, exactly as the other v6 tests do.
"""
import importlib.util
import json
import math
import os
import re
import sys
import time
import urllib.request
from datetime import date as _date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
UA = E.UA
START_CASH = 100.0
FLOOR0 = 85.0
CENSUS_START, CENSUS_END = "2016-11-21", "2026-11-20"
WINDOWS = [("FULL", "2019-01-02", "2026-11-20"),
           ("VALIDATION", "2023-01-03", "2026-11-20")]
CIK_OVERRIDES = {"XOM": 34088}   # champion's override, carried over

def _ord(dstr):
    return _date(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()

def add_months(dstr, months):
    """Calendar month shift on a YYYY-MM-DD string (day clamped)."""
    y, m, d = int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])
    m2 = m + months
    y += (m2 - 1) // 12
    m2 = (m2 - 1) % 12 + 1
    # clamp day to month length
    if m2 == 12:
        nxt = _date(y + 1, 1, 1)
    else:
        nxt = _date(y, m2 + 1, 1)
    last_day = (nxt - timedelta(days=1)).day
    return _date(y, m2, min(d, last_day)).isoformat()

# ------------------------------------------------------------- EDGAR census
def fetch_cached(url, path, headers=None, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                blob = r.read()
            with open(path, "wb") as f:
                f.write(blob)
            return blob
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")

def atom_candidates(cik):
    """All SC 13D-family entries in EDGAR's subject-company index for
    this CIK (discovery only — every hit is header-verified later)."""
    out = []
    start = 0
    while True:
        url = (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
               f"&CIK={cik:010d}&type=SC+13D&dateb=&owner=include"
               f"&count=100&start={start}&output=atom")
        path = os.path.join(DATA, f"atom_{cik:010d}_{start}.xml")
        blob = fetch_cached(url, path)
        x = blob.decode("utf-8", "replace")
        entries = re.findall(r"<entry>(.*?)</entry>", x, re.S)
        for e in entries:
            t = re.search(r"<filing-type>(.*?)</filing-type>", e)
            d = re.search(r"<filing-date>(.*?)</filing-date>", e)
            h = re.search(r"<filing-href>(.*?)</filing-href>", e)
            if t and d and h:
                out.append({"form": t.group(1).strip(),
                            "date": d.group(1).strip(),
                            "href": h.group(1).strip()})
        if len(entries) < 100 or len(out) > 2000:
            break
        start += 100
        time.sleep(0.15)
    return out

def parse_header(href):
    """Fetch the filing's SGML header (-index-headers.html) and pull
    the acceptance datetime, subject company, and filer identity."""
    m = re.search(r"/data/(\d+)/(\d+)/(\d+-\d+-\d+)-index\.htm", href)
    if not m:
        return None
    subj_dir, acc_nodash, acc = m.group(1), m.group(2), m.group(3)
    url = (f"https://www.sec.gov/Archives/edgar/data/{subj_dir}/"
           f"{acc_nodash}/{acc}-index-headers.html")
    path = os.path.join(DATA, f"hdr_{acc}.html")
    blob = fetch_cached(url, path)
    x = blob.decode("utf-8", "replace")
    x = re.sub(r"&lt;", "<", x)
    x = re.sub(r"&gt;", ">", x)
    x = x.replace("&amp;", "&")
    acc_dt = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", x)
    form = re.search(r"CONFORMED SUBMISSION TYPE:\s*(\S[^\n]*)", x)
    subj = re.search(r"SUBJECT COMPANY:.*?CENTRAL INDEX KEY:\s*(\d+)", x, re.S)
    subj_name = re.search(r"SUBJECT COMPANY:.*?COMPANY CONFORMED NAME:\s*([^\n]+)", x, re.S)
    filer = re.search(r"FILED BY:.*?COMPANY CONFORMED NAME:\s*([^\n]+)", x, re.S)
    filer_cik = re.search(r"FILED BY:.*?CENTRAL INDEX KEY:\s*(\d+)", x, re.S)
    members = re.findall(r"GROUP MEMBERS:\s*([^\n]+)", x)
    return {"accession": acc,
            "acceptance": acc_dt.group(1) if acc_dt else None,
            "form": form.group(1).strip() if form else None,
            "subject_cik": int(subj.group(1)) if subj else None,
            "subject_name": subj_name.group(1).strip() if subj_name else None,
            "filer_name": filer.group(1).strip() if filer else None,
            "filer_cik": int(filer_cik.group(1)) if filer_cik else None,
            "group_members": [g.strip() for g in members]}

PREDECESSOR_CIKS = {"DIS": [1001039]}   # TWDC Enterprises era change, 2019
ISSUER_TOKENS = {
    "AAPL": ["APPLE"], "MSFT": ["MICROSOFT"], "AMZN": ["AMAZON"],
    "GOOGL": ["ALPHABET"], "META": ["META PLATFORMS", "FACEBOOK"],
    "BRK-B": ["BERKSHIRE"], "JPM": ["JPMORGAN"], "XOM": ["EXXON"],
    "JNJ": ["JOHNSON & JOHNSON"], "PG": ["PROCTER"], "V": ["VISA"],
    "WMT": ["WALMART", "WAL-MART"], "HD": ["HOME DEPOT"],
    "BAC": ["BANK OF AMERICA"], "CVX": ["CHEVRON"], "PFE": ["PFIZER"],
    "VZ": ["VERIZON"], "T": ["AT&T", "AT AND T"], "DIS": ["DISNEY"],
    "NFLX": ["NETFLIX"], "INTC": ["INTEL"], "CSCO": ["CISCO"],
    "GE": ["GENERAL ELECTRIC"], "IBM": ["INTERNATIONAL BUSINESS MACHINES"],
    "MMM": ["3M"], "UNH": ["UNITEDHEALTH"], "MA": ["MASTERCARD"],
    "KO": ["COCA"], "PEP": ["PEPSICO"], "WFC": ["WELLS FARGO"],
}

def doc_issuer(href):
    """The issuer named on the Schedule 13D cover itself: read the head
    of the full filing text and take the words before '(Name of
    Issuer)'. Returns the raw issuer string (upper-cased) or None."""
    m = re.search(r"/data/(\d+)/(\d+)/(\d+-\d+-\d+)-index\.htm", href)
    if not m:
        return None
    dir_cik, acc_nodash, acc = m.group(1), m.group(2), m.group(3)
    path = os.path.join(DATA, f"doctxt_{acc}.txt")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            blob = f.read()
    else:
        url = (f"https://www.sec.gov/Archives/edgar/data/{dir_cik}/"
               f"{acc_nodash}/{acc}.txt")
        blob = b""
        for i in range(3):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": UA,
                                  "Range": "bytes=0-131071"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    blob = r.read(262144)
                break
            except Exception:  # noqa
                time.sleep(2 * (i + 1))
        if not blob:
            return None
        with open(path, "wb") as f:
            f.write(blob)
    text = blob.decode("utf-8", "replace")
    text = text.replace("&amp;", "&").replace("&#160;", " ")
    text = text.replace("&nbsp;", " ").replace("&#38;", "&")
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    mm = re.search(r"(.{0,120}?)\(\s*Name of Issuer\s*\)", text, re.I)
    if not mm:
        mm = re.search(r"(.{0,120}?)Name of Issuer", text, re.I)
    if not mm:
        return None
    return mm.group(1).strip()[-80:].upper()

def build_census(ciks):
    events, rejected = [], []
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        cik_set = {cik} | set(PREDECESSOR_CIKS.get(t, []))
        cands, seen_acc = [], set()
        for c_ in sorted(cik_set):
            for cand in atom_candidates(c_):
                m = re.search(r"(\d+-\d+-\d+)-index\.htm", cand["href"])
                key = m.group(1) if m else cand["href"]
                if key not in seen_acc:
                    seen_acc.add(key)
                    cands.append(cand)
        kept = [c for c in cands
                if c["form"] == "SC 13D" and CENSUS_START <= c["date"] <= CENSUS_END]
        print(f"{t} (CIK {sorted(cik_set)}): {len(cands)} index entries, "
              f"{len(kept)} initial SC 13D candidates in census window",
              flush=True)
        for c in kept:
            hdr = parse_header(c["href"])
            time.sleep(0.15)
            issuer = doc_issuer(c["href"])
            time.sleep(0.15)
            hdr_ok = bool(hdr) and hdr["subject_cik"] in cik_set \
                and hdr["form"] == "SC 13D"
            doc_ok = None if issuer is None else \
                any(tok in issuer for tok in ISSUER_TOKENS[t])
            if doc_ok is None:
                keep, basis = hdr_ok, "header (document check unresolved)"
            else:
                keep, basis = doc_ok, "document"
            rec = {"ticker": t, "atom": c, "header": hdr,
                   "doc_issuer": issuer, "header_ok": hdr_ok,
                   "doc_ok": doc_ok, "basis": basis,
                   "disagreement": (doc_ok is not None and doc_ok != hdr_ok)}
            if rec["disagreement"]:
                print(f"   HEADER/DOCUMENT DISAGREEMENT: {c['date']} "
                      f"header_subject={hdr['subject_name'] if hdr else None} "
                      f"doc_issuer={issuer} -> decided by {basis}", flush=True)
            if not keep:
                rejected.append(rec)
                print(f"   REJECTED ({basis}): {c['date']} {c['href']} "
                      f"doc_issuer={issuer}", flush=True)
                continue
            a = hdr["acceptance"]
            fdate = f"{a[:4]}-{a[4:6]}-{a[6:8]}"
            ftime = f"{a[8:10]}:{a[10:12]}:{a[12:14]}"
            events.append({"ticker": t, "target_cik": cik,
                           "target_name": hdr["subject_name"],
                           "filer_name": hdr["filer_name"],
                           "filer_cik": hdr["filer_cik"],
                           "group_members": hdr["group_members"],
                           "accession": hdr["accession"],
                           "filed_date": fdate, "filed_time_et": ftime,
                           "acceptance_raw": a,
                           "doc_issuer": issuer, "basis": basis})
            print(f"   EVENT: {fdate} {ftime} ET — {hdr['filer_name']} -> {t} "
                  f"({hdr['accession']}; doc issuer: {issuer})", flush=True)
    events.sort(key=lambda e: (e["filed_date"], e["filed_time_et"], e["ticker"]))
    return events, rejected

# ------------------------------------------------------- long price series
def get_prices_long(ticker, p1="2016-06-01", p2="2026-11-21"):
    """Champion-identical Yahoo parsing, longer window, own cache."""
    path = os.path.join(DATA, f"px_long_{ticker}.json")
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            blob = f.read()
    else:
        import calendar
        t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d"))
        t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
        blob = fetch_cached(url, path, headers={"User-Agent": "Mozilla/5.0"})
    j = json.loads(blob)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, tstamp in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(tstamp))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

# ------------------------------------------------------------ event engine
def entry_day_for(pb, ev, shift_months=0):
    """First trading day whose 09:30 ET open is strictly after the
    (possibly shifted) acceptance timestamp."""
    a = ev["acceptance_raw"]
    base = f"{a[:4]}-{a[4:6]}-{a[6:8]}"
    tsec = int(a[8:10]) * 3600 + int(a[10:12]) * 60 + int(a[12:14])
    if shift_months:
        base = add_months(base, shift_months)
    open_sec = 9 * 3600 + 30 * 60
    for d in pb.dates:
        if d < base:
            continue
        if d == base and tsec >= open_sec:
            continue
        return d
    return None

def exit_day_for(pb, entry_day):
    """First trading day on/after the 12-month anniversary of entry."""
    anniv = add_months(entry_day, 12)
    for d in pb.dates:
        if d >= anniv:
            return d
    return None

def run_event_pot(pb, events, start, end, shift_months=0, label=""):
    """Event-driven pot. events: census dicts (any dates); only events
    FILED inside [start, end] are taken. Returns champion-shaped dict
    plus lot detail and the skip log."""
    cash = START_CASH
    total_costs = 0.0
    trades = []
    lots = []            # open lots: dicts
    closed = []          # finished lot records
    skipped = []
    curve = []
    halted, halt_info = None, None
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    # schedule entries
    sched = {}
    for ev in events:
        if not (start <= ev["filed_date"] <= end):
            continue
        ed = entry_day_for(pb, ev, shift_months=shift_months)
        if ed is None or ed > end:
            skipped.append({**ev, "reason": "no entry day inside window"})
            continue
        sched.setdefault(ed, []).append(ev)
    exits = {}           # day -> [lot ids]
    lot_seq = [0]

    def open_value(d):
        v = cash
        for lot in lots:
            b = pb.bar(lot["ticker"], d)
            px = b["o"] if b else pb.close_on_or_before(lot["ticker"], d)
            if px:
                v += lot["shares"] * px
        return v

    def close_value(d):
        v = cash
        for lot in lots:
            c = pb.close_on_or_before(lot["ticker"], d)
            if c:
                v += lot["shares"] * c
        return v

    def sell_lot(lot, d, price, reason):
        nonlocal cash, total_costs
        val = lot["shares"] * price
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((d, lot["ticker"], "SELL-" + reason, lot["shares"],
                       price, val, c))
        rec = {**lot, "exit_date": d, "exit_price": round(price, 4),
               "exit_reason": reason,
               "proceeds_net": round(val - c, 2),
               "return_pct": round((val - c) / lot["outlay"] * 100 - 100, 2)}
        closed.append(rec)
        return rec

    for di, d in enumerate(days):
        # (1) exits scheduled today, at the open — before entries
        for lid in exits.pop(d, []):
            lot = next((L for L in lots if L["id"] == lid), None)
            if lot is None:
                continue
            b = pb.bar(lot["ticker"], d)
            if b:
                lots.remove(lot)
                sell_lot(lot, d, b["o"], "12MO")
        # (2) entries scheduled today, at the open
        for ev in sched.get(d, []):
            if len(lots) >= 5:
                skipped.append({**ev, "reason": "book full (5 lots open)",
                                "entry_day": d})
                print(f"  [{label}] SKIP {ev['filed_date']} {ev['ticker']} "
                      f"({ev['filer_name']}) — book full", flush=True)
                continue
            pv = open_value(d)
            slice_val = pv / 5.0
            b = pb.bar(ev["ticker"], d)
            if not b:
                skipped.append({**ev, "reason": "no bar on entry day",
                                "entry_day": d})
                continue
            buy_val = min(slice_val, cash / 1.001)
            if buy_val <= 0.005:
                skipped.append({**ev, "reason": "no cash for slice",
                                "entry_day": d})
                continue
            sh = buy_val / b["o"]
            c = buy_val * 0.001
            cash -= buy_val + c
            total_costs += c
            trades.append((d, ev["ticker"], "BUY", sh, b["o"], buy_val, c))
            lot_seq[0] += 1
            xd = exit_day_for(pb, d)
            lot = {"id": lot_seq[0], "ticker": ev["ticker"],
                   "filer_name": ev["filer_name"],
                   "filed_date": ev["filed_date"],
                   "accession": ev["accession"],
                   "entry_date": d, "entry_price": round(b["o"], 4),
                   "shares": sh, "outlay": round(buy_val + c, 2),
                   "exit_due": xd}
            lots.append(lot)
            if xd is not None and xd <= end:
                exits.setdefault(xd, []).append(lot["id"])
            print(f"  [{label}] BUY {d} {ev['ticker']} ${buy_val:,.2f} @ "
                  f"{b['o']:,.2f} (filed {ev['filed_date']} by "
                  f"{ev['filer_name']}; exit due {xd})", flush=True)
        # (3) end of day: floor check
        v = close_value(d)
        curve.append((d, v))
        if v <= FLOOR0 and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": FLOOR0}
            nd = days[di + 1]
            for lot in list(lots):
                b = pb.bar(lot["ticker"], nd)
                if b:
                    lots.remove(lot)
                    sell_lot(lot, nd, b["o"], "HALT")
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "curve": curve,
                    "lots": closed, "skipped": skipped}
    # end of window: liquidate at final close
    last = days[-1]
    for lot in list(lots):
        c_ = pb.close_on_or_before(lot["ticker"], last)
        if c_:
            lots.remove(lot)
            sell_lot(lot, last, c_, "END")
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "curve": curve,
            "lots": closed, "skipped": skipped}

def standalone_event_return(pb, ev):
    """One event on its own: $20 slice, entry open -> exit open at
    12 months (truncated at the last available close if the data ends
    first). SPY over the identical span, identical cost treatment."""
    ed = entry_day_for(pb, ev)
    if ed is None:
        return None
    b = pb.bar(ev["ticker"], ed)
    if not b:
        return None
    xd = exit_day_for(pb, ed)
    truncated = False
    if xd is None:
        xd = pb.dates[-1]
        truncated = True
    xb = pb.bar(ev["ticker"], xd)
    exit_px = xb["o"] if (xb and not truncated) else pb.close_on_or_before(ev["ticker"], xd)
    out = {"entry_date": ed, "entry_price": round(b["o"], 4),
           "exit_date": xd, "exit_price": round(exit_px, 4),
           "truncated": truncated}
    for t, key in ((ev["ticker"], "ret_pct"), ("SPY", "spy_ret_pct")):
        bb = pb.bar(t, ed)
        xx = pb.bar(t, xd)
        xp = xx["o"] if (xx and not truncated) else pb.close_on_or_before(t, xd)
        buy_val = 20.0 / 1.001
        sh = buy_val / bb["o"]
        val = sh * xp
        net = val - (val * 0.001 + 0.01)
        out[key] = round(net / 20.0 * 100 - 100, 2)
    out["abnormal_pct"] = round(out["ret_pct"] - out["spy_ret_pct"], 2)
    return out

def curve_stats(r):
    if r is None:
        return None
    diag = E.diagnostics(r, FLOOR0)
    return {"final": round(r["final"], 2),
            "return_pct": round(r["final"] / START_CASH * 100 - 100, 2),
            "orders": len(r["trades"]), "costs": round(r["costs"], 2),
            "halted": r["halted"], "halt_info": r["halt_info"],
            "max_drawdown_pct": diag["max_drawdown_pct"],
            "worst_close": diag["worst_close"],
            "worst_close_date": diag["worst_close_date"],
            "year_end_closes": diag["year_end_closes"]}

# --------------------------------------------------------------------- main
def build_champion_inputs(ciks):
    equity_rows, shares_rows = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (
            E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
            E.pit_series(facts, "us-gaap",
                         "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                         prio=1))
        shares_rows[t] = (
            E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
            E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
            E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
        time.sleep(0.05)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
    return E.PriceBook(bars), equity_rows, shares_rows

def main():
    ciks = E.get_ciks()
    out = {"strategy": "13D ACTIVIST EVENTS: initial SC 13D on the honest "
                       "top-30, entry next open after filing, 12-month "
                       "hold, 1/5 pot slices, max 5 concurrent, $100, "
                       "plain -15% floor",
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0,
           "champion_published": {"full_final": 544.47,
                                  "validation_final": 288.05,
                                  "full_spy": 313.62,
                                  "validation_spy": 187.77}}

    # ---- (0) replication check on the champion's own caches
    pb_c, equity_rows, shares_rows = build_champion_inputs(ciks)
    for tag, (ws, we), expect, spy_expect in (
            ("FULL", ("2019-01-02", "2026-11-20"), 544.47, 313.62),
            ("VALIDATION", ("2023-01-03", "2026-11-20"), 288.05, 187.77)):
        r = E.run_pot(pb_c, equity_rows, shares_rows, ws, we, START_CASH,
                      FLOOR0, [], label=f"REPL {tag}", quiet=True)
        s, _ = E.spy_net(pb_c, ws, we, START_CASH)
        ok = abs(r["final"] - expect) < 0.005 and abs(s - spy_expect) < 0.005
        print(f"REPLICATION {tag}: champion=${r['final']:,.2f} "
              f"expected=${expect:,.2f} | SPY=${s:,.2f} "
              f"expected=${spy_expect:,.2f} match={ok}", flush=True)
        out[f"replication_{tag.lower()}"] = {
            "champion_final": round(r["final"], 2), "expected": expect,
            "spy_net": round(s, 2), "spy_expected": spy_expect, "match": ok}
        if not ok:
            raise SystemExit("REPLICATION FAILED — variant numbers untrusted")

    # ---- (1) census
    events, rejected = build_census(ciks)
    out["census_count"] = len(events)
    out["census_rejected"] = rejected
    print(f"CENSUS: {len(events)} qualifying initial SC 13D events "
          f"{CENSUS_START} -> {CENSUS_END}", flush=True)

    # ---- long price book for the event engine
    bars_long = {}
    for t in UNIVERSE + ["SPY"]:
        bars_long[t] = get_prices_long(t)
        print(f"{t}: {len(bars_long[t])} long bars "
              f"{bars_long[t][0]['d']}..{bars_long[t][-1]['d']}", flush=True)
    pb = E.PriceBook(bars_long)

    # ---- per-event standalone returns (whole census)
    for ev in events:
        sr = standalone_event_return(pb, ev)
        ev["standalone"] = sr
        if sr:
            print(f"EVENT {ev['filed_date']} {ev['filer_name']} -> "
                  f"{ev['ticker']}: {sr['ret_pct']:+.2f}% vs SPY "
                  f"{sr['spy_ret_pct']:+.2f}% (abnormal "
                  f"{sr['abnormal_pct']:+.2f}%)"
                  f"{' TRUNCATED' if sr['truncated'] else ''}", flush=True)
    out["census"] = events

    # ---- (2) event pots per window (+ placebo where supported)
    for tag, ws, we in WINDOWS:
        spy, _ = E.spy_net(pb_c, ws, we, START_CASH)
        in_window = [ev for ev in events if ws <= ev["filed_date"] <= we]
        r = run_event_pot(pb, events, ws, we, label=f"{tag} 13D")
        st = curve_stats(r)
        st.update({"start": ws, "end": we, "events_in_window": len(in_window),
                   "spy_net_final": round(spy, 2),
                   "lots": r["lots"], "skipped": r["skipped"]})
        print(f"{tag} 13D POT: final=${r['final']:,.2f} "
              f"({st['return_pct']:+.2f}%) events={len(in_window)} "
              f"lots={len(r['lots'])} skipped={len(r['skipped'])} "
              f"costs=${r['costs']:,.2f} halted={r['halted']} | "
              f"SPY=${spy:,.2f}", flush=True)
        if len(in_window) >= 4:
            rp = run_event_pot(pb, events, ws, we, shift_months=6,
                               label=f"{tag} 13D PLACEBO+6M")
            stp = curve_stats(rp)
            stp.update({"lots": rp["lots"], "skipped": rp["skipped"]})
            st["placebo_shift6m"] = stp
            print(f"{tag} PLACEBO (+6mo): final=${rp['final']:,.2f} "
                  f"({stp['return_pct']:+.2f}%) lots={len(rp['lots'])} "
                  f"halted={rp['halted']}", flush=True)
        else:
            st["placebo_shift6m"] = None
            print(f"{tag}: only {len(in_window)} in-window events — "
                  f"date-shifted placebo not supported", flush=True)
        out[tag.lower()] = st

    out["verdict_basis"] = (
        "UNTESTABLE-ON-THIS-POND if census_count < 4" if len(events) < 4
        else "portfolio verdict per Terry's tests (most money, then the "
             "date-shifted placebo, then SPY)")
    with open(os.path.join(HERE, "activist-13d-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
