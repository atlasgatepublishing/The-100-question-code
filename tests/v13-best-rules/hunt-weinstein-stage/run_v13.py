#!/usr/bin/env python3
"""V13 BEST RULES — Weinstein Stage Analysis. Simulation only; no orders placed.

Frozen design: BEST-RULES-SPEC.md in this folder. Weekly closes; Stage 2 =
close above 30-week SMA and 4-week MA slope > 0; eligible names ranked by
26-week RS vs SPY; book of 10 equal slots (entry size = equity/10), filled as
slots open; exit at next open after a weekly close below the 30-week MA;
NO volume condition, NO base requirement, NO index gate, NO portfolio floor.
Costs 0.10%/side (the v12 Weinstein chassis rate). Signals on Friday close,
execution at the next trading day's open. Point-in-time only.

Data: shared read-only cache prices_cache.npz (154 pond names + SPY,
2008-01-02..2026-11-20) from the v12 slice-7 hunt workspace.
"""
import json, os, random, statistics, sys
from datetime import date
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser(
    "~/workspace/agents/cd3fd65b-e413-4760-815d-70c64f9aaa24/s7/prices_cache.npz")
COST = 0.001
MAXN = 10
START = 100.0

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
TASK_ROADS = dict(ROADS)
CHAMP = {"LONG": 1415.62, "DECADE": 667.35, "CONT": 544.47, "VAL": 288.05}
SPYREF = {"LONG": 822.94, "DECADE": 367.80, "CONT": 313.62, "VAL": 187.77}
PUBLISHED = {"LONG": 102.50, "DECADE": 102.50, "CONT": 102.50, "VAL": 100.00}


def dord(s):
    y, m, d = map(int, s.split("-")); return date(y, m, d).toordinal()


def max_dd(curve):
    peak = -1.0; dd = 0.0
    for _, e in curve:
        peak = max(peak, e); dd = max(dd, (peak - e) / peak if peak > 0 else 0.0)
    return round(dd * 100, 2)


def period_stats(curve, tempo="weekly"):
    if tempo == "weekly":
        def key(d):
            o = dord(d); return str(o - date.fromordinal(o).weekday())
    elif tempo == "monthly":
        key = lambda d: d[:7]
    elif tempo == "annual":
        key = lambda d: d[:4]
    else:
        key = lambda d: d
    last = {}
    for d, e in curve: last[key(d)] = (d, e)
    pts = [last[k] for k in sorted(last)]
    rets = [pts[i][1] / pts[i - 1][1] - 1.0 for i in range(1, len(pts)) if pts[i - 1][1] > 0]
    if not rets: return {"periods": 0}
    pos = sum(1 for r in rets if r > 0)
    ls = cur = 0
    for r in rets:
        cur = cur + 1 if r < 0 else 0; ls = max(ls, cur)
    peak = pts[0][1]; since = 0; longest = 0
    for d, e in pts:
        if e >= peak: peak = e; since = 0
        else: since += 1; longest = max(longest, since)
    return {"periods": len(rets), "share_positive": round(pos / len(rets), 4),
            "median": round(statistics.median(rets), 5), "best": round(max(rets), 5),
            "worst": round(min(rets), 5), "longest_losing_streak": ls,
            "longest_between_highs_periods": longest,
            "average_secondary": round(statistics.mean(rets), 5)}


# ---------------------------------------------------------------- data
z = np.load(CACHE)
CAL = list(z["dates"]); TKS = list(z["tks"])
Cm = z["C"].astype(float); Om = z["O"].astype(float); Vm = z["V"].astype(float)
N = len(CAL)
SPYi = TKS.index("SPY")
POND = [t for t in TKS if t != "SPY"]
PK = {t: TKS.index(t) for t in POND}
FF = Cm.copy()
for k in range(Cm.shape[1]):
    col = FF[:, k]; idx = np.where(col > 0, np.arange(N), 0)
    np.maximum.accumulate(idx, out=idx); FF[:, k] = col[idx]
OF = np.where(Om > 0, Om, FF)  # open, forward-close fallback for missing opens
ORDS = np.array([dord(d) for d in CAL])
WEEKID = np.array([o - date.fromordinal(int(o)).weekday() for o in ORDS])

