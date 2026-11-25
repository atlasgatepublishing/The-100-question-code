#!/usr/bin/env python3
"""V13 Best Rules — hunt-2yr-ma-multiplier. Implements BEST-RULES-SPEC.md exactly.
Dial: R=price/SMA730 (trailing only, PIT). Weekly decision closes (every 7th bar
of the window): R<3 -> weight 1.0; 3<=R<5 -> 0.5; R>=5 -> 0.0. Close-to-close
chassis (decision at close t earns t->t+1), cost 0.60% on traded fraction.
No floor. $100 pots. Roads FULL/DESIGN/VALIDATION as the v12 family record.
BTC primary; ETH labeled EXTENSION. Placebos (BTC, FULL+VALIDATION, 20 seeds):
matched random-timing + shifted-signal.
Data: CoinMetrics Community PriceUSD, shared read-only cache in
v12-completions/crypto-onchain/data/cm_{btc,eth}.json (same source as v12)."""
import json, os, random, sys
sys.path.insert(0, os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-2yr-ma-multiplier"))
from common import sma_series, period_stats, maxdd, sim_close_exec, buyhold_close

HERE = os.path.expanduser("~/workspace/stock-app/backtests/v13-best-rules/hunt-2yr-ma-multiplier")
CACHE = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/crypto-onchain/data")
START, COST = 100.0, 0.006

def load(asset):
    rows = json.load(open(os.path.join(CACHE, f"cm_{asset}.json")))
    bars = [{"d": r["time"][:10], "c": float(r["PriceUSD"])} for r in rows]
    bars.sort(key=lambda b: b["d"])
    return [b for b in bars if b["d"] <= "2026-11-21"]

def target_weight(r):
    if r is None: return 0.0
    if r < 3.0: return 1.0
    if r < 5.0: return 0.5
    return 0.0

def sim_weighted(bars, targets_by_idx):
    """targets_by_idx: dict bar_index -> target weight applied at that bar's close."""
    cash, coin = START, 0.0; curve = []; trades = 0; costs = 0.0; wsum = 0.0
    for i, b in enumerate(bars):
        if i > 0:
            coin *= b["c"] / bars[i-1]["c"]
        if i in targets_by_idx:
            total = cash + coin
            tgt = targets_by_idx[i] * total
            amt = abs(tgt - coin)
            if amt > 1e-9:
                fee = amt * COST; costs += fee; total -= fee; trades += 1
                coin = targets_by_idx[i] * total; cash = total - coin
        total = cash + coin
        wsum += (coin / total if total > 0 else 0.0)
        curve.append({"d": b["d"], "eq": round(total, 4)})
    return {"final": curve[-1]["eq"] if curve else START, "curve": curve, "trades": trades,
            "costs": round(costs, 2), "maxdd": maxdd(curve),
            "avg_weight": round(wsum / max(1, len(bars)), 4)}

def run_asset(asset):
    bars = load(asset); closes = [b["c"] for b in bars]
    sma = sma_series(closes, 730)
    ratio = [None if sma[i] is None else closes[i] / sma[i] for i in range(len(closes))]
    first = next(i for i, v in enumerate(sma) if v is not None)
    windows = {"FULL": (bars[first]["d"], "2026-11-20"), "DESIGN": (bars[first]["d"], "2022-12-31"),
               "VALIDATION": ("2023-01-01", "2026-11-20")}
    res = {}
    for wname, (s, e) in windows.items():
        idx = [i for i, b in enumerate(bars) if s <= b["d"] <= e]
        wb = [bars[i] for i in idx]
        dec_local = list(range(0, len(idx), 7))          # weekly decision bars (window-local)
        targets = {j: target_weight(ratio[idx[j]]) for j in dec_local}
        real = sim_weighted(wb, targets)
        entry = {"real": real, "buyhold": round(buyhold_close(wb), 2),
                 "periods_monthly": period_stats(real["curve"], "monthly"),
                 "buyhold_periods_monthly": None,
                 "n_decisions": len(dec_local),
                 "target_freq": {str(w): sum(1 for v in targets.values() if v == w) for w in (1.0, 0.5, 0.0)},
                 "window": [wb[0]["d"], wb[-1]["d"]]}
        # buy-hold curve period stats
        bh_curve = []; sh = START * (1 - COST) / wb[0]["c"]
        for b in wb: bh_curve.append({"d": b["d"], "eq": round(sh * b["c"], 4)})
        entry["buyhold_periods_monthly"] = period_stats(bh_curve, "monthly")
        entry["buyhold_maxdd"] = maxdd(bh_curve)
        if asset == "btc" and wname in ("FULL", "VALIDATION"):
            tlist = [targets[j] for j in dec_local]
            levels = sorted(set(tlist)); freq = {w: tlist.count(w) / len(tlist) for w in levels}
            rt_finals, sh_finals = [], []
            for sd in range(1, 21):
                rng = random.Random(1000 + sd)
                rt = {j: rng.choices(levels, weights=[freq[w] for w in levels])[0] for j in dec_local}
                rt_finals.append(sim_weighted(wb, rt)["final"])
                rng2 = random.Random(2000 + sd)
                off = rng2.randrange(4, max(5, len(tlist) - 3))
                shifted = tlist[off:] + tlist[:off]
                sh_finals.append(sim_weighted(wb, {j: shifted[k] for k, j in enumerate(dec_local)})["final"])
            real_f = real["final"]
            entry["placebos"] = {
                "random_timing": {"finals": [round(f, 2) for f in rt_finals],
                                  "beaten": sum(1 for f in rt_finals if real_f > f),
                                  "percentile": round(100.0 * sum(1 for f in rt_finals if real_f > f) / len(rt_finals), 1)},
                "shifted_signal": {"finals": [round(f, 2) for f in sh_finals],
                                   "beaten": sum(1 for f in sh_finals if real_f > f),
                                   "percentile": round(100.0 * sum(1 for f in sh_finals if real_f > f) / len(sh_finals), 1)}}
        res[wname] = entry
    return res

# --- verification: reproduce v12 ZONE BTC FULL on this data tape ---
bars = load("btc"); closes = [b["c"] for b in bars]; sma = sma_series(closes, 730)
first = next(i for i, v in enumerate(sma) if v is not None)
idx = [i for i, b in enumerate(bars) if bars[first]["d"] <= b["d"] <= "2026-11-20"]
st = []
for i in idx:
    st.append(0 if closes[i] >= 5.0 * sma[i] else 1)
chk = sim_close_exec([bars[i] for i in idx], st)
print(f"VERIFY v12 ZONE BTC FULL: got {chk['final']:.2f} (v12 record 108669.06)")

out = {"family": "hunt-2yr-ma-multiplier", "program": "v13-best-rules",
       "verify_v12_zone_btc_full": round(chk["final"], 2),
       "BTC": run_asset("btc"), "ETH_EXTENSION": run_asset("eth")}
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
for coin in ["BTC", "ETH_EXTENSION"]:
    for w in ["FULL", "DESIGN", "VALIDATION"]:
        r = out[coin][w]
        print(coin, w, r["window"], "real", r["real"]["final"], "dd", r["real"]["maxdd"],
              "trades", r["real"]["trades"], "avgw", r["real"]["avg_weight"], "bh", r["buyhold"], "bhdd", r["buyhold_maxdd"],
              "freq", r["target_freq"])
        if "placebos" in r:
            print("   placebos RT beaten", r["placebos"]["random_timing"]["beaten"], "/20  SH beaten", r["placebos"]["shifted_signal"]["beaten"], "/20")
