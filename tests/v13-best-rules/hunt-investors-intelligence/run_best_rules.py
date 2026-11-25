#!/usr/bin/env python3
"""v13 BEST RULES — hunt-investors-intelligence (II advisor-sentiment timing).

Implements BEST-RULES-SPEC.md exactly as frozen:
  weekly II print -> quarter-step exposure dial anchored on II's published
  bands (bulls 36/60, bears 55 override), fill at first session open AFTER
  publication, trade delta only, program costs 0.10%/side + $0.01 sell fee,
  cash 0%, NO floor. 20-seed random-timing placebos (circular shift of the
  target-weight path). Per-year distribution reporting.

DATA GATE: requires a free point-in-time weekly II bulls%/bears% series at
  data/ii_sentiment.csv  with header:  publication_date,bulls_pct,bears_pct
(publication_date = the date the reading was published, e.g. the Wednesday
print date). If the file is absent or does not cover a road, that road is
NOT run and the closure is recorded. No substitute series is ever loaded.
"""
import csv, json, math, os, random, sys, time
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "ii_sentiment.csv")
V7 = os.path.expanduser("~/workspace/stock-app/backtests/v7/long-hold/data")
START = 100.0
COST = 0.001          # 0.10% per side on traded delta
FEE = 0.01            # per sell order
ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
BLOCKER = ("Investors Intelligence weekly Advisors Sentiment history is a paid "
           "product ($1,890 historic file; $365/yr subscription, per the v12 record) "
           "with no free point-in-time archive.")

# ---------- frozen dial (BEST-RULES-SPEC section 3) ----------
def target_weight(bulls, bears):
    if bears is not None and bears >= 55.0:
        return 1.0                      # published strong contrarian-bullish zone
    if bulls >= 60.0: return 0.0        # published max contrarian-bearish zone
    if bulls >= 54.0: return 0.25
    if bulls >= 48.0: return 0.50
    if bulls >= 42.0: return 0.75
    return 1.0

# ---------- data ----------
def load_spy():
    j = json.load(open(os.path.join(V7, "pxfull_SPY.json")))
    r = j["chart"]["result"][0]; ts = r["timestamp"]; q = r["indicators"]["quote"][0]
    adj = r["indicators"]["adjclose"][0]["adjclose"]
    bars = []
    for i, t in enumerate(ts):
        if q["close"][i] is None or adj[i] is None or q["open"][i] is None: continue
        ratio = adj[i] / q["close"][i]
        bars.append({"d": time.strftime("%Y-%m-%d", time.gmtime(t)),
                     "o": q["open"][i] * ratio, "c": adj[i]})
    bars.sort(key=lambda b: b["d"]); return bars

def load_ii(path=DATA):
    if not os.path.exists(path): return None
    rows = []
    with open(path) as f:
        for row in csv.DictReader(f):
            rows.append({"pub": row["publication_date"].strip(),
                         "bulls": float(row["bulls_pct"]),
                         "bears": float(row["bears_pct"]) if row.get("bears_pct") else None})
    rows.sort(key=lambda r: r["pub"]); return rows

def hunt_local():
    """Scan the workspace for any pre-existing II weekly series (v13 fresh hunt, local leg)."""
    hits = []
    root = os.path.expanduser("~/workspace/stock-app")
    for dp, dn, fn in os.walk(root):
        if "hunt-investors-intelligence" in dp and "v13" in dp: continue
        for name in fn:
            low = name.lower()
            if ("investors" in low and "intelligence" in low) or low.startswith("ii_") or "_ii_" in low:
                if low.endswith((".csv", ".json", ".xlsx", ".txt")):
                    hits.append(os.path.join(dp, name))
    return hits

# ---------- simulation ----------
def simulate(bars, weight_path):
    """weight_path[i] = target weight decided before bar i's open (or None = hold).
    Rebalance at bar i open to the target; curve marked at closes."""
    cash, shares = START, 0.0; curve = []; trades = 0; costs = 0.0; wdays = 0
    cur_w = 0.0
    for i, b in enumerate(bars):
        w = weight_path[i]
        if w is not None and abs(w - cur_w) > 1e-9:
            eq_open = cash + shares * b["o"]
            target_val = w * eq_open
            cur_val = shares * b["o"]
            delta = target_val - cur_val
            if delta > 0:   # buy
                spend = delta / (1 + COST); costs += delta - spend
                shares += spend / b["o"]; cash -= delta
            else:           # sell
                proceeds = -delta * (1 - COST) - FEE; costs += -delta * COST + FEE
                shares += delta / b["o"]; cash += proceeds
            trades += 1; cur_w = w
        eq = cash + shares * b["c"]
        if shares > 1e-9: wdays += 1
        curve.append({"d": b["d"], "eq": round(eq, 4)})
    return {"final": curve[-1]["eq"] if curve else START, "curve": curve,
            "trades": trades, "costs": round(costs, 2),
            "maxdd": maxdd(curve), "invested_frac": round(wdays / max(1, len(bars)), 4)}