# weekly bars per ticker: weekkey -> (last daily idx, close)
def weekly(kcol):
    out = {}
    for i in range(N):
        if Cm[i, kcol] <= 0: continue
        out[int(WEEKID[i])] = (i, float(Cm[i, kcol]))
    keys = sorted(out)
    return keys, [out[w][0] for w in keys], [out[w][1] for w in keys]

SPY_WK, SPY_WI, SPY_WC = weekly(SPYi)
SPY_POS = {w: j for j, w in enumerate(SPY_WK)}
DECISION_DAYS = set(SPY_WI)  # last trading day of each week (market calendar)

WEEKLY = {}   # tk -> dict with keys/idx/closes/ma/slope/stage2/rs arrays
for tk in POND:
    wk, wi, wc = weekly(PK[tk])
    n_w = len(wc)
    ma = [None] * n_w; slope = [None] * n_w; s2 = [False] * n_w; rs = [None] * n_w
    for i in range(n_w):
        if i >= 29:
            ma[i] = sum(wc[i - 29:i + 1]) / 30.0
        if i >= 33 and ma[i] is not None and ma[i - 4] is not None:
            slope[i] = (ma[i] - ma[i - 4]) / ma[i]
            s2[i] = (wc[i] > ma[i]) and (slope[i] > 0)
        if i >= 26:
            j = SPY_POS.get(wk[i])
            if j is not None and j >= 26:
                rs[i] = (wc[i] / wc[i - 26] - 1.0) - (SPY_WC[j] / SPY_WC[j - 26] - 1.0)
    WEEKLY[tk] = {"wk": wk, "wi": wi, "wc": wc, "ma": ma, "s2": s2, "rs": rs,
                  "pos": {w: i for i, w in enumerate(wk)}}


def signal_at(tk, day_idx):
    """(stage2, rs) for tk at the weekly bar whose last day is day_idx, else None."""
    W = WEEKLY[tk]; i = W["pos"].get(int(WEEKID[day_idx]))
    if i is None or i < 33 or W["rs"][i] is None: return None
    return W["s2"][i], W["rs"][i], W["wc"][i], W["ma"][i]


# ---------------------------------------------------------------- sim
def sim(start, end, mode="real", seed=None, entry_counts=None):
    si = next(i for i, d in enumerate(CAL) if d >= start)
    ei = max(i for i, d in enumerate(CAL) if d <= end)
    cash = START; shares = {}  # tk -> shares
    curve = []; costs = 0.0; pending = []  # (side, tk)
    entries_made = {}  # signal date str -> count (real mode, for placebos)
    n_entries = 0; n_exits = 0
    rng = random.Random(seed)
    for i in range(si, ei + 1):
        # execute pending at today's open
        for side, tk in pending:
            k = PK[tk]; px = float(OF[i, k])
            if px <= 0: continue
            if side == "sell" and tk in shares:
                proceeds = shares.pop(tk) * px
                cash += proceeds * (1 - COST); costs += proceeds * COST; n_exits += 1
            elif side == "buy" and tk not in shares and len(shares) < MAXN:
                eq = cash + sum(sh * float(FF[i, PK[t]]) for t, sh in shares.items())
                amt = min(eq / MAXN, cash)
                if amt > 0:
                    shares[tk] = amt * (1 - COST) / px; cash -= amt; costs += amt * COST
                    n_entries += 1
        pending = []
        eq = cash + sum(sh * float(FF[i, PK[t]]) for t, sh in shares.items())
        curve.append((CAL[i], eq))
        # weekly decision at today's close
        if i in DECISION_DAYS and i < ei:
            sells = []
            for tk in list(shares):
                s = signal_at(tk, i)
                if s is not None and not s[0]:
                    sells.append(tk)
                elif s is not None and s[2] < s[3]:  # close below MA (stage2 false covers it; belt)
                    sells.append(tk)
            buys = []
            free = MAXN - (len(shares) - len(sells))
            if free > 0:
                if mode == "real":
                    cand = []
                    for tk in POND:
                        if tk in shares and tk not in sells: continue
                        s = signal_at(tk, i)
                        if s is not None and s[0]: cand.append((-s[1], tk))
                    cand.sort()
                    buys = [tk for _, tk in cand[:free]]
                    if buys: entries_made[CAL[i]] = len(buys)
                else:  # placebo: same entry count as the real run on this date
                    cnt = min(entry_counts.get(CAL[i], 0), free)
                    if cnt > 0:
                        pool = [tk for tk in POND if tk not in shares
                                and signal_at(tk, i) is not None]
                        if pool:
                            buys = rng.sample(pool, min(cnt, len(pool)))
            pending = [("sell", tk) for tk in sells] + [("buy", tk) for tk in buys]
    return {"final": round(curve[-1][1], 2),
            "curve": [(d, round(float(e), 4)) for d, e in curve],
            "costs": round(costs, 2), "max_dd_pct": max_dd(curve),
            "n_entries": n_entries, "n_exits": n_exits, "entries_made": entries_made}


