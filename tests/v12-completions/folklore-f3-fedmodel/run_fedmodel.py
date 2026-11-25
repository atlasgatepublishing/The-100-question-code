"""Fed Model (Yardeni) — v12 CONSTRUCTED run. See CONSTRUCTION-SPEC.md (frozen).
E leg: FactSet consensus forward EPS from dated Earnings Insight PDFs
(eps-estimates-collector CSV, PIT: each report used only from its Report_Date).
FEY = fwdEPS / (SPY adj close x10) vs FRED DGS10 at month-end.
Monthly: FEY >= TBY -> SPY next month, else cash (0%). Cost 0.10%/side.
Placebos: 20 circular shifts of the signal series per window."""
import csv, json, math, pathlib, random, datetime, re
HERE = pathlib.Path(__file__).parent
SRC = pathlib.Path.home()/"workspace/stock-app/backtests/v10-retest/leveraged-trend/data"

def load_spy():
    d = json.loads((SRC/"SPY.json").read_text())
    r = d["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose")
    rows = []
    for i, t in enumerate(ts):
        c = (adj[i] if adj else q["close"][i])
        if c is None: continue
        rows.append((datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"), c))
    return rows
spy = load_spy()
spy_d = dict(spy)

# DGS10
dgs = {}
for row in csv.DictReader(open(HERE/"data/dgs10.csv")):
    try: dgs[row["observation_date"]] = float(row["DGS10"])
    except ValueError: pass
dgs_dates = sorted(dgs)

def dgs_on_or_before(date):
    import bisect
    i = bisect.bisect_right(dgs_dates, date) - 1
    return dgs[dgs_dates[i]] if i >= 0 else None

# FactSet forward EPS per report
def qkey(label):  # "Q1'14" -> (2014,1)
    m = re.match(r"Q(\d)'(\d\d)", label); return (2000+int(m.group(2)), int(m.group(1)))
reports = []  # (date, fwd_eps)
with open(HERE/"data/extracted_estimates.csv") as f:
    rd = csv.DictReader(f)
    cols = [c for c in rd.fieldnames if c != "Report_Date"]
    qmap = {c: qkey(c) for c in cols}
    for row in rd:
        d = row["Report_Date"]
        y, mo = int(d[:4]), int(d[5:7]); q0 = (mo-1)//3 + 1
        need = []
        yy, qq = y, q0
        for _ in range(4):
            need.append((yy, qq)); qq += 1
            if qq == 5: qq = 1; yy += 1
        vals = []
        ok = True
        for nq in need:
            lab = [c for c in cols if qmap[c] == nq]
            v = row[lab[0]].replace("*", "").strip() if lab else ""
            if not v: ok = False; break
            vals.append(float(v))
        if ok: reports.append((d, sum(vals)))
reports.sort()
rep_dates = [d for d, _ in reports]
import bisect
def fwd_eps_on_or_before(date):
    i = bisect.bisect_right(rep_dates, date) - 1
    return reports[i] if i >= 0 else (None, None)

# Month-end trading days
months = {}
for d, c in spy: months.setdefault(d[:7], []).append(d)
mend = sorted(months[m][-1] for m in sorted(months))

# Monthly signal + SPY month return series
sig_rows = []  # (month_end_date, fey, tby, invested_next, spy_ret_next)
for i in range(len(mend)-1):
    d0, d1 = mend[i], mend[i+1]
    rd_, feps = fwd_eps_on_or_before(d0)
    if feps is None: continue
    price = spy_d[d0]*10.0
    fey = feps/price*100.0
    tby = dgs_on_or_before(d0)
    if tby is None: continue
    ret = spy_d[d1]/spy_d[d0] - 1
    sig_rows.append({"signal_date": d0, "report_date": rd_, "fwd_eps": round(feps,2),
                     "fey_pct": round(fey,3), "tby_pct": tby,
                     "invested": fey >= tby, "next_month_ret": ret, "next_month_end": d1})

# OCR audit: month-over-month jumps in forward EPS at used month-ends
jumps = []
prev = None
for r in sig_rows:
    if prev is not None and abs(r["fwd_eps"]/prev - 1) > 0.08:
        jumps.append([r["signal_date"], prev, r["fwd_eps"]])
    prev = r["fwd_eps"]

COST = 0.0010
def run(rows, signals):
    eq = 100.0; pos = False; curve = []; switches = 0; costs = 0.0
    peak = 100.0; maxdd = 0.0
    for r, inv in zip(rows, signals):
        if inv != pos:
            ch = eq*COST; eq -= ch; costs += ch; switches += 1; pos = inv
        if pos: eq *= (1 + r["next_month_ret"])
        peak = max(peak, eq); maxdd = min(maxdd, eq/peak - 1)
        curve.append([r["next_month_end"], round(eq, 4)])
    return {"final": round(eq, 2), "max_dd_pct": round(maxdd*100, 2),
            "switches": switches, "costs": round(costs, 2), "curve": curve}

def spy_bh(rows):
    if not rows: return None
    p0 = spy_d[rows[0]["signal_date"]]; p1 = spy_d[rows[-1]["next_month_end"]]
    return round(100*p1/p0, 2)

windows = {"DECADE*": ("2017-01-01", "2026-07-10"), "CONT": ("2019-01-01", "2026-07-10"),
           "VAL": ("2023-01-01", "2026-07-10")}
out = {"strategy": "Fed Model CONSTRUCTED (FactSet consensus proxy, monthly binary FEY>=TBY -> SPY else cash 0%)",
       "native_source_paywalled": "I/B/E/S point-in-time vintages; LONG 2010-2016 not runnable free",
       "cost_per_side": COST, "ocr_audit_fwd_eps_jumps_over_8pct": jumps,
       "n_reports_parsed": len(reports), "windows": {}}
for name, (s, e) in windows.items():
    rows = [r for r in sig_rows if s <= r["signal_date"] <= e]
    sig = [r["invested"] for r in rows]
    res = run(rows, sig); res["spy_buyhold_same_window"] = spy_bh(rows)
    res["months"] = len(rows); res["months_invested"] = sum(sig)
    rng = random.Random(1222)
    plac = []
    n = len(sig)
    for seed in range(20):
        off = rng.randrange(1, n)
        shifted = sig[off:] + sig[:off]
        plac.append(run(rows, shifted)["final"])
    plac.sort()
    res["placebo_shifted_signal"] = {"finals_sorted": plac,
        "median": plac[10], "real_beats_of_20": sum(1 for p in plac if res["final"] > p)}
    # per-year folds (confirmation material)
    folds = {}
    for y in sorted(set(r["signal_date"][:4] for r in rows)):
        yr = [r for r in rows if r["signal_date"][:4] == y]
        folds[y] = run(yr, [r["invested"] for r in yr])["final"]
    res["year_folds_final_per_100"] = folds
    res["signal_log"] = rows
    out["windows"][name] = res
    print(name, "final", res["final"], "SPYbh", res["spy_buyhold_same_window"],
          "maxDD", res["max_dd_pct"], "invested", res["months_invested"], "/", res["months"],
          "beats placebos", res["placebo_shifted_signal"]["real_beats_of_20"], "/20")
(HERE/"results.json").write_text(json.dumps(out, indent=1))
print("reports parsed:", len(reports), "signal months:", len(sig_rows), "audit jumps:", len(jumps))
