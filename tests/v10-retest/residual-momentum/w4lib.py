"""W4 shared harness for THE GREAT RETEST (v10). Simulation only.
Shared inputs are read-only; all outputs go to backtests/v10-retest/<slug>/.
"""
import json, os, sys, time, urllib.request
from datetime import date

BT = os.path.expanduser("~/workspace/stock-app/backtests")
LR = os.path.join(BT, "long-run-2010")
sys.path.insert(0, LR)
import lr_common as C  # noqa: E402

champ = C.champ
END = "2026-11-20"
DEC = ("2016-11-21", "2026-11-20")
CONT = ("2019-01-02", "2026-11-20")
VAL = ("2023-01-03", "2026-11-20")
POND2010 = ["XOM", "MSFT", "WMT", "AAPL", "JNJ", "PG", "IBM", "T", "JPM",
            "GE", "CVX", "GOOG", "PFE", "CSCO", "BAC", "WFC", "ORCL",
            "HPQ", "INTC", "PEP", "VZ", "PM", "GS", "ABT", "SLB", "QCOM",
            "COP", "C", "MCD", "OXY"]
CACHE = "/tmp/w4cache"
os.makedirs(CACHE, exist_ok=True)


def load_mod(name, path):
    return C.load_module(name, path)


def payload_for(t):
    """Yahoo full-range payload: long-hold cache (read-only) first, else
    lr data dir, else a fresh download into /tmp/w4cache."""
    lh = os.path.join(BT, "v7", "long-hold", "data", f"pxfull_{t}.json")
    if os.path.exists(lh) and os.path.getsize(lh) > 100:
        return C.yahoo_payload(t)
    p2 = os.path.join(CACHE, f"pxfull_{t}.json")
    if os.path.exists(p2) and os.path.getsize(p2) > 100:
        with open(p2) as f:
            return json.load(f)
    import calendar
    t1 = calendar.timegm(time.strptime("2008-01-01", "%Y-%m-%d"))
    t2 = calendar.timegm(time.strptime("2026-11-22", "%Y-%m-%d"))
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{t}"
           f"?period1={t1}&period2={t2}&interval=1d&events=div,split")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=90) as r:
        blob = r.read()
    with open(p2, "wb") as f:
        f.write(blob)
    return json.loads(blob)


def book_for(tickers, include_spy=True):
    bars = {}
    for t in tickers:
        bars[t] = C.bars_adj(payload_for(t))
    if include_spy:
        bars["SPY"] = C.bars_adj(payload_for("SPY"))
    return C.FastPriceBook(bars)


def spy_final(pb, start, end):
    v, _ = champ.spy_net(pb, start, end, 100.0)
    return round(v, 2)


def spy_diag(pb, start, end):
    """SPY buy-hold final + max drawdown over the window (from bars)."""
    bl = [b for b in pb.bars["SPY"] if start <= b["d"] <= end]
    if not bl:
        return {"final": None, "max_dd_pct": None}
    curve = [(bl[0]["d"], 100.0)]
    base = bl[0]["c"]
    # spy_net buys at first open; approximate curve with closes scaled so
    # the final matches spy_net exactly.
    f = spy_final(pb, start, end)
    raw_final = 100.0 * bl[-1]["c"] / base
    k = f / raw_final if raw_final else 1.0
    curve = [(b["d"], 100.0 * b["c"] / base * k) for b in bl]
    d = C.curve_diagnostics(curve)
    return {"final": f, "max_dd_pct": d["max_drawdown_pct"]}


def run_stats(curve, final, start, end):
    cg, yrs = C.cagr(final, 100.0, start, end)
    d = C.curve_diagnostics(curve) if curve else {
        "worst_close": None, "worst_close_date": None,
        "max_drawdown_pct": None, "max_drawdown_date": None}
    return {"final": round(final, 2), "cagr_pct": cg,
            "max_dd_pct": d["max_drawdown_pct"],
            "worst_close": d["worst_close"],
            "worst_close_date": d["worst_close_date"]}


