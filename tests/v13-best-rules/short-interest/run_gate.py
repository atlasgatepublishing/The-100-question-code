#!/usr/bin/env python3
"""
SHORT INTEREST — V13 BEST RULES: the SI AVOIDANCE GATE on the champion.
Implements BEST-RULES-SPEC.md exactly as frozen. Simulation only.

Design: champion value+momentum (book-to-market form) run VERBATIM,
with exactly one change at each quarterly selection: a name whose
freshest published FINRA short-interest ratio is >= 2.5% of shares
outstanding (Desai et al.'s published high-SI threshold) is ineligible;
the book walks the host ranking top-down and takes the first 5 ungated
names. Fallback: if fewer than 5 ungated names exist, fill in host-rank
order from gated names (logged). Names with no usable FINRA reading
are NOT gated (gate fires only on positive evidence; occurrences
logged).

FINRA discipline (v6, unchanged): settlement files from the v6 cache
(read-only); a reading is usable at selection D only if its
publication date (7th trading day after settlement) is strictly
before D; ratio = FINRA short shares / EDGAR point-in-time shares
outstanding as of the settlement date.

Prior folders are READ-ONLY: FINRA raw/extracted files are read from
the v6 cache; extracted rows are re-cached only inside THIS folder.
The champion engine is imported from v4 (its caches are read by the
engine's own loaders, as in v6).

Blocks: (0) replication of the published champion ($544.47 CONT /
$288.05 VAL + placebo medians/beats) — the run counts only if this
passes; (1) gated ranked runs CONT + VAL with host in-run finals and
SPY net; (2) 20-seed placebos per road (random 5 from the host's
scored pool, same engine); (3) walk-forward folds 2020-2026, gated
vs host head-to-head (pre-registered confirmation block); (4)
per-period (quarterly) distribution stats from the daily curves.
"""
import csv
import importlib.util
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
V6_FINRA = os.path.expanduser(
    "~/workspace/stock-app/backtests/v6/short-interest/finra-cache")
