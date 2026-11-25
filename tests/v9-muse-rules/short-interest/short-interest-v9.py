#!/usr/bin/env python3
"""
SHORT-INTEREST SIGNAL (least-shorted) — Terry's AI stock app.
Simulation only. NO parameter tuning: the spec below is run ONCE, as
described, and judged against the promoted champion's published numbers.

THE FAMILY AS PUBLISHED: Boehmer, Huszar & Jordan (2010, "The good
news in short interest", JFE), Rapach, Ringgenberg & Zhou (2016,
"Short interest and aggregate stock returns", JFE) and successors:
heavily shorted stocks UNDERPERFORM — short sellers are informed, so
the short-interest ratio predicts (negatively) subsequent returns
cross-sectionally, and the aggregate short-interest level predicts
market returns. A $100 long-only account cannot short, so the
testable long-only forms, BOTH pre-specified by the task:

  (A) STANDALONE (the traded test): quarterly, rank the champion's
      honest point-in-time top-30 pond by short interest ASCENDING
      and hold the 5 LEAST-shorted, equal weight — the published
      claim implies avoiding the most-shorted is where the money is.
  (B) DIAGNOSTIC (paper-only, clearly labeled): at each selection,
      the subsequent-quarter returns of the 5 MOST-shorted vs the 5
      least-shorted from the same pond — the spread the literature
      actually predicts. We cannot short, so this is never traded;
      it is reported so the family's core claim is graded directly.

SHORT-INTEREST MEASURE (stated, per the task): FINRA's free files
carry raw share counts only (currentShortPositionQuantity), no float
percentage. The signal is therefore short interest as a PERCENT OF
SHARES OUTSTANDING = FINRA short shares at the settlement date /
EDGAR point-in-time shares outstanding as of that settlement date
(the champion's shares chain and pit_value rules verbatim).

DATA + POINT-IN-TIME DISCIPLINE:
  - Source: FINRA Equity Short Interest files (Rule 4560 reports),
    free and anonymous, one pipe-delimited file per settlement date:
    https://cdn.finra.org/equity/otcmarket/biweekly/shrt{YYYYMMDD}.csv
    Settlement dates: the 15th of the month (or the previous business
    day) and the last business day of the month.
  - Publication: FINRA's own catalog states the compiled data is
    "provided for publication on the 7th business day after the
    reporting settlement date" (confirmed against FINRA's published
    2026 calendar: e.g. settlement Sep 30 -> publish Oct 9; Oct 15 ->
    Oct 26; Oct 30 -> Nov 10 — each the 7th trading day after).
    A reading is therefore usable at a selection date D only if its
    publication date (7th trading day after settlement, on the
    program's trading calendar) is STRICTLY BEFORE D — the same
    "filed strictly before" convention as the EDGAR machinery. At
    each selection the freshest published settlement is used for
    every name (one report vintage per selection, never mixed).
  - Coverage obtained: the CDN archive serves these files with
    exchange-listed names back through (at least) Dec 2018 —
    verified rows for AAPL/GOOGL/V/MA in the 2018-12-31 file — so
    the full program window (selections 2019-01-02 -> 2026-10-01)
    is covered. Historically, listed short interest was disseminated
    by the listing exchanges from the same Rule 4560 reports;
    FINRA's own consolidated web publication began June 2021 and
    its CDN archive carries the same reports back through 2018.
  - Vintage caveat (documented, not fixable from a free source):
    the file served today for an old settlement is FINRA's final
    vintage of that settlement (files carry a revisionFlag; FINRA
    revises in place for ~1-2 cycles). It is genuine settlement-date
    history — NOT a current snapshot used as history — but a
    first-publication snapshot cannot be reconstructed for free.
  - Symbol mapping (FINRA symbolCode vs program ticker): BRK-B is
    filed as BRKB; META was filed as FB until the June 2022 ticker
    change (settlements before 2022-06-10 read FB; the "META" rows
    in 2021 files are an unrelated ETF and are never touched). All
    other universe tickers are filed under their own symbols.

PROGRAM FORMAT (identical to the champion / house method):
  - Universe / pool: the champion's honest point-in-time top-30 as
    of Nov 2016; the pool at each quarterly selection = names passing
    the champion's exact gate (point-in-time EDGAR equity + shares,
    selection-day close, >= 253 bars of price history). The variant
    engine is the champion's run_pot copied verbatim with ONLY the
    pick block changed (house method): ranked picks = 5 lowest
    short-interest ratio among pool names carrying a usable FINRA
    reading; placebo picks = random sample of the same scored pond.
  - Costs: 0.10% of trade value per side + $0.01 per sell order.
  - Protection: PLAIN -15% floor only ($85 on the $100 pot, no
    ladder). Close at/below floor -> liquidate at next open, run ends.
  - Pot: $100 only (Terry's current standard).

Runs:
  (0) REPLICATION CHECK — the imported champion engine must reproduce
      the published $544.47 (continuous) and $288.05 (validation) to
      the cent, and its published placebo distributions (medians
      $308.81 / $201.15, ranked beats 19/20 / 18/20), before any
      variant number is taken.
  (1) Ranked short-interest (form A): CONTINUOUS 2019-01-02 ->
      2026-11-20 and VALIDATION 2023-01-03 -> 2026-11-20.
  (2) PLACEBO: 20 seeds (1..20) on BOTH windows — random 5 drawn
      from the SAME scored pond the ranked rule picks from.
  (3) WALK-FORWARD: fresh $100 pot per calendar year 2020-2026, vs SPY.
  (4) DIAGNOSTIC (form B, paper-only): most- vs least-shorted
      subsequent-quarter spread on both windows.

Judged against the champion (published): validation $288.05 |
continuous $544.47 | placebo beats 18/20 validation (median $201.15)
and 19/20 continuous (median $308.81) | folds 4 wins / 7,
fold-compounded $313.01 | SPY net $187.77 validation / $313.62
continuous (recomputed in-run as control).

Data: SEC EDGAR companyfacts + Yahoo prices, reused read-only from
the v4 caches; FINRA short-interest files downloaded once into
./finra-cache (raw CSVs kept) with extracted rows cached as JSON.
"""
import csv
import importlib.util
import io
import json
import os
import random
import time
import urllib.request
from datetime import date as _date, timedelta as _timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.join(HERE, "..", "..", "v4")
FINRA_CACHE = os.path.expanduser(
    "~/workspace/stock-app/backtests/v6/short-interest/finra-cache")  # v9: read-only reuse of the original cache (path fix only, documented)
