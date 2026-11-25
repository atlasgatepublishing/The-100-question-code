#!/usr/bin/env python3
"""
GAP TEST A-5 — LAZY PRICES (Cohen, Malloy & Nguyen 2020, J. Finance 75(3)).
Simulation only. One clean shot, spec frozen from
research/v7-completeness/missing-families.md, Table A, item A-5.

THE RULE AS PUBLISHED / AS SPECIFIED:
  Firms that barely change their 10-K language from one year to the next
  subsequently outperform firms that change it a lot. Signal = whole-document
  cosine similarity of a firm's current 10-K vs its prior-year 10-K (the
  paper's simplest of its four measures — frozen per the spec). Each quarter,
  rank the pond by most recent similarity and hold the top-5 "non-changers,"
  equal weight, until the next quarter.

HOUSE CHASSIS (identical to the champion engine, value-momentum-plainfloor):
  - $100 pot; costs 0.10% of trade value per side + $0.01 per sell order.
  - Plain -15% floor: a close at/below $85.00 liquidates at the next open
    and ends the run. No ladder.
  - Quarterly selection: first trading day of Jan/Apr/Jul/Oct; rebalance
    executes at the NEXT open; sells before buys; end-of-window liquidation
    at the final close.
  - Windows: CONTINUOUS 2019-01-02 -> 2026-11-20 and VALIDATION
    2023-01-03 -> 2026-11-20. Plus fresh-pot calendar-year folds 2020-2026.
  - Placebos: 20 seeds (1..20); on each selection date, sample 5 names at
    random from the same scored pool, same mechanics, same floor.
  - Benchmarks: SPY buy-hold net of the same costs (published: $313.62
    continuous / $187.77 validation — this script's spy_net must reproduce
    them before any A-5 number is trusted); champion reference
    $544.47 / $288.05.
  - Universe: the honest top-30 pond as of Nov 2016 (the champion's list).

FORCED READINGS (declared before any result was seen):
  1. "The document" = the ENTIRE primary 10-K document as filed on EDGAR
     (all items, exhibits embedded in the primary document included as
     filed), with HTML/SGML markup stripped. No section selection: the
     spec freezes the paper's WHOLE-document measure. Documents
     incorporated by reference (e.g. Part III proxy material) are not
     separate filings and are not fetched — the primary document is the
     document, as in the paper's EDGAR-based construction.
  2. Filings counted: form "10-K" only. Amendments (10-K/A) are excluded —
     the signal is the document as originally filed, and an amendment's
     acceptance date would corrupt the point-in-time ordering. (Count of
     excluded 10-K/A filings is reported.)
  3. Timing: a filing is usable only from its EDGAR acceptance date
     (acceptanceDateTime, UTC date). At a selection date d, a name's
     signal is its most recent similarity whose acceptance date is
     STRICTLY BEFORE d — the champion engine's filed-before discipline.
  4. "Prior-year 10-K" = the immediately preceding 10-K filing by the
     same registrant (CIK), in acceptance order. No fiscal-year matching
     is attempted; consecutive filings are compared, as filed.
  5. Text extraction: markup tags removed, HTML entities unescaped, text
     lowercased, tokens = maximal [a-z0-9]+ runs (so numbers are tokens,
     as in the paper's word-count vectors). Similarity = cosine of the
     raw term-frequency vectors. No stemming, no stopword removal, no
     length normalization beyond the cosine itself — the paper's simplest
     measure, unmodified.
  6. A name is scorable at a selection date only if it has at least one
     similarity value by then (>= 2 filed 10-Ks). Names that cannot be
     scored are excluded from that quarter's pool, never patched.
  7. Filings fetched: every 10-K with filing date 2016-01-01..2026-11-20
     (the 2016-2018 filings exist so that the first in-window signals
     rest on real prior-year documents, not on a truncated history).

Data: SEC EDGAR (submissions API + Archives full text, free, UA declared)
+ Yahoo Finance chart API prices reused read-only from the champion's
shared cache (~/workspace/stock-app/backtests/v4/data).
"""
import gzip, html, json, math, os, random, re, sys, time, urllib.request
from collections import Counter
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DOCS = os.path.join(DATA, "docs")
VECS = os.path.join(DATA, "vecs")
for d in (DATA, DOCS, VECS):
    os.makedirs(d, exist_ok=True)
SHARED = os.path.expanduser("~/workspace/stock-app/backtests/v4/data")