def spy_curve(start, end):
    si = next(i for i, d in enumerate(CAL) if d >= start)
    ei = max(i for i, d in enumerate(CAL) if d <= end)
    p0 = float(FF[si, SPYi])
    return [(CAL[i], round(START * float(FF[i, SPYi]) / p0, 4)) for i in range(si, ei + 1)]


def main():
    out = {"family": "hunt-weinstein-stage", "program": "v13-best-rules",
           "spec": "BEST-RULES-SPEC.md (frozen before run)",
           "rules": "Stage2 = weekly close > 30wk SMA and 4wk slope>0; rank by 26wk RS vs SPY; "
                    "10 equal slots; exit next open after weekly close < 30wk MA; no volume/base/"
                    "index-gate/floor; costs 0.10%/side; next-open execution",
           "roads": {}}
    beat_roads = []
    for road, (a, b) in ROADS.items():
        real = sim(a, b, mode="real")
        ec = real.pop("entries_made")
        pbs = []
        for s in range(1, 21):
            pb = sim(a, b, mode="placebo", seed=s, entry_counts=ec)
            pbs.append(pb["final"])
        beaten = sum(1 for x in pbs if real["final"] > x)
        spy = spy_curve(a, b)
        out["roads"][road] = {
            "best_rules": real, "placebos_20": pbs, "placebos_beaten": beaten,
            "placebo_median": round(statistics.median(pbs), 2),
            "period_stats_weekly": period_stats(real["curve"], "weekly"),
            "period_stats_monthly": period_stats(real["curve"], "monthly"),
            "spy_final_check": spy[-1][1], "spy_ref": SPYREF[road],
            "champion_vm": CHAMP[road], "published_v12": PUBLISHED[road]}
        print(road, "final", real["final"], "dd", real["max_dd_pct"], "costs", real["costs"],
              "entries", real["n_entries"], "exits", real["n_exits"],
              "placebos_beaten", beaten, "/20  placebo_median", out["roads"][road]["placebo_median"],
              "spy_check", spy[-1][1], flush=True)
        if real["final"] > CHAMP[road]: beat_roads.append(road)
    # ---- confirmation (frozen bars in spec) for any road beating the champion
    conf = {}
    for road in beat_roads:
        a, b = ROADS[road]
        folds = {}
        for y in range(int(a[:4]), int(b[:4]) + 1):
            fs, fe = f"{y}-01-01", f"{y}-12-31"
            if fe < a or fs > b: continue
            fs = max(fs, a); fe = min(fe, b)
            r = sim(fs, fe, mode="real"); r.pop("entries_made", None)
            folds[str(y)] = r["final"]
        mid_ord = (dord(a) + dord(b)) // 2
        mid = date.fromordinal(mid_ord).isoformat()
        halves = {}
        for name, (hs, he) in {"H1": (a, mid), "H2": (mid, b)}.items():
            r = sim(hs, he, mode="real"); r.pop("entries_made", None)
            sp = spy_curve(hs, he)
            halves[name] = {"final": r["final"], "spy_final": sp[-1][1],
                            "beats_spy": r["final"] > sp[-1][1]}
        vals = sorted(folds.values())
        med = round(statistics.median(vals), 2) if vals else None
        share_pos = round(sum(1 for v in vals if v > 100) / len(vals), 4) if vals else None
        passed = (med is not None and med > 100 and share_pos >= 0.5
                  and all(h["beats_spy"] for h in halves.values()))
        conf[road] = {"yearly_folds": folds, "median_fold": med, "share_folds_positive": share_pos,
                      "half_windows": halves, "confirmation_passed": passed}
        print("CONFIRM", road, "median_fold", med, "share_pos", share_pos,
              "halves", halves, "PASSED", passed, flush=True)
    out["confirmation"] = conf
    json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    print("done", flush=True)


if __name__ == "__main__":
    main()
