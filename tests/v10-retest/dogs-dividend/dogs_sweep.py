#!/usr/bin/env python3
"""
DOGS OF THE DOW (dogs-dividend) — THE GREAT RETEST v10, cadence sweep.

Strategy: rank the program's 30-name point-in-time universe by trailing
dividend yield (EDGAR per-share dividends, point-in-time, exactly the
v6/v9 method), hold the top 5 equal weight. Published Dogs form is
ANNUAL (January reconstitution); the original program test re-picked
QUARTERLY. This script:
  1. INTEGRITY: reproduces the original published finals in the original
     (quarterly, his-rules plain-floor) form — CONT $80.79 halted
     2020-03-20, VAL $183.02 — through the original v9 module's own
     engine and data, before any sweep number is taken.
  2. SWEEP: DECADE 2016-11-21 -> 2026-11-20 x 7 cadences under the
     SPEC's uniform cadence definition, $100/cell, program costs
     (0.10%/side + $0.01/sell order), adopted v9 protections (plain
     -15% floor, 90-day sit-out, restart at next cadence date, episode-2
     floor -15% from restart balance, second halt ends the run).
     Dividends credited as cash per the program method (EDGAR-estimated
     credits on the dividend-UNADJUSTED basis-B price book).
  3. 20-seed placebos per cell (random 5 from the cell's own scored
     pool at each cadence date, identical mechanics/credits/protections;
     one Random(seed) per twin, carried across episodes).

Data: EDGAR companyfacts + Yahoo prices reused read-only from the v4
caches (integrity). For the sweep, Yahoo chart files were re-downloaded
with the original fetch method extended to period1=2016-11-01 (the v4
cache starts 2017-06-01) and cached in ./cache/; the script validates
the extended book by re-running the v9 quarterly CONT/VAL runs on it
and requiring the published v9 finals ($66.33 / $183.02) to reproduce.
The 1.7GB long-run cache is NOT bulk-loaded; only SPY's decade figure
is taken as the SPEC reference ($367.80, verified in-plumbing below
from the extended SPY bars).
"""
import bisect, importlib.util, json, math, os, random, time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
V9 = os.path.expanduser("~/workspace/stock-app/backtests/v9-muse-rules/dogs-dividend/dogs-dividend-v9.py")
spec = importlib.util.spec_from_file_location("dogs_v9", V9)
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)
E = D.E
UNIVERSE = D.UNIVERSE
START_CASH = 100.0
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
DECADE = ("2016-11-21", "2026-11-20")
CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]

# ------------------------------------------------------------- fast book
class FastBook:
    """Same semantics as E.PriceBook, O(log n) close_on_or_before."""
    def __init__(self, bars_by_ticker):
        self.bars = bars_by_ticker
        self.dates = sorted({b["d"] for bl in bars_by_ticker.values()
                             for b in bl})
        self.idx = {t: {b["d"]: b for b in bl}
                    for t, bl in bars_by_ticker.items()}
        self._cd = {t: [b["d"] for b in bl] for t, bl in bars_by_ticker.items()}
        self._cc = {t: [b["c"] for b in bl] for t, bl in bars_by_ticker.items()}

    def bar(self, t, d):
        return self.idx.get(t, {}).get(d)

    def close_on_or_before(self, t, d):
        ds = self._cd.get(t, [])
        i = bisect.bisect_right(ds, d) - 1
        return self._cc[t][i] if i >= 0 else None

def load_raw_from(path):
    with open(path, "rb") as f:
        j = json.loads(f.read())
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
        bars.append({"d": d, "o_raw": o, "c_raw": c, "c_adj": a})
    bars.sort(key=lambda b: b["d"])
    ev = res.get("events") or {}
    divs = []
    for _, dv in (ev.get("dividends") or {}).items():
        divs.append({"d": time.strftime("%Y-%m-%d", time.gmtime(dv["date"])),
                     "amount": float(dv["amount"])})
    divs.sort(key=lambda x: x["d"])
    splits = []
    for _, sv in (ev.get("splits") or {}).items():
        splits.append({"d": time.strftime("%Y-%m-%d", time.gmtime(sv["date"])),
                       "num": float(sv["numerator"]),
                       "den": float(sv["denominator"])})
    splits.sort(key=lambda x: x["d"])
    return bars, divs, splits

