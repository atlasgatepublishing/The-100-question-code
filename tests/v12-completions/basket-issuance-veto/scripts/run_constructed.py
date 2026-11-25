"""basket-issuance-veto v12 CONSTRUCTED run. See CONSTRUCTION-SPEC.md (frozen)
+ Second-Chance grid cells (PROGRAM.md amendment 2026-11-22 ~09:32).
Long side of Pontiff-Woodgate published sort: PIT S&P500 universe,
NSI = ln(split-adj shares now / 12m ago) from EDGAR as-first-filed facts.
Cells per road: primary monthly/quintile/native; annual/quintile/native
(published annual form); monthly/decile/native; monthly/quintile/v9-floor.
Value-weighted, 0.10%/side, 20-seed placebos per cell. Vanished prices -> zero.
Crypto: NOT-APPLICABLE (filings-based cross-sectional signal; no EDGAR
share issuance exists for coins)."""
import csv, json, math, pathlib, random, datetime, bisect, statistics
from fractions import Fraction

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
DATA = ROOT / "data"
LIFE = pathlib.Path.home() / "workspace/stock-app/backtests/v12-completions/gap-a10-div-capture/data/sp500_ticker_start_end.csv"
SPY_SRC = pathlib.Path.home() / "workspace/stock-app/backtests/v10-retest/leveraged-trend/data/SPY.json"
COST = 0.001

spy_raw = json.loads(SPY_SRC.read_text())
r = spy_raw["chart"]["result"][0]
spy = []
_adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose")
for i, t in enumerate(r["timestamp"]):
    c = _adj[i] if _adj else None
    if c: spy.append((datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime("%Y-%m-%d"), c))
spy_dates = [d for d, _ in spy]
months = {}
for d, _ in spy: months.setdefault(d[:7], []).append(d)
MEND = sorted(months[m][-1] for m in sorted(months))
MFIRST = sorted(months[m][0] for m in sorted(months))

life = {}
for row in csv.DictReader(open(LIFE)):
    life.setdefault(row["ticker"], []).append((row["start_date"], row["end_date"] or "9999-12-31"))
def member(t, date):
    return any(s <= date <= e for s, e in life.get(t, ()))

cik_map = json.loads((DATA / "cik_map.json").read_text())

