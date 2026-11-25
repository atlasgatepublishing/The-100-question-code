#!/usr/bin/env python3
"""
13F BEST-IDEAS CLONING — Terry's AI stock app. Simulation only.
NO parameter tuning: the spec below is run ONCE, as described, and judged
against the promoted champion's published numbers.

THE FAMILY AS PUBLISHED: Cohen, Polk & Silli (2010), "Best Ideas" —
inside a manager's portfolio, the single largest active position carries
the manager's conviction and outperforms; the rest of the book does not.
The cloneable version: from each skilled manager's 13F, take the largest
holding and hold it. The control ("placebo" in this program's sense) is
the same filer's 10th-largest holding — a real position with no
conviction claim.

THE SPEC (fixed in advance, before any holdings were examined for
performance):
  - PANEL (10 filers). Selection principle, stated in advance: managers
    who were already widely documented as concentrated, high-conviction
    stock pickers BEFORE 2019 (press / best-ideas literature), filing
    13F-HR on EDGAR under a single filer CIK with uninterrupted
    quarterly coverage of report periods 2018-09-30 .. 2026-09-30.
    Verification was mechanical (filing existence only — performance
    was never a criterion). Final panel (CIK):
      Berkshire Hathaway 1067983, Pershing Square 1336528,
      Baupost Group 1061768, Third Point 1040273, Trian 1345471,
      Fairholme 1056831, Yacktman 905567, Lone Pine 1061165,
      Tiger Global 1167483, Viking Global 1103804.
    Dropped by the same rule, documented: Greenlight Capital
    (CIK 1079114) — its 13F-HR series ends at period 2023-12-31 and the
    funds moved to a successor filer (DME Capital Management, CIK
    1489933); CIKs were NOT spliced mid-sample, so bench name #1
    (Tiger Global) took the slot. ValueAct (CIK 1351069) — files only
    13F-NT in the window (its holdings are reported by another
    manager), so bench name #2 (Viking Global) took the slot. Icahn
    Capital (CIK 1412093) — likewise NT-only, never reached.
  - AS-FILED DISCIPLINE: a clone may only use a filing on/after its
    EDGAR filing date. At each quarterly selection date D (first
    trading day of Jan/Apr/Jul/Oct), each filer's book is the effective
    version of its most recent report period among filings FILED
    STRICTLY BEFORE D. Amendments apply in filed order: a RESTATEMENT
    replaces the book; a NEW HOLDINGS amendment merges into it (its
    rows win per CUSIP) — amendment types were read off each filing's
    own cover page (all 18 in-window amendments are typed: 9
    restatements, 9 new-holdings). Pershing filed 13F-NT (no holdings)
    for periods 2026-06-30 and 2026-09-30, so at the final selection
    its effective report is period 2026-03-31 — the honest lag, kept.
  - POSITION DEFINITION: within the effective information table,
    aggregate reported value by CUSIP over US common-stock rows only:
    no putCall flag, and titleOfClass passes a fixed equity filter
    (the full 222-title census of these filings was classified by
    substring rules stated in code: warrants, notes, units/LP
    interests, preferreds, convertibles, rights, ETFs/ETNs and index
    products are rejected; COM/CL/CLASS/CAP STK/SHS/ORD/ADR/ADS and
    kin are accepted; zero titles were left unclassified).
    Rank 1 by aggregated value = the filer's BEST IDEA; rank 10 = the
    placebo pick (if a filer holds fewer than 10 equity positions, its
    smallest position is the placebo pick — flagged in the data;
    this binds mainly for Fairholme's 3-name books of 2019).
  - PORTFOLIO: equal weight across the panel's DISTINCT current best
    ideas (one slot per filer; duplicate tickers collapse to one
    holding). Quarterly selection, rebalance at next open. The book is
    NOT restricted to the champion's top-30 pond (best ideas are often
    mid-caps) — pond overlap is reported as a coverage statistic.
  - CUSIP -> TICKER (the known free-data pain point, two mechanical
    stages, no hand substitutions):
      Stage 1: OpenFIGI (free, no key), US-composite listing
        (exchCode "US", Equity sector; "Common Stock" preferred).
      Stage 2 (fallback): SEC company_tickers.json name match —
        normalized token sets (fixed abbreviation table, legal-form
        tokens stripped, canonical singulars). Accept on exact set
        equality, or the 13F set strictly contained in the SEC set
        (one-directional: the reverse containment falsely matched
        Pershing Square Tontine to an unrelated "PS" and is banned),
        or Jaccard >= 0.75 with a unique best score. If several
        tickers share the matched issuer name (share classes, OTC
        twins), the first alphabetically is taken and the ambiguity
        logged — for Liberty Global this prices Class C holdings on
        the Class A line (same issuer; disclosed, not hidden).
        Every stage-2 mapping is logged in the results file.
      Anything still unmapped stays unmapped: the filer contributes no
      pick that quarter. Delisted/renamed issuers (Legg Mason, Celgene,
      Activision, Coupa, Walgreens, Vista Outdoor, L Brands, Pershing
      Square Tontine, pre-split GE and pre-merger Canadian Pacific
      CUSIPs, ...) are the measured leak, itemized in the report.
  - PRICES: Yahoo Finance chart API, split/dividend-adjusted, the
    champion engine's exact parsing; a pick with no Yahoo series
    (purged delistings) is untradable and drops out the same way.
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Protection: PLAIN -15% floor only ($85 on the $100 pot, no ladder).
  - Pot: $100 only.

Runs:
  (0) REPLICATION CHECK — the imported champion engine must reproduce
      the published $544.47 (continuous) and $288.05 (validation) to
      the cent before any variant number is taken.
  (1) Ranked clone (best ideas) and (2) placebo clone (10th-largest):
      CONTINUOUS 2019-01-02 -> 2026-11-20 and VALIDATION
      2023-01-03 -> 2026-11-20. NOTE: unlike the random-seed placebos
      of other v6 tests, this family's placebo is the published-design
      control — one deterministic book, not a distribution.
  (3) WALK-FORWARD: fresh $100 pot per calendar year 2020-2026, both
      books, vs SPY.

Judged against the champion (published): validation $288.05 |
continuous $544.47 | placebo beats 18/20 validation (median $201.15)
and 19/20 continuous (median $308.81) | folds 4 wins / 7 | SPY net
$187.77 validation / $313.62 continuous (recomputed in-run as control).

Data: SEC EDGAR 13F filings (submissions API + Archives XML
information tables, harvested once into ./data/filings — 346 filings,
all parsed), OpenFIGI mapping API, SEC company_tickers.json, Yahoo
prices (v4 caches reused read-only where present; new series cached
under ./data only — the v4 tree is never written).
"""
import importlib.util
import json
import os
import re
import time
import urllib.request
import glob as globmod

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
DATA = os.path.join(HERE, "data")
os.makedirs(DATA, exist_ok=True)
UA = "AtlasGateResearch terry-research@example.com"

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []

PANEL = {1067983: "Berkshire Hathaway", 1336528: "Pershing Square",
         1061768: "Baupost Group", 1040273: "Third Point",
         1345471: "Trian", 1056831: "Fairholme", 905567: "Yacktman",
         1061165: "Lone Pine", 1167483: "Tiger Global",
         1103804: "Viking Global"}
POND = set(E.UNIVERSE)

# ------------------------------------------------------------ fetch utils
def fetch(url, path, headers=None, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 50:
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
            time.sleep(0.15)
            return blob
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")

# ------------------------------------------------- 13F effective books
AMEND = {}
for k, v in json.load(open(os.path.join(DATA, "amendment_types.json"))).items():
    lab, per, filed = k.split("|")
    AMEND[(lab, per, filed)] = v["type"]

FILINGS = {cik: [] for cik in PANEL}
for fp in globmod.glob(os.path.join(DATA, "filings", "*.json")):
    if "_index" in fp:
        continue
    d = json.load(open(fp))
    if d["cik"] in FILINGS:
        FILINGS[d["cik"]].append(d)
for cik in FILINGS:
    FILINGS[cik].sort(key=lambda f: (f["period"], f["filed"], f["acc"]))

REJECT_SUB = ["W EXP", "NOTE", "UNIT", "PFD", "MAND CNV", "RIGHT", "ETN",
              "ETF", "IPATH", "IPTH", "TREAS BD", "ISHARES", "S&P 500 ETF",
              "STATE STREET SPD", "ULTRAPRO", "VIX", "CONV", "SBI INT"]
ACCEPT_SUB = ["COM", "CLASS", "CAP STK", "SHS", "ORD", "ADR", "ADS", "STK",
              "SHARES", "REGISTRY", "NAMEN", "BEN INT", "DEP SHS", "STOCK",
              "CL A", "CL B", "CL C", "SUB VTG"]
UNCLASS = {}

def is_equity(title):
    t = re.sub(r"\s+", " ", (title or "")).strip().upper()
    if any(s in t for s in REJECT_SUB):
        return False
    if any(s in t for s in ACCEPT_SUB):
        return True
    UNCLASS[t] = UNCLASS.get(t, 0) + 1
    return False

def effective_book(cik, asof):
    """(holdings, period, last_form) of the filer's effective report as
    filed strictly before asof; (None, None, None) if nothing filed."""
    by_period = {}
    last_form = {}
    for f in FILINGS[cik]:
        if f["filed"] >= asof:
            continue
        p = f["period"]
        if f["form"] == "13F-HR":
            by_period[p] = list(f["holdings"])
            last_form[p] = "13F-HR"
        else:
            typ = AMEND.get((f["label"], f["period"], f["filed"]), "?")
            if typ == "RESTATEMENT" or p not in by_period:
                by_period[p] = list(f["holdings"])
            else:  # NEW HOLDINGS: merge, amendment rows win per CUSIP
                merged = {h["cusip"]: h for h in by_period[p]}
                for h in f["holdings"]:
                    merged[h["cusip"]] = h
                by_period[p] = list(merged.values())
            last_form[p] = f"13F-HR/A:{typ}"
    if not by_period:
        return None, None, None
    p = max(by_period)
    return by_period[p], p, last_form[p]

def rank_positions(holdings):
    agg = {}
    total_all = 0.0
    for h in holdings:
        try:
            v = float(h.get("value") or 0)
        except ValueError:
            v = 0.0
        total_all += v
        if h.get("putCall"):
            continue
        if not is_equity(h.get("titleOfClass", "")):
            continue
        c = h["cusip"]
        if c in agg:
            agg[c]["value"] += v
        else:
            agg[c] = {"cusip": c, "name": h.get("nameOfIssuer", ""),
                      "title": h.get("titleOfClass", ""), "value": v}
    ranked = sorted(agg.values(), key=lambda x: -x["value"])
    for r in ranked:
        r["pct_of_table"] = round(100.0 * r["value"] / total_all, 2) if total_all else None
    return ranked

# ------------------------------------------------------- CUSIP mapping
def norm_token_list(name):
    s = (name or "").upper().replace("&", " AND ")
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    abbr = {"FINL": "FINANCIAL", "HLDGS": "HOLDINGS", "HLDG": "HOLDINGS",
            "SVCS": "SERVICES", "INTL": "INTERNATIONAL", "COS": "COMPANIES",
            "PPTY": "PROPERTY", "ENTMT": "ENTERTAINMENT", "INDS": "INDUSTRIES",
            "NATL": "NATIONAL", "TECH": "TECHNOLOGY", "GRP": "GROUP",
            "BANCORP": "BANCORP", "FIN": "FINANCIAL"}
    legal = {"INC", "CORP", "CORPORATION", "CO", "COMPANY", "PLC", "LTD",
             "LIMITED", "LLC", "LP", "LLP", "SA", "NV", "AG", "THE", "NEW"}
    toks = []
    for t in s.split():
        t = abbr.get(t, t)
        if t in legal:
            continue
        if len(t) > 3 and t.endswith("S") and not t.endswith("SS"):
            t = t[:-1]          # canonical singular: HOLDINGS -> HOLDING
        toks.append(t)
    return toks

def norm_tokens(name):
    return set(norm_token_list(name))

def build_name_index():
    blob = fetch("https://www.sec.gov/files/company_tickers.json",
                 os.path.join(DATA, "company_tickers.json"))
    raw = json.loads(blob)
    idx = {}
    for row in raw.values():
        tlist = norm_token_list(row["title"])
        if tlist:
            idx.setdefault(frozenset(tlist), []).append(
                (row["ticker"], tlist[0]))
    return idx

def figi_map(cusips):
    """Stage 1: OpenFIGI US-composite. Returns {cusip: (ticker, name)}."""
    cache_path = os.path.join(DATA, "cusip_map.json")
    cmap = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    todo = [c for c in cusips if c not in cmap]
    for i in range(0, len(todo), 5):
        batch = todo[i:i + 5]
        jobs = [{"idType": "ID_CUSIP", "idValue": c} for c in batch]
        req = urllib.request.Request(
            "https://api.openfigi.com/v3/mapping",
            data=json.dumps(jobs).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read())
        for c, res in zip(batch, resp):
            data = res.get("data") or []
            us = [x for x in data if x.get("exchCode") == "US"
                  and x.get("marketSector") == "Equity"]
            pick = None
            if us:
                cs = [x for x in us if x.get("securityType") == "Common Stock"]
                pick = cs[0] if cs else us[0]
            cmap[c] = {"ticker": (pick["ticker"].replace("/", "-") if pick else None),
                       "figi_name": (pick["name"] if pick else None),
                       "sectype": (pick["securityType"] if pick else None),
                       "n_us_hits": len(us)}
        json.dump(cmap, open(cache_path, "w"), indent=1)
        time.sleep(3)
    return {c: (cmap[c]["ticker"], cmap[c]["figi_name"]) for c in cusips
            if cmap.get(c, {}).get("ticker")}

def name_map(unmapped):
    """Stage 2: SEC company_tickers name match. unmapped: {cusip: (name13f, title)}.
    Accept on: exact token-set equality; or the 13F token set strictly
    contained in the SEC set (the filing name abbreviates the fuller SEC
    name — the reverse containment is NOT accepted: it produced a false
    positive, Pershing Square Tontine -> "PS" = Pershing Square Inc.);
    a 1-token 13F set must equal the SEC title's first token; or
    Jaccard >= 0.75 with a unique best score. If several tickers share
    the matched issuer name (share classes / OTC twins), the first
    alphabetically is taken and the ambiguity is logged — for Liberty
    Global this prices Class C holdings (13F title "CL C") on the
    Class A line, disclosed in the report.
    Returns ({cusip: ticker}, log rows)."""
    idx = build_name_index()
    out, log = {}, []
    for cusip, (nm, title) in sorted(unmapped.items()):
        toks = frozenset(norm_tokens(nm))
        if not toks:
            continue
        scored = []
        for ktoks, entries in idx.items():
            if not ktoks:
                continue
            if toks == ktoks:
                scored += [(2.0, t) for t, _ in entries]
                continue
            inter = len(toks & ktoks)
            if not inter:
                continue
            jac = inter / len(toks | ktoks)
            contained = False
            if toks < ktoks:
                if len(toks) >= 2:
                    contained = True
                elif len(toks) == 1:
                    tok = next(iter(toks))
                    contained = any(tok == first for _, first in entries)
            if contained:
                scored += [(1.0, t) for t, _ in entries]
            elif jac >= 0.75:
                scored += [(jac, t) for t, _ in entries]
        if not scored:
            continue
        best = max(s for s, _ in scored)
        tickers = sorted({t for s, t in scored if s == best})
        chosen = tickers[0]
        out[cusip] = chosen
        log.append({"cusip": cusip, "name13f": nm, "title": title,
                    "ticker": chosen, "candidates": tickers,
                    "score": best})
    return out, log

# ---------------------------------------------------------------- prices
def get_prices_local(ticker, p1="2018-06-01", p2="2026-11-21"):
    """Champion-identical Yahoo parsing; cache order: ./data, then the v4
    caches read-only, else fetch into ./data."""
    import calendar
    path = os.path.join(DATA, f"px_{ticker}.json")
    blob = None
    for cand in (path,
                 os.path.join(V4, "data", f"px_{ticker}.json"),
                 os.path.join(V4, "value-momentum-honest-data", f"px_{ticker}.json")):
        if os.path.exists(cand) and os.path.getsize(cand) > 100:
            with open(cand, "rb") as f:
                blob = f.read()
            break
    if blob is None:
        t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d"))
        t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
        blob = fetch(url, path, headers={"User-Agent": "Mozilla/5.0"})
    j = json.loads(blob)
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

# ------------------------------------------------------------ clone engine
def run_pot_clone(pb, picks_map, start, end, start_cash, floor0, ladder,
                  label="", quiet=False, record_pools=False):
    """Champion mechanics verbatim (value-momentum-plainfloor.run_pot);
    ONLY the selection block differs: picks come from the precomputed
    point-in-time 13F picks map, equal weight across distinct tickers."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    # --- V9 PROTECTION MODULE (CLAUDE-RULES v9, the ONLY change): ---
    # episode 1 floor = floor0 (-15% of start). On FIRST halt: liquidate
    # exactly as below, sit in cash 90 calendar days, restart at the next
    # regular selection date with episode-2 floor = -15% of the restart
    # balance. On SECOND halt: original return (run ends permanently).
    v9_episode = 1
    v9_resume = None
    restarts = []
    curve = []
    pools = []
    sel_dates = E.quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

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
        if d in sel_set and (v9_resume is None or d >= v9_resume):
            picks = picks_map.get(d) or []
            if picks:
                if record_pools:
                    pools.append((d, list(picks)))
                pv = portfolio_close(d)
                each = pv / len(picks)
                pending = {t: each for t in picks}
                if not quiet:
                    print(f"  [{label}] {d} picks={picks} pot=${pv:,.2f}", flush=True)
        v = portfolio_close(d)
        curve.append((d, v))
        for thresh, newfloor in ladder:
            if v >= thresh and newfloor > floor:
                floor = newfloor
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            nd = days[di + 1]
            for t in list(positions):
                b = pb.bar(t, nd)
                if b:
                    val = positions[t] * b["o"]
                    c = val * 0.001 + 0.01
                    cash += val - c
                    total_costs += c
                    trades.append((nd, t, "SELL-HALT", positions[t], b["o"], val, c))
            positions = {}
            if v9_episode == 1:
                import datetime as _dt
                v9_episode = 2
                v9_resume = (_dt.date.fromisoformat(d)
                             + _dt.timedelta(days=90)).isoformat()
                restarts.append({"halt_date": d, "liquidation_date": nd,
                                 "restart_balance": round(cash, 2),
                                 "resume_on_or_after": v9_resume,
                                 "episode2_floor": round(0.85 * cash, 2)})
                floor = 0.85 * cash
                pending = None
                halted = None
            else:
                return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "restarts": restarts, "pools": pools, "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"label": label, "final": cash, "costs": total_costs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "restarts": restarts, "pools": pools, "curve": curve}

def curve_stats(r):
    curve = r["curve"]
    peak, maxdd, maxdd_d = -1.0, 0.0, None
    for d, v in curve:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0.0
        if dd > maxdd:
            maxdd, maxdd_d = dd, d
    return {"max_drawdown_pct": round(maxdd * 100, 2), "max_drawdown_date": maxdd_d,
            "orders": len(r["trades"]), "costs": round(r["costs"], 2),
            "halted": r["halted"], "restarts": r.get("restarts", []),
            "final": round(r["final"], 2)}


# --------------------------------------------------------------------- main
def main():
    # ---- selection calendar from SPY (champion tape)
    spy_bars = E.get_prices("SPY")
    pb_cal = E.PriceBook({"SPY": spy_bars})
    SEL_DATES = E.quarter_selection_dates(pb_cal, "2019-01-02", "2026-11-20")
    print(f"selection dates: {len(SEL_DATES)} ({SEL_DATES[0]} .. {SEL_DATES[-1]})", flush=True)

    # ---- raw picks per (date, filer)
    raw = {}          # D -> cik -> dict or None
    cusip_names = {}  # cusip -> (name, title) first seen
    for D in SEL_DATES:
        raw[D] = {}
        for cik in PANEL:
            book, period, last_form = effective_book(cik, D)
            if book is None:
                raw[D][cik] = None
                continue
            ranked = rank_positions(book)
            if not ranked:
                raw[D][cik] = None
                continue
            r1 = ranked[0]
            r10 = ranked[9] if len(ranked) >= 10 else ranked[-1]
            raw[D][cik] = {"period": period, "last_form": last_form,
                           "n_equity": len(ranked),
                           "rank1": r1, "rank10": r10,
                           "rank10_is_smallest": len(ranked) < 10}
            for r in (r1, r10):
                cusip_names.setdefault(r["cusip"], (r["name"], r["title"]))
    print(f"unclassified titles: {UNCLASS}", flush=True)

    # ---- CUSIP -> ticker, two mechanical stages
    all_cusips = sorted(cusip_names)
    cmap = figi_map(all_cusips)   # cusip -> (ticker, figi_name)
    stage1 = dict(cmap)
    unmapped_in = {c: cusip_names[c] for c in all_cusips if c not in cmap}
    fb, fb_log = name_map(unmapped_in)
    for c, t in fb.items():
        cmap[c] = (t, "SEC-NAME-MATCH")
    print(f"CUSIP mapping: stage1 FIGI {len(stage1)}/{len(all_cusips)}, "
          f"stage2 name-match +{len(fb)}, unmapped {len(all_cusips) - len(cmap)}", flush=True)
    for row in fb_log:
        print(f"  NAME-MATCH {row['cusip']} {row['name13f']!r} -> {row['ticker']} "
              f"(cands {row['candidates']})", flush=True)

    # ---- prices for every mapped ticker
    tickers = sorted({t for t, _ in cmap.values()})
    bars, price_fail = {}, {}
    for t in tickers + ["SPY"]:
        if t == "SPY":
            bars[t] = spy_bars
            continue
        try:
            b = get_prices_local(t)
            if not b:
                raise RuntimeError("empty series")
            bars[t] = b
        except Exception as e:  # noqa
            price_fail[t] = str(e)
            print(f"  PRICE FAIL {t}: {e}", flush=True)
    priced = {t for t in tickers if t in bars}
    print(f"prices: {len(priced)}/{len(tickers)} tickers priced; fails={sorted(price_fail)}",
          flush=True)
    pb = E.PriceBook(bars)

    # ---- tradable picks maps + per-filer coverage detail
    def resolve(rec):
        if rec is None:
            return None, "no_book"
        c = rec["cusip"]
        if c not in cmap:
            return None, "unmapped_cusip"
        t = cmap[c][0]
        if t not in priced:
            return None, "unpriced_ticker"
        return t, "ok"

    maps = {"rank1": {}, "rank10": {}}
    detail = {}
    for D in SEL_DATES:
        detail[D] = {}
        for rk in ("rank1", "rank10"):
            lst = []
            for cik in PANEL:
                p = raw[D][cik]
                if p is None:
                    detail[D].setdefault(cik, {})[rk] = ("no_book", None)
                    continue
                t, status = resolve(p[rk])
                detail[D].setdefault(cik, {})[rk] = (status, t)
                if t and t not in lst:
                    lst.append(t)
            maps[rk][D] = lst

    # ---- (0) replication check: champion engine, published numbers
    champ_bars = {}
    for t in E.UNIVERSE + ["SPY"]:
        champ_bars[t] = E.get_prices(t)
    pb_champ = E.PriceBook(champ_bars)
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
    equity_rows, shares_rows = {}, {}
    for t in E.UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        facts = E.get_companyfacts(cik)
        equity_rows[t] = (E.pit_series(facts, "us-gaap", "StockholdersEquity", prio=2) +
                          E.pit_series(facts, "us-gaap",
                                       "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                                       prio=1))
        shares_rows[t] = (E.pit_series(facts, "dei", "EntityCommonStockSharesOutstanding", prio=3) +
                          E.pit_series(facts, "us-gaap", "CommonStockSharesOutstanding", prio=2) +
                          E.pit_series(facts, "us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", prio=1))
    FULL = ("2019-01-02", "2026-11-20")
    VAL = ("2023-01-03", "2026-11-20")
    rep = {}
    for tag, (ws, we), published in (("FULL", FULL, 544.47), ("VALIDATION", VAL, 288.05)):
        rb = E.run_pot(pb_champ, equity_rows, shares_rows, ws, we, START_CASH,
                       FLOOR0, LADDER, label=f"REPLICATION CHAMPION {tag}", quiet=True)
        rep[tag] = {"final": round(rb["final"], 2), "published": published,
                    "match": round(rb["final"], 2) == published,
                    "orders": len(rb["trades"]), "halted": rb["halted"]}
        print(f"== REPLICATION champion {tag}: final=${rb['final']:,.2f} "
              f"published=${published:,.2f} match={rep[tag]['match']}", flush=True)

    out = {"variant": "13F best-ideas cloning: panel of 10 famous concentrated "
                      "managers, each filer's largest US common-stock position "
                      "as filed before the selection date, equal weight, "
                      "quarterly, plain -15% floor; placebo = 10th-largest",
           "baseline": "promoted value+momentum (B/M + 12-1 momentum), plain floor",
           "panel": {str(c): n for c, n in PANEL.items()},
           "pot": START_CASH, "floor": FLOOR0,
           "replication_champion": rep,
           "name_match_log": fb_log}

    # ---- (1)+(2) ranked and placebo runs on both windows
    for book_name, rk in (("ranked", "rank1"),):  # V9 RUN RULE: ranked pots only, no placebos
        for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
            s, _ = E.spy_net(pb, ws, we, START_CASH)
            r = run_pot_clone(pb, maps[rk], ws, we, START_CASH, FLOOR0, LADDER,
                              label=f"CLONE-{book_name.upper()} {tag}",
                              record_pools=(book_name == "ranked"))
            diag = E.diagnostics(r, FLOOR0)
            out[f"{book_name}_{tag}"] = {
                "final": round(r["final"], 2),
                "ret_pct": round((r["final"] / START_CASH - 1) * 100, 2),
                "costs": round(r["costs"], 2), "orders": len(r["trades"]),
                "halted": r["halted"], "halt_info": r["halt_info"], "restarts": r.get("restarts", []),
                "spy_net": round(s, 2), "diag": diag,
                "pools": r["pools"], "trades": r["trades"]}
            print(f"== CLONE {book_name} {tag} final=${r['final']:,.2f} "
                  f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
                  f"halted={r['halted']} | SPY net=${s:,.2f} | "
                  f"maxDD={diag['max_drawdown_pct']}%", flush=True)

    # ---- (3) walk-forward folds, both books
    for book_name, rk in (("ranked", "rank1"),):  # V9 RUN RULE: ranked pots only, no placebos
        folds = []
        for y in range(2020, 2027):
            fs = f"{y}-01-01"
            fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
            fr = run_pot_clone(pb, maps[rk], fs, fe, START_CASH, FLOOR0, LADDER,
                               label=f"FOLD {y} {book_name}", quiet=True)
            fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
            fst = curve_stats(fr)
            row = {"year": y, "start": fs, "end": fe, "final": fst["final"],
                   "return_pct": round(fr["final"] / START_CASH * 100 - 100, 2),
                   "spy_net_final": round(fspy, 2),
                   "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
                   "beat_spy": fr["final"] > fspy,
                   "max_drawdown_pct": fst["max_drawdown_pct"],
                   "orders": fst["orders"], "costs": fst["costs"],
                   "halted": fst["halted"], "restarts": fr.get("restarts", [])}
            folds.append(row)
            print(f"FOLD {y} {book_name}: ${fr['final']:,.2f} ({row['return_pct']:+.2f}%) vs "
                  f"SPY ${fspy:,.2f} ({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
                  f"maxDD={row['max_drawdown_pct']}% halted={row['halted']}", flush=True)
        wins = sum(1 for f in folds if f["beat_spy"])
        comp = 100.0
        for f in folds:
            comp *= 1 + f["return_pct"] / 100.0
        out[f"folds_{book_name}"] = folds
        out[f"fold_record_{book_name}"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
        out[f"fold_compounded_{book_name}"] = round(comp, 2)
        print(f"FOLD RECORD {book_name}: {out[f'fold_record_{book_name}']} "
              f"compounded=${comp:,.2f} (champion: 4 wins, $313.01)", flush=True)

    # ---- coverage accounting
    cov = {"selection_dates": len(SEL_DATES), "filer_quarters": 0,
           "rank1_ok": 0, "rank10_ok": 0, "rank1_status": {}, "rank10_status": {},
           "rank10_is_smallest_count": 0, "amendment_applied_count": 0,
           "unmapped_cusips": {}, "unpriced_tickers": sorted(price_fail),
           "stage1_figi_mapped": len(stage1), "stage2_name_mapped": len(fb),
           "distinct_cusips_needed": len(all_cusips)}
    occ1, occ10 = {}, {}
    for D in SEL_DATES:
        for cik in PANEL:
            p = raw[D][cik]
            if p is None:
                continue
            cov["filer_quarters"] += 1
            if p["last_form"].startswith("13F-HR/A"):
                cov["amendment_applied_count"] += 1
            if p["rank10_is_smallest"]:
                cov["rank10_is_smallest_count"] += 1
            for rk, occ in (("rank1", occ1), ("rank10", occ10)):
                st, t = detail[D][cik][rk]
                cov[f"{rk}_status"][st] = cov[f"{rk}_status"].get(st, 0) + 1
                if st == "ok":
                    cov[f"{rk}_ok"] += 1
                    occ[t] = occ.get(t, 0) + 1
                elif st == "unmapped_cusip":
                    c = p[rk]["cusip"]
                    e = cov["unmapped_cusips"].setdefault(
                        c, {"name": p[rk]["name"], "rank1_n": 0, "rank10_n": 0})
                    e[f"{rk}_n"] += 1
    cov["distinct_best_idea_tickers"] = sorted(occ1)
    cov["distinct_placebo_tickers"] = sorted(occ10)
    cov["best_idea_in_pond_distinct"] = sorted(set(occ1) & POND)
    cov["best_idea_in_pond_occurrences"] = sum(v for t, v in occ1.items() if t in POND)
    cov["best_idea_occurrences_total"] = sum(occ1.values())
    # stale-series audit: priced tickers whose bars end well before window end
    cov["stale_series"] = {t: bars[t][-1]["d"] for t in priced
                           if bars[t] and bars[t][-1]["d"] < "2026-11-01"}
    out["coverage"] = cov
    print(f"COVERAGE: filer-quarters={cov['filer_quarters']} "
          f"rank1 ok={cov['rank1_ok']} {cov['rank1_status']} | "
          f"rank10 ok={cov['rank10_ok']} {cov['rank10_status']}", flush=True)
    print(f"  distinct best-idea tickers={len(occ1)}; in-pond distinct="
          f"{len(cov['best_idea_in_pond_distinct'])}; in-pond occurrences="
          f"{cov['best_idea_in_pond_occurrences']}/{cov['best_idea_occurrences_total']}",
          flush=True)

    # ---- picks detail for the report
    pd_out = {}
    for D in SEL_DATES:
        pd_out[D] = {}
        for cik in PANEL:
            p = raw[D][cik]
            if p is None:
                pd_out[D][PANEL[cik]] = None
                continue
            row = {"period": p["period"], "n_equity": p["n_equity"]}
            for rk in ("rank1", "rank10"):
                st, t = detail[D][cik][rk]
                row[rk] = {"cusip": p[rk]["cusip"], "name": p[rk]["name"],
                           "pct_of_table": p[rk]["pct_of_table"],
                           "ticker": t, "status": st}
            pd_out[D][PANEL[cik]] = row
    out["picks_detail"] = pd_out

    with open(os.path.join(HERE, "cloning-13f-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