def bars_a_from_loaded(rbars):
    out = []
    for b in rbars:
        ratio = b["c_adj"] / b["c_raw"] if b["c_raw"] else 1.0
        out.append({"d": b["d"], "o": (b["o_raw"] * ratio if b["o_raw"]
                                       else b["c_adj"]), "c": b["c_adj"]})
    return out

# ------------------------------------------------- fast point-in-time DPS
def preextract(facts):
    """Per concept: quarterly-duration rows and annual-duration rows,
    pre-filtered from D.dps_rows output (identical row set the original
    quarterly_dps_at / annual_dps_at scan)."""
    out = {}
    for concept in (D.DECLARED, D.CASHPAID):
        rows = D.dps_rows(facts, concept)
        q = [r for r in rows if 60 <= D._dur_days(r[0], r[1]) <= 100]
        a = [r for r in rows if 300 <= D._dur_days(r[0], r[1]) <= 400]
        out[concept] = (q, a)
    return out

def quarterly_fast(qrows, asof, splits):
    per_end = {}
    for start, end, filed, val in qrows:
        if filed >= asof:
            continue
        cur = per_end.get(end)
        if cur is None or filed > cur[0]:
            per_end[end] = (filed, val)
    if len(per_end) < 4:
        return None
    ends = sorted(per_end)[-4:]
    latest = ends[-1]
    if latest < (date.fromisoformat(asof) - timedelta(days=200)).isoformat():
        return None
    if (date.fromisoformat(ends[-1]) - date.fromisoformat(ends[0])).days > 400:
        return None
    total = sum(per_end[e][1] * D.split_factor_after(splits, e) for e in ends)
    return (total, latest, per_end[latest][0])

def annual_fast(arows, asof, splits):
    cutoff = (date.fromisoformat(asof) - timedelta(days=548)).isoformat()
    best = None
    for start, end, filed, val in arows:
        if filed >= asof or end < cutoff or end > asof:
            continue
        key = (end, filed)
        if best is None or key > best[0]:
            best = (key, (val, end, filed))
    if best is None:
        return None
    val, end, filed = best[1]
    return (val * D.split_factor_after(splits, end), end, filed)

def trailing_fast(pre, asof, splits):
    for concept in (D.DECLARED, D.CASHPAID):
        got = quarterly_fast(pre[concept][0], asof, splits)
        if got is not None:
            return (got[0], concept + "-Q", got[1])
    for concept in (D.DECLARED, D.CASHPAID):
        got = annual_fast(pre[concept][1], asof, splits)
        if got is not None:
            return (got[0], concept + "-A", got[1])
    return None

def build_yield_table_fast(pre_by_t, splits_by_t, raw_by_t, sel_dates):
    """Identical yields to D.build_yield_table; price_at uses bisect +
    precomputed post-date spinoff (pseudo-split) suffix factors."""
    price_at = {}
    for t, bars in raw_by_t.items():
        dates = [b["d"] for b in bars]
        closes = [b["c_raw"] for b in bars]
        pseudo = [s for s in splits_by_t[t]
                  if s["num"] > 25 or s["den"] > 25]
        suf = [1.0] * (len(dates) + 1)
        pi = len(pseudo) - 1
        run = 1.0
        for i in range(len(dates) - 1, -1, -1):
            while pi >= 0 and pseudo[pi]["d"] > dates[i]:
                run *= pseudo[pi]["num"] / pseudo[pi]["den"]
                pi -= 1
            suf[i] = run
        price_at[t] = (dates, closes, suf)

    def px(t, d):
        dates, closes, suf = price_at[t]
        i = bisect.bisect_right(dates, d) - 1
        if i < 0:
            return None
        return closes[i] * suf[i]

    table = {}
    for d in sel_dates:
        yields, excluded = {}, []
        for t in UNIVERSE:
            got = trailing_fast(pre_by_t[t], d, D.true_splits(splits_by_t[t]))
            if got is None:
                excluded.append(t)
                continue
            p = px(t, d)
            if p is None or p <= 0:
                excluded.append(t)
                continue
            yields[t] = got[0] / p
        table[d] = (yields, excluded, {})
    return table

