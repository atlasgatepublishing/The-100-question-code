#!/usr/bin/env python3
"""
FOLKLORE TEST F-3 — THE FED MODEL (trailing-earnings form).
Terry's AI stock app. Simulation only.

Spec source: ~/workspace/stock-app/research/v7-completeness/folklore-audit.md,
Spec F-3 — implemented VERBATIM. The spec is frozen; nothing below improves,
reinterprets, or tunes it.

THE SPEC AS WRITTEN:
  * Universe/data: SPY only. Earnings yield = trailing 12-month as-reported
    S&P 500 earnings / index price, and the 10-year Treasury yield, BOTH from
    Robert Shiller's free published dataset (ie_data). The original model
    uses forward I/B/E/S earnings (paid data); the trailing substitution is
    the standard free-data form declared in the spec — the verdict names
    this defendant.
  * Rule (frozen): evaluate on the last trading day of each month, using
    the most recent monthly values published by that date. If E/P > 10-year
    yield -> hold SPY for the next month. If E/P <= yield -> hold cash.
    Execute switches at the next open.
  * Chassis (audit, shared by all F-specs): $100 pot; execution at the next
    session's open after a signal computed on closes; costs 0.10% of trade
    value per side + $0.01 per sell order; plain -15% floor at the pot level
    (a close at or below $85 liquidates everything at the next open and
    ends the run); windows continuous 2019-01-01 -> 2026-11-20 and
    validation 2023-01-01 -> 2026-11-20; benchmarks SPY buy-hold net of the
    same costs and the 20-seed random placebo distribution on the same
    universe and cadence; promotion requires beating SPY AND the placebo
    median on validation.

FORCED READINGS (stated here, before any result — the spec leaves these
points to the implementer; each follows the program's existing precedent):
  1. The 10-year yield is Shiller's own "Long Interest Rate" (GS10) column
     from the same ie_data row as the earnings — the spec says both series
     come from Shiller's dataset, so no second yield source is used.
     (FRED DGS10 / treasury.gov were therefore not needed.)
  2. "Most recent monthly values published by that date": at an evaluation
     on the last trading day of month M, the rule uses Shiller's row for
     month M-1. This is the same ~1-month publication lag the program's
     CAPE test used (multpl value dated the 1st of the decision month).
     If the M-1 row lacks an earnings or rate value, the most recent
     earlier complete row is used.
  3. E/P is computed from the same Shiller row: E (trailing 12-month
     as-reported earnings) / P (index price), expressed in percent,
     compared against the GS10 value (percent).
  4. The strategy is always-on (CAPE-test precedent): at a window's start
     the pot takes the position dictated by the most recent month-end
     evaluation on or before the window start, executed at the window's
     first open.
  5. Cash earns 0% (program convention).
  6. PLACEBO (the chassis requires a 20-seed random placebo on the same
     universe and cadence; for a single-asset monthly timer the house
     reading is): circular shifts of the strategy's own realized sequence
     of monthly targets. A shift preserves the exact number of invested
     months AND the exact number of switches — only WHICH months are
     invested changes. Seeds 1..20 each draw one nonzero shift via
     random.Random(seed). This is stated before results, per discipline.

DATA LIMITS (stated, not patched):
  * Shiller's ie_data is the CURRENT vintage: historical earnings embed
    later revisions, and the most recent months' earnings are partly
    Shiller's estimates. Same limitation the program's CAPE test carried.
  * SPY prices: Yahoo adjusted (adjclose-ratio) daily bars, the program's
    shared cache — the same series the champion's spy_net uses. Integrity
    gate: this script's SPY buy-hold must reproduce the published
    $313.62 (2019->2026) and $187.77 (2023->2026) before any F-3 number
    is taken; if it does not, the script aborts.

MECHANICS (identical to the champion engine / CAPE test):
  * Buy: spend cash/1.001 at the open (0.10% buy cost).
  * Sell: proceeds less 0.10% + $0.01 at the open.
  * Floor: close equity <= $85 on any day but the window's last ->
    liquidate at next open, run ends, final = cash after costs.
  * End of window: liquidate at the final close (sell cost applies), so
    every final is post-liquidation cash, like the champion's $544.47.
"""
import bisect
import csv
import json
import os
import random
import time

