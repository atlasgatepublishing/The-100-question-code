#!/usr/bin/env python3
"""V13 best-rules hunt-raschke-anti — BEST-RULES-SPEC.md (frozen before run).
SPY only, long only, $100 all-in, one position at a time.
Oscillator published: Fast=SMA3-SMA10 closes, Slow=SMA16(Fast).
Armed whenever Slow>0. Pullback = first Fast<=Slow after Fast above Slow.
Entry next session buy stop at pullback-bar high x1.001 (lapses if not hit).
Stop = min low from pre-pullback Fast-peak bar through pullback bar x0.999
(baked into exit scan; entry-bar breach = stopped).
Exit: close on first bar Slow<=0 (trend death). No floor.
Costs SPY 0.10%/side + $0.01 sell fee. Placebos: 20 seeds, pullback bars
shifted +-30..250 bars, same machinery. Simulation only."""
import json, os, sys, random
V12 = os.path.expanduser("~/workspace/stock-app/backtests/v12-completions/hunt-raschke-anti")
sys.path.insert(0, V12)
from raschke_common import load_spy, simulate, monthly_stats, window_idx, bh
HERE = os.path.dirname(os.path.abspath(__file__))

def osc(bars):
    c = [b["c"] for b in bars]; N = len(bars)
    def sma(x, n):
        out = [None]*N; s = 0.0
        for i, v in enumerate(x):
            s += v
            if i >= n: s -= x[i-n]
            if i >= n-1: out[i] = s/n
        return out
    s3 = sma(c, 3); s10 = sma(c, 10)
    fast = [None if (a is None or b is None) else a-b for a, b in zip(s3, s10)]
    fv = [v if v is not None else 0.0 for v in fast]
    slow = sma(fv, 16)
    for i in range(N):
        if fast[i] is None: slow[i] = None
    return fast, slow

def build(bars, fast, slow, p, peak_bar):
    """p = pullback bar. Entry next session at bars[p].high*1.001 if taken out.
    Exit scan: stop breach (incl. entry bar) -> stop; else first Slow<=0 close;
    else last bar close."""
    n = len(bars); e = p + 1
    if e >= n: return None
    entry = bars[p]["h"] * 1.001
    if bars[e]["h"] < entry: return None
    stop = min(b["l"] for b in bars[peak_bar:p+1]) * 0.999
    if stop >= entry: return None
    for k in range(e, n):
        if bars[k]["l"] <= stop:
            return dict(entry_i=e, entry_px=entry, stop_px=-1.0, exit_i=k, exit_px=stop, exit_reason="stop")
        if slow[k] is not None and slow[k] <= 0:
            return dict(entry_i=e, entry_px=entry, stop_px=-1.0, exit_i=k, exit_px=bars[k]["c"], exit_reason="trend-death")
    return dict(entry_i=e, entry_px=entry, stop_px=-1.0, exit_i=n-1, exit_px=bars[n-1]["c"], exit_reason="data-end")

def gen(bars):
    fast, slow = osc(bars)
    trades = []; was_above = False; peak_bar = None; peak_val = None; busy_until = -1
    for t in range(1, len(bars)):
        if slow[t] is None or fast[t] is None: continue
        if slow[t] <= 0:
            was_above = False; peak_val = None; continue
        if t <= busy_until: continue
        if fast[t] > slow[t]:
            if peak_val is None or fast[t] > peak_val: peak_val = fast[t]; peak_bar = t
            was_above = True
        elif was_above and fast[t] <= slow[t]:
            tr = build(bars, fast, slow, t, peak_bar if peak_bar is not None else t)
            if tr:
                trades.append(tr); busy_until = tr["exit_i"]
            was_above = False; peak_val = None
    return trades, fast, slow

ROADS = {"LONG": ("2010-01-04", "2026-11-20"), "DECADE": ("2016-11-21", "2026-11-20"),
         "CONT": ("2019-01-02", "2026-11-20"), "VAL": ("2023-01-03", "2026-11-20")}
COST, FEE = 0.001, 0.01
bars = load_spy()
trades, fast, slow = gen(bars)
out = {"family": "hunt-raschke-anti", "program": "v13-best-rules", "asset": "SPY",
       "n_trades_total": len(trades), "roads": {}}
for rn, (a, b) in ROADS.items():
    w0, w1 = window_idx(bars, a, b)
    f, curve, done, dd, _ = simulate(bars, trades, COST, FEE, floor=False, w0=w0, w1=w1)
    finals = []
    for s in range(20):
        rng = random.Random(13000 + s); ptr = []; busy = -1
        for tr in trades:
            p = tr["entry_i"] - 1 + rng.choice([-1, 1]) * rng.randint(30, 250)
            if p <= busy or not (30 <= p < len(bars) - 2): continue
            nt = build(bars, fast, slow, p, max(0, p - 10))
            if nt: ptr.append(nt); busy = nt["exit_i"]
        pf, _, _, _, _ = simulate(bars, ptr, COST, FEE, w0=w0, w1=w1)
        finals.append(pf)
    rets = [x["ret"] for x in done]
    exp = round(sum(rets) / len(rets), 4) if rets else None
    r = dict(final=f, max_dd=dd, n_trades=len(done),
             win_rate=round(sum(1 for x in done if x["ret"] > 0) / len(done), 3) if done else None,
             expectancy_per_trade=exp,
             cost_drag_est=round(len(done) * 0.002 * 100, 2),
             bh_bar=bh(bars, w0, w1, COST, FEE),
             placebo_finals=finals, placebo_beaten=sum(1 for x in finals if f > x),
             placebo_median=sorted(finals)[10] if finals else None,
             monthly=monthly_stats(curve), trades=done, curve=curve)
    out["roads"][rn] = r
    print(rn, "final", f, "dd", dd, "ntr", r["n_trades"], "wr", r["win_rate"],
          "exp", exp, "BH", r["bh_bar"], "placebo_beaten", r["placebo_beaten"], "/", len(finals))
json.dump(out, open(os.path.join(HERE, "results.json"), "w"), indent=1)
print("total trades generated:", len(trades))
