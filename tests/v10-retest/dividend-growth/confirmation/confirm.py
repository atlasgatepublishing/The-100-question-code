#!/usr/bin/env python3
"""
DIVIDEND-GROWTH CONFIRMATION RUN (v10 GREAT RETEST) — simulation only.

Cross-year confirmation of the three DECADE money cadences from the
dividend-growth cadence sweep (weekly $415.97 20/20, biweekly $433.37
20/20, monthly $419.55 18/20 vs SPY $367.80), per the SPEC CONFIRMATION
RULE: a changed verdict / new money cadence must be re-run on the OTHER
roads (LONG, CONT, VAL) plus fresh yearly folds before it counts.

Mechanics are IDENTICAL to the sweep: this script imports the sweep
folder's sweep.py (read-only) and calls its run_pot_div / eligibility /
cadence_dates / cell_stats verbatim — same $100 start, same program
costs (0.10%/side + $0.01 per sell order), same point-in-time EDGAR
no-cut >=6yr dividend screen ranked by 5y dividend growth, top 5 equal
weight, raw split-adjusted prices + ex-date cash dividend credits, same
v9 protections (plain -15% floor from episode start, 90-day cash sit,
one restart at -15% of restart balance, second halt ends).

The ONLY local change is plumbing: a bisect-based PriceBook with the
same interface as the champion engine's (bar / close_on_or_before /
dates) so the 2010-start LONG road is computable in shared RAM/time.
The integrity gate below proves the plumbing: the decade biweekly cell
must reproduce $433.37 and all 20 placebo twin finals exactly before
any other number in this folder counts.

DATA (loaded narrowly, per ticker, never bulk):
  - DECADE/CONT/VAL roads: the sweep folder's own decade Yahoo blobs
    (data/px_<t>.json, 2016-11-01 -> 2026-11-20) — the exact price
    source the sweep's numbers came from.
  - LONG road + folds: full-range Yahoo pxfull_<t>.json payloads
    (2008-01-02 -> 2026-11-20) read read-only from
    backtests/v7/long-hold/data/ (the long-run-2010 plumbing's price
    cache, md5-verified there against the program's own copies).
    GOOGL had no pxfull file there; a fresh pull of the same Yahoo
    chart channel is cached in this folder's data/pxfull_GOOGL.json.
    (GOOGL paid no dividend until 2024, so it cannot enter the
    6-year no-cut pool anywhere in these windows regardless.)
  - EDGAR companyfacts: the sweep's own channel — E.get_companyfacts
    reading the v4 shared cache read-only. Companyfacts are full
    history, so DPS chains filed before 2010 are point-in-time
    available for the LONG road; nothing is backfilled.
"""
import bisect, importlib.util, json, os, random, sys, time
from datetime import date as _d

HERE = os.path.dirname(os.path.abspath(__file__))
DG = os.path.dirname(HERE)                       # dividend-growth/ (read-only)
BT = os.path.expanduser("~/workspace/stock-app/backtests")
LH_DATA = os.path.join(BT, "v7", "long-hold", "data")

spec = importlib.util.spec_from_file_location("dg_sweep", os.path.join(DG, "sweep.py"))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
E = S.E
UNIVERSE = S.UNIVERSE
SEEDS = S.PLACEBO_SEEDS
END = "2026-11-20"

# ------------------------------------------------------------ fast PriceBook
class FastPriceBook:
    """Same interface/semantics as E.PriceBook (bar, close_on_or_before,
    dates) with bisect lookups. close_on_or_before returns the close of
    the last bar with date <= d, exactly like the original linear scan."""
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values() for b in bl})
        self.idx = {t: {b["d"]: b for b in bl} for t, bl in bars_by_ticker.items()}
        self._dl = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        dl = self._dl.get(t)
        if not dl:
            return None
        i = bisect.bisect_right(dl, d) - 1
        if i < 0:
            return None
        return self.bars[t][i]["c"]

# ------------------------------------------------------------ market loaders
def parse_payload(j):
    """Raw (split-adjusted, dividend-UNadjusted) bars + dividend events
    + split events from a Yahoo chart payload — the sweep's
    load_raw_market construction, per ticker."""
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    bl = []
    for i, tt in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(tt))
        c = q["close"][i]
        if c is None:
            continue
        o = q["open"][i] if q["open"][i] else c
        bl.append({"d": d, "o": o, "c": c})
    bl.sort(key=lambda b: b["d"])
    dv = {}
    for k, v in res.get("events", {}).get("dividends", {}).items():
        d = time.strftime("%Y-%m-%d", time.gmtime(int(k)))
        dv[d] = dv.get(d, 0.0) + float(v["amount"])
    sp = []
    for k, v in res.get("events", {}).get("splits", {}).items():
        d = time.strftime("%Y-%m-%d", time.gmtime(int(k)))
        sp.append((d, float(v["numerator"]) / float(v["denominator"])))
    return bl, dv, sorted(sp)