HERE = os.path.dirname(os.path.abspath(__file__))
START_CASH = 100.0
FLOOR0 = 85.0
CONTINUOUS = ("2019-01-01", "2026-11-20")
VALIDATION = ("2023-01-01", "2026-11-20")
PUBLISHED_SPY = {"continuous": 313.62, "validation": 187.77}
PLACEBO_SEEDS = list(range(1, 21))


# --------------------------------------------------------------------- data
def load_spy_bars():
    """Verbatim from the program's CAPE test (same shared cache series)."""
    path = os.path.join(HERE, "data", "px_SPY.json")
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
        ratio = a / c if c else 1.0
        bars.append({"d": d, "o": (o * ratio if o else a), "c": a})
    bars.sort(key=lambda b: b["d"])
    return bars


def load_shiller():
    """Parse Shiller's ie_data.xls -> {yyyymm: {p, e, gs10}} and write
    shiller_monthly.csv alongside for auditability."""
    import xlrd
    path = os.path.join(HERE, "data", "ie_data.xls")
    wb = xlrd.open_workbook(path)
    # MECHANICAL FIX (data parsing only, applied by the completion run):
    # the current Yale file's first sheet is a 1x1 "Disclaimer" sheet and
    # the data lives on the "Data" sheet — search every sheet for the
    # header row instead of assuming sheet 0.
    sh, hdr = None, None
    for si in range(wb.nsheets):
        cand = wb.sheet_by_index(si)
        for r in range(min(15, cand.nrows)):
            row = [str(cand.cell_value(r, c)).strip()
                   for c in range(cand.ncols)]
            if any("Price" in v for v in row) and \
                    any("Earnings" in v for v in row):
                sh, hdr = cand, r
                break
        if sh is not None:
            break
    if hdr is None:
        raise SystemExit("ie_data header row not found")
    header = [str(sh.cell_value(hdr, c)).strip() for c in range(sh.ncols)]
    col = {}
    for i, h in enumerate(header):
        hl = h.lower()
        if hl == "date":
            col["date"] = i
        elif h == "P":
            col["p"] = i
        elif h == "E":
            col["e"] = i
        elif ("long" in hl and "rate" in hl) or "gs10" in hl:
            # MECHANICAL FIX (data parsing only): in the current Yale
            # file the long-rate label is split across three header rows
            # ("Long" / "Interest" / "Rate GS10"), so the label row
            # itself reads "Rate GS10" — accept the GS10 tag for the
            # same column forced reading 1 names.
            col["gs10"] = i
    missing = {"date", "p", "e", "gs10"} - set(col)
    if missing:
        raise SystemExit(f"ie_data columns not found: {missing}; header={header}")
    rows = {}
    for r in range(hdr + 1, sh.nrows):
        dv = sh.cell_value(r, col["date"])
        if not isinstance(dv, (int, float)) or dv <= 0:
            continue
        yr = int(dv)
        mo = int(round((dv - yr) * 100))
        if not (1 <= mo <= 12):
            continue
        key = f"{yr:04d}-{mo:02d}"
        vals = {}
        ok = True
        for name in ("p", "e", "gs10"):
            v = sh.cell_value(r, col[name])
            if not isinstance(v, (int, float)) or v == 0:
                ok = False
                break
            vals[name] = float(v)
        if ok:
            rows[key] = vals
    with open(os.path.join(HERE, "shiller_monthly.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["month", "price", "earnings_trailing", "gs10_pct",
                    "earnings_yield_pct"])
        for k in sorted(rows):
            v = rows[k]
            w.writerow([k, v["p"], v["e"], v["gs10"],
                        round(v["e"] / v["p"] * 100, 4)])
    return rows