def build_weight_path(bars, prints):
    """prints effective at first bar with date > publication date (frozen PIT rule)."""
    path = [None] * len(bars)
    for p in prints:
        for i, b in enumerate(bars):
            if b["d"] > p["pub"]:
                path[i] = target_weight(p["bulls"], p["bears"]); break
    return path

def maxdd(curve):
    peak = -1e18; dd = 0.0
    for p in curve:
        peak = max(peak, p["eq"]); dd = max(dd, (peak - p["eq"]) / peak if peak > 0 else 0.0)
    return round(dd * 100, 2)

def year_stats(curve):
    years = {}
    for c in curve: years[c["d"][:4]] = c["eq"]
    ks = sorted(years); rets = []; prev = START
    for k in ks: rets.append((k, years[k] / prev - 1 if prev > 0 else 0.0)); prev = years[k]
    if not rets: return {}
    vals = sorted(r for _, r in rets)
    med = vals[len(vals) // 2] if len(vals) % 2 else (vals[len(vals)//2 - 1] + vals[len(vals)//2]) / 2
    pos = sum(1 for _, r in rets if r > 0)
    streak = cur = 0
    for _, r in rets:
        cur = cur + 1 if r <= 0 else 0; streak = max(streak, cur)
    peak = START; since = 0; longest = 0
    for c in curve:
        if c["eq"] >= peak: peak = c["eq"]; since = 0
        else: since += 1; longest = max(longest, since)
    return {"median_year_pct": round(med * 100, 2), "share_positive": f"{pos}/{len(rets)}",
            "best_year": f"{max(rets, key=lambda x: x[1])[0]} {max(r for _, r in rets)*100:+.1f}%",
            "worst_year": f"{min(rets, key=lambda x: x[1])[0]} {min(r for _, r in rets)*100:+.1f}%",
            "longest_losing_streak_yrs": streak, "longest_between_highs_days": longest,
            "years": {k: round(r * 100, 2) for k, r in rets}}

def buyhold(bars):
    if len(bars) < 2: return START
    shares = START * (1 - COST) / bars[0]["o"]
    return round(shares * bars[-1]["c"] * (1 - COST) - FEE, 2)

def main():
    log = []
    local_hits = hunt_local()
    log.append(f"local hunt: {len(local_hits)} candidate II data files in workspace {local_hits}")
    prints = load_ii()
    out = {"family": "hunt-investors-intelligence", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md (frozen 2026-11-22 before any run)",
           "verdict_ceiling": "CANDIDATE", "ran": False, "roads": {},
           "champions_vm": CHAMP, "spy_reference": SPYREF, "blocker": None,
           "local_hunt_hits": local_hits}
    if prints is None:
        out["blocker"] = BLOCKER
        out["verdict"] = "STILL UNBUILDABLE"
        out["equity_curves"] = None
        log.append("data gate: data/ii_sentiment.csv ABSENT -> no road runs; closure recorded.")
        json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
        print("\n".join(log)); print("VERDICT: STILL UNBUILDABLE — " + BLOCKER); return
    bars_all = load_spy()
    out["ran"] = True
    for road, (s, e) in ROADS.items():
        bars = [b for b in bars_all if s <= b["d"] <= e]
        road_prints = [p for p in prints if p["pub"] < e]
        cov_start = road_prints[0]["pub"] if road_prints else None
        if not road_prints or cov_start > s:
            out["roads"][road] = {"ran": False, "reason": f"II coverage starts {cov_start}, road starts {s}"}
            continue
        path = build_weight_path(bars, [p for p in road_prints if p["pub"] >= bars[0]["d"]])
        res = simulate(bars, path)
        # 20-seed random-timing placebos: circular shift of the target-weight path
        base = [w if w is not None else -1 for w in path]
        filled = []; last = 0.0
        for w in base: last = w if w >= 0 else last; filled.append(last)
        beaten = 0; pfinals = []
        for seed in range(20):
            rng = random.Random(1000 + seed)
            k = rng.randrange(1, len(filled))
            shifted = filled[k:] + filled[:k]
            spath = [None] * len(bars); prev = None
            for i, w in enumerate(shifted):
                if w != prev: spath[i] = w; prev = w
            pf = simulate(bars, spath)["final"]; pfinals.append(round(pf, 2))
            if res["final"] > pf: beaten += 1
        out["roads"][road] = {"ran": True, "final": res["final"], "maxdd_pct": res["maxdd"],
            "trades": res["trades"], "costs": res["costs"], "invested_frac": res["invested_frac"],
            "spy_same_plumbing": buyhold(bars), "champion_vm": CHAMP[road],
            "beats_champion": res["final"] > CHAMP[road],
            "placebo_beaten": f"{beaten}/20", "placebo_finals": pfinals,
            "distribution": year_stats(res["curve"]), "equity_curve": res["curve"]}
        log.append(f"{road}: final {res['final']} maxDD {res['maxdd']}% placebos beaten {beaten}/20")
    out["equity_curves"] = {r: out["roads"][r].get("equity_curve") for r in ROADS if out["roads"].get(r, {}).get("ran")}
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("\n".join(log))

if __name__ == "__main__":
    main()