UA = "AtlasGateResearch terry-research@example.com"
UNIVERSE = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "BRK-B", "JPM", "XOM",
            "JNJ", "PG", "V", "WMT", "HD", "BAC", "CVX", "PFE", "VZ", "T",
            "DIS", "NFLX", "INTC", "CSCO", "GE", "IBM", "MMM", "UNH", "MA",
            "KO", "PEP", "WFC"]
CIK_OVERRIDES = {"XOM": 34088}   # listed parent, as in the champion engine
PLACEBO_SEEDS = list(range(1, 21))
FETCH_FROM, FETCH_TO = "2016-01-01", "2026-11-20"

# ------------------------------------------------------------------ fetching
def fetch(url, path, headers=None, tries=3, sleep=0.15):
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
            time.sleep(sleep)
            return blob
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"fetch failed {url}: {last}")

def get_ciks():
    with open(os.path.join(SHARED, "company_tickers.json"), "rb") as f:
        raw = json.loads(f.read())
    out = {}
    for row in raw.values():
        out[row["ticker"]] = (int(row["cik_str"]), row["title"])
    return out

def get_filing_index(cik):
    """All filings for a CIK: recent + every additional history file."""
    path = os.path.join(DATA, f"submissions_{cik:010d}.json")
    blob = fetch(f"https://data.sec.gov/submissions/CIK{cik:010d}.json", path)
    j = json.loads(blob)
    blocks = [j["filings"]["recent"]]
    for extra in j["filings"].get("files", []):
        if extra["filingTo"] < "2015-01-01":
            continue
        p2 = os.path.join(DATA, f"submissions_{cik:010d}_{extra['name']}")
        b2 = fetch(f"https://data.sec.gov/submissions/{extra['name']}", p2)
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
                "primary_doc": blk["primaryDocument"][i],
                "period": blk.get("reportDate", [""] * n)[i],
            })
    return rows

def doc_text(blob):
    s = blob.decode("utf-8", errors="ignore")
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = html.unescape(s)
    return s

TOKEN_RE = re.compile(r"[a-z0-9]+")

def get_vector(cik, filing):
    """Term-frequency Counter for one filing, cached as gzipped JSON."""
    acc = filing["accession"]
    vpath = os.path.join(VECS, f"vec_{cik:010d}_{acc}.json.gz")
    if os.path.exists(vpath) and os.path.getsize(vpath) > 100:
        with gzip.open(vpath, "rt") as f:
            return Counter(json.load(f))
    dpath = os.path.join(DOCS, f"{cik:010d}_{acc}_{filing['primary_doc']}")
    url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/"
           f"{acc.replace('-', '')}/{filing['primary_doc']}")
    blob = fetch(url, dpath)
    counts = Counter(TOKEN_RE.findall(doc_text(blob).lower()))
    with gzip.open(vpath, "wt") as f:
        json.dump(dict(counts), f)
    return counts

def cosine(a, b):
    if not a or not b:
        return None
    small, large = (a, b) if len(a) <= len(b) else (b, a)
    dot = sum(c * large.get(tok, 0) for tok, c in small.items())
    na = math.sqrt(sum(c * c for c in a.values()))
    nb = math.sqrt(sum(c * c for c in b.values()))
    if na == 0 or nb == 0:
        return None
    return dot / (na * nb)

def build_signals():
    """Returns (signals, census): signals[ticker] = sorted list of
    (acceptance_date_str, similarity, accession); census = per-ticker
    filing counts for the report."""
    ciks = get_ciks()
    signals, census = {}, {}
    for t in UNIVERSE:
        cik = CIK_OVERRIDES.get(t, ciks[t][0])
        rows = get_filing_index(cik)
        k10 = [r for r in rows if r["form"] == "10-K"
               and FETCH_FROM <= r["filing_date"] <= FETCH_TO]
        ka = [r for r in rows if r["form"] == "10-K/A"
              and FETCH_FROM <= r["filing_date"] <= FETCH_TO]
        k10.sort(key=lambda r: r["acceptance"])
        sigs, prev = [], None
        total_tokens = 0
        for r in k10:
            vec = get_vector(cik, r)
            total_tokens += sum(vec.values())
            if prev is not None:
                sim = cosine(prev, vec)
                if sim is not None:
                    sigs.append((r["acceptance"][:10], round(sim, 6), r["accession"]))
            prev = vec
        signals[t] = sigs
        census[t] = {"cik": cik, "n_10k": len(k10), "n_10ka_excluded": len(ka),
                     "n_similarities": len(sigs),
                     "total_tokens": total_tokens,
                     "first_filing": k10[0]["filing_date"] if k10 else None,
                     "last_filing": k10[-1]["filing_date"] if k10 else None}
        print(f"{t}: CIK {cik} 10-Ks={len(k10)} (10-K/A excluded={len(ka)}) "
              f"similarities={len(sigs)} tokens={total_tokens:,}", flush=True)
    return signals, census