def load_px(t):
    p = DATA / f"px_{t}.json"
    if not p.exists(): return None
    try: d = json.loads(p.read_text())
    except Exception: return None
    res = d.get("chart", {}).get("result")
    if not res: return None
    r0 = res[0]; ts = r0.get("timestamp") or []
    q = r0["indicators"]["quote"][0]
    adj = (r0["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    rows = {}
    for i, tstamp in enumerate(ts):
        dt = datetime.datetime.fromtimestamp(tstamp, datetime.timezone.utc).strftime("%Y-%m-%d")
        cl, ac = q["close"][i], (adj[i] if adj else None)
        if cl and ac: rows[dt] = (cl, ac)
    splits = []
    for ts_, s in sorted(((r0.get("events") or {}).get("splits") or {}).items()):
        fr = Fraction(float(s["numerator"]) / float(s["denominator"])).limit_denominator(100000)
        if fr.numerator <= 20 and fr.denominator <= 20:
            dt = datetime.datetime.fromtimestamp(int(ts_), datetime.timezone.utc).strftime("%Y-%m-%d")
            splits.append((dt, float(fr)))
    return {"px": rows, "dates": sorted(rows), "splits": splits}

PX = {}
for t in sorted(life):
    px = load_px(t)
    if px: PX[t] = px

def px_on_or_before(t, date, kind=1):
    px = PX.get(t)
    if not px: return None
    i = bisect.bisect_right(px["dates"], date) - 1
    if i < 0: return None
    return px["px"][px["dates"][i]][kind]

CONCEPTS = [("dei", "EntityCommonStockSharesOutstanding"),
            ("us-gaap", "CommonStockSharesIssued"),
            ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic")]
def load_concept(cik, tax, concept):
    p = DATA / (f"concept_{cik:010d}_dei.json" if tax == "dei" else f"concept_{cik:010d}_{concept}.json")
    if not p.exists(): return None
    try: return json.loads(p.read_text())
    except Exception: return None

def issuance_series(t):
    cik = cik_map.get(t)
    if not cik: return None
    splits = PX.get(t, {}).get("splits", [])
    for tax, concept in CONCEPTS:
        d = load_concept(cik, tax, concept)
        if d is None: continue
        entries = None
        for u, v in (d.get("units") or {}).items():
            if "shares" in u: entries = v; break
        if not entries: continue
        best = {}
        for e in entries:
            if e.get("form") not in ("10-K", "10-Q", "10-K/A", "10-Q/A", "20-F", "40-F"): continue
            end, filed, val = e.get("end"), e.get("filed"), e.get("val")
            if not end or not filed or not val or val <= 0: continue
            if end not in best or filed < best[end][0]:
                best[end] = (filed, val)
        if len(best) < 8: continue
        obs = []
        for end, (filed, val) in best.items():
            # Split-adjustment pivot = the obs's own first-filing date, NOT the
            # period end: dei cover shares are actuals as of the cover/filing
            # date. GOOGL (split 2022-07-18, Q2 period end 2022-06-30, filed
            # 2022-07-27 with post-split cover shares) and NFLX (split
            # 2015-07-15, period end 2015-06-30) double-count under an
            # end-pivot — caught by the spec's verification audit (NSI +2.97 /
            # +1.96 at the split) and corrected here before final results.
            adj = val
            for sd, ratio in splits:
                if sd > filed: adj *= ratio
            obs.append((end, filed, adj))
        obs.sort()
        return {"concept": f"{tax}:{concept}", "obs": obs}
    return None

ISS = {}
for t in cik_map:
    s = issuance_series(t)
    if s: ISS[t] = s

def nsi_at(t, sig_date):
    s = ISS.get(t)
    if not s: return None
    vis = [o for o in s["obs"] if o[1] <= sig_date]
    if len(vis) < 2: return None
    e1, _, sh1 = vis[-1]
    if e1 > sig_date: return None
    target = (datetime.date.fromisoformat(e1) - datetime.timedelta(days=365)).isoformat()
    cand = [o for o in vis[:-1] if abs((datetime.date.fromisoformat(o[0]) - datetime.date.fromisoformat(target)).days) <= 122]
    if not cand: return None
    e0, _, sh0 = min(cand, key=lambda o: abs((datetime.date.fromisoformat(o[0]) - datetime.date.fromisoformat(target)).days))
    if sh0 <= 0 or sh1 <= 0: return None
    return math.log(sh1 / sh0), sh1

# ---------- verification audit ----------
audit = {"split_checks": [], "real_issuance_checks": []}
SPLITTERS = {"AAPL": ["2014-06-09", "2020-08-31"], "NVDA": ["2021-07-20", "2024-06-10"],
             "TSLA": ["2020-08-31", "2022-08-25"], "AMZN": ["2022-06-03"],
             "GOOGL": ["2022-07-15"], "WMT": ["2024-02-26"], "NFLX": ["2015-07-15"]}
for t, sds in SPLITTERS.items():
    for sd in sds:
        sig = (datetime.date.fromisoformat(sd) + datetime.timedelta(days=45)).isoformat()
        v = nsi_at(t, sig)
        audit["split_checks"].append({"ticker": t, "split": sd, "nsi_after": None if v is None else round(v[0], 4)})
for t, sig, label in [("DIS", "2019-12-31", "Fox issuance year"), ("CVX", "2026-06-30", "Hess issuance year"),
                      ("AAPL", "2024-12-31", "buyback year")]:
    v = nsi_at(t, sig)
    audit["real_issuance_checks"].append({"ticker": t, "asof": sig, "label": label, "nsi": None if v is None else round(v[0], 4)})
print(json.dumps(audit, indent=1), flush=True)

# ---------- eligibility (cached across roads/cells) ----------
ELIG = {}
def eligible(sig_date):
    if sig_date in ELIG: return ELIG[sig_date]
    out = []
    for t in PX:
        if not member(t, sig_date): continue
        v = nsi_at(t, sig_date)
        if v is None: continue
        raw = px_on_or_before(t, sig_date, 0)
        if raw is None: continue
        out.append((t, v[0], v[1] * raw))
    ELIG[sig_date] = out
    return out

def sig_of(f):
    i = bisect.bisect_left(MEND, f) - 1
    return MEND[i] if i >= 0 else None

def period_stats(curve):
    rets = [curve[i + 1][1] / curve[i][1] - 1 for i in range(len(curve) - 1) if curve[i][1] > 0]
    if not rets: return {}
    pos = sum(1 for x in rets if x > 0)
    streak = run = 0
    for x in rets:
        run = run + 1 if x <= 0 else 0
        streak = max(streak, run)
    peak, last_high, longest = -1, 0, 0
    for i, (_, v) in enumerate(curve):
        if v >= peak: peak, last_high = v, i
        longest = max(longest, i - last_high)
    return {"periods": len(rets), "pct_positive": round(100 * pos / len(rets), 1),
            "median_pct": round(statistics.median(rets) * 100, 2),
            "mean_pct_secondary": round(statistics.mean(rets) * 100, 2),
            "best_pct": round(max(rets) * 100, 2), "worst_pct": round(min(rets) * 100, 2),
            "longest_losing_streak": streak, "longest_months_between_new_highs": longest}

def simulate(forms, eval_mends, pick_fn, floor=False):
    val = 100.0; hold = {}; curve = []; costs = 0.0; orders = 0; halted = None
    prev = eval_mends[0]
    form_set = set(forms)
    first_sig = sig_of(forms[0])
    curve.append((first_sig, 100.0))
    prev = first_sig
    for m in eval_mends:
        if m <= first_sig: continue
        new_hold = {}
        for t, dollars in hold.items():
            p0, p1 = px_on_or_before(t, prev, 1), px_on_or_before(t, m, 1)
            if p1 is None or PX[t]["dates"][-1] < m: continue
            new_hold[t] = dollars * (p1 / p0) if p0 else 0.0
        val = sum(new_hold.values()) + (val - sum(hold.values()))
        hold = new_hold
        if floor and halted is None and val <= 85.0:
            halted = m; hold = {}; val = val  # liquidate to cash, stays cash
        f_next = [f for f in forms if sig_of(f) == m]
        if f_next and halted is None:
            elig = eligible(m)
            sel = pick_fn(elig)
            tot_cap = sum(c for _, _, c in sel)
            target = {t: val * c / tot_cap for t, _, c in sel} if tot_cap > 0 else {}
            traded = sum(abs(target.get(t, 0.0) - hold.get(t, 0.0)) for t in set(target) | set(hold))
            c = COST * traded; costs += c; val -= c
            sc = (val / sum(target.values())) if target and sum(target.values()) > 0 else 0
            hold = {t: v * sc for t, v in target.items()}
            orders += len(set(target) | set(hold))
        curve.append((m, round(val, 4)))
        prev = m
    peak, mdd = -1, 0.0
    for _, v in curve:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1 if peak > 0 else 0)
    yrs = (datetime.date.fromisoformat(curve[-1][0]) - datetime.date.fromisoformat(curve[0][0])).days / 365.25
    return {"final": round(val, 2), "cagr_pct": round(((val / 100) ** (1 / yrs) - 1) * 100, 2) if val > 0 else -100.0,
            "max_dd_pct": round(mdd * 100, 1), "costs": round(costs, 2), "orders": orders,
            "halted": halted, "curve": curve, "period_stats_monthly": period_stats(curve)}

def run_road(start, end):
    forms_all = [f for f in MFIRST if start <= f <= end]
    start_i = None
    for i, f in enumerate(forms_all):
        s = sig_of(f)
        if s and len(eligible(s)) >= 250: start_i = i; break
    if start_i is None: return {"status": "NOT-RUNNABLE", "reason": "never >=250 eligible"}
    forms = forms_all[start_i:]
    eval_mends = [m for m in MEND if sig_of(forms[0]) <= m <= end]
    def pick_q(elig):
        srt = sorted(elig, key=lambda x: x[1]); return srt[:max(1, len(srt) // 5)]
    def pick_d(elig):
        srt = sorted(elig, key=lambda x: x[1]); return srt[:max(1, len(srt) // 10)]
    annual_forms = [f for f in forms if f[5:7] == "01"] or forms[:1]
    cells = {}
    cell_defs = [("monthly_quintile_native", forms, pick_q, False),
                 ("annual_quintile_native", annual_forms, pick_q, False),
                 ("monthly_decile_native", forms, pick_d, False),
                 ("monthly_quintile_v9floor", forms, pick_q, True)]
    for name, cforms, pick, fl in cell_defs:
        real = simulate(cforms, eval_mends, pick, fl)
        k = 5 if "decile" in name else 5
        placebos = []
        for seed in range(1, 21):
            rng = random.Random(seed * 7919 + len(name))
            def p_pick(elig, rng=rng, pick=pick):
                kk = max(1, len(elig) // (10 if pick == pick_d else 5))
                return rng.sample(elig, kk)
            placebos.append(simulate(cforms, eval_mends, p_pick, fl)["final"])
        beaten = sum(1 for p in placebos if real["final"] > p)
        real["placebo_finals"] = placebos
        real["placebo_beaten"] = f"{beaten}/20"
        cells[name] = real
    i = bisect.bisect_right(spy_dates, cells["monthly_quintile_native"]["curve"][0][0]) - 1
    j = bisect.bisect_right(spy_dates, end) - 1
    spy_final = round(100 * spy[j][1] / spy[i][1], 2)
    return {"start": cells["monthly_quintile_native"]["curve"][0][0], "end": end,
            "eligible_at_start": len(eligible(sig_of(forms[0]))),
            "spy_same_window": spy_final, "cells": cells}

ROADS = {"LONG": ("2010-01-01", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-01", "2026-11-20"), "VAL": ("2023-01-01", "2026-11-20")}
results = {"family": "basket-issuance-veto", "form": "CONSTRUCTED long side of Pontiff-Woodgate published sort + grid cells",
           "audit": audit, "coverage": {"px_tickers": len(PX), "issuance_tickers": len(ISS), "cik_mapped": len(cik_map)},
           "crypto": "NOT-APPLICABLE — filings-based cross-sectional signal; no EDGAR share issuance exists for coins",
           "roads": {}}
for name, (s, e) in ROADS.items():
    print(f"running {name}...", flush=True)
    results["roads"][name] = run_road(s, e)
    rd = results["roads"][name]
    if "cells" in rd:
        print(name, {c: (v["final"], v["placebo_beaten"]) for c, v in rd["cells"].items()}, "SPY", rd["spy_same_window"], flush=True)
    else:
        print(name, rd, flush=True)
tmp = ROOT / "results.json.tmp"
tmp.write_text(json.dumps(results, indent=1))
tmp.replace(ROOT / "results.json")
print("DONE", flush=True)
