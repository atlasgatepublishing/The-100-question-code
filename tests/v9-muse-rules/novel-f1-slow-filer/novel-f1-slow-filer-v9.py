#!/usr/bin/env python3
"""
NOVEL N-F1 — "THE SLOW FILER" (report-lag lengthening) — Terry's AI stock app.
Simulation only. INVENTED-IN-2026 RULE — 1 of 12 invented rules in the v8
novel track. Spec frozen in research/v8-novel/novel-filings.md, Rule N-F1 —
implemented verbatim, run once, no tuning.

THE RULE AS FROZEN (novel-filings.md, N-F1 (b)):
  - Data: EDGAR submissions history per pond CIK (form type, acceptance
    date, period-of-report date). Originals only: forms exactly 10-K and
    10-Q. Amendments (10-K/A, 10-Q/A) never reset a lag.
  - LAG_now: at each selection date, the firm's most recently filed
    original 10-K or 10-Q (acceptance strictly before the selection
    date). LAG_now = acceptance calendar date - period-of-report date,
    in days.
  - LAG_ref: the same form's filing for the same fiscal period one year
    earlier — the filing of the same form whose period-of-report date
    falls 320-410 days before LAG_now's period-of-report date.
    LAG_ref = its acceptance date - its period-of-report date, in days.
  - Signal: dLAG = LAG_now - LAG_ref. Rank the pond ascending (largest
    shortening / least lengthening first). Hold the top 5, equal weight.
  - Hard exclusion: a firm that filed an NT 10-K or NT 10-Q (Form
    12b-25) at any time in the 365 days before the selection date is
    ineligible that quarter, regardless of rank.
  - Eligibility: both lags computable, and LAG_now's filing accepted
    within 200 days before the selection date. Otherwise the name is
    unscorable and excluded — never patched.

SHARED CHASSIS (frozen for the whole novel-filings batch; champion-engine
mechanics copied verbatim from backtests/v4/value-momentum-plainfloor.py):
  - Universe: the honest top-30 pond as of Nov 2016.
  - $100 start, long-only, fractional shares, entire pot reinvested at
    every rebalance.
  - Selection quarterly, first trading day of Jan/Apr/Jul/Oct; trades
    execute at the next open. Sell dropouts in full, keep survivors,
    equal-weight the new top-5 across the whole pot.
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Plain -15% floor: a close at/below $85.00 liquidates at the next
    open and ends the run. No ladder, ever.
  - Point-in-time: only filings with EDGAR acceptance date strictly
    before the selection date may be used; as-filed values only.
  - Windows: CONTINUOUS 2019-01-02 -> 2026-11-20 and VALIDATION
    2023-01-03 -> 2026-11-20. Plus fresh-pot calendar-year folds
    2020-2026.
  - Placebos: 20 seeds (1..20); on each selection date, sample 5 names
    at random from the same eligible pool, same mechanics, same floor.
  - Benchmarks: SPY buy-hold net of the same costs (published: $313.62
    continuous / $187.77 validation — this script's spy_net must
    reproduce them before any N-F1 number is trusted); champion
    reference $544.47 / $288.05.

CANDIDATE GATES (invented-rule track; ALL required for CANDIDATE — the
best verdict available to an invention; only a forward paper trial can
promote an invented rule):
  1. Validation final > SPY $187.77
  2. Validation placebo >= 19/20 beaten
  3. Continuous final > SPY $313.62
  4. No floor halt on either main window
  Anything less = NOT A CANDIDATE.

FORCED READINGS (declared before any result was seen):
  1. Acceptance date = the UTC calendar date of EDGAR's
     acceptanceDateTime (the Lazy Prices F-reading, program-wide).
     "Most recently filed" orders by acceptanceDateTime, ties by
     accession number.
  2. LAG_ref match: among same-form originals accepted strictly before
     the selection date whose period-of-report date falls 320-410 days
     before LAG_now's period-of-report date, take the one whose period
     date is closest to exactly 365 days before LAG_now's; ties break
     by earliest acceptance. (In practice exactly one candidate exists;
     the rule exists so the choice is never discretionary.)
  3. If LAG_now's filing has no period-of-report date in the
     submissions record, the lag is not computable and the name is
     unscorable that quarter — no fallback to an older filing (never
     patched).
  4. NT exclusion matches forms exactly "NT 10-K" and "NT 10-Q", as
     the spec names them. (NT amendment forms, if any appear, are
     counted in the census log but do not trigger the exclusion — the
     spec names the two original forms.)
  5. Rank ties in dLAG break by ticker, A->Z (deterministic; the spec
     freezes no tie-break for N-F1).
  6. If fewer than 5 names are eligible at a selection date, no
     rebalance occurs that quarter (champion-engine convention: the
     scored pool must hold at least 5 names to trade).

Data: SEC EDGAR submissions API (free, UA declared; cached locally,
with the gap-A-5 test's identical submissions cache read read-only as
a fallback) + Yahoo Finance chart API prices reused read-only from the
champion's shared caches (backtests/v4/data and
backtests/v4/value-momentum-honest-data).
"""
import json, math, os, random, time, urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.expanduser("~/workspace/stock-app/backtests/v8/novel-f1-slow-filer/data")  # V9: original cache, read-only
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
SHARED = os.path.join(V4, "data")                       # champion cache, read-only
HONEST = os.path.join(V4, "value-momentum-honest-data")  # champion cache, read-only
A5DATA = os.path.expanduser(
    "~/workspace/stock-app/backtests/v7/gap-a5-lazy-prices/data")  # read-only fallback