LOCAL_FINRA = os.path.join(HERE, "finra-cache-local")
os.makedirs(LOCAL_FINRA, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
PLACEBO_SEEDS = list(range(1, 21))
START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
GATE_THRESHOLD = 0.025          # Desai et al. high-SI line: 2.5% of shares out
PUB_LAG_TRADING_DAYS = 7        # FINRA: publication 7th business day after settlement

from datetime import date as _date  # noqa: E402

# ------------------------------------------------------- FINRA layer
def finra_symbol(ticker, settlement):
    if ticker == "BRK-B":
        return "BRKB"
    if ticker == "META":
        return "FB" if settlement < "2022-06-10" else "META"
    return ticker

def settlement_dates(trading_days):
    by_month = {}
    for d in trading_days:
        by_month.setdefault(d[:7], []).append(d)
    out = set()
    for ym, days in by_month.items():
        days = sorted(days)
        mid = [d for d in days if int(d[8:10]) <= 15]
        if mid:
            out.add(mid[-1])
        out.add(days[-1])
    return sorted(out)

def publication_date(settlement, trading_days, day_index):
    i = day_index.get(settlement)
    if i is None or i + PUB_LAG_TRADING_DAYS >= len(trading_days):
        return None
    return trading_days[i + PUB_LAG_TRADING_DAYS]

def fetch_si_file(settlement):
    """Extracted universe rows for one settlement. Read order: this
    folder's local extracted cache -> v6 extracted cache (read-only)
    -> v6 raw CSV (read-only, parsed here; extraction cached locally).
    Never writes outside this folder; never downloads (the v6 cache
    is complete for the program window)."""
    compact = settlement.replace("-", "")
    local_ext = os.path.join(LOCAL_FINRA, f"si_{compact}.json")
    if os.path.exists(local_ext) and os.path.getsize(local_ext) > 10:
        with open(local_ext) as f:
            return json.load(f)
    v6_ext = os.path.join(V6_FINRA, f"si_{compact}.json")
    if os.path.exists(v6_ext) and os.path.getsize(v6_ext) > 10:
        with open(v6_ext) as f:
            return json.load(f)
    raw_path = os.path.join(V6_FINRA, f"shrt{compact}.csv")
    if not (os.path.exists(raw_path) and os.path.getsize(raw_path) > 1000):
        raise RuntimeError(f"FINRA file missing from v6 cache: {raw_path}")
    wanted = {}
    for t in UNIVERSE:
        wanted.setdefault(finra_symbol(t, settlement), []).append(t)
    out = {}
    with open(raw_path, newline="") as f:
        rdr = csv.DictReader(f, delimiter="|")
        for row in rdr:
            sym = row["symbolCode"]
            if sym in wanted:
                if row["settlementDate"] != settlement:
                    raise RuntimeError(
                        f"settlement mismatch in {raw_path}: "
                        f"{row['settlementDate']} != {settlement}")
                for t in wanted[sym]:
                    if t in out:
                        raise RuntimeError(f"duplicate FINRA row {sym} {settlement}")
                    out[t] = float(row["currentShortPositionQuantity"])
    with open(local_ext, "w") as f:
        json.dump(out, f, indent=1)
    return out

class ShortInterest:
    def __init__(self, pb):
        self.days = pb.dates
        self.day_index = {d: i for i, d in enumerate(self.days)}
        self.settlements = settlement_dates(self.days)
        self.pub = {s: publication_date(s, self.days, self.day_index)
                    for s in self.settlements}
        self.cache = {}

    def freshest_usable(self, d):
        best = None
        for s in self.settlements:
            p = self.pub[s]
            if p is not None and p < d and s < d:
                if best is None or s > best[0]:
                    best = (s, p)
        return best if best else (None, None)

    def readings(self, settlement):
        if settlement not in self.cache:
            self.cache[settlement] = fetch_si_file(settlement)
        return self.cache[settlement]

# ------------------------------------------------------------- selection
SELECTION_CACHE = {}

def compute_selection(pb, d, data):
    """Host scoring VERBATIM (the champion run_pot selection block)
    plus SI ratios for every scored name. Returns scores, combined
    percentile-average ranking, ratios, gated set, settlement used."""
    if d in SELECTION_CACHE:
        return SELECTION_CACHE[d]
    scores = {}
    for t in UNIVERSE:
        be = E.pit_value(data["equity"].get(t, []), d)
        so = E.pit_value(data["shares"].get(t, []), d)
        px = pb.close_on_or_before(t, d)
        if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
            continue
        mcap = so[2] * px
        if mcap <= 0:
            continue
        bm = be[2] / mcap
        bl = pb.bars.get(t, [])
        didx = None
        for i, b in enumerate(bl):
            if b["d"] == d:
                didx = i
                break
        if didx is None or didx < 253:
            continue
        mom = bl[didx - 21]["c"] / bl[didx - 252]["c"] - 1.0
        scores[t] = (bm, mom)
    combined = {}
    if scores:
        vr = E.percentile_ranks({t: v[0] for t, v in scores.items()})
        mr = E.percentile_ranks({t: v[1] for t, v in scores.items()})
        combined = {t: (vr[t] + mr[t]) / 2.0 for t in scores}
    ranking = sorted(combined, key=lambda t: -combined[t])
    host_picks = ranking[:5]
    # SI layer
    si = data["si"]
    settlement, pub = si.freshest_usable(d)
    ratios, missing = {}, []
    if settlement is not None:
        rows = si.readings(settlement)
        for t in scores:
            if t not in rows:
                missing.append(t)
                continue
            so_s = E.pit_value(data["shares"].get(t, []), settlement)
            if so_s is None or so_s[2] <= 0:
                missing.append(t)
                continue
            ratios[t] = rows[t] / so_s[2]
    gated = {t for t, r in ratios.items() if r >= GATE_THRESHOLD}
    # gated picks: walk ranking, skip gated, take 5; fallback fill in rank order
    picks, skipped = [], []
    for t in ranking:
        if len(picks) >= 5:
            break
        if t in gated:
            skipped.append(t)
            continue
        picks.append(t)
    fallback = []
    if len(picks) < 5:
        for t in ranking:
            if len(picks) >= 5:
                break
            if t in gated and t not in picks:
                picks.append(t)
                fallback.append(t)
    gate_events = []
    for t in host_picks:
        if t in gated:
            gate_events.append({"gated_out": t,
                                "ratio_pct": round(ratios[t] * 100, 3)})
    sel = {"scores": scores, "ranking": ranking, "host_picks": host_picks,
           "ratios": ratios, "gated": sorted(gated), "picks": picks,
           "fallback": fallback, "missing_si": missing,
           "settlement": settlement, "publication": pub,
           "gate_events": gate_events}
    SELECTION_CACHE[d] = sel
    return sel

# ------------------------------------------------------------------ engine
def run_pot_gate(pb, data, start, end, start_cash,
                 floor0, ladder, placebo_rng=None, label="",
                 quiet=False, record_pools=False):
    """Champion run_pot copied verbatim EXCEPT the pick block: ranked
    picks = first 5 ungated names in the host ranking (fallback per
    spec); placebo picks = random sample of the host's scored pool.
    Execution, costs, floor, halt and liquidation mechanics unchanged."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    halted = None
    halt_info = None
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
        if d in sel_set:
            sel = compute_selection(pb, d, data)
            scores = sel["scores"]
            if len(scores) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scores), 5)
                else:
                    picks = sel["picks"]
                if record_pools:
                    pools.append((d, sorted(scores),
                                  {t: round(sel["ratios"][t] * 100, 4)
                                   for t in sorted(sel["ratios"])},
                                  list(sel["host_picks"]), list(picks),
                                  sel["settlement"], sel["gate_events"],
                                  list(sel["fallback"]), list(sel["missing_si"])))
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                if not quiet:
                    print(f"  [{label}] {d} pool={len(scores)} "
                          f"settle={sel['settlement']} gated={sel['gated']} "
                          f"host={sel['host_picks']} picks={picks} pot=${pv:,.2f}",
                          flush=True)
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
            return {"label": label, "final": cash, "costs": total_costs,
                    "trades": trades, "halted": halted, "end": nd,
                    "halt_info": halt_info, "pools": pools, "curve": curve}
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
            "halt_info": None, "pools": pools, "curve": curve}

# ------------------------------------------------------------- stats
def period_stats(curve, sel_dates, start, end):
    """Quarterly (selection-to-selection) period distribution from the
    daily equity curve, per PROGRAM.md reporting rules."""
    cmap = dict(curve)
    days = [d for d, _ in curve]
    def close_at(d):
        if d in cmap:
            return cmap[d]
        prior = [x for x in days if x <= d]
        return cmap[prior[-1]] if prior else None
    bounds = [start] + [d for d in sel_dates if start < d <= end] + [end]
    rets = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        va, vb = close_at(a), close_at(b)
        if va and vb:
            rets.append((a, b, vb / va - 1.0))
    vals = sorted(r for _, _, r in rets)
    n = len(vals)
    med = E._pct(vals, 0.50) if vals else None
    mean = sum(vals) / n if n else None
    pos = sum(1 for v in vals if v > 0)
    streak = longest = 0
    for _, _, r in rets:
        if r <= 0:
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0
    # longest stretch between new highs (daily curve)
    peak = -1.0
    peak_d = None
    longest_gap_days = 0
    last_peak_d = None
    for d, v in curve:
        if v >= peak:
            if last_peak_d is not None:
                gap = (_date(int(d[:4]), int(d[5:7]), int(d[8:10])) -
                       _date(int(last_peak_d[:4]), int(last_peak_d[5:7]),
                             int(last_peak_d[8:10]))).days
                longest_gap_days = max(longest_gap_days, gap)
            peak = v
            last_peak_d = d
    if curve and last_peak_d is not None:
        d_end = curve[-1][0]
        gap = (_date(int(d_end[:4]), int(d_end[5:7]), int(d_end[8:10])) -
               _date(int(last_peak_d[:4]), int(last_peak_d[5:7]),
                     int(last_peak_d[8:10]))).days
        longest_gap_days = max(longest_gap_days, gap)
    return {"n_periods": n,
            "median_period_pct": round(med * 100, 2) if med is not None else None,
            "pct_periods_positive": round(100.0 * pos / n, 1) if n else None,
            "best_period_pct": round(vals[-1] * 100, 2) if vals else None,
            "worst_period_pct": round(vals[0] * 100, 2) if vals else None,
            "longest_losing_streak_periods": longest,
            "longest_stretch_between_new_highs_months":
                round(longest_gap_days / 30.44, 1),
            "mean_period_pct_secondary": round(mean * 100, 2) if mean is not None else None,
            "periods": [[a, b, round(r * 100, 2)] for a, b, r in rets]}

CKPT_PATH = os.path.join(HERE, "placebo_checkpoint.json")

def _load_ckpt():
    if os.path.exists(CKPT_PATH):
        with open(CKPT_PATH) as f:
            return json.load(f)
    return {}

def _save_ckpt(ck):
    with open(CKPT_PATH, "w") as f:
        json.dump(ck, f, indent=1)

def placebo_block(pb, data, ws, we, ranked_final, tag):
    ck = _load_ckpt()
    done = {r["seed"]: r for r in ck.get(f"placebo_{tag}", [])}
    finals, prow = [], []
    for seed in PLACEBO_SEEDS:
        if seed in done:
            rp = done[seed]
            finals.append(rp["final_raw"])
            prow.append({"seed": seed, "final": rp["final"],
                         "costs": rp["costs"], "orders": rp["orders"],
                         "halted": rp["halted"]})
            print(f"  [{tag}] placebo seed {seed:2d}: CACHED ${rp['final']:,.2f}",
                  flush=True)
            continue
        rng = random.Random(seed)
        rp = run_pot_gate(pb, data, ws, we, START_CASH, FLOOR0, LADDER,
                          placebo_rng=rng, label=f"{tag} PLACEBO s{seed}",
                          quiet=True)
        finals.append(rp["final"])
        row = {"seed": seed, "final": round(rp["final"], 2),
               "final_raw": rp["final"],
               "costs": round(rp["costs"], 2),
               "orders": len(rp["trades"]), "halted": rp["halted"]}
        prow.append(row)
        ck = _load_ckpt()
        ck.setdefault(f"placebo_{tag}", []).append(row)
        _save_ckpt(ck)
        print(f"  [{tag}] placebo seed {seed:2d}: final=${rp['final']:,.2f} "
              f"halted={rp['halted']} orders={len(rp['trades'])}", flush=True)
    sfin = sorted(finals)
    n_beat = sum(1 for v in finals if ranked_final > v)
    dist = {"n_seeds": len(finals),
            "median_final": round(E._pct(sfin, 0.50), 2),
            "p25_final": round(E._pct(sfin, 0.25), 2),
            "p75_final": round(E._pct(sfin, 0.75), 2),
            "best_final": round(sfin[-1], 2),
            "worst_final": round(sfin[0], 2),
            "mean_final": round(sum(finals) / len(finals), 2),
            "n_halted": sum(1 for r_ in prow if r_["halted"]),
            "ranked_final": round(ranked_final, 2),
            "ranked_minus_median": round(ranked_final - E._pct(sfin, 0.50), 2),
            "ranked_beats_n_of_20": n_beat,
            "ranked_percentile": round(100.0 * n_beat / len(finals), 1),
            "rows": prow}
    print(f"== {tag} PLACEBO_DIST median=${dist['median_final']:,.2f} "
          f"best=${dist['best_final']:,.2f} worst=${dist['worst_final']:,.2f} "
          f"halted={dist['n_halted']}/20 | ranked=${ranked_final:,.2f} "
          f"beats {n_beat}/20", flush=True)
    return dist

def host_run(pb, data, start, end, placebo_rng=None, label="", quiet=True):
    return E.run_pot(pb, data["equity"], data["shares"], start, end,
                     START_CASH, FLOOR0, LADDER, placebo_rng=placebo_rng,
                     label=label, quiet=quiet)

# --------------------------------------------------------------------- main
def main():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}
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
        print(f"{t}: equity={len(equity_rows[t])} shares={len(shares_rows[t])}", flush=True)
        time.sleep(0.05)

    bars = {}
    for t in UNIVERSE + ["SPY"]:
        bars[t] = E.get_prices(t)
        print(f"{t}: {len(bars[t])} bars {bars[t][0]['d']}..{bars[t][-1]['d']}", flush=True)
    pb = E.PriceBook(bars)
    si = ShortInterest(pb)
    data = {"equity": equity_rows, "shares": shares_rows, "si": si}
    print(f"FINRA settlements derivable: {len(si.settlements)} "
          f"({si.settlements[0]}..{si.settlements[-1]})", flush=True)

    CONT = ("2019-01-02", "2026-11-20")
    VAL = ("2023-01-03", "2026-11-20")
    out = {"family": "short-interest",
           "form": "V13 BEST RULES: SI avoidance gate (>=2.5% of shares out) "
                   "on champion V+M (B/M form), host verbatim otherwise",
           "gate_threshold_pct": GATE_THRESHOLD * 100,
           "host_published": {"CONT": 544.47, "VAL": 288.05},
           "family_published_best_traded": {
               "form": "Form A standalone least-shorted (v6 pond)",
               "CONT": 383.29, "VAL": 249.79},
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0}

    # ---- (0) replication: champion ranked + placebos must match published
    rep = {}
    published = {"CONT": {"final": 544.47, "placebo_median": 308.81, "beats": 19},
                 "VAL": {"final": 288.05, "placebo_median": 201.15, "beats": 18}}
    host_finals = {}
    for tag, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
        rb = host_run(pb, data, ws, we, label=f"REPLICATION CHAMPION {tag}")
        host_finals[tag] = rb
        finals = []
        for seed in PLACEBO_SEEDS:
            rng = random.Random(seed)
            rp = host_run(pb, data, ws, we, placebo_rng=rng,
                          label=f"CHAMPION {tag} PLACEBO s{seed}")
            finals.append(rp["final"])
        sfin = sorted(finals)
        med = round(E._pct(sfin, 0.50), 2)
        beats = sum(1 for v in finals if rb["final"] > v)
        rep[tag] = {"final": round(rb["final"], 2),
                    "published_final": published[tag]["final"],
                    "match": round(rb["final"], 2) == published[tag]["final"],
                    "placebo_median": med,
                    "published_placebo_median": published[tag]["placebo_median"],
                    "placebo_median_match": med == published[tag]["placebo_median"],
                    "placebo_beats": beats,
                    "published_placebo_beats": published[tag]["beats"],
                    "placebo_beats_match": beats == published[tag]["beats"],
                    "orders": len(rb["trades"]), "halted": rb["halted"]}
        print(f"== REPLICATION champion {tag}: final=${rb['final']:,.2f} "
              f"published=${published[tag]['final']:,.2f} match={rep[tag]['match']} | "
              f"placebo median=${med:,.2f} match={rep[tag]['placebo_median_match']} "
              f"beats {beats}/20 match={rep[tag]['placebo_beats_match']}", flush=True)
    out["replication_champion"] = rep
    if not all(rep[t]["match"] and rep[t]["placebo_median_match"]
               and rep[t]["placebo_beats_match"] for t in rep):
        raise RuntimeError("REPLICATION FAILED — gated numbers do not count")

    # ---- (1) gated ranked runs
    for tag, (ws, we) in (("CONT", CONT), ("VAL", VAL)):
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        r = run_pot_gate(pb, data, ws, we, START_CASH, FLOOR0, LADDER,
                         label=f"GATED {tag}", record_pools=True)
        diag = E.diagnostics(r, FLOOR0)
        sel_dates = E.quarter_selection_dates(pb, ws, we)
        gate_log = []
        for (d, pool_sorted, ratios, host_picks, picks, settlement,
             events, fallback, missing) in r["pools"]:
            if events or fallback:
                gate_log.append({"date": d, "settlement": settlement,
                                 "host_picks": host_picks, "gated_picks": picks,
                                 "gate_events": events, "fallback": fallback,
                                 "missing_si": missing})
        out[f"gated_{tag}"] = {
            "final": round(r["final"], 2),
            "ret_pct": round((r["final"] / START_CASH - 1) * 100, 2),
            "costs": round(r["costs"], 2), "orders": len(r["trades"]),
            "halted": r["halted"], "halt_info": r["halt_info"],
            "host_final_in_run": round(host_finals[tag]["final"], 2),
            "host_diag": E.diagnostics(host_finals[tag], FLOOR0),
            "spy_net": round(s, 2), "diag": diag,
            "period_stats": period_stats(r["curve"], sel_dates, ws, we),
            "host_period_stats": period_stats(host_finals[tag]["curve"],
                                              sel_dates, ws, we),
            "n_selections": len(r["pools"]),
            "n_gate_changed_selections": len(gate_log),
            "gate_log": gate_log,
            "pools": r["pools"], "trades": r["trades"],
            "curve": [[d, round(v, 2)] for d, v in r["curve"]],
            "host_curve": [[d, round(v, 2)] for d, v in host_finals[tag]["curve"]]}
        print(f"== GATED {tag} final=${r['final']:,.2f} vs host "
              f"${host_finals[tag]['final']:,.2f} | SPY net=${s:,.2f} | "
              f"costs=${r['costs']:,.2f} orders={len(r['trades'])} "
              f"halted={r['halted']} maxDD={diag['max_drawdown_pct']}% | "
              f"gate changed {len(gate_log)}/{len(r['pools'])} selections",
              flush=True)

    # ---- (2) placebos for the gated engine
    out["placebo_VAL"] = placebo_block(pb, data, VAL[0], VAL[1],
                                       out["gated_VAL"]["final"], "VAL")
    out["placebo_CONT"] = placebo_block(pb, data, CONT[0], CONT[1],
                                        out["gated_CONT"]["final"], "CONT")

    # ---- (3) walk-forward folds 2020-2026: gated vs host (confirmation block)
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        gr = run_pot_gate(pb, data, fs, fe, START_CASH, FLOOR0, LADDER,
                          label=f"GATED FOLD {y}", quiet=True)
        hr = host_run(pb, data, fs, fe, label=f"HOST FOLD {y}")
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        gd = E.diagnostics(gr, FLOOR0)
        row = {"year": y, "start": fs, "end": fe,
               "gated_final": round(gr["final"], 2),
               "gated_return_pct": round(gr["final"] / START_CASH * 100 - 100, 2),
               "host_final": round(hr["final"], 2),
               "host_return_pct": round(hr["final"] / START_CASH * 100 - 100, 2),
               "spy_net_final": round(fspy, 2),
               "gated_beats_host": gr["final"] > hr["final"],
               "gated_beats_spy": gr["final"] > fspy,
               "gated_max_drawdown_pct": gd["max_drawdown_pct"],
               "gated_orders": len(gr["trades"]), "gated_costs": round(gr["costs"], 2),
               "gated_halted": gr["halted"], "host_halted": hr["halted"]}
        folds.append(row)
        print(f"FOLD {y}: gated ${gr['final']:,.2f} ({row['gated_return_pct']:+.2f}%) vs "
              f"host ${hr['final']:,.2f} ({row['host_return_pct']:+.2f}%) vs "
              f"SPY ${fspy:,.2f} | gated beats host={row['gated_beats_host']} "
              f"maxDD={row['gated_max_drawdown_pct']}% halted={row['gated_halted']}",
              flush=True)
    out["folds"] = folds
    gwins = sum(1 for f in folds if f["gated_beats_host"])
    gcomp = hcomp = 100.0
    for f in folds:
        gcomp *= 1 + f["gated_return_pct"] / 100.0
        hcomp *= 1 + f["host_return_pct"] / 100.0
    out["fold_record_gated_vs_host"] = f"{gwins} wins, {len(folds) - gwins} losses"
    out["fold_compounded_gated"] = round(gcomp, 2)
    out["fold_compounded_host"] = round(hcomp, 2)
    print(f"FOLD RECORD gated vs host: {out['fold_record_gated_vs_host']}; "
          f"fold-compounded gated ${out['fold_compounded_gated']:,.2f} vs "
          f"host ${out['fold_compounded_host']:,.2f}", flush=True)

    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