def norm_v9(out, start, end):
    """Normalize an episode-style result dict {final,costs,trades|orders,
    curve, restarts/second_halt or halts} into the SPEC run shape."""
    halts = 0
    restart = False
    second = False
    if out.get("halts") is not None:
        halts = len(out["halts"])
        restart = bool(out.get("restart"))
        if restart and out["restart"]:
            second = bool(out["restart"].get("second_halt"))
    else:
        if out.get("ep1_halted"):
            halts += 1
        if out.get("restart"):
            restart = True
        if out.get("ep2_halted"):
            halts += 1
            second = True
        if out.get("restarts"):
            restart = True
            halts = max(halts, len(out["restarts"]) +
                        (1 if out.get("second_halt") else 0))
            if out.get("second_halt"):
                second = True
    orders = out.get("orders")
    if orders is None:
        orders = len(out.get("trades", []))
    st = run_stats(out.get("curve") or [], out["final"], start, end)
    return {"start": start, "end": end, "final": st["final"],
            "cagr_pct": st["cagr_pct"], "max_dd_pct": st["max_dd_pct"],
            "worst_close": st["worst_close"],
            "halts": halts, "restart": restart, "second_halt": second,
            "costs": round(out.get("costs", 0.0), 2), "orders": orders,
            "placebo_beaten": None}


CADENCES = ["daily", "weekly", "biweekly", "monthly", "quarterly",
            "semiannual", "annual"]


def cadence_dates(pb, start, end, cad):
    """Uniform operational cadence (SPEC: THE CADENCE SWEEP): selection
    dates are the first trading day of each cadence period inside
    [start, end]. Biweekly periods are anchored on absolute week parity
    (Monday ordinal // 7) so sub-windows (v9 episodes) stay consistent."""
    from datetime import date as _d
    days = [d for d in pb.dates if start <= d <= end]
    if cad == "daily":
        return days
    out, seen = [], set()
    for d in days:
        dt = _d.fromisoformat(d)
        if cad == "weekly":
            key = ("W", dt.isocalendar()[0], dt.isocalendar()[1])
        elif cad == "biweekly":
            monday = dt.toordinal() - dt.weekday()
            if (monday // 7) % 2 != 0:
                continue
            key = ("B", monday)
        elif cad == "monthly":
            key = ("M", d[:4], d[5:7])
        elif cad == "quarterly":
            if d[5:7] not in ("01", "04", "07", "10"):
                continue
            key = ("Q", d[:4], d[5:7])
        elif cad == "semiannual":
            if d[5:7] not in ("01", "07"):
                continue
            key = ("S", d[:4], d[5:7])
        elif cad == "annual":
            key = ("A", d[:4])
        else:
            raise ValueError(cad)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def cadence_fn(cad):
    def f(pb, start, end):
        return cadence_dates(pb, start, end, cad)
    return f


def cell_norm(out, start, end):
    """Normalize any episode-style result into a sweep cell dict."""
    c = norm_v9(out, start, end)
    return {"final": c["final"], "cagr_pct": c["cagr_pct"],
            "max_dd_pct": c["max_dd_pct"], "halts": c["halts"],
            "restart": c["restart"], "second_halt": c["second_halt"],
            "costs": c["costs"], "orders": c["orders"],
            "placebo_beaten": None, "placebo_note": None}


def write_outputs(slug, payload, md_text):
    d = os.path.join(BT, "v10-retest", slug)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "results.json"), "w") as f:
        json.dump(payload, f, indent=1, default=str)
    with open(os.path.join(d, "RESULTS.md"), "w") as f:
        f.write(md_text)
    print(f"WROTE {slug}", flush=True)


def md_table(runs, spy):
    lines = ["| Window | Start | Final | SPY | CAGR % | Max DD % | Halts | Costs | Orders | Placebo |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for w in ("LONG", "DECADE", "CONT", "VAL"):
        r = runs.get(w)
        if r is None:
            lines.append(f"| {w} | — | not run (see notes) | — | — | — | — | — | — | — |")
            continue
        pb = r.get("placebo_beaten")
        lines.append(
            f"| {w} | {r['start']} | ${r['final']:,.2f} | ${spy[w]:,.2f} | "
            f"{r['cagr_pct']} | {r['max_dd_pct']} | {r['halts']} | "
            f"${r['costs']:,.2f} | {r['orders']} | "
            f"{(str(pb) + '/20') if pb is not None else '—'} |")
    return "\n".join(lines)