def adj_bars(j):
    """Dividend-adjusted bars (champion convention: adjclose ratio
    applied to OHLC) from a Yahoo chart payload."""
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose")
    bars = []
    for i, tt in enumerate(ts):
        d = time.strftime("%Y-%m-%d", time.gmtime(tt))
        o, c = q["open"][i], q["close"][i]
        if c is None:
            continue
        a = adj[i] if adj and adj[i] else c
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars

def load_market(source):
    """source='decade': sweep folder blobs. source='full': v7 long-hold
    pxfull payloads (GOOGL from this folder's data/). Returns
    (raw_pb, adj_spy_pb, divs, splits). One ticker at a time."""
    bars, divs, splits = {}, {}, {}
    spy_adj = None
    for t in UNIVERSE + ["SPY"]:
        if source == "decade":
            p = os.path.join(DG, "data", f"px_{t}.json")
        else:
            p = os.path.join(LH_DATA, f"pxfull_{t}.json")
            if not os.path.exists(p):
                p = os.path.join(HERE, "data", f"pxfull_{t}.json")
        with open(p, "rb") as f:
            j = json.loads(f.read())
        bl, dv, sp = parse_payload(j)
        bars[t] = bl
        divs[t] = dv
        splits[t] = sp
        if t == "SPY":
            spy_adj = adj_bars(j)
        del j
    return FastPriceBook(bars), FastPriceBook({"SPY": spy_adj}), divs, splits

# ------------------------------------------------------------ eligibility
class PoolBuilder:
    def __init__(self, splits):
        ciks = E.get_ciks()
        self.facts, self.filed_idx = {}, {}
        for t in UNIVERSE:
            cik = 34088 if t == "XOM" else ciks[t][0]
            self.facts[t] = E.get_companyfacts(cik)
            fds = sorted({e[2] for c in ("CommonStockDividendsPerShareDeclared",
                                         "CommonStockDividendsPerShareCashPaid")
                          for e in S.dps_entries(self.facts[t], c)})
            self.filed_idx[t] = fds
        self.splits = splits
        self.cache = {}

    def pool_at(self, d):
        ranked = []
        for t in UNIVERSE:
            key = (t, bisect.bisect_left(self.filed_idx[t], d))
            if key not in self.cache:
                self.cache[key] = S.eligibility(self.facts[t], d,
                                                self.splits.get(t, []))
            res = self.cache[key]
            if res is not None:
                ranked.append((t, res[0]))
        ranked.sort(key=lambda kv: (-kv[1], kv[0]))
        return ranked

    def pools_for(self, sel_dates):
        return {d: self.pool_at(d) for d in sel_dates}

# ------------------------------------------------------------ run helpers
def run_cell(pb, divs, pools_builder, cadence, start, end, with_placebos=True):
    sels = S.cadence_dates(pb.dates, cadence, start, end)
    pools = pools_builder.pools_for(sels)
    r = S.run_pot_div(pb, divs, pools, start, end, label=f"{cadence} {start}",
                      sel_dates=sels)
    st = S.cell_stats(r, start, end)
    out = dict(st)
    out["window"] = [start, end]
    out["cadence"] = cadence
    out["n_selection_dates"] = len(sels)
    out["pool_sizes"] = [len(pools[d]) for d in sels]
    if with_placebos:
        finals = []
        for seed in SEEDS:
            rng = random.Random(seed)
            pr = S.run_pot_div(pb, divs, pools, start, end, placebo_rng=rng,
                               label=f"PLB {cadence} {start} {seed}", sel_dates=sels)
            finals.append(round(pr["final"], 2))
        srt = sorted(finals)
        out["placebo_finals"] = finals
        out["placebo_beaten"] = sum(1 for f in finals if f < r["final"])
        out["placebo_median"] = round(E._pct(srt, 0.50), 2)
        out["placebo_best"] = srt[-1]
        out["placebo_worst"] = srt[0]
    return out

def spy_final(adj_pb, start, end):
    v, _ = E.spy_net(adj_pb, start, end, 100.0)
    return round(v, 2)

