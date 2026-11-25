"""V11 native PEAD engine (Bernard & Thomas seasonal-random-walk SUE, long leg only).

Usage: python3 engine.py <lite|small> <out_prefix>
- lite : universe = all tickers with cached prices in v3+v4 caches (broadened sample)
- small: universe = v4 pead-small cache tickers only (small/mid habitat)
Rules (frozen in NATIVE-SPEC.md): SUE = (EPS_q - EPS_{q-4}) / sd(prior up-to-8 UEs, min 4);
announcement date = EDGAR filed date of the quarterly EPS fact (conservative);
entry if SUE >= 90th pct of SUEs filed in the PREVIOUS calendar quarter (min 20 obs);
enter at adjusted close of first trading day after filing; hold 60 trading days;
slice = 10% of equity at entry, max 10 concurrent; costs lite 0.10%/side, small 0.35%/side.
No stop, no floor (the published system has none). $100 pot, fractional shares.
Placebos: same number of signals, random ticker + random trading day, seeds 1..20.
"""
import json, os, sys, glob, math, random, statistics
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
V3 = "/home/hatch/workspace/stock-app/backtests/v3/pead-cache"
V4 = "/home/hatch/workspace/stock-app/backtests/v4/pead-small-cache"
EPS = os.path.join(HERE, "eps_cache")

def load_px(t):
    for c in (V3, V4):
        p = os.path.join(c, f"px_{t}.json")
        if os.path.exists(p):
            d = json.load(open(p))["chart"]["result"][0]
            ts = d["timestamp"]; adj = d["indicators"]["adjclose"][0]["adjclose"]
            out = {}
            for i, x in enumerate(ts):
                if adj[i]:
                    out[date.fromtimestamp(x).isoformat()] = adj[i]
            return out
    return {}