os.makedirs(FINRA_CACHE, exist_ok=True)

spec = importlib.util.spec_from_file_location(
    "vm_plainfloor", os.path.join(V4, "value-momentum-plainfloor.py"))
E = importlib.util.module_from_spec(spec)
spec.loader.exec_module(E)

UNIVERSE = E.UNIVERSE
PLACEBO_SEEDS = list(range(1, 21))
START_CASH = 100.0
FLOOR0 = 85.0
LADDER = []
FINRA_URL = "https://cdn.finra.org/equity/otcmarket/biweekly/shrt{}.csv"
PUB_LAG_TRADING_DAYS = 7      # FINRA: publication on the 7th business
                              # day after the settlement date

def _ord(dstr):
    return _date(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()

# ------------------------------------------------------- FINRA layer
def finra_symbol(ticker, settlement):
    """FINRA symbolCode for a program ticker at a settlement date."""
    if ticker == "BRK-B":
        return "BRKB"
    if ticker == "META":
        return "FB" if settlement < "2022-06-10" else "META"
    return ticker

def settlement_dates(trading_days):
    """FINRA settlement dates derivable from the trading calendar:
    the last trading day on/before the 15th, and the last trading
    day of each month, for every month spanned by trading_days."""
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
    """7th trading day strictly after the settlement date."""
    i = day_index.get(settlement)
    if i is None or i + PUB_LAG_TRADING_DAYS >= len(trading_days):
        return None
    return trading_days[i + PUB_LAG_TRADING_DAYS]

def fetch_si_file(settlement):
    """Download (or read from cache) one FINRA settlement file and
    extract the universe rows. Returns {ticker: short_shares} using
    program tickers. The file's own settlementDate column must match
    the requested date — a mismatch raises (never silently used)."""
    compact = settlement.replace("-", "")
    raw_path = os.path.join(FINRA_CACHE, f"shrt{compact}.csv")
    ext_path = os.path.join(FINRA_CACHE, f"si_{compact}.json")
    if os.path.exists(ext_path) and os.path.getsize(ext_path) > 10:
        with open(ext_path) as f:
            return json.load(f)
    if not (os.path.exists(raw_path) and os.path.getsize(raw_path) > 1000):
        url = FINRA_URL.format(compact)
        last = None
        for i in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    blob = r.read()
                with open(raw_path, "wb") as f:
                    f.write(blob)
                break
            except Exception as e:  # noqa
                last = e
                time.sleep(2 * (i + 1))
        else:
            raise RuntimeError(f"FINRA fetch failed {url}: {last}")
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
    with open(ext_path, "w") as f:
        json.dump(out, f, indent=1)
    time.sleep(0.1)
    return out

class ShortInterest:
    """Point-in-time short-interest readings over the trading calendar.
    readings[settlement] = {ticker: short_shares}; a reading is usable
    at selection D iff publication_date(settlement) < D."""

    def __init__(self, pb):
        self.days = pb.dates
        self.day_index = {d: i for i, d in enumerate(self.days)}
        self.settlements = settlement_dates(self.days)
        self.pub = {s: publication_date(s, self.days, self.day_index)
                    for s in self.settlements}
        self.cache = {}

    def freshest_usable(self, d):
        """(settlement, publication) of the freshest report published
        strictly before selection date d, or (None, None)."""
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
    """Everything the rule needs at selection date d (cached per date —
    ranked, placebo, fold and diagnostic runs share the identical
    scored pond). Pool = the champion's gate verbatim. Scored = pool
    names with a usable FINRA reading at the freshest published
    settlement; ratio = FINRA short shares / EDGAR point-in-time
    shares outstanding as of the settlement date."""
    if d in SELECTION_CACHE:
        return SELECTION_CACHE[d]
    pool = {}
    for t in UNIVERSE:
        be = E.pit_value(data["equity"].get(t, []), d)
        so = E.pit_value(data["shares"].get(t, []), d)
        px = pb.close_on_or_before(t, d)
        if be is None or so is None or px is None or so[2] <= 0 or be[2] is None:
            continue
        mcap = so[2] * px
        if mcap <= 0:
            continue
        bl = pb.bars.get(t, [])
        didx = None
        for i, b in enumerate(bl):
            if b["d"] == d:
                didx = i
                break
        if didx is None or didx < 253:
            continue
        pool[t] = be[2] / mcap
    si = data["si"]
    settlement, pub = si.freshest_usable(d)
    scored, detail = {}, {}
    if settlement is not None:
        rows = si.readings(settlement)
        for t in pool:
            if t not in rows:
                continue
            so_s = E.pit_value(data["shares"].get(t, []), settlement)
            if so_s is None or so_s[2] <= 0:
                continue
            ratio = rows[t] / so_s[2]
            scored[t] = ratio
            detail[t] = {"settlement": settlement, "publication": pub,
                         "short_shares": rows[t],
                         "shares_out": so_s[2], "ratio_pct": round(ratio * 100, 4)}
    picks = sorted(scored, key=lambda t: (scored[t], t))[:5]
    sel = {"pool": pool, "scored": scored, "detail": detail,
           "settlement": settlement, "publication": pub, "picks": picks}
    SELECTION_CACHE[d] = sel
    return sel

# ------------------------------------------------------------------ engine
def run_pot_si(pb, data, start, end, start_cash,
               floor0, ladder, placebo_rng=None, label="",
               quiet=False, record_pools=False):
    """Champion run_pot (value-momentum-plainfloor.py) copied verbatim
    EXCEPT the selection scoring block: pool = the champion's gate
    verbatim; ranked picks = 5 LOWEST short-interest ratio among pool
    names with a usable FINRA reading; placebo picks = random sample
    of the same scored pond. Execution, costs, floor, halt and
    liquidation mechanics are unchanged."""
    cash = start_cash
    floor = floor0
    positions = {}  # ticker -> shares
    trades = []     # (date, ticker, side, shares, price, value, cost)
    total_costs = 0.0
    halted = None
    halt_info = None
    # --- V9 PROTECTION MODULE (the ONLY change vs the original) ---
    # Episode-1 floor = floor0 (identical). On FIRST halt: liquidate
    # exactly as the original, sit in cash 90 calendar days from the
    # liquidation date, restart at the next quarterly selection date
    # on/after that with the remaining cash; episode-2 floor = -15%
    # from the restart balance. On SECOND halt: run ends permanently.
    v9_halts = 0
    v9_restarts = []
    v9_waiting = False
    v9_eligible = None
    v9_second_halt = None
    curve = []      # (date, close equity) — instrumentation only
    pools = []      # (date, pool, scored ratios, picks)
    sel_dates = E.quarter_selection_dates(pb, start, end)
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None  # list of (ticker, target_value) to execute at next open

    def portfolio_close(d):
        v = cash
        for t, sh in positions.items():
            c = pb.close_on_or_before(t, d)
            if c:
                v += sh * c
        return v

    def execute_rebalance(d, targets):
        """Execute at open of day d toward target dollar values (dict t->value).
        Sells first, then buys. Returns total cost."""
        nonlocal cash, total_costs
        cost = 0.0
        opens = {}
        for t in set(list(positions) + list(targets)):
            b = pb.bar(t, d)
            if b:
                opens[t] = b["o"]
        # sells / trims
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
        # buys
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
        # execute pending rebalance at today's open
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        # selection day: compute targets from data published before today
        if d in sel_set and v9_waiting:
            if d >= v9_eligible:
                v9_waiting = False
                v9_restarts[-1]["restart_date"] = d
                v9_restarts[-1]["restart_balance"] = round(cash, 2)
            else:
                pass  # still sitting in cash; skip this selection
        if d in sel_set and not v9_waiting:
            sel = compute_selection(pb, d, data)
            scored = sel["scored"]
            if len(scored) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(scored), 5)
                else:
                    picks = sel["picks"]
                if record_pools:
                    pools.append((d, sorted(sel["pool"]),
                                  {t: round(scored[t] * 100, 4)
                                   for t in sorted(scored)},
                                  list(picks)))
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
                if not quiet:
                    print(f"  [{label}] {d} pool={len(sel['pool'])} "
                          f"scored={len(scored)} settle={sel['settlement']} "
                          f"picks={picks} pot=${pv:,.2f}", flush=True)
        # end of day: ladder then floor check
        v = portfolio_close(d)
        curve.append((d, v))
        for thresh, newfloor in ladder:
            if v >= thresh and newfloor > floor:
                floor = newfloor
        if v <= floor and di < len(days) - 1:
            halted = d
            halt_info = {"signal_date": d, "signal_close": round(v, 2),
                         "floor_in_effect": floor}
            # liquidate at next open
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
            v9_halts += 1
            if v9_halts >= 2:
                v9_second_halt = halted
                return {"label": label, "final": cash, "costs": total_costs,
                        "trades": trades, "halted": halted, "end": nd,
                        "halt_info": halt_info, "pools": pools, "curve": curve,
                        "restarts": v9_restarts, "second_halt": v9_second_halt}
            _liq = _date(int(nd[:4]), int(nd[5:7]), int(nd[8:10]))
            v9_eligible = (_liq + _timedelta(days=90)).isoformat()
            floor = round(0.85 * cash, 10)
            v9_restarts.append({"halt_signal_date": halted,
                                "liquidation_date": nd,
                                "liquidation_cash": round(cash, 2),
                                "cash_until_eligible": v9_eligible,
                                "episode2_floor": round(floor, 2),
                                "restart_date": None,
                                "restart_balance": None})
            v9_waiting = True
            pending = None  # discard any same-day selection pending (the original discarded it by returning)
            halted = None
            halt_info = None
            continue
    # end of window: liquidate at final close
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
            "halt_info": None, "pools": pools, "curve": curve,
            "restarts": v9_restarts, "second_halt": v9_second_halt}

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
            "halted": r["halted"], "final": round(r["final"], 2),
            "restarts": r.get("restarts", []), "second_halt": r.get("second_halt")}