def latest_signal(sigs, asof):
    """Most recent similarity with acceptance date strictly before asof."""
    best = None
    for acc_date, sim, acc in sigs:
        if acc_date < asof:
            best = (acc_date, sim, acc)
        else:
            break
    return best

# ------------------------------------------------------------------- prices
HONEST_DATA = os.path.expanduser(
    "~/workspace/stock-app/backtests/v4/value-momentum-honest-data")

def get_prices(ticker):
    # Same lookup order as the champion engine: shared cache, then the
    # honest cache, else a fresh Yahoo fetch cached into this test's data/.
    path = os.path.join(SHARED, f"px_{ticker}.json")
    if not (os.path.exists(path) and os.path.getsize(path) > 100):
        alt = os.path.join(HONEST_DATA, f"px_{ticker}.json")
        if os.path.exists(alt) and os.path.getsize(alt) > 100:
            path = alt
        else:
            import calendar
            t1 = calendar.timegm(time.strptime("2017-06-01", "%Y-%m-%d"))
            t2 = calendar.timegm(time.strptime("2026-11-21", "%Y-%m-%d"))
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                   f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
            path = os.path.join(DATA, f"px_{ticker}.json")
            fetch(url, path, headers={"User-Agent": "Mozilla/5.0"})
    with open(path, "rb") as f:
        j = json.loads(f.read())
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

class PriceBook:
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        best = None
        for b in self.bars.get(t, []):
            if b["d"] <= d:
                best = b
            else:
                break
        return best["c"] if best else None

def quarter_selection_dates(pb, start, end):
    out, seen = [], set()
    for d in pb.dates:
        if start <= d <= end:
            key = (d[:4], d[5:7])
            if d[5:7] in ("01", "04", "07", "10") and key not in seen:
                seen.add(key)
                out.append(d)
    return out

# ------------------------------------------------------------------- engine
def run_pot(pb, signals, start, end, start_cash=100.0, floor0=85.0,
            placebo_rng=None, label="", record_pools=False):
    """Champion mechanics verbatim; only the scoring differs (top-5 by
    most-recent 10-K similarity)."""
    cash = start_cash
    positions, trades, pools = {}, [], []
    total_costs = 0.0
    halted, halt_info = None, None
    # V9 protection state
    episode = 1
    floor_cur = floor0
    restarts, halts = [], []
    waiting_until = None
    curve = []
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
        if waiting_until is not None and d < waiting_until:
            curve.append((d, cash))
            continue
        if waiting_until is not None and d == waiting_until:
            waiting_until = None
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            scores = {}
            for t in UNIVERSE:
                sig = latest_signal(signals.get(t, []), d)
                if sig is not None:
                    scores[t] = sig[1]
            if len(scores) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    picks = sorted(scores, key=lambda t: -scores[t])[:5]
                if record_pools:
                    pools.append({"date": d, "pool": len(scores),
                                  "scores": {t: round(scores[t], 4)
                                             for t in sorted(scores)},
                                  "picks": list(picks)})
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
        v = portfolio_close(d)
        curve.append((d, v))
        if v <= floor_cur and di < len(days) - 1:
            if halted is None:
                halted = d
                halt_info = {"signal_date": d, "signal_close": round(v, 2),
                             "floor_in_effect": floor_cur}
            halts.append(d)
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
            # V9: first halt -> 90 calendar days in cash, restart at the
            # next quarterly selection date on/after liquidation + 90d.
            if episode == 1:
                from datetime import date as _date, timedelta as _td
                _y, _m, _dd = (int(x) for x in nd.split("-"))
                earliest = (_date(_y, _m, _dd) + _td(days=90)).isoformat()
                restart_sel = next((sd_ for sd_ in sel_dates if sd_ >= earliest), None)
                if restart_sel is not None:
                    episode = 2
                    floor_cur = 0.85 * cash
                    restarts.append({
                        "halt_signal_date": d, "liquidation_date": nd,
                        "restart_date": restart_sel,
                        "restart_balance": round(cash, 2),
                        "episode2_floor": round(floor_cur, 2)})
                    waiting_until = restart_sel
                    continue
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "pools": pools, "curve": curve,
                    "restarts": restarts, "halts": halts}
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
            "trades": trades, "halted": halted, "end": last,
            "halt_info": halt_info, "pools": pools, "curve": curve,
            "restarts": restarts, "halts": halts}