def main():
    mode, prefix = sys.argv[1], sys.argv[2]
    if mode == "lite":
        tickers = sorted({os.path.basename(f)[3:-5] for c in (V3, V4)
                          for f in glob.glob(os.path.join(c, "px_*.json"))} - {"SPY"})
        cost = 0.0010
    else:
        tickers = sorted({os.path.basename(f)[3:-5] for f in glob.glob(os.path.join(V4, "px_*.json"))} - {"SPY"})
        cost = 0.0035
    px = {t: load_px(t) for t in tickers}
    spy = load_px("SPY")
    cal = sorted(spy.keys())                      # SPY trading calendar
    cal_idx = {d: i for i, d in enumerate(cal)}

    # --- SUE per announcement ---
    anns = []  # (filed, ticker, sue)
    for t in tickers:
        fp = os.path.join(EPS, f"eps_{t}.json")
        if not os.path.exists(fp): continue
        facts = json.load(open(fp))["facts"]
        eps_by_end = {f["end"]: f["val"] for f in facts}
        ues = []
        for f in facts:
            e = date.fromisoformat(f["end"])
            prior = None
            for g in facts:
                ge = date.fromisoformat(g["end"])
                if 330 <= (e - ge).days <= 400: prior = g["val"]
            if prior is None: ues.append(None); continue
            ues.append(f["val"] - prior)
        for i, f in enumerate(facts):
            ue = ues[i]
            hist = [u for u in ues[max(0, i-8):i] if u is not None]
            if ue is None or len(hist) < 4: continue
            sd = statistics.pstdev(hist)
            if sd <= 0: continue
            anns.append((f["filed"], t, ue / sd))
    anns.sort()

    # --- signals: top-decile vs previous calendar quarter's SUE distribution ---
    def prev_q(filed):
        y, m = int(filed[:4]), int(filed[5:7])
        q = (m - 1) // 3
        if q == 0: return (y - 1, 4)
        return (y, q)
    signals = []
    for filed, t, sue in anns:
        py, pq = prev_q(filed)
        pool = [s for (fd, _, s) in anns
                if int(fd[:4]) == py and (int(fd[5:7]) - 1) // 3 + 1 == pq]
        if len(pool) < 20: continue
        pool.sort()
        thr = pool[min(len(pool) - 1, int(0.90 * len(pool)))]
        if sue >= thr and sue > 0:
            signals.append({"filed": filed, "ticker": t, "sue": round(sue, 3)})

    def run(sig_list, start, end):
        # entry date = first cal day > filed; exit = entry idx + 60
        trades = []
        for s in sig_list:
            cand = [d for d in cal if d > s["filed"]]
            if not cand: continue
            ed = cand[0]
            if not (start <= ed <= end): continue
            i = cal_idx[ed]
            if i + 60 >= len(cal): continue
            xd = cal[i + 60]
            p0 = px[s["ticker"]].get(ed); p1 = px[s["ticker"]].get(xd)
            if not p0 or not p1: continue
            trades.append({**s, "entry": ed, "exit": xd, "p0": p0, "p1": p1})
        trades.sort(key=lambda x: x["entry"])
        cash, pos, curve, total_cost = 100.0, [], [], 0.0
        ti = 0
        for d in cal:
            if not (start <= d <= end): continue
            # exits
            still = []
            for p in pos:
                if d >= p["exit"]:
                    proceeds = p["shares"] * px[p["ticker"]].get(d, p["p1"]) * (1 - cost)
                    total_cost += p["shares"] * px[p["ticker"]].get(d, p["p1"]) * cost
                    cash += proceeds
                else: still.append(p)
            pos = still
            # entries
            while ti < len(trades) and trades[ti]["entry"] == d:
                tr = trades[ti]; ti += 1
                equity = cash + sum(p["shares"] * px[p["ticker"]].get(d, p["p0"]) for p in pos)
                slice_amt = 0.10 * equity
                if len(pos) < 10 and cash >= slice_amt > 0:
                    shares = slice_amt * (1 - cost) / tr["p0"]
                    total_cost += slice_amt * cost
                    cash -= slice_amt
                    pos.append({**tr, "shares": shares})
            equity = cash + sum(p["shares"] * px[p["ticker"]].get(d, p["p0"]) for p in pos)
            curve.append([d, round(equity, 2)])
        final = curve[-1][1] if curve else 100.0
        peak, mdd = 100.0, 0.0
        for _, v in curve:
            peak = max(peak, v); mdd = min(mdd, v / peak - 1)
        spy_r = None
        s0 = spy.get(curve[0][0]) if curve else None; s1 = spy.get(curve[-1][0]) if curve else None
        if s0 and s1: spy_r = round(100 * s1 / s0, 2)
        return {"final": final, "max_dd_pct": round(mdd * 100, 2), "costs": round(total_cost, 2),
                "n_signals": len(trades), "spy_final": spy_r, "curve": curve}

    windows = {"FULL_2019_2026": ("2019-01-01", "2026-11-20"),
               "DESIGN_2019_2022": ("2019-01-01", "2022-12-31"),
               "VAL_2023_2026": ("2023-01-01", "2026-11-20")}
    out = {"mode": mode, "universe_n": len(tickers), "tickers": tickers,
           "n_announcements_with_sue": len(anns), "n_signals_full": None, "windows": {}}
    for w, (a, b) in windows.items():
        r = run(signals, a, b)
        out["windows"][w] = {k: v for k, v in r.items()}
        if w == "FULL_2019_2026": out["n_signals_full"] = r["n_signals"]
    # placebos on FULL
    a, b = windows["FULL_2019_2026"]
    real_n = out["windows"]["FULL_2019_2026"]["n_signals"]
    days = [d for d in cal if a <= d <= b]
    pls = []
    for seed in range(1, 21):
        rng = random.Random(seed)
        fake = [{"filed": rng.choice(days), "ticker": rng.choice(tickers), "sue": 0} for _ in range(real_n)]
        # shift filed back a day so entry lands on a trading day inside window
        fake = [{**f, "filed": cal[max(0, cal_idx[f["filed"]] - 1)]} for f in fake]
        pls.append(run(fake, a, b)["final"])
    real_final = out["windows"]["FULL_2019_2026"]["final"]
    out["placebos_full"] = {"finals": pls, "beaten": sum(1 for x in pls if real_final > x),
                            "median": round(statistics.median(pls), 2)}
    json.dump(out, open(os.path.join(HERE, f"{prefix}.json"), "w"))
    print(mode, "signals", out["n_signals_full"], "anns", len(anns),
          {w: out["windows"][w]["final"] for w in windows},
          "spy", {w: out["windows"][w]["spy_final"] for w in windows},
          "placebo beaten", out["placebos_full"]["beaten"], "/20 median", out["placebos_full"]["median"])

if __name__ == "__main__":
    main()