# ------------------------------------------------------------------- signal
class FedSignal:
    """Spec F-3 signal from Shiller monthly rows, with the declared
    one-month publication lag (forced reading 2)."""

    def __init__(self, rows):
        self.rows = rows                       # {yyyymm: {p, e, gs10}}
        self.months = sorted(rows)

    def row_for_decision(self, decision_date):
        """Shiller row usable at an evaluation on decision_date: the row
        for the month BEFORE the decision month; if that row is missing,
        the most recent earlier complete row. Returns (month, row)."""
        dm = decision_date[:7]
        yr, mo = int(dm[:4]), int(dm[5:7])
        mo -= 1
        if mo == 0:
            yr, mo = yr - 1, 12
        target = f"{yr:04d}-{mo:02d}"
        if target in self.rows:
            return target, self.rows[target]
        prior = [m for m in self.months if m < target]
        if not prior:
            return None, None
        k = prior[-1]
        return k, self.rows[k]

    def decision(self, decision_date):
        m, row = self.row_for_decision(decision_date)
        if row is None:
            return None
        ep = row["e"] / row["p"] * 100.0
        y = row["gs10"]
        return {"decision_date": decision_date, "shiller_month": m,
                "price": round(row["p"], 2), "earnings": round(row["e"], 2),
                "ep_pct": round(ep, 3), "gs10_pct": round(y, 3),
                "target": "SPY" if ep > y else "CASH"}


# ------------------------------------------------------------------- engine
class Book:
    def __init__(self, bars):
        self.bars = bars
        self.dates = [b["d"] for b in bars]
        self.by_date = {b["d"]: b for b in bars}

    def bar(self, d):
        return self.by_date.get(d)


def month_end_days(book, start, end):
    """Last trading day of each calendar month within [start, end]."""
    out, seen = [], set()
    for d in book.dates:
        if start <= d <= end:
            seen.add(d[:7])
    for m in sorted(seen):
        days = [d for d in book.dates if d[:7] == m and start <= d <= end]
        if days:
            out.append(days[-1])
    return out


def last_month_end_on_or_before(book, date):
    cands = month_end_days(book, book.dates[0], date)
    return cands[-1] if cands else None


def decision_dates(book, start, end):
    """[entry-check date] + [month-end days inside the window]."""
    entry = last_month_end_on_or_before(book, start)
    ds = [entry] if entry else []
    ds += [d for d in month_end_days(book, start, end) if d != entry]
    return ds


def run_window(book, targets, start, end, label=""):
    """targets: list of 'SPY'/'CASH' aligned with decision_dates(book,
    start, end) — index 0 is the entry check (executed at the window's
    first open), the rest are month-end evaluations (executed at the
    next open). Mechanics copied from the program's CAPE test."""
    days = [d for d in book.dates if start <= d <= end]
    if not days:
        return None
    dec_dates = decision_dates(book, start, end)
    assert len(targets) == len(dec_dates), (len(targets), len(dec_dates))
    cash = START_CASH
    shares = 0.0
    total_costs = 0.0
    trades = []
    curve = []
    days_invested = 0
    pending = None
    if targets[0] == "SPY":
        pending = "SPY"
    dec_set = {d: i for i, d in enumerate(dec_dates[1:], start=1)}

    def equity_close(d):
        return cash + shares * book.by_date[d]["c"]

    halted = None
    for di, d in enumerate(days):
        bar = book.bar(d)
        if pending is not None:
            if pending == "SPY" and shares == 0.0 and cash > 0:
                buy_val = cash / 1.001
                c = buy_val * 0.001
                shares = buy_val / bar["o"]
                cash -= buy_val + c
                total_costs += c
                trades.append((d, "BUY", round(shares, 6), bar["o"],
                               round(buy_val, 2), round(c, 2)))
            elif pending == "CASH" and shares > 0:
                val = shares * bar["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((d, "SELL", round(shares, 6), bar["o"],
                               round(val, 2), round(c, 2)))
                shares = 0.0
            pending = None
        if d in dec_set:
            tgt = targets[dec_set[d]]
            cur = "SPY" if shares > 0 else "CASH"
            if tgt != cur:
                pending = tgt
        v = equity_close(d)
        curve.append((d, v))
        if shares > 0:
            days_invested += 1
        if v <= FLOOR0 and di < len(days) - 1:
            halted = d
            nd = days[di + 1]
            if shares > 0:
                val = shares * book.bar(nd)["o"]
                c = val * 0.001 + 0.01
                cash += val - c
                total_costs += c
                trades.append((nd, "SELL-HALT", round(shares, 6),
                               book.bar(nd)["o"], round(val, 2), round(c, 2)))
                shares = 0.0
            return finish(label, cash, total_costs, trades, curve,
                          days_invested, len(days), halted)
    last = days[-1]
    if shares > 0:
        val = shares * book.by_date[last]["c"]
        c = val * 0.001 + 0.01
        cash += val - c
        total_costs += c
        trades.append((last, "SELL-END", round(shares, 6),
                       book.by_date[last]["c"], round(val, 2), round(c, 2)))
        shares = 0.0
    return finish(label, cash, total_costs, trades, curve,
                  days_invested, len(days), None)