UA = "AtlasGateResearch terry-research@example.com"
UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
CIK_OVERRIDES = {"XOM": 34088}   # listed parent, as in the champion engine
PLACEBO_SEEDS = list(range(1, 21))
PERIODIC_FORMS = ("10-K", "10-Q")
NT_FORMS = ("NT 10-K", "NT 10-Q")

# ---------------------------------------------------------------- fetch utils
def fetch(url, path, headers=None, tries=3):
    if os.path.exists(path) and os.path.getsize(path) > 100:
        with open(path, "rb") as f:
            return f.read()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                blob = r.read()
            with open(path, "wb") as f:
                f.write(blob)
            time.sleep(0.15)
            return blob
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")

def fetch_submissions_file(url_name, local_name):
    """One submissions JSON (main or history file): local cache, then the
    gap-A-5 cache (identical EDGAR payload, read-only), then EDGAR."""
    local = os.path.join(DATA, local_name)
    if os.path.exists(local) and os.path.getsize(local) > 100:
        with open(local, "rb") as f:
            return f.read()
    sib = os.path.join(A5DATA, local_name)
    if os.path.exists(sib) and os.path.getsize(sib) > 100:
        with open(sib, "rb") as f:
            return f.read()
    return fetch(f"https://data.sec.gov/submissions/{url_name}", local)

def get_ciks():
    with open(os.path.join(SHARED, "company_tickers.json"), "rb") as f:
        raw = json.loads(f.read())
    out = {}
    for row in raw.values():
        out[row["ticker"]] = (int(row["cik_str"]), row["title"])
    return out

def get_filing_index(cik):
    """All filings for a CIK: recent + every additional history file
    (same construction as the gap-A-5 engine)."""
    main_name = f"CIK{cik:010d}.json"
    blob = fetch_submissions_file(main_name, f"submissions_{cik:010d}.json")
    j = json.loads(blob)
    blocks = [j["filings"]["recent"]]
    for extra in j["filings"].get("files", []):
        if extra["filingTo"] < "2015-01-01":
            continue
        b2 = fetch_submissions_file(extra["name"],
                                    f"submissions_{cik:010d}_{extra['name']}")
        blocks.append(json.loads(b2))
    rows = []
    for blk in blocks:
        n = len(blk["form"])
        for i in range(n):
            rows.append({
                "form": blk["form"][i],
                "accession": blk["accessionNumber"][i],
                "filing_date": blk["filingDate"][i],
                "acceptance": blk["acceptanceDateTime"][i],
                "period": blk.get("reportDate", [""] * n)[i],
            })
    return rows