def save(name, obj):
    p = os.path.join(HERE, name)
    with open(p, "w") as f:
        json.dump(obj, f, indent=1)
    print(f"saved {name}", flush=True)

def log(*a):
    print(*a, flush=True)

# ------------------------------------------------------------ phases
def phase_integrity():
    """Reproduce the sweep's decade biweekly cell exactly."""
    raw_pb, adj_pb, divs, splits = load_market("decade")
    pb = PoolBuilder(splits)
    cell = run_cell(raw_pb, divs, pb, "biweekly", "2016-11-21", END)
    ref = json.load(open(os.path.join(DG, "cells", "biweekly.json")))
    ok_final = abs(cell["final"] - 433.37) < 0.005
    ok_plb = cell["placebo_finals"] == ref["placebo_finals"]
    ok_all = ok_final and ok_plb and cell["placebo_beaten"] == 20 \
        and abs(cell["costs"] - ref["costs"]) < 0.005 \
        and cell["orders"] == ref["orders"]
    res = {"gate": "decade biweekly cell through confirmation plumbing",
           "expected_final": 433.37, "got_final": cell["final"],
           "expected_placebo_finals": ref["placebo_finals"],
           "got_placebo_finals": cell["placebo_finals"],
           "placebo_beaten": cell["placebo_beaten"],
           "costs": cell["costs"], "orders": cell["orders"],
           "dividends_credited": cell["dividends_credited"],
           "spy_decade": spy_final(adj_pb, "2016-11-21", END),
           "status": "REPRODUCED" if ok_all else "FAILED"}
    save("integrity.json", res)
    log(f"INTEGRITY: final=${cell['final']} expected 433.37 | placebos match={ok_plb} | status={res['status']}")
    return res["status"] == "REPRODUCED"

ROADS = [("LONG", "full", "2010-01-04"), ("CONT", "decade", "2019-01-02"),
         ("VAL", "decade", "2023-01-03")]
CADENCES = ["weekly", "biweekly", "monthly"]

def phase_roads():
    summary = {}
    for road, source, start in ROADS:
        raw_pb, adj_pb, divs, splits = load_market(source)
        pb = PoolBuilder(splits)
        spy = spy_final(adj_pb, start, END)
        log(f"== {road} {start}->{END} SPY=${spy}")
        summary[road] = {"window": [start, END], "spy_final": spy, "cells": {}}
        for cad in CADENCES:
            cell = run_cell(raw_pb, divs, pb, cad, start, END)
            save(f"{road.lower()}_{cad}.json", cell)
            summary[road]["cells"][cad] = {
                k: cell[k] for k in ("final", "cagr_pct", "max_dd_pct", "costs",
                                     "orders", "dividends_credited",
                                     "placebo_beaten", "placebo_median",
                                     "placebo_best", "placebo_worst", "restart")}
            summary[road]["cells"][cad]["halts_n"] = len(cell["halts"]) + (1 if cell["second_halt"] else 0)
            log(f"   {road} {cad}: final=${cell['final']} SPY=${spy} "
                f"placebo {cell['placebo_beaten']}/20 median=${cell['placebo_median']} "
                f"DD={cell['max_dd_pct']}% costs=${cell['costs']} divs=${cell['dividends_credited']} "
                f"halts={summary[road]['cells'][cad]['halts_n']}")
        del raw_pb, adj_pb, divs, splits, pb
    save("roads_summary.json", summary)
    return summary

def phase_folds():
    raw_pb, adj_pb, divs, splits = load_market("full")
    pb = PoolBuilder(splits)
    folds = {}
    for y in range(2010, 2027):
        start, end = f"{y}-01-01", f"{y}-12-31"
        if y == 2026:
            end = END
        cell = run_cell(raw_pb, divs, pb, "biweekly", start, end, with_placebos=False)
        spy = spy_final(adj_pb, start, end)
        cell["spy_final"] = spy
        cell["beat_spy"] = cell["final"] > spy
        cell["beat_100"] = cell["final"] > 100.0
        folds[str(y)] = cell
        log(f"   FOLD {y}: final=${cell['final']} SPY=${spy} "
            f"beat_spy={cell['beat_spy']} halts={len(cell['halts']) + (1 if cell['second_halt'] else 0)}")
    save("folds.json", folds)
    return folds

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "integrity"):
        if not phase_integrity():
            log("INTEGRITY GATE FAILED — stopping, per task instructions.")
            sys.exit(2)
    if which in ("all", "roads"):
        phase_roads()
    if which in ("all", "folds"):
        phase_folds()
    log("CONFIRMATION RUN DONE")