def finish(label, cash, costs, trades, curve, days_inv, n_days, halted):
    peak, maxdd = -1.0, 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            maxdd = max(maxdd, (peak - v) / peak)
    worst = min((v for _, v in curve), default=None)
    return {"label": label, "final": round(cash, 2),
            "return_pct": round(cash / START_CASH * 100 - 100, 2),
            "costs": round(costs, 2), "orders": len(trades),
            "switches": sum(1 for t in trades if t[1] in ("BUY", "SELL")),
            "halted": halted,
            "max_drawdown_pct": round(maxdd * 100, 2),
            "worst_close": round(worst, 2) if worst is not None else None,
            "time_in_market_pct": round(100.0 * days_inv / n_days, 1) if n_days else 0.0,
            "days": n_days, "days_invested": days_inv,
            "trades": trades}


def spy_net(book, start, end):
    """Champion engine's buy-hold, verbatim semantics (CAPE test copy)."""
    days = [d for d in book.dates if start <= d <= end]
    first, last = days[0], days[-1]
    o = book.bar(first)["o"]
    sh = (START_CASH / 1.001) / o
    buy_cost = START_CASH - sh * o
    val = sh * book.by_date[last]["c"]
    sell_cost = val * 0.001 + 0.01
    return round(val - sell_cost, 2), round(buy_cost + sell_cost, 2)


def strategy_targets(book, sig, start, end):
    decs = []
    for d in decision_dates(book, start, end):
        dec = sig.decision(d)
        if dec is None:
            raise SystemExit(f"no Shiller row usable at {d}")
        decs.append(dec)
    return decs