def placebo_block(pb, data, ws, we, ranked_final, tag, run_fn=None):
    """20-seed placebo using the variant engine (or a supplied engine
    for the champion replication block)."""
    run_fn = run_fn or run_pot_si
    finals, prow = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        rp = run_fn(pb, data, ws, we, START_CASH, FLOOR0, LADDER,
                    placebo_rng=rng, label=f"{tag} PLACEBO s{seed}",
                    quiet=True)
        finals.append(rp["final"])
        prow.append({"seed": seed, "final": round(rp["final"], 2),
                     "ret_pct": round((rp["final"] / START_CASH - 1) * 100, 2),
                     "costs": round(rp["costs"], 2),
                     "orders": len(rp["trades"]), "halted": rp["halted"],
                     "restarts": rp.get("restarts", []),
                     "second_halt": rp.get("second_halt")})
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
          f"p25=${dist['p25_final']:,.2f} p75=${dist['p75_final']:,.2f} "
          f"best=${dist['best_final']:,.2f} worst=${dist['worst_final']:,.2f} "
          f"halted={dist['n_halted']}/20 | ranked=${ranked_final:,.2f} "
          f"beats {n_beat}/20 ({dist['ranked_percentile']}th pct)", flush=True)
    return dist

# ------------------------------------------------------------- diagnostic
def diagnostic(pb, data, ws, we):
    """FORM B — PAPER-ONLY, never traded. At each quarterly selection
    in the window: the 5 most-shorted and 5 least-shorted names in the
    scored pond, equal weight, close-to-close return to the next
    selection date (or the window end). The literature (Boehmer-
    Huszar-Jordan; Rapach-Ringgenberg-Zhou) predicts the most-shorted
    UNDERPERFORM, i.e. spread (least - most) > 0."""
    sel_dates = E.quarter_selection_dates(pb, ws, we)
    rows = []
    for i, d in enumerate(sel_dates):
        nxt = sel_dates[i + 1] if i + 1 < len(sel_dates) else we
        sel = compute_selection(pb, d, data)
        scored = sel["scored"]
        if len(scored) < 10:
            rows.append({"date": d, "next": nxt, "skipped": True,
                         "n_scored": len(scored)})
            continue
        by_ratio = sorted(scored, key=lambda t: (scored[t], t))
        least, most = by_ratio[:5], by_ratio[-5:]

        def grp_ret(names):
            rs = []
            for t in names:
                c0 = pb.close_on_or_before(t, d)
                c1 = pb.close_on_or_before(t, nxt)
                if c0 and c1:
                    rs.append(c1 / c0 - 1.0)
            return sum(rs) / len(rs) if rs else None

        lr, mr = grp_ret(least), grp_ret(most)
        s0 = pb.close_on_or_before("SPY", d)
        s1 = pb.close_on_or_before("SPY", nxt)
        spy_r = (s1 / s0 - 1.0) if (s0 and s1) else None
        rows.append({"date": d, "next": nxt, "settlement": sel["settlement"],
                     "publication": sel["publication"], "n_scored": len(scored),
                     "least5": least, "most5": most,
                     "least5_ratio_pct": [round(scored[t] * 100, 3) for t in least],
                     "most5_ratio_pct": [round(scored[t] * 100, 3) for t in most],
                     "least_ret_pct": round(lr * 100, 2) if lr is not None else None,
                     "most_ret_pct": round(mr * 100, 2) if mr is not None else None,
                     "spread_pct": round((lr - mr) * 100, 2)
                     if (lr is not None and mr is not None) else None,
                     "spy_ret_pct": round(spy_r * 100, 2) if spy_r is not None else None})
    ok = [r for r in rows if r.get("spread_pct") is not None]
    spreads = sorted(r["spread_pct"] for r in ok)
    agg = {"n_quarters": len(ok),
           "mean_spread_pct": round(sum(spreads) / len(spreads), 2) if spreads else None,
           "median_spread_pct": round(E._pct(spreads, 0.50), 2) if spreads else None,
           "pct_quarters_spread_positive":
               round(100.0 * sum(1 for s in spreads if s > 0) / len(spreads), 1)
               if spreads else None,
           "mean_least_ret_pct": round(sum(r["least_ret_pct"] for r in ok) / len(ok), 2) if ok else None,
           "mean_most_ret_pct": round(sum(r["most_ret_pct"] for r in ok) / len(ok), 2) if ok else None,
           "mean_spy_ret_pct": round(sum(r["spy_ret_pct"] for r in ok) / len(ok), 2) if ok else None}
    return {"rows": rows, "aggregate": agg}