# ------------------------------------------------------- generalized engine
def run_gen(pb, yield_table, credits_by_t, sel_dates, start, end,
            start_cash, floor0, placebo_rng=None):
    """Byte-for-byte mechanics of D.run_pot_dogs (champion mechanics,
    0.10%/side + $0.01/sell, plain floor, halt/end liquidation, EDGAR
    dividend cash credits) with the selection-date set supplied by the
    caller instead of quarter_selection_dates."""
    cash = start_cash
    floor = floor0
    positions = {}
    trades = []
    total_costs = 0.0
    total_divs = 0.0
    halted = None
    halt_info = None
    curve = []
    pools = []
    sel_set = set(sel_dates)
    days = [d for d in pb.dates if start <= d <= end]
    if not days:
        return None
    pending = None
    credit_idx = {t: 0 for t in credits_by_t}
    credits_sorted = {t: sorted(credits_by_t.get(t, []))
                      for t in credits_by_t}

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
        for t in list(positions):
            cl = credits_sorted.get(t, [])
            i = credit_idx[t]
            while i < len(cl) and cl[i][0] <= d:
                if cl[i][0] == d:
                    amt = positions[t] * cl[i][1]
                    cash += amt
                    total_divs += amt
                    trades.append((d, t, "DIV", positions[t], None, amt, 0.0))
                i += 1
            credit_idx[t] = i
        if pending is not None:
            execute_rebalance(d, pending)
            pending = None
        if d in sel_set:
            yields, excluded, detail = yield_table.get(d, ({}, [], {}))
            if len(yields) >= 5:
                if placebo_rng is not None:
                    picks = placebo_rng.sample(sorted(yields), 5)
                else:
                    picks = sorted(yields,
                                   key=lambda t: (-yields[t], t))[:5]
                pools.append((d, sorted(yields),
                              {t: round(yields[t], 4) for t in picks},
                              list(picks), excluded))
                pv = portfolio_close(d)
                each = pv / 5.0
                pending = {t: each for t in picks}
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
                    trades.append((nd, t, "SELL-HALT", positions[t],
                                   b["o"], val, c))
            positions = {}
            return {"final": cash, "costs": total_costs,
                    "dividends": total_divs, "trades": trades,
                    "halted": halted, "end": nd, "halt_info": halt_info,
                    "pools": pools, "curve": curve}
    last = days[-1]
    for t in list(positions):
        c_ = pb.close_on_or_before(t, last)
        if c_:
            val = positions[t] * c_
            cst = val * 0.001 + 0.01
            cash += val - cst
            total_costs += cst
            trades.append((last, t, "SELL-END", positions[t], c_, val, cst))
    return {"final": cash, "costs": total_costs, "dividends": total_divs,
            "trades": trades, "halted": None, "end": last,
            "halt_info": None, "pools": pools, "curve": curve}

def _ord(dstr):
    return date(int(dstr[:4]), int(dstr[5:7]), int(dstr[8:10])).toordinal()