def placebo_block(book, strat_targets, start, end, label):
    """Circular shifts of the strategy's realized target sequence
    (forced reading 6). Returns the 20-seed distribution summary."""
    n = len(strat_targets)
    finals, rows = [], []
    for seed in PLACEBO_SEEDS:
        rng = random.Random(seed)
        shift = rng.randrange(1, n)
        shifted = [strat_targets[(i + shift) % n] for i in range(n)]
        r = run_window(book, shifted, start, end, label=f"{label} P{seed}")
        finals.append(r["final"])
        rows.append({"seed": seed, "shift": shift, "final": r["final"],
                     "halted": r["halted"], "orders": r["orders"],
                     "costs": r["costs"]})
        print(f"  {label} PLACEBO seed {seed:2d} shift {shift:2d}: "
              f"final=${r['final']:,.2f} halted={r['halted']}", flush=True)
    srt = sorted(finals)
    med = srt[len(srt) // 2] if len(srt) % 2 else (srt[len(srt)//2 - 1] + srt[len(srt)//2]) / 2
    return {"median": round(med, 2), "best": round(srt[-1], 2),
            "worst": round(srt[0], 2),
            "mean": round(sum(finals) / len(finals), 2),
            "halted_count": sum(1 for r in rows if r["halted"]),
            "rows": rows}


# --------------------------------------------------------------------- main
def main():
    bars = load_spy_bars()
    book = Book(bars)
    rows = load_shiller()
    sig = FedSignal(rows)
    months = sorted(rows)
    print(f"SPY bars: {bars[0]['d']} -> {bars[-1]['d']} ({len(bars)})")
    print(f"Shiller months: {months[0]} -> {months[-1]} ({len(months)})")
    for m in ("2018-11", "2020-02", "2022-10", "2023-06", "2026-09"):
        if m in rows:
            v = rows[m]
            print(f"  Shiller[{m}]: P={v['p']} E={v['e']} GS10={v['gs10']} "
                  f"E/P={v['e']/v['p']*100:.2f}%")

    # ---- integrity gate: reproduce the published SPY buy-hold nets
    for name, (ws, we) in (("continuous", CONTINUOUS), ("validation", VALIDATION)):
        spy, _ = spy_net(book, ws, we)
        pub = PUBLISHED_SPY[name]
        ok = abs(spy - pub) < 0.005
        print(f"INTEGRITY {name}: SPY net=${spy:,.2f} published=${pub:,.2f} "
              f"match={ok}", flush=True)
        if not ok:
            raise SystemExit("SPY reconciliation FAILED — F-3 numbers untrusted")

    out = {"strategy": "FOLKLORE F-3 — FED MODEL (trailing-earnings form): "
                       "monthly, SPY vs cash; hold SPY iff Shiller trailing "
                       "E/P > Shiller GS10, evaluated last trading day of "
                       "month on the M-1 Shiller row, switches at next open",
           "source": "Shiller ie_data (Yale, free): trailing as-reported "
                     "earnings, index price, Long Interest Rate (GS10); "
                     "SPY = Yahoo adjusted, program shared cache",
           "pot": START_CASH, "floor": FLOOR0, "windows": {}}

    for name, (ws, we) in (("continuous", CONTINUOUS), ("validation", VALIDATION)):
        decs = strategy_targets(book, sig, ws, we)
        targets = [d["target"] for d in decs]
        r = run_window(book, targets, ws, we, label=name.upper())
        spy, spy_costs = spy_net(book, ws, we)
        r["spy_net"] = spy
        r["spy_costs"] = spy_costs
        r["vs_spy"] = round(r["final"] - spy, 2)
        r["decisions"] = decs
        r["months_invested"] = sum(1 for t in targets if t == "SPY")
        r["months_total"] = len(targets)
        print(f"{name.upper()}: FED ${r['final']:,.2f} ({r['return_pct']:+.2f}%) "
              f"vs SPY ${spy:,.2f} | invested {r['months_invested']}/"
              f"{r['months_total']} months, time-in {r['time_in_market_pct']}% "
              f"switches {r['switches']} maxDD {r['max_drawdown_pct']}% "
              f"costs ${r['costs']} halted={r['halted']}", flush=True)
        r["placebo"] = placebo_block(book, targets, ws, we, name.upper())
        pl = r["placebo"]
        below = sum(1 for row in pl["rows"] if row["final"] < r["final"])
        r["placebo_seeds_beaten"] = below
        print(f"{name.upper()} PLACEBO: median=${pl['median']:,.2f} "
              f"best=${pl['best']:,.2f} worst=${pl['worst']:,.2f} "
              f"halted={pl['halted_count']}/20 | RANKED ${r['final']:,.2f} "
              f"beat {below}/20", flush=True)
        out["windows"][name] = r

    folds = []
    for y in range(2020, 2027):
        fs = f"{y}-01-01"
        fe = "2026-11-20" if y == 2026 else f"{y}-12-31"
        decs = strategy_targets(book, sig, fs, fe)
        targets = [d["target"] for d in decs]
        fr = run_window(book, targets, fs, fe, label=f"FOLD {y}")
        fspy, _ = spy_net(book, fs, fe)
        row = {"year": y, "final": fr["final"], "return_pct": fr["return_pct"],
               "spy_net": fspy, "beat_spy": fr["final"] > fspy,
               "time_in_market_pct": fr["time_in_market_pct"],
               "switches": fr["switches"], "halted": fr["halted"],
               "max_drawdown_pct": fr["max_drawdown_pct"],
               "costs": fr["costs"]}
        folds.append(row)
        print(f"FOLD {y}: FED ${fr['final']:,.2f} ({fr['return_pct']:+.2f}%) vs "
              f"SPY ${fspy:,.2f} beat={row['beat_spy']} "
              f"in-market {fr['time_in_market_pct']}% halted={fr['halted']}",
              flush=True)
    out["folds"] = folds
    wins = sum(1 for f in folds if f["beat_spy"])
    out["fold_record"] = f"{wins} wins, {len(folds) - wins} losses vs SPY"
    comp = 100.0
    for f in folds:
        comp *= 1 + f["return_pct"] / 100.0
    out["fold_compounded_final"] = round(comp, 2)

    with open(os.path.join(HERE, "fedmodel-results.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print("DONE")


if __name__ == "__main__":
    main()
