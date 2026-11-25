#!/usr/bin/env python3
"""V13 Best Rules — Hirsch Best Six Months.
MY RULES (frozen in BEST-RULES-SPEC.md before this run):
  invested Nov 1 -> Apr 30 in SPY (broad index), off-season May 1 -> Oct 31
  in SHY (1-3yr UST = the Almanac's T-bill leg, tradable form). Raw calendar
  dates, no MACD gate, no floor, 100%/100%, program costs
  (0.10%/side + $0.01 sell fee). Switch at close of prior trading day so the
  position state matches the calendar month (v12 convention).
Placebos: 20 seeds, same 6-month window rotated by a random non-zero month
offset (v12 construction), same two-asset rotation and costs.
Per-period distribution at semiannual tempo. Simulation only.
Chassis conventions copied from the v12 folder (read-only shared input)."""
import json, os, sys, random, statistics, time

HERE = os.path.dirname(os.path.abspath(__file__))
COST = 0.001
SELLFEE = 0.01

def load_bars(path):
    j = json.load(open(path))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None:
            continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "c": adj[i],
                     "v": q["volume"][i] if q.get("volume") and q["volume"][i] else 0})
    bars.sort(key=lambda b: b["d"])
    return bars

spy = load_bars(os.path.join(HERE, "data", "SPY.json"))
shy = load_bars(os.path.join(HERE, "data", "SHY.json"))
shy_close = {b["d"]: b["c"] for b in shy}
# master series: SPY dates, with SHY close attached (calendars must agree)
bars = []
missing = 0
for b in spy:
    if b["d"] in shy_close:
        bars.append({"d": b["d"], "SPY": b["c"], "SHY": shy_close[b["d"]]})
    else:
        missing += 1
print(f"master bars {len(bars)} ({bars[0]['d']} -> {bars[-1]['d']}), SPY dates missing SHY: {missing}")
assert missing == 0

def build_state(offset=0):
    inv = set()
    for k in range(6):
        inv.add((11 + offset + k - 1) % 12 + 1)
    st = []
    for i, b in enumerate(bars):
        nxt = bars[i + 1]["d"] if i + 1 < len(bars) else b["d"]
        st.append(1 if int(nxt[5:7]) in inv else 0)
    return st

def simulate(state, start, end):
    """pos in {None,'SPY','SHY'}; state decided at close of day i earns i->i+1."""
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    if len(idx) < 2: return None
    eq = 100.0; pos = None; curve = []; trades = 0; costs = 0.0
    peak = 100.0; maxdd = 0.0
    for k, i in enumerate(idx):
        b = bars[i]
        if k > 0 and pos is not None:
            prev = bars[idx[k - 1]]
            eq *= b[pos] / prev[pos]
        desired = "SPY" if state[i] == 1 else "SHY"
        if desired != pos:
            if pos is not None:
                c = eq * COST + SELLFEE; eq -= c; costs += c; trades += 1
            c = eq * COST; eq -= c; costs += c; trades += 1; pos = desired
        curve.append([b["d"], round(eq, 4)])
        peak = max(peak, eq); maxdd = max(maxdd, 1 - eq / peak)
    return {"final": round(eq, 2), "curve": curve, "trades": trades,
            "costs": round(costs, 2), "max_dd": round(maxdd, 4)}

def buy_hold(asset, start, end):
    idx = [i for i, b in enumerate(bars) if start <= b["d"] <= end]
    eq = 100.0 * (1 - COST)
    eq *= bars[idx[-1]][asset] / bars[idx[0]][asset]
    eq *= (1 - COST)
    return round(eq, 2)

def period_stats(curve, freq="H"):
    marks = {}
    for d, v in curve:
        if freq == "H": key = d[:4] + "-H" + ("1" if d[5:7] <= "06" else "2")
        elif freq == "Y": key = d[:4]
        else: key = d[:7]
        marks[key] = v
    keys = sorted(marks)
    vals = [100.0] + [marks[k] for k in keys]
    rets = [vals[i + 1] / vals[i] - 1 for i in range(len(vals) - 1)]
    if not rets: return {}
    pos = sum(1 for r in rets if r > 0)
    streak = cur = 0
    for r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    peak = vals[0]; since_high = cur2 = 0
    for v in vals[1:]:
        if v >= peak: peak = v; cur2 = 0
        else: cur2 += 1
        since_high = max(since_high, cur2)
    return {"periods": len(rets), "share_positive": round(pos / len(rets), 3),
            "median": round(statistics.median(rets), 4),
            "best": round(max(rets), 4), "worst": round(min(rets), 4),
            "longest_losing_streak": streak, "longest_below_high_periods": since_high,
            "average_secondary": round(sum(rets) / len(rets), 4)}

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED_V12 = {"LONG": 285.93, "DECADE": 154.91, "CONT": 143.20, "VAL": 113.82}

