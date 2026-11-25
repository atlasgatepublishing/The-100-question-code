#!/usr/bin/env python3
"""V13 best-rules runner — SPF recession probability.
Spec: ../BEST-RULES-SPEC.md (frozen before this run).
Signal: Philadelphia Fed SPF mean responses (data/ workbooks, never revised,
released mid-month of months 2/5/8/11; decisions at those months' month-end
close, executed next trading day close via shared chassis engine).
Forms run per road: my-rules graduated dial (no floor, quarterly decisions,
no interim rebalance), published binary form (faithful: quarterly signal,
monthly rebalance), static 60/40 SPY/IEF, SPY buy-hold, 20 timing-shuffle
placebos of the my-rules target sequence."""
import json, os, random, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import engine
from engine import Panel, load_etf_json, simulate, period_stats, ROADS, SPY_REF, CHAMP

FOLDER = os.path.dirname(HERE)
DATA = os.path.join(FOLDER, "data")

# ---------------- SPF data ----------------
def load_spf():
    import openpyxl
    def num(v):
        return None if v in ("#N/A", None, "") else float(v)
    out = {}
    wb = openpyxl.load_workbook(os.path.join(DATA, "Mean_RECESS_Level.xlsx"), data_only=True)
    for r in list(wb.active.iter_rows(values_only=True))[1:]:
        if r[0] is None: continue
        out.setdefault((int(r[0]), int(r[1])), {})["RECESS"] = [num(v) for v in r[2:7]]
    wb = openpyxl.load_workbook(os.path.join(DATA, "Mean_TBOND_Level.xlsx"), data_only=True)
    for r in list(wb.active.iter_rows(values_only=True))[1:]:
        if r[0] is None: continue
        out.setdefault((int(r[0]), int(r[1])), {})["TBOND"] = [num(v) for v in r[2:8]]
    return out

SPF = load_spf()
SURVEYS = sorted(SPF.keys())  # chronological (year, quarter)

def survey_signal(key):
    """Return (delta_recess_pp, defensive_sym) for survey `key` vs prior survey,
    using the published matched-target-quarter comparisons. None if inputs missing."""
    j = SURVEYS.index(key)
    if j == 0: return None
    prev = SURVEYS[j - 1]
    cur_r, prev_r = SPF[key].get("RECESS"), SPF[prev].get("RECESS")
    cur_t, prev_t = SPF[key].get("TBOND"), SPF[prev].get("TBOND")
    if not cur_r or not prev_r or any(v is None for v in cur_r[1:4] + prev_r[2:5]):
        return None
    d_recess = sum(cur_r[1:4]) / 3 - sum(prev_r[2:5]) / 3
    defensive = "IEF"  # default if TBOND unavailable (not the case 2010+)
    if cur_t and prev_t and all(v is not None for v in cur_t[2:5] + prev_t[3:6]):
        d_tbond = sum(cur_t[2:5]) / 3 - sum(prev_t[3:6]) / 3
        defensive = "IEF" if d_tbond <= 0 else "CASH"
    return d_recess, defensive

def target_mine(key):
    s = survey_signal(key)
    if s is None: return {}
    d, dfn = s
    w = 0.60 if d <= 0 else (0.30 if d <= 5.0 else 0.0)
    t = {}
    if w > 0: t["SPY"] = w
    if dfn == "IEF": t["IEF"] = round(1.0 - w, 4)
    return t

def target_published(key):
    s = survey_signal(key)
    if s is None: return {}
    d, dfn = s
    t = {}
    if d <= 0:
        t["SPY"] = 0.60
        if dfn == "IEF": t["IEF"] = 0.40
    else:
        if dfn == "IEF": t["IEF"] = 1.0
    return t

# ---------------- panel & decision dates ----------------
def load_adj(sym):
    """Total-return (adjclose) series from the program data_etf cache — matches
    the program's SPY/champion reference basis."""
    import datetime as dt
    d = json.load(open(os.path.expanduser(f"~/workspace/stock-app/backtests/v3/data_etf/{sym}.json")))
    res = d["chart"]["result"][0]
    ts = res["timestamp"]; adj = res["indicators"]["adjclose"][0]["adjclose"]
    cl = res["indicators"]["quote"][0]["close"]
    ds, cs = [], []
    for t, a, c in zip(ts, adj, cl):
        v = a if a is not None else c
        if v is None: continue
        ds.append(dt.datetime.utcfromtimestamp(t).date()); cs.append(float(v))
    return ds, cs