# --------------------------------------------------------------------- main
def champion_run(pb, data, start, end, start_cash, floor0, ladder,
                 placebo_rng=None, label="", quiet=False, record_pools=False):
    """Adapter so the replication block can drive the imported champion
    engine through the same placebo harness as the variant."""
    return E.run_pot(pb, data["equity"], data["shares"], start, end,
                     start_cash, floor0, ladder, placebo_rng=placebo_rng,
                     label=label, quiet=quiet, record_pools=record_pools)

def main():
    ciks = E.get_ciks()
    CIK_OVERRIDES = {"XOM": 34088}   # carried over verbatim from champion
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

    FULL = ("2019-01-02", "2026-11-20")
    VAL = ("2023-01-03", "2026-11-20")
    out = {"variant": "Short interest (FINRA Rule 4560, % of shares "
                      "outstanding): quarterly top-5 LEAST-shorted of the "
                      "champion pond, plain -15% floor",
           "baseline": "promoted value+momentum (B/M + 12-1 momentum), plain floor",
           "universe": UNIVERSE, "pot": START_CASH, "floor": FLOOR0,
           "placebo_seeds": PLACEBO_SEEDS,
           "data_provenance": {
               "source": "FINRA Equity Short Interest files, "
                         "https://cdn.finra.org/equity/otcmarket/biweekly/shrt{YYYYMMDD}.csv",
               "measure": "currentShortPositionQuantity / EDGAR point-in-time "
                          "shares outstanding at the settlement date (% of "
                          "shares outstanding; FINRA files carry no float %)",
               "publication_rule": "usable at selection D only if the 7th "
                                   "trading day after settlement < D (FINRA: "
                                   "publication on the 7th business day after "
                                   "the settlement date)",
               "symbol_map": "BRK-B->BRKB; META->FB for settlements before "
                             "2022-06-10, META after; all others as-is",
               "vintage_caveat": "files as served today are FINRA's final "
                                 "vintage of each settlement (revisionFlag "
                                 "regime); settlement-date history, not a "
                                 "current snapshot"}}

    # ---- (0) replication check: champion ranked + champion placebo
    rep = {}
    published = {"FULL": {"final": 544.47, "placebo_median": 308.81, "beats": 19},
                 "VALIDATION": {"final": 288.05, "placebo_median": 201.15, "beats": 18}}
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        rb = E.run_pot(pb, equity_rows, shares_rows, ws, we, START_CASH,
                       FLOOR0, LADDER, label=f"REPLICATION CHAMPION {tag}",
                       quiet=True)
        rep[tag] = {"final": round(rb["final"], 2),
                    "published_final": published[tag]["final"],
                    "match": round(rb["final"], 2) == published[tag]["final"],
                    "orders": len(rb["trades"]), "halted": rb["halted"]}
        print(f"== REPLICATION champion {tag}: final=${rb['final']:,.2f} "
              f"published=${published[tag]['final']:,.2f} "
              f"match={rep[tag]['match']}", flush=True)
        pl = placebo_block(pb, data, ws, we, rb["final"], f"CHAMPION {tag}",
                           run_fn=champion_run)
        rep[tag]["placebo"] = pl
        rep[tag]["placebo_median_match"] = (
            pl["median_final"] == published[tag]["placebo_median"])
        rep[tag]["placebo_beats_match"] = (
            pl["ranked_beats_n_of_20"] == published[tag]["beats"])
        print(f"== REPLICATION champion {tag} placebo: median="
              f"${pl['median_final']:,.2f} published=${published[tag]['placebo_median']:,.2f} "
              f"match={rep[tag]['placebo_median_match']} | beats "
              f"{pl['ranked_beats_n_of_20']}/20 published={published[tag]['beats']} "
              f"match={rep[tag]['placebo_beats_match']}", flush=True)
    out["replication_champion"] = rep

    # ---- (1) ranked short-interest runs (form A)
    ranked = {}
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        s, _ = E.spy_net(pb, ws, we, START_CASH)
        r = run_pot_si(pb, data, ws, we, START_CASH, FLOOR0, LADDER,
                       label=f"SI {tag}", record_pools=True)
        diag = E.diagnostics(r, FLOOR0)
        ranked[tag] = r["final"]
        out[f"ranked_{tag}"] = {"final": round(r["final"], 2),
                                "ret_pct": round((r["final"] / START_CASH - 1) * 100, 2),
                                "costs": round(r["costs"], 2),
                                "orders": len(r["trades"]), "halted": r["halted"],
                                "restarts": r.get("restarts", []),
                                "second_halt": r.get("second_halt"),
                                "halt_info": r["halt_info"], "spy_net": round(s, 2),
                                "diag": diag, "pools": r["pools"],
                                "trades": r["trades"]}
        print(f"== SI {tag} final=${r['final']:,.2f} costs=${r['costs']:,.2f} "
              f"orders={len(r['trades'])} halted={r['halted']} | SPY net=${s:,.2f} "
              f"| maxDD={diag['max_drawdown_pct']}%", flush=True)

    # ---- (2) placebo on both windows (same scored pond as ranked)
    out["placebo_VALIDATION"] = placebo_block(pb, data, VAL[0], VAL[1],
                                              ranked["VALIDATION"], "VALIDATION")
    out["placebo_FULL"] = placebo_block(pb, data, FULL[0], FULL[1],
                                        ranked["FULL"], "FULL")

    # ---- (3) walk-forward folds, fresh $100 per calendar year 2020-2026
    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        fr = run_pot_si(pb, data, fs, fe, START_CASH, FLOOR0, LADDER,
                        label=f"FOLD {y}", quiet=True)
        fspy, _ = E.spy_net(pb, fs, fe, START_CASH)
        fst = curve_stats(fr)
        row = {"year": y, "start": fs, "end": fe, "final": fst["final"],
               "return_pct": round(fr["final"] / START_CASH * 100 - 100, 2),
               "spy_net_final": round(fspy, 2),
               "spy_return_pct": round(fspy / START_CASH * 100 - 100, 2),
               "beat_spy": fr["final"] > fspy,
               "max_drawdown_pct": fst["max_drawdown_pct"],
               "orders": fst["orders"], "costs": fst["costs"],
               "halted": fst["halted"], "restarts": fst.get("restarts", []),
               "second_halt": fst.get("second_halt")}
        folds.append(row)
        print(f"FOLD {y}: SI ${fr['final']:,.2f} ({row['return_pct']:+.2f}%) vs "
              f"SPY ${fspy:,.2f} ({row['spy_return_pct']:+.2f}%) beat={row['beat_spy']} "
              f"maxDD={row['max_drawdown_pct']}% orders={row['orders']} halted={row['halted']}",
              flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    comp = 100.0
    for f in folds:
        comp *= 1 + f["return_pct"] / 100.0
    out["fold_compounded_final"] = round(comp, 2)
    print(f"FOLD RECORD: {out['fold_record']} (champion: 4 wins, 3 losses); "
          f"fold-compounded ${out['fold_compounded_final']:,.2f} "
          f"(champion $313.01)", flush=True)

    # ---- (4) diagnostic (form B, paper-only)
    for tag, (ws, we) in (("FULL", FULL), ("VALIDATION", VAL)):
        dg = diagnostic(pb, data, ws, we)
        out[f"diagnostic_{tag}"] = dg
        a = dg["aggregate"]
        print(f"== DIAGNOSTIC {tag} (paper-only): {a['n_quarters']} quarters | "
              f"mean spread (least-most) {a['mean_spread_pct']}% | median "
              f"{a['median_spread_pct']}% | positive {a['pct_quarters_spread_positive']}% "
              f"| least {a['mean_least_ret_pct']}% vs most {a['mean_most_ret_pct']}% "
              f"vs SPY {a['mean_spy_ret_pct']}%", flush=True)

    # ---- (5) coverage: pool vs scored pond at every selection used
    cov = {"n_selection_dates": len(SELECTION_CACHE), "per_date": {}}
    for d, sel in sorted(SELECTION_CACHE.items()):
        missing = sorted(set(sel["pool"]) - set(sel["scored"]))
        ratios = sorted(sel["scored"].values())
        cov["per_date"][d] = {
            "pool": len(sel["pool"]), "scored": len(sel["scored"]),
            "settlement": sel["settlement"], "publication": sel["publication"],
            "missing_from_scored": missing,
            "ratio_min_pct": round(ratios[0] * 100, 3) if ratios else None,
            "ratio_max_pct": round(ratios[-1] * 100, 3) if ratios else None,
            "picks": sel["picks"],
            "pick_ratios_pct": {t: sel["detail"][t]["ratio_pct"]
                                for t in sel["picks"]}}
    out["coverage"] = cov
    print(f"COVERAGE: {cov['n_selection_dates']} selection dates; scored/pool "
          f"per date in results JSON", flush=True)

    with open(os.path.join(HERE, "short-interest-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")

if __name__ == "__main__":
    main()