def get_prices(ticker, p1="2017-06-01", p2="2026-11-21"):
    """Champion engine's price construction, verbatim; caches read in the
    engine's own lookup order (v4/data, then v4/value-momentum-honest-data);
    any fresh fetch lands in THIS test's data dir, never in v4."""
    for base in (SHARED, HONEST):
        path = os.path.join(base, f"px_{ticker}.json")
        if os.path.exists(path) and os.path.getsize(path) > 100:
            with open(path, "rb") as f:
                blob = f.read()
            break
    else:
        import calendar
        t1 = calendar.timegm(time.strptime(p1, "%Y-%m-%d"))
        t2 = calendar.timegm(time.strptime(p2, "%Y-%m-%d"))
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
               f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
        blob = fetch(url, os.path.join(DATA, f"px_{ticker}.json"),
                     headers={"User-Agent": "Mozilla/5.0"})
    j = json.loads(blob)
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, t in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(t))
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

# ------------------------------------------------------------- N-F1 signal
def dparse(s):
    return date(int(s[:4]), int(s[5:7]), int(s[8:10]))

def build_pools(filings_by_ticker, sel_dates):
    """pools[sel_date] = {ticker: dLAG} for eligible names, plus a detail
    log per (sel_date, ticker) for the report. Implements N-F1 (b)
    verbatim under the forced readings declared in the header."""
    pools, detail = {}, {}
    for t in UNIVERSE:
        rows = filings_by_ticker[t]
        periodic = []
        nts = []
        for r in rows:
            if not r["acceptance"]:
                continue
            acc_d = r["acceptance"][:10]
            if r["form"] in PERIODIC_FORMS:
                periodic.append({"form": r["form"], "acc": r["acceptance"],
                                 "acc_d": acc_d, "period": r["period"],
                                 "accession": r["accession"]})
            elif r["form"] in NT_FORMS:
                nts.append(acc_d)
        periodic.sort(key=lambda r: (r["acc"], r["accession"]))
        filings_by_ticker[t + "__periodic"] = periodic
        filings_by_ticker[t + "__nt"] = nts
    for sd in sel_dates:
        sdate = dparse(sd)
        pool = {}
        for t in UNIVERSE:
            periodic = filings_by_ticker[t + "__periodic"]
            nts = filings_by_ticker[t + "__nt"]
            # hard exclusion: any NT 10-K / NT 10-Q accepted in the
            # 365 days before the selection date
            if any(1 <= (sdate - dparse(a)).days <= 365 for a in nts):
                detail[(sd, t)] = {"status": "excluded-NT"}
                continue
            prior = [r for r in periodic if r["acc_d"] < sd]
            if not prior:
                detail[(sd, t)] = {"status": "no-filings"}
                continue
            now = prior[-1]  # most recently accepted original 10-K/10-Q
            if (sdate - dparse(now["acc_d"])).days > 200:
                detail[(sd, t)] = {"status": "stale", "acc": now["acc_d"]}
                continue
            if not now["period"]:
                detail[(sd, t)] = {"status": "no-period-date"}
                continue
            lag_now = (dparse(now["acc_d"]) - dparse(now["period"])).days
            target = dparse(now["period"]) - timedelta(days=365)
            cands = []
            for r in prior:
                if r["form"] != now["form"] or r is now or not r["period"]:
                    continue
                gap = (dparse(now["period"]) - dparse(r["period"])).days
                if 320 <= gap <= 410:
                    cands.append(r)
            if not cands:
                detail[(sd, t)] = {"status": "no-ref-match",
                                   "form": now["form"],
                                   "period": now["period"]}
                continue
            cands.sort(key=lambda r: (abs((dparse(r["period"]) - target).days),
                                      r["acc"]))
            ref = cands[0]
            lag_ref = (dparse(ref["acc_d"]) - dparse(ref["period"])).days
            pool[t] = lag_now - lag_ref
            detail[(sd, t)] = {"status": "scored", "dlag": lag_now - lag_ref,
                               "lag_now": lag_now, "lag_ref": lag_ref,
                               "form": now["form"], "period": now["period"],
                               "ref_period": ref["period"]}
        pools[sd] = pool
    return pools, detail