def build_panel():
    p = Panel(load_adj("SPY"))
    ds, cs = load_adj("SPY"); p.series["SPY"] = cs[:]
    p.add("IEF", load_adj("IEF"))
    return p

def month_end_indices(p, months=None):
    """Last trading-day index of each month (optionally only given months)."""
    out = []
    for i, d in enumerate(p.dates):
        if months and d.month not in months: continue
        nxt = p.dates[i + 1] if i + 1 < len(p.dates) else None
        if nxt is None or (nxt.year, nxt.month) != (d.year, d.month):
            out.append(i)
    return out

def survey_key_for(d):
    """Survey released in month d.month of year d.year: Feb->Q1, May->Q2, Aug->Q3, Nov->Q4."""
    return (d.year, {2: 1, 5: 2, 8: 3, 11: 4}[d.month])

def run_form(p, idx, dec_idx, target_by_idx):
    def fn(i):
        return target_by_idx.get(i, {})
    return simulate(p, idx, set(dec_idx), fn, rulebook="native")

def main():
    p = build_panel()
    q_dec_all = month_end_indices(p, months={2, 5, 8, 11})
    m_dec_all = month_end_indices(p)
    out = {"family": "catalog-taa-spf-recession-probability", "roads": {},
           "decision_log": []}
    # full decision log (for false-alarm exhibit)
    for i in q_dec_all:
        d = p.dates[i]; key = survey_key_for(d)
        s = survey_signal(key)
        if s is None: continue
        out["decision_log"].append({"date": str(d), "survey": f"{key[0]}Q{key[1]}",
            "delta_recess_pp": round(s[0], 2), "defensive": s[1],
            "my_spy_weight": target_mine(key).get("SPY", 0.0),
            "published_spy_weight": target_published(key).get("SPY", 0.0)})
    ridx = engine.road_indices(p, ROADS)
    for rname, idx in ridx.items():
        days = set(idx)
        q_dec = [i for i in q_dec_all if i in days]
        m_dec = [i for i in m_dec_all if i in days]
        mine_t = {i: target_mine(survey_key_for(p.dates[i])) for i in q_dec}
        # published: signal updates at quarterly dates, target persists; monthly rebalance dates
        pub_t = {}
        cur = {}
        qset = set(q_dec)
        for i in m_dec:
            if i in qset: cur = target_published(survey_key_for(p.dates[i]))
            pub_t[i] = dict(cur)
        static_t = {i: {"SPY": 0.6, "IEF": 0.4} for i in q_dec}
        spy_t = {i: {"SPY": 1.0} for i in q_dec}
        res = {}
        r_mine = run_form(p, idx, q_dec, mine_t)
        res["mine"] = r_mine
        res["published"] = run_form(p, idx, m_dec, pub_t)
        res["static6040"] = run_form(p, idx, q_dec, static_t)
        res["spy_bh"] = run_form(p, idx, q_dec, spy_t)
        # 20 timing-shuffle placebos of my target sequence
        seq = [mine_t[i] for i in q_dec]
        twins = []
        for seed in range(1, 21):
            rng = random.Random(seed)
            perm = seq[:]; rng.shuffle(perm)
            pt = {i: perm[k] for k, i in enumerate(q_dec)}
            twins.append(run_form(p, idx, q_dec, pt)["final"])
        road = {}
        for form in ("mine", "published", "static6040", "spy_bh"):
            r = res[form]
            road[form] = {k: r[k] for k in ("final", "max_dd_pct", "costs", "orders", "halts")}
        road["mine"]["placebo_finals"] = twins
        road["mine"]["placebos_beaten"] = sum(1 for t in twins if r_mine["final"] > t)
        road["mine"]["placebo_median"] = sorted(twins)[10]
        out["roads"][rname] = road
        out.setdefault("curves", {})[rname] = {
            "mine": r_mine["curve"], "published": res["published"]["curve"],
            "static6040": res["static6040"]["curve"], "spy_bh": res["spy_bh"]["curve"]}
        out.setdefault("period_stats", {})[rname] = {
            f: period_stats(res[f]["curve"], p.dates, "quarterly")
            for f in ("mine", "published", "static6040", "spy_bh")}
        print(rname, {f: road[f]["final"] for f in road if isinstance(road[f], dict)},
              "placebos beaten", road["mine"]["placebos_beaten"], "/20")
    out["spy_ref_program"] = SPY_REF; out["champ_vm"] = CHAMP
    with open(os.path.join(FOLDER, "results.json"), "w") as fh:
        json.dump(out, fh, indent=1)
    print("wrote results.json")

if __name__ == "__main__":
    main()