def main():
    out = {"family": "hunt-hirsch-best-six-months", "program": "v13-best-rules",
           "form": "SPY Nov-Apr / SHY May-Oct, raw dates, no gate, no floor",
           "roads": {}}
    st = build_state()
    beaten = []
    for road, (s, e) in ROADS.items():
        r = simulate(st, s, e)
        ent = {"final": r["final"], "max_dd": r["max_dd"], "trades": r["trades"],
               "costs": r["costs"], "curve": r["curve"],
               "period_stats_semiannual": period_stats(r["curve"], "H"),
               "spy_buy_hold_computed": buy_hold("SPY", s, e),
               "spy_reference_program": SPYREF[road],
               "champion_vm": CHAMP[road],
               "published_form_v12_dia_cash": PUBLISHED_V12[road]}
        out["roads"][road] = ent
        if r["final"] > CHAMP[road]: beaten.append(road)
        print(road, "mine", r["final"], "maxdd", r["max_dd"], "trades", r["trades"],
              "costs", r["costs"], "| published", PUBLISHED_V12[road],
              "| SPY bh (computed)", ent["spy_buy_hold_computed"], "| champ", CHAMP[road])
    out["placebos"] = {}
    for road, (s, e) in ROADS.items():
        finals = []
        for seed in range(1, 21):
            rng = random.Random(seed); off = rng.randint(1, 11)
            finals.append(simulate(build_state(off), s, e)["final"])
        sysf = out["roads"][road]["final"]
        out["placebos"][road] = {"finals": finals,
                                 "median": round(statistics.median(finals), 2),
                                 "best": max(finals), "worst": min(finals),
                                 "system_final": sysf,
                                 "beats": sum(1 for f in finals if sysf > f)}
        print("placebo", road, out["placebos"][road])
    # Confirmation (Terry's rule) — only if a road beat the champion; bars frozen in spec.
    out["confirmation"] = {"triggered_on_roads": beaten}
    if beaten:
        conf = {}
        for road in beaten:
            s, e = ROADS[road]
            folds = []
            for y in range(2017, 2027):
                fs, fe = f"{y}-01-01", f"{y}-12-31"
                if fe > "2026-11-20": fe = "2026-11-20"
                rf = simulate(st, fs, fe); bh = buy_hold("SPY", fs, fe)
                folds.append({"year": y, "mine": rf["final"] if rf else None,
                              "spy_bh": bh})
            comp_mine = 100.0; comp_bh = 100.0; above = 0
            for f in folds:
                if f["mine"] is None: continue
                comp_mine *= f["mine"] / 100.0; comp_bh *= f["spy_bh"] / 100.0
                if f["mine"] > 100: above += 1
            mid = bars[[i for i, b in enumerate(bars) if s <= b["d"] <= e][len([i for i, b in enumerate(bars) if s <= b["d"] <= e]) // 2]]["d"]
            halves = []
            for hs, he in ((s, mid), (mid, e)):
                rh = simulate(st, hs, he)
                halves.append({"window": [hs, he], "mine": rh["final"],
                               "spy_bh": buy_hold("SPY", hs, he)})
            passed = (comp_mine > comp_bh and above >= 7
                      and all(h["mine"] > h["spy_bh"] for h in halves))
            conf[road] = {"folds": folds, "fold_compounded_mine": round(comp_mine, 2),
                          "fold_compounded_spy_bh": round(comp_bh, 2),
                          "folds_above_100": above, "halves": halves,
                          "confirmation_passed": passed}
            print("CONFIRMATION", road, conf[road])
        out["confirmation"]["results"] = conf
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("done")

if __name__ == "__main__":
    main()