def run_v9_gen(pb, yield_table, credits_by_t, sel_dates, start, end,
               start_cash=100.0, placebo_rng=None):
    """Adopted v9 protections on an arbitrary cadence: plain -15% floor;
    first halt -> liquidate (engine), sit in cash 90 calendar days,
    restart at the next cadence date with episode-2 floor -15% from the
    restart balance; second halt ends the run."""
    sel = sorted(d for d in sel_dates if start <= d <= end)
    floor1 = round(0.85 * start_cash, 2)
    r1 = run_gen(pb, yield_table, credits_by_t, sel, start, end,
                 start_cash, floor1, placebo_rng=placebo_rng)
    out = {"final": r1["final"], "costs": r1["costs"],
           "dividends": r1["dividends"], "trades": list(r1["trades"]),
           "curve": list(r1["curve"]), "halts": [], "restarts": [],
           "second_halt": None, "restart": False}
    if r1["halted"] is None:
        return out
    out["halts"].append({"episode": 1, "signal_date": r1["halted"],
                         "signal_close": r1["halt_info"]["signal_close"],
                         "floor_in_effect": floor1,
                         "liquidation_date": r1["end"],
                         "liquidation_final": round(r1["final"], 2)})
    liq = r1["end"]
    cash = r1["final"]
    day90 = _ord(r1["halted"]) + 90
    restart = None
    for cand in sel:
        if _ord(cand) >= day90:
            restart = cand
            break
    seg_end = restart if restart else end
    for d in pb.dates:
        if liq < d < seg_end:
            out["curve"].append((d, cash))
    if restart is None:
        if end > liq:
            out["curve"].append((end, cash))
        out["curve"].sort(key=lambda kv: kv[0])
        return out
    floor2 = round(0.85 * cash, 2)
    out["restart"] = True
    out["restarts"].append({"halt_signal_date": r1["halted"],
                             "liquidation_date": liq,
                             "halt_signal_close": r1["halt_info"]["signal_close"],
                             "restart_date": restart,
                             "restart_balance": round(cash, 2),
                             "episode2_floor": floor2})
    r2 = run_gen(pb, yield_table, credits_by_t, sel, restart, end,
                 cash, floor2, placebo_rng=placebo_rng)
    out["final"] = r2["final"]
    out["costs"] += r2["costs"]
    out["dividends"] += r2["dividends"]
    out["trades"] += list(r2["trades"])
    out["curve"] += list(r2["curve"])
    if r2["halted"] is not None:
        out["second_halt"] = {"signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "final": round(r2["final"], 2)}
        out["halts"].append({"episode": 2, "signal_date": r2["halted"],
                              "signal_close": r2["halt_info"]["signal_close"],
                              "floor_in_effect": r2["halt_info"]["floor_in_effect"],
                              "liquidation_date": r2["end"],
                              "liquidation_final": round(r2["final"], 2)})
    out["curve"].sort(key=lambda kv: kv[0])
    return out

def cadence_dates(pb, cadence, start, end):
    days = [d for d in pb.dates if start <= d <= end]
    if cadence == "daily":
        return days
    out, seen = [], set()
    week_idx = {}
    for d in days:
        dt = date.fromisoformat(d)
        if cadence == "weekly":
            key = dt.isocalendar()[:2]
        elif cadence == "biweekly":
            key = dt.isocalendar()[:2]
        elif cadence == "monthly":
            key = (d[:4], d[5:7])
        elif cadence == "quarterly":
            if d[5:7] not in ("01", "04", "07", "10"):
                continue
            key = (d[:4], d[5:7])
        elif cadence == "semiannual":
            if d[5:7] not in ("01", "07"):
                continue
            key = (d[:4], d[5:7])
        elif cadence == "annual":
            if d[5:7] != "01":
                continue
            key = d[:4]
        else:
            raise ValueError(cadence)
        if cadence == "biweekly":
            if key not in week_idx:
                week_idx[key] = len(week_idx)
            if key in seen or week_idx[key] % 2 != 0:
                continue
            seen.add(key)
            out.append(d)
        else:
            if key in seen:
                continue
            seen.add(key)
            out.append(d)
    return out

def stats_from_curve(curve, final, start, end):
    vals = [v for _, v in curve] + [final]
    peak, maxdd = -1.0, 0.0
    for v in vals:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    years = (date.fromisoformat(end) - date.fromisoformat(start)).days / 365.25
    cagr = (final / START_CASH) ** (1.0 / years) - 1.0 if final > 0 else -1.0
    return round(cagr * 100, 2), round(maxdd * 100, 2)

# ------------------------------------------------------------------- main
def main():
    t0 = time.time()
    log = []
    def say(s):
        print(s, flush=True)
        log.append(s)

    ciks = E.get_ciks()
    facts_by_t = {}
    for t in UNIVERSE:
        cik = {"XOM": 34088}.get(t, ciks[t][0])
        facts_by_t[t] = E.get_companyfacts(cik)
    pre_by_t = {t: preextract(facts_by_t[t]) for t in UNIVERSE}

    # ---------- INTEGRITY on the ORIGINAL v4 cache + original engine
    bars_b0, splits0, tsplits0, raw0 = {}, {}, {}, {}
    for t in UNIVERSE:
        rbars, divs, splits = D.load_raw(t)
        raw0[t] = rbars
        splits0[t] = splits
        tsplits0[t] = D.true_splits(splits)
        bars_b0[t] = D.basis_b_from_loaded(rbars, divs, splits)
    pb0 = E.PriceBook(bars_b0)
    sel_q0 = E.quarter_selection_dates(pb0, CONT[0], CONT[1])
    yt0 = D.build_yield_table(facts_by_t, splits0, raw0, sel_q0)
    credits0 = {t: D.build_credits(facts_by_t[t], tsplits0[t], pb0.dates)
                for t in UNIVERSE}
    integ = {}
    for name, (ws, we), pub, pub_halt in (
            ("CONT", CONT, 80.79, "2020-03-20"), ("VAL", VAL, 183.02, None)):
        # yield table for this window's quarterly dates (superset built
        # from CONT selections covers VAL dates too: build explicitly)
        selw = E.quarter_selection_dates(pb0, ws, we)
        ytw = D.build_yield_table(facts_by_t, splits0, raw0, selw)
        r = D.run_pot_dogs(pb0, ytw, credits0, ws, we, START_CASH, 85.0,
                           label=f"INTEG {name}", quiet=True)
        ok = abs(round(r["final"], 2) - pub) < 0.005 and r["halted"] == pub_halt
        integ[name] = {"window": [ws, we], "published_final": pub,
                       "reproduced_final": round(r["final"], 2),
                       "published_halted": pub_halt, "reproduced_halted": r["halted"],
                       "dividends_credited": round(r["dividends"], 2),
                       "costs": round(r["costs"], 2), "match": bool(ok)}
        say(f"INTEGRITY {name}: published=${pub} reproduced=${r['final']:,.2f} "
            f"halted={r['halted']} match={ok}")
    assert all(v["match"] for v in integ.values()), "INTEGRITY FAILED — stop"

    # fast-yield validation vs original on every CONT quarterly date
    ytf = build_yield_table_fast(pre_by_t, splits0, raw0, sel_q0)
    worst = 0.0
    for d in sel_q0:
        y0, _, _ = yt0[d]
        y1, _, _ = ytf[d]
        assert set(y0) == set(y1), f"yield pool mismatch {d}"
        for t in y0:
            worst = max(worst, abs(y0[t] - y1[t]))
    say(f"fast yield table validation: max |diff| vs original = {worst:.2e} "
        f"over {len(sel_q0)} quarterly dates")
    assert worst < 1e-12

    # ---------- extended book (2016-11-01 ->) for the decade sweep
    cache = os.path.join(HERE, "cache")
    bars_bX, splitsX, tsplitsX, rawX, bars_aX = {}, {}, {}, {}, {}
    for t in UNIVERSE + ["SPY"]:
        rbars, divs, splits = load_raw_from(os.path.join(cache, f"px_{t}.json"))
        rawX[t] = rbars
        if t == "SPY":
            bars_aX[t] = bars_a_from_loaded(rbars)
            continue
        splitsX[t] = splits
        tsplitsX[t] = D.true_splits(splits)
        bars_bX[t] = D.basis_b_from_loaded(rbars, divs, splits)
        bars_aX[t] = bars_a_from_loaded(rbars)
    pbX = FastBook(bars_bX)
    pbAX = FastBook(bars_aX)
    creditsX = {t: D.build_credits(facts_by_t[t], tsplitsX[t], pbX.dates)
                for t in UNIVERSE}

    # validate extended book: v9 quarterly CONT/VAL must reproduce the
    # published v9 finals ($66.33 / $183.02) through the generic engine
    sel_q_dec = cadence_dates(pbX, "quarterly", DECADE[0], DECADE[1])
    all_days = cadence_dates(pbX, "daily", DECADE[0], DECADE[1])
    ytX_q = build_yield_table_fast(pre_by_t, splitsX,
                                   {t: rawX[t] for t in UNIVERSE}, sel_q_dec)
    for name, (ws, we), v9pub in (("CONT", CONT, 66.33), ("VAL", VAL, 183.02)):
        selw = [d for d in sel_q_dec if ws <= d <= we]
        r = run_v9_gen(pbX, ytX_q, creditsX, selw, ws, we)
        say(f"extended-book v9 check {name}: generic=${r['final']:,.2f} "
            f"published v9=${v9pub} match={abs(round(r['final'],2)-v9pub)<0.005}")
        assert abs(round(r["final"], 2) - v9pub) < 0.005, \
            "extended book does not reproduce v9 — aborting sweep"

    spy_dec, spy_costs = E.spy_net(pbAX, DECADE[0], DECADE[1], START_CASH)
    say(f"SPY decade (extended book, spy_net): ${spy_dec:,.2f} "
        f"(SPEC reference $367.80)")

    # ---------- full yield table for every decade trading day
    yt_all = build_yield_table_fast(pre_by_t, splitsX,
                                    {t: rawX[t] for t in UNIVERSE}, all_days)
    say(f"yield table built for {len(all_days)} decade trading days "
        f"({time.time()-t0:.0f}s)")

    # ---------- sweep
    cells = {}
    cell_files = {}
    for cad in CADENCES:
        sel = cadence_dates(pbX, cad, DECADE[0], DECADE[1])
        r = run_v9_gen(pbX, yt_all, creditsX, sel, DECADE[0], DECADE[1])
        orders = len([x for x in r["trades"] if x[2] != "DIV"])
        cagr, maxdd = stats_from_curve(r["curve"], r["final"],
                                       DECADE[0], DECADE[1])
        finals, rows = [], []
        for seed in range(1, 21):
            rng = random.Random(seed)
            rp = run_v9_gen(pbX, yt_all, creditsX, sel, DECADE[0], DECADE[1],
                            placebo_rng=rng)
            finals.append(round(rp["final"], 2))
            rows.append({"seed": seed, "final": round(rp["final"], 2),
                         "dividends": round(rp["dividends"], 2),
                         "halts": rp["halts"], "second_halt": rp["second_halt"]})
        beaten = sum(1 for f in finals if f < round(r["final"], 2))
        cell = {"final": round(r["final"], 2), "cagr_pct": cagr,
                "max_dd_pct": maxdd, "halts": r["halts"],
                "restart": r["restart"], "second_halt": bool(r["second_halt"]),
                "second_halt_detail": r["second_halt"],
                "restarts": r["restarts"], "costs": round(r["costs"], 2),
                "orders": orders, "dividends_credited": round(r["dividends"], 2),
                "placebo_beaten": beaten,
                "placebo_note": "20 random-5 twins (seeds 1-20) drawn from the "
                                "cell's own scored pool at each cadence date, "
                                "identical credits/costs/v9 protections; one "
                                "Random(seed) per twin carried across episodes.",
                "placebo_finals": finals,
                "n_selection_dates": len(sel)}
        cells[cad] = cell
        cell_files[cad] = {"slug": "dogs-dividend", "cadence": cad,
                           "window": list(DECADE), "start_cash": START_CASH,
                           **cell, "placebo_rows": rows,
                           "equity_curve": [[d, round(v, 4)]
                                            for d, v in r["curve"]]}
        with open(os.path.join(HERE, "cells", f"{cad}.json"), "w") as f:
            json.dump(cell_files[cad], f, indent=1, default=str)
        say(f"CELL {cad}: sel_dates={len(sel)} final=${r['final']:,.2f} "
            f"CAGR={cagr}% maxDD={maxdd}% costs=${r['costs']:,.2f} "
            f"orders={orders} divs=${r['dividends']:,.2f} "
            f"halts={len(r['halts'])} restart={r['restart']} "
            f"second_halt={bool(r['second_halt'])} placebo_beaten={beaten}/20")

    money = [c for c in CADENCES
             if cells[c]["final"] > round(spy_dec, 2)
             and cells[c]["placebo_beaten"] >= 11]
    results = {
        "slug": "dogs-dividend",
        "area": "Long-holding fundamental sort (W3) — Dogs of the Dow: "
                "highest trailing dividend yield, top-5, equal weight, "
                "on the program's 30-name point-in-time pond",
        "area_source": "backtests/v10-retest/SPEC.md, worker batch W3 + CADENCE GRID",
        "native_cadence": "annual",
        "cadence": "annual",
        "original_cadence_foreign": {
            "foreign": True,
            "note": "Published Dogs form is ANNUAL (January reconstitution, "
                    "native). The original program test (v6/v9) re-picked "
                    "QUARTERLY — a foreign cadence vs the published form. "
                    "Integrity below reproduces that quarterly original form; "
                    "the sweep's annual cell is the native form."},
        "integrity": {
            "status": "reproduced",
            "note": "Original (quarterly, his-rules plain -15% floor, basis-B "
                    "prices + EDGAR cash dividend credits) reproduced through "
                    "the original v9 module's own engine and the v4 caches, "
                    "to the cent, before any sweep run. CONT placebo record "
                    "in the original: ranked beat 0/20 twins (median $271.88); "
                    "VAL: 8/20 (median $186.13). Extended-book check: the "
                    "generic cadence engine on the re-downloaded 2016-start "
                    "Yahoo book reproduces the published v9 finals CONT "
                    "$66.33 and VAL $183.02 to the cent.",
            "original_finals": {"CONT_his_rules": 80.79, "VAL_his_rules": 183.02,
                                "CONT_v9": 66.33, "VAL_v9": 183.02},
            "reproduced_finals": {"CONT_his_rules": integ["CONT"]["reproduced_final"],
                                  "VAL_his_rules": integ["VAL"]["reproduced_final"]},
            "detail": integ},
        "decade_spy_final": round(spy_dec, 2),
        "decade_window": list(DECADE),
        "decade_note": "Decade covered in full: Yahoo chart files re-downloaded "
                       "with the original fetch method from 2016-11-01 (v4 cache "
                       "starts 2017-06-01), cached in ./cache/, validated by the "
                       "v9 CONT/VAL reproduction above. SPY decade computed "
                       "in-plumbing via the champion engine's spy_net on the "
                       "extended adjusted book.",
        "champion_decade_reference": 65.89,
        "cells": cells,
        "money_cadences": money,
        "verdict_area": "NO GROUND" if not money else "REAL BUT SMALL",
        "verdict_change": "placeholder — set in RESULTS.md assembly",
        "run_log": log}
    with open(os.path.join(HERE, "results.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    say(f"DONE in {time.time()-t0:.0f}s; money cadences: {money}")

if __name__ == "__main__":
    main()