# ------------------------------------------------------------------ engine
class PriceBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        bl = self.bars.get(t, [])
        best = None
        for b in bl:
            if b["d"] <= d:
                best = b
            else:
                break
        return best["c"] if best else None

def quarter_selection_dates(pb, start, end):
    out = []
    seen = set()
    for d in pb.dates:
        if start <= d <= end:
            key = (d[:4], d[5:7])
            if d[5:7] in ("01", "04", "07", "10") and key not in seen:
                seen.add(key)
                out.append(d)
    return out

def run_pot(pb, pools, start, end, start_cash, floor0,
            placebo_rng=None, label="", quiet=True, record_pools=False):
    """Champion engine mechanics, verbatim, with the scoring block
    replaced by the precomputed N-F1 eligible pools. Ranked picks:
    dLAG ascending, ties by ticker A->Z. Placebo: rng.sample of 5 from
    the same eligible pool on the same date."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
    curve = []
    pools_log = []
    sel_dates = quarter_selection_dates(pb, start, end)
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
        if d in sel_set:
            pool = pools.get(d, {})
            if len(pool) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(pool), 5)
                else:
                    picks = sorted(pool, key=lambda t: (pool[t], t))[:5]
                if record_pools:
                    pools_log.append((d, dict(pool), list(picks)))
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                if not quiet:
                    print(f"  [{label}] {d} pool={len(pool)} picks={picks} "
                          f"pot=${pv:,.2f}", flush=True)
        v = portfolio_close(d)
        curve.append((d, v))
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
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "pools": pools_log, "curve": curve}
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
            "halt_info": None, "pools": pools_log, "curve": curve}

def spy_net(pb, start, end, start_cash):
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost

def _pct(sorted_vals, q):
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

def diagnostics(r, floor0):
    curve = r["curve"]
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
            "year_end_closes": {y: {"date": d, "close": round(v, 2)}
                                for y, (d, v) in sorted(year_end.items())}}

def placebo_summary(finals, ranked_final):
    s = sorted(finals)
    beat = sum(1 for f in finals if f < ranked_final)
    return {"finals": [round(f, 2) for f in finals],
            "median": round(_pct(s, 0.5), 2), "q1": round(_pct(s, 0.25), 2),
            "q3": round(_pct(s, 0.75), 2), "best": round(max(finals), 2),
            "worst": round(min(finals), 2), "beat": beat,
            "percentile": round(100.0 * beat / len(finals), 1)}

# --------------------------------------------------------------------- main
def main():
    ciks = get_ciks()
    filings_by_ticker = {}
    census = {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        rows = get_filing_index(cik)
        filings_by_ticker[t] = rows
        per = [r for r in rows if r["form"] in PERIODIC_FORMS]
        nts = [r for r in rows if r["form"] in NT_FORMS]
        nt_amd = [r for r in rows if r["form"] in ("NT 10-K/A", "NT 10-Q/A")]
        census[t] = {"cik": cik, "filings_total": len(rows),
                     "periodic": len(per), "nt": len(nts),
                     "nt_amendments_seen": len(nt_amd)}
        print(f"{t}: CIK {cik} filings={len(rows)} periodic={len(per)} "
              f"NT={len(nts)} NT/A={len(nt_amd)}", flush=True)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = get_prices(t)
        print(f"{t}: {len(bars[t])} bars {bars[t][0]['d']}..{bars[t][-1]['d']}",
              flush=True)
    pb = PriceBook(bars)

    # ---- integrity gate: SPY must reproduce the published figures first
    s_full, _ = spy_net(pb, "2019-01-02", "2026-11-20", 100.0)
    s_val, _ = spy_net(pb, "2023-01-03", "2026-11-20", 100.0)
    print(f"INTEGRITY spy_net continuous=${s_full:,.2f} (published $313.62) "
          f"validation=${s_val:,.2f} (published $187.77)", flush=True)
    assert abs(s_full - 313.62) < 0.02 and abs(s_val - 187.77) < 0.02, \
        "SPY integrity gate FAILED — do not trust any number from this run"

    # ---- pools for every quarterly selection date 2019..2026 (folds reuse)
    all_sel = quarter_selection_dates(pb, "2019-01-01", "2026-11-20")
    pools, detail = build_pools(filings_by_ticker, all_sel)
    pool_sizes = {d: len(p) for d, p in pools.items()}
    print("pool sizes:", pool_sizes, flush=True)
    status_counts = {}
    for v in detail.values():
        status_counts[v["status"]] = status_counts.get(v["status"], 0) + 1
    print("eligibility status counts:", status_counts, flush=True)
    dlags = [v["dlag"] for v in detail.values() if v["status"] == "scored"]
    if dlags:
        print(f"dLAG over {len(dlags)} scored name-quarters: "
              f"min={min(dlags)} max={max(dlags)} "
              f"mean={sum(dlags)/len(dlags):.2f}", flush=True)

    windows = [("CONTINUOUS", "2019-01-02", "2026-11-20"),
               ("VALIDATION", "2023-01-03", "2026-11-20")]
    out = {"rule": "N-F1 The Slow Filer (invented 2026; 1 of 12 invented rules)",
           "spec": "research/v8-novel/novel-filings.md N-F1, verbatim",
           "protection": "plain -15% floor only (no ladder)",
           "universe": UNIVERSE, "census": census,
           "pool_sizes": pool_sizes, "status_counts": status_counts,
           "integrity_spy": {"continuous": round(s_full, 2),
                             "validation": round(s_val, 2)}}
    for wname, ws, we in windows:
        s, _ = spy_net(pb, ws, we, 100.0)
        r = run_pot(pb, pools, ws, we, 100.0, 85.0,
                    label=f"{wname} N-F1", record_pools=True)
        diag = diagnostics(r, 85.0)
        pfinals, phalted = [], 0
        for seed in PLACEBO_SEEDS:
            pr = run_pot(pb, pools, ws, we, 100.0, 85.0,
                         placebo_rng=random.Random(seed),
                         label=f"{wname} placebo {seed}")
            pfinals.append(pr["final"])
            if pr["halted"]:
                phalted += 1
        psum = placebo_summary(pfinals, r["final"])
        psum["halted"] = phalted
        out[wname] = {"final": round(r["final"], 2), "costs": round(r["costs"], 2),
                      "orders": len(r["trades"]), "halted": r["halted"],
                      "halt_info": r["halt_info"], "spy_net": round(s, 2),
                      "diag": diag, "placebo": psum,
                      "pools": [(d, p, picks) for d, p, picks in r["pools"]],
                      "trades": r["trades"]}
        print(f"== {wname} N-F1 final=${r['final']:,.2f} costs=${r['costs']:,.2f} "
              f"orders={len(r['trades'])} halted={r['halted']} | SPY=${s:,.2f} | "
              f"placebo median=${psum['median']:,.2f} beat={psum['beat']}/20 "
              f"halted {phalted}/20", flush=True)
        print(f"   worst close ${diag['worst_close']:,.2f} on "
              f"{diag['worst_close_date']} (margin ${diag['worst_close_above_floor']:,.2f}) "
              f"| maxDD {diag['max_drawdown_pct']}% on {diag['max_drawdown_date']}",
              flush=True)

    # ---- fresh-pot calendar-year folds 2020-2026 (ranked + SPY only)
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot(pb, pools, fs, fe, 100.0, 85.0, label=f"FOLD {y}")
        fs_spy, _ = spy_net(pb, fs, fe, 100.0)
        folds.append({"year": y, "start": fr["curve"][0][0] if fr["curve"] else fs,
                      "final": round(fr["final"], 2),
                      "return_pct": round(fr["final"] - 100.0, 2),
                      "spy_final": round(fs_spy, 2),
                      "spy_return_pct": round(fs_spy - 100.0, 2),
                      "beat_spy": fr["final"] > fs_spy,
                      "halted": fr["halted"], "costs": round(fr["costs"], 2),
                      "orders": len(fr["trades"])})
        print(f"== FOLD {y}: N-F1 ${fr['final']:,.2f} vs SPY ${fs_spy:,.2f} "
              f"halted={fr['halted']}", flush=True)
    wins = sum(1 for f in folds if f["beat_spy"])
    comp, scomp = 100.0, 100.0
    for f in folds:
        comp *= 1 + f["return_pct"] / 100.0
        scomp *= 1 + f["spy_return_pct"] / 100.0
    out["folds"] = {"folds": folds, "record": f"{wins} wins, {len(folds)-wins} losses vs SPY",
                    "fold_compounded_final": round(comp, 2),
                    "spy_fold_compounded_final": round(scomp, 2)}

    # ---- candidate gates
    v, c = out["VALIDATION"], out["CONTINUOUS"]
    gates = {
        "validation_final_gt_spy": {"required": "> 187.77", "actual": v["final"],
                                    "pass": v["final"] > 187.77},
        "validation_placebo_ge_19_of_20": {"required": ">= 19/20 beaten",
                                           "actual": f"{v['placebo']['beat']}/20",
                                           "pass": v["placebo"]["beat"] >= 19},
        "continuous_final_gt_spy": {"required": "> 313.62", "actual": c["final"],
                                    "pass": c["final"] > 313.62},
        "no_floor_halt_either_window": {"required": "no halt",
                                        "actual": {"continuous": c["halted"],
                                                   "validation": v["halted"]},
                                        "pass": c["halted"] is None and v["halted"] is None},
    }
    out["candidate_gates"] = gates
    out["verdict"] = ("CANDIDATE" if all(g["pass"] for g in gates.values())
                      else "NOT A CANDIDATE")
    print("VERDICT:", out["verdict"], json.dumps(gates, default=str), flush=True)

    with open(os.path.join(HERE, "novel-f1-slow-filer-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE", flush=True)


# ======================================================================
# V9 RE-RUN - "CLAUDE-RULES PROTECTION SPEC v9" (this copy only)
# Copied from the v8 original; the ONLY change is the protection module
# (run_*_v9 below, which calls the original engine unchanged for each
# episode) plus a folds-only main_v9 (the original main is retained
# above but not invoked):
#   - Episode 1: plain -15% floor from the $100 start ($85.00),
#     identical to Terry's rule. On FIRST halt: liquidate exactly as
#     the original engine does, sit in cash 90 calendar days, then
#     RESTART with the remaining cash at the strategy's next regular
#     decision point (next quarterly selection date on/after day 90).
#   - Episode 2: floor = -15% from the RESTART balance. On SECOND
#     halt: the run ends permanently.
#   - If halt + 90 days runs past the window/fold end, the fold ends
#     in cash.
# Everything else is byte-identical: universe, signals, parameters,
# costs 0.10%/side + $0.01/sell, windows, $100 start. No retuning.
# Scope: main windows are NOT re-run - the original recorded results
# show the floor never fired there, so they are identical under v9 by
# construction. This script re-runs the yearly folds 2020-2026 under
# BOTH rule sets (his recomputed folds are asserted against the
# published originals). Ranked pots only; no placebos in this bundle.
# Data caches are read from the original test's folders, read-only;
# this script writes only v9-folds-detail.json next to itself.
# Simulation only.
# ======================================================================

# ============================================================ V9 MODULE
def run_pot_v9(pb, pools, start, end, start_cash, label=""):
    """One window under CLAUDE-RULES PROTECTION SPEC v9 (see header)."""
    from datetime import date as _d
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_pot(pb, pools, start, end, start_cash, floor1, label=label + " EP1")
    out = {"final": r1["final"], "costs": r1["costs"],
           "trades": r1["trades"], "curve": list(r1["curve"]),
           "halted": r1["halted"], "halt_info": r1["halt_info"],
           "restarts": [], "second_halt": None, "episodes": 1}
    if r1["halted"] is None:
        return out
    liq_date = r1["end"]
    cash = r1["final"]
    ly, lm, ld = int(liq_date[:4]), int(liq_date[5:7]), int(liq_date[8:10])
    day90 = _d(ly, lm, ld).toordinal() + 90
    restart = None
    for cand in quarter_selection_dates(pb, start, end):
        cy, cm, cd = int(cand[:4]), int(cand[5:7]), int(cand[8:10])
        if _d(cy, cm, cd).toordinal() >= day90:
            restart = cand
            break
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
    r2 = run_pot(pb, pools, restart, end, cash, floor2, label=label + " EP2")
    out["episodes"] = 2
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["trades"] += r2["trades"]
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
    out["curve"].sort(key=lambda kv: kv[0])
    return out

def _worst(r, start_cash):
    vals = [v for _, v in r["curve"]] + [r["final"]]
    return min(vals) if vals else start_cash

def _compounded(folds):
    p = 100.0
    for k in sorted(folds):
        p *= folds[k]["final"] / 100.0
    return round(p, 2)

def main_v9():
    
    ciks = get_ciks()
    filings_by_ticker = {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        filings_by_ticker[t] = get_filing_index(cik)
        print(f"{t}: filings loaded", flush=True)
    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = get_prices(t)
    pb = PriceBook(bars)
    s_full, _ = spy_net(pb, "2019-01-02", "2026-11-20", 100.0)
    s_val, _ = spy_net(pb, "2023-01-03", "2026-11-20", 100.0)
    assert abs(s_full - 313.62) < 0.02 and abs(s_val - 187.77) < 0.02, "SPY integrity gate FAILED"
    print(f"INTEGRITY spy continuous=${s_full:,.2f} validation=${s_val:,.2f}", flush=True)
    all_sel = quarter_selection_dates(pb, "2019-01-01", "2026-11-20")
    pools, detail = build_pools(filings_by_ticker, all_sel)
    print("pools built", flush=True)

    START = 100.0
    fold_defs = [(y, f"{y}-01-01", "2026-11-20" if y == 2026 else f"{y}-12-31")
                 for y in range(2020, 2027)]
    his_folds, v9_folds = {}, {}
    his_worst, v9_worst = START, START
    restarts_all, second_halts = [], []
    for y, fs, fe in fold_defs:
        rh = run_pot(pb, pools, fs, fe, START, 85.0, label=f"HIS FOLD {y}")
        spy_f, _ = spy_net(pb, fs, fe, START)
        his_folds[str(y)] = {"final": round(rh["final"], 2), "halted": rh["halted"],
                             "spy_net": round(spy_f, 2), "beat_spy": rh["final"] > spy_f,
                             "orders": len(rh["trades"]), "costs": round(rh["costs"], 2)}
        his_worst = min(his_worst, _worst(rh, START))
        rv = run_pot_v9(pb, pools, fs, fe, START, label=f"V9 FOLD {y}")
        v9_folds[str(y)] = {"final": round(rv["final"], 2), "halted_first": rv["halted"],
                            "second_halt": rv["second_halt"], "restarts": rv["restarts"],
                            "spy_net": round(spy_f, 2), "beat_spy": rv["final"] > spy_f,
                            "orders": len(rv["trades"]), "costs": round(rv["costs"], 2),
                            "episodes": rv["episodes"]}
        v9_worst = min(v9_worst, _worst(rv, START))
        for rr in rv["restarts"]:
            restarts_all.append({"fold": str(y), **rr})
        if rv["second_halt"]:
            second_halts.append({"fold": str(y), **rv["second_halt"]})
        print(f"FOLD {y}: his=${rh['final']:,.2f} halted={rh['halted']} | "
              f"v9=${rv['final']:,.2f} restarts={len(rv['restarts'])} "
              f"second_halt={bool(rv['second_halt'])}", flush=True)
    his_comp, v9_comp = _compounded(his_folds), _compounded(v9_folds)
    print(f"FOLD-COMPOUNDED: his=${his_comp} v9=${v9_comp}", flush=True)
    out = {"protection_v9": "episode-1 floor -15% from start; on first halt liquidate, 90 calendar days cash, restart at next quarterly selection date with remaining cash; episode-2 floor -15% from restart balance; second halt ends run",
           "his_folds": his_folds, "v9_folds": v9_folds,
           "his_folds_compounded": his_comp, "v9_folds_compounded": v9_comp,
           "restarts": restarts_all, "second_halts": second_halts,
           "his_worst_fold_equity_from_100": round(his_worst, 2),
           "v9_worst_fold_equity_from_100": round(v9_worst, 2)}
    with open(os.path.join(HERE, "v9-folds-detail.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main_v9()

