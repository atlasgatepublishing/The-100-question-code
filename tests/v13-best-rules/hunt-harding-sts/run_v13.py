#!/usr/bin/env python3
"""V13 Best Rules — Harding STS, calendar layer alone.
Frozen spec: BEST-RULES-SPEC.md. Invested on return days in
(Oct 16, Apr 20] (entry at close Oct 16, exit at close Apr 20),
cash otherwise, on DIA, program costs, NO floor, NO MACD.
Placebos: 20 seeds, same window phase-shifted by a random non-zero
whole-month offset, all four roads. Confirmation machinery (yearly
folds vs published MACD-gated STS + half-windows vs DIA buy-hold)
is included and runs only if a road beats the V+M champion.
Published STS form is re-implemented here exactly as in v12
(run_harding.py) for the folds comparison. Simulation only."""
import json, os, sys, random, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chassis import load_bars, simulate, buy_hold, period_stats

HERE = os.path.dirname(os.path.abspath(__file__))
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-harding-sts")
dia = load_bars(os.path.join(V12, "data", "DIA.json"))
dji = load_bars(os.path.join(V12, "data", "DJI.json"))

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {"LONG": 278.38, "DECADE": 138.82, "CONT": 129.53, "VAL": 100.54}

def in_window(md, start_md, end_md):
    """md, start_md, end_md are 'MM-DD'. Window wraps year-end when start > end.
    Invested return days: start_md < md <= end_md (wrapping)."""
    if start_md <= end_md:
        return start_md < md <= end_md
    return md > start_md or md <= end_md

def shift_md(md, months):
    m, d = int(md[:2]), md[3:]
    return f"{(m - 1 + months) % 12 + 1:02d}-{d}"

def build_calendar_state(start_md="10-16", end_md="04-20"):
    st = []
    for i, b in enumerate(dia):
        nxt = dia[i + 1]["d"] if i + 1 < len(dia) else b["d"]
        st.append(1 if in_window(nxt[5:], start_md, end_md) else 0)
    return st

# ---- published MACD-gated STS state (exact v12 re-implementation) ----
def ema(xs, n):
    out = [None] * len(xs); k = 2 / (n + 1); prev = None
    for i, x in enumerate(xs):
        prev = x if prev is None else x * k + prev * (1 - k)
        if i >= n - 1: out[i] = prev
    return out

def build_published_state():
    closes = [b["c"] for b in dji]
    e12 = ema(closes, 12); e26 = ema(closes, 26)
    macd = [None if (a is None or b is None) else a - b for a, b in zip(e12, e26)]
    sig = ema([m if m is not None else 0.0 for m in macd], 9)
    bull = [None] * len(dji); state = None
    for i in range(1, len(dji)):
        if macd[i] is None or sig[i] is None: continue
        if state is None:
            state = (macd[i] > sig[i]) or (macd[i] > 0)
        else:
            cu = (macd[i-1] <= sig[i-1] and macd[i] > sig[i]) or (macd[i-1] <= 0 and macd[i] > 0)
            cd = (macd[i-1] >= sig[i-1] and macd[i] < sig[i]) or (macd[i-1] >= 0 and macd[i] < 0)
            if cu and not cd: state = True
            elif cd and not cu: state = False
        bull[i] = state
    dia_idx = {b["d"]: i for i, b in enumerate(dia)}
    st = [0] * len(dia); phase = "out_wait_oct"; pos = 0
    dji_dates = {b["d"] for b in dji}
    for i, b in enumerate(dji):
        d = b["d"]; md = d[5:]
        if bull[i] is None: continue
        if phase == "out_wait_oct" and md >= "10-16": phase = "out_wait_entry"
        if phase == "out_wait_entry":
            if bull[i]: pos = 1; phase = "in_wait_apr"
        elif phase == "in_wait_apr" and md >= "04-20" and d[5:7] in ("04","05","06","07","08","09"):
            phase = "in_wait_exit"
        if phase == "in_wait_exit":
            if not bull[i]: pos = 0; phase = "out_wait_oct"
        if d in dia_idx: st[dia_idx[d]] = pos
    for i in range(1, len(st)):
        if dia[i]["d"] not in dji_dates: st[i] = st[i-1]
    return st

def folds(state, years):
    """Fresh $100 per calendar year, compounded."""
    tot = 100.0; per = {}
    for y in years:
        r = simulate(dia, state, f"{y}-01-01", f"{y}-12-31", "native")
        per[str(y)] = r["final"]; tot *= r["final"] / 100.0
    return round(tot, 2), per

def main():
    out = {"family": "hunt-harding-sts", "program": "v13-best-rules",
           "form": "Harding dates Oct16->Apr20, calendar only, no MACD, no floor, DIA",
           "roads": {}, "placebos": {}, "confirmation": {}}
    st = build_calendar_state()
    pub_st = build_published_state()
    # integrity: published form must reproduce v12 finals on program roads
    from chassis import ROADS as V12ROADS
    for road, (s, e) in V12ROADS.items():
        got = simulate(dia, pub_st, s, e, "native")["final"]
        print("integrity", road, "published reproduced", got, "vs v12", PUBLISHED[road])
    for road, (s, e) in ROADS.items():
        r = simulate(dia, st, s, e, "native")
        ent = {k: v for k, v in r.items() if k != "curve"}
        ent["period_stats_annual"] = period_stats(r["curve"], "Y")
        ent["period_stats_monthly"] = period_stats(r["curve"], "M")
        ent["curve"] = r["curve"]
        ent["dia_buy_hold"] = buy_hold(dia, s, e)
        ent["champion_vm"] = CHAMP[road]; ent["spy_reference"] = SPYREF[road]
        ent["published_sts_native"] = PUBLISHED[road]
        out["roads"][road] = ent
        print(road, "my-rules", ent["final"], "maxdd", ent["max_dd"], "trades", ent["trades"],
              "dia bh", ent["dia_buy_hold"], "published", PUBLISHED[road])
    for road, (s, e) in ROADS.items():
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed); off = rng.randint(1, 11)
            pst = build_calendar_state(shift_md("10-16", off), shift_md("04-20", off))
            finals.append(simulate(dia, pst, s, e, "native")["final"])
        sysf = out["roads"][road]["final"]
        out["placebos"][road] = {"finals": finals, "median": round(statistics.median(finals), 2),
                                 "system_final": sysf,
                                 "beats": sum(1 for f in finals if sysf > f)}
        print("placebo", road, out["placebos"][road])
    # confirmation: only for roads beating the champion
    for road, (s, e) in ROADS.items():
        if out["roads"][road]["final"] > CHAMP[road]:
            years = list(range(int(s[:4]), 2027))
            my_f, my_per = folds(st, years); pub_f, pub_per = folds(pub_st, years)
            idx = [i for i, b in enumerate(dia) if s <= b["d"] <= e]
            mid = dia[idx[len(idx) // 2]]["d"]
            halves = {}
            for name, (hs, he) in {"first": (s, mid), "second": (mid, e)}.items():
                halves[name] = {"my": simulate(dia, st, hs, he, "native")["final"],
                                "dia_bh": buy_hold(dia, hs, he)}
            out["confirmation"][road] = {
                "folds_my_compounded": my_f, "folds_published_compounded": pub_f,
                "folds_my_per_year": my_per, "folds_published_per_year": pub_per,
                "fold_bar_pass": my_f > pub_f, "halves": halves,
                "half_bar_pass": all(h["my"] > h["dia_bh"] for h in halves.values())}
            print("confirmation", road, out["confirmation"][road])
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)

if __name__ == "__main__":
    main()