def spy_net(pb, start, end, start_cash=100.0):
    days = [d for d in pb.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = pb.bar("SPY", first)["o"]
    sh = (start_cash / 1.001) / o
    buy_cost = start_cash - sh * o
    c_ = pb.close_on_or_before("SPY", last)
    val = sh * c_
    sell_cost = val * 0.001 + 0.01
    return val - sell_cost, buy_cost + sell_cost

def diagnostics(r, floor0=85.0):
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

def _pct(sorted_vals, q):
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = q * (len(sorted_vals) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac

# ---------------------------------------------------------------------- main
def main():
    """V9 scope: folds 2020 + 2022 (the only folds that halted), the
    continuous-window 20-seed placebos (7 twins halted), and — as a
    verification only — the validation placebos (0 twins halted under
    his rules, so v9 must reproduce them exactly). Ranked main windows
    never halted and are NOT re-run."""
    orig_sim = os.path.expanduser(
        "~/workspace/stock-app/backtests/v7/gap-a5-lazy-prices/data/similarities.json")
    with open(orig_sim) as f:
        blob = json.load(f)
    signals, census = blob["signals"], blob["census"]

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = get_prices(t)
    pb = PriceBook(bars)

    out = {"test": "Gap A-5 Lazy Prices — CLAUDE-RULES v9 re-run",
           "protection": "v9: plain -15% per episode, 90d sit-out, one restart at next quarterly selection, 2nd halt ends",
           "scope": "folds 2020/2022 + continuous placebos re-run; validation placebos verification"}

    # folds that halted under his rules
    folds_v9 = {}
    for y in (2020, 2022):
        ws, we = f"{y}-01-02", f"{y}-12-31"
        sv, _ = spy_net(pb, ws, we)
        r = run_pot(pb, signals, ws, we, label=f"FOLD {y} V9")
        folds_v9[str(y)] = {"final": round(r["final"], 2),
                            "return_pct": round(r["final"] - 100.0, 2),
                            "spy_net": round(sv, 2), "beat_spy": r["final"] > sv,
                            "halts": r["halts"], "restarts": r["restarts"],
                            "orders": len(r["trades"]), "costs": round(r["costs"], 2)}
        print(f"fold {y} V9: ${r['final']:,.2f} vs SPY ${sv:,.2f} "
              f"halts={r['halts']} restarts={r['restarts']}", flush=True)
    out["folds_v9"] = folds_v9

    # placebos: continuous (re-run) + validation (verification)
    ranked_final = {"CONTINUOUS": 504.34, "VALIDATION": 324.12}
    for wname, ws, we in [("CONTINUOUS", "2019-01-02", "2026-11-20"),
                          ("VALIDATION", "2023-01-03", "2026-11-20")]:
        twins = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            tr = run_pot(pb, signals, ws, we, placebo_rng=rng,
                         label=f"{wname} PLACEBO V9 seed {seed}")
            twins.append({"seed": seed, "final": round(tr["final"], 2),
                          "costs": round(tr["costs"], 2),
                          "orders": len(tr["trades"]), "halted": tr["halted"],
                          "halts": tr["halts"], "restarts": tr["restarts"]})
        finals = sorted(tw["final"] for tw in twins)
        beats = sum(1 for x in finals if ranked_final[wname] > x)
        out[wname] = {"placebo_v9": {
            "finals_sorted": finals, "median": round(_pct(finals, 0.5), 2),
            "best": finals[-1], "worst": finals[0],
            "ranked_beats": beats,
            "twin_halts_first": sum(1 for tw in twins if len(tw["halts"]) >= 1),
            "twin_halts_second": sum(1 for tw in twins if len(tw["halts"]) >= 2),
            "twins": twins}}
        print(f"{wname} placebo V9: median=${_pct(finals,0.5):,.2f} "
              f"beats {beats}/20 twins={twins}", flush=True)
    with open(os.path.join(HERE, "v9-raw.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
