#!/usr/bin/env python3
"""V13 BEST RULES — Basket-ROA-Gate. Spec: BEST-RULES-SPEC.md (frozen).

ROA demoted from binary gate to CO-EQUAL RANK: monthly, honest Nov-2016
top-30 pond, 200d eligibility, score = 0.5*pct-rank(ROA PIT) +
0.5*pct-rank(12-1 momentum), top 5 equal weight, NO floor.
Costs 0.10%/side + $0.01/sell. Prices: read-only v4 honest cache.
ROA: SEC EDGAR companyfacts from the read-only v4 data cache, instrument
verbatim from v4/basket-roa-gate.py (NI/Assets, same accession, annual
periods, most recently FILED strictly before signal day; XOM CIK 34088).
Modes: blend (my rules), host (ungated pure-momentum control, same
engine), placebo (random 5 of the same blend-eligible pool)."""
import importlib.util, json, os, random

HERE = os.path.dirname(os.path.abspath(__file__))
V4 = os.path.expanduser("~/workspace/stock-app/backtests/v4")
CACHE = os.path.join(V4, "momentum-basket-honest-data")
UNIVERSE = ["AAPL","MSFT","AMZN","GOOGL","META","BRK-B","JPM","XOM","JNJ","PG","V","WMT","HD","BAC","CVX","PFE","VZ","T","DIS","NFLX","INTC","CSCO","GE","IBM","MMM","UNH","MA","KO","PEP","WFC"]
BENCH = "SPY"; COST = 0.001; FEE = 0.01; N = 5
ROADS = {"DECADE": ("2016-11-21","2026-11-20"), "CONT": ("2019-01-01","2026-11-20"), "VAL": ("2023-01-01","2026-11-20")}
CIK_OVERRIDES = {"XOM": 34088}
NI_CONCEPTS = ["NetIncomeLoss", "ProfitLoss"]

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

qm = _load("qm_v4", os.path.join(V4, "quality-momentum.py"))

def build_roa_observations(facts):
    """Verbatim from v4/basket-roa-gate.py."""
    assets_by_accn = {}
    for e in qm._entries(facts, "Assets"):
        if "val" not in e or "end" not in e: continue
        accn = e.get("accn", "")
        assets_by_accn.setdefault(accn, {})[e["end"]] = (float(e["val"]), e.get("filed", ""))
    def assets_for(accn, period_end):
        m = assets_by_accn.get(accn, {})
        if period_end in m: return m[period_end]
        earlier = [en for en in m if en <= period_end]
        return m[max(earlier)] if earlier else None
    ni = {}
    for concept in NI_CONCEPTS:
        for e in qm._annual(qm._entries(facts, concept)):
            accn = e.get("accn", ""); key = (e["start"], e["end"])
            slot = ni.setdefault(accn, {})
            if key not in slot: slot[key] = (float(e["val"]), e.get("filed", ""))
    obs = []
    for accn, periods in ni.items():
        for (start, end), (nval, nfiled) in periods.items():
            a = assets_for(accn, end)
            if a is None or a[0] <= 0: continue
            obs.append((max(nfiled, a[1]), end, nval / a[0], "ROA"))
    obs.sort(); return obs

def load_roa():
    ciks = qm.get_ciks()
    for t, cik in CIK_OVERRIDES.items(): ciks[t] = cik
    out = {}
    for t in UNIVERSE:
        out[t] = build_roa_observations(qm.get_companyfacts(ciks[t]))
    return out

def roa_at(obs, asof):
    return qm.quality_at(obs, asof)  # (filed, end, val, method) or None

def load(t):
    with open(os.path.join(CACHE, f"{t}.json")) as f: return json.load(f)

class Mkt:
    def __init__(self):
        spy = load(BENCH); self.cal = [r["d"] for r in spy]
        self.bars = {}; self.closes = {}
        for t in UNIVERSE + [BENCH]:
            raw = spy if t == BENCH else load(t)
            self.bars[t] = {r["d"]: (r["o"], r["c"]) for r in raw}
            arr = []; last = None
            for d in self.cal:
                if d in self.bars[t]: last = self.bars[t][d][1]
                arr.append(last)
            self.closes[t] = arr
    def op(self, t, i):
        d = self.cal[i]; return self.bars[t][d][0] if d in self.bars[t] else None
    def cp(self, t, i): return self.closes[t][i]
    def sma(self, t, i, n):
        if i + 1 < n: return None
        seg = self.closes[t][i-n+1:i+1]
        return None if any(v is None for v in seg) else sum(seg)/n
    def mom(self, t, i):
        if i - 252 < 0: return None
        a, b = self.closes[t][i-252], self.closes[t][i-21]
        return None if (a is None or b is None or a <= 0) else b/a - 1.0

def pct_ranks(vals):
    items = sorted(vals.items(), key=lambda kv: kv[1]); n = len(items)
    if n == 1: return {items[0][0]: 0.5}
    return {t: i/(n-1) for i, (t, _) in enumerate(items)}

def simulate(mkt, roa_obs, sd, ed, mode, seed=42, pot0=100.0):
    rng = random.Random(seed)
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= sd)
    i1 = max(i for i, d in enumerate(mkt.cal) if d <= ed)
    cash = float(pot0); pos = {}; curve = []; orders = 0; costs = 0.0; cur = None
    def eq(i, use_open):
        tot = cash
        for t, sh in pos.items():
            px = mkt.op(t, i) if use_open else mkt.cp(t, i)
            if px is None: px = mkt.cp(t, i)
            tot += sh * px
        return tot
    for i in range(i0, i1+1):
        d = mkt.cal[i]; mk = d[:7]
        if mk != cur and i > 0:
            cur = mk; j = i - 1; sd_str = mkt.cal[j]
            base = []  # 200d + momentum eligible
            for t in UNIVERSE:
                s = mkt.sma(t, j, 200); c = mkt.cp(t, j)
                if s is None or c is None or c <= s: continue
                m = mkt.mom(t, j)
                if m is not None: base.append((t, m))
            if mode == "host":
                base.sort(key=lambda x: -x[1]); picks = [t for t, _ in base[:N]]
            else:
                scored = {}
                for t, m in base:
                    q = roa_at(roa_obs.get(t, []), sd_str)
                    if q is not None: scored[t] = (q[2], m)
                if mode == "blend":
                    if len(scored) >= 1:
                        rr = pct_ranks({t: v[0] for t, v in scored.items()})
                        mr = pct_ranks({t: v[1] for t, v in scored.items()})
                        picks = sorted(scored, key=lambda t: -(0.5*rr[t] + 0.5*mr[t]))[:N]
                    else: picks = []
                else:  # placebo
                    names = sorted(scored)
                    picks = rng.sample(names, min(N, len(names))) if names else []
            # host chassis convention: fixed 20% of equity per pick (verified:
            # host control reproduces published ungated $439.45/$208.27 to the cent)
            eqo = eq(i, True); tgt = {t: 0.20*eqo for t in picks} if picks else {}
            for t in list(pos):
                px = mkt.op(t, i)
                if px is None: continue
                cv = pos[t]*px; want = tgt.get(t, 0.0)
                if cv > want + 0.01:
                    sv = cv - want; fee = sv*COST + FEE; cash += sv - fee; costs += fee; orders += 1
                    pos[t] -= sv/px
                    if want <= 0 or pos[t]*px < 0.01: del pos[t]
            for t in picks:
                px = mkt.op(t, i)
                if px is None: continue
                deficit = tgt[t] - pos.get(t, 0.0)*px
                if deficit <= 0.01: continue
                bv = min(deficit, cash/(1+COST))
                if bv <= 0.01: continue
                fee = bv*COST; cash -= bv + fee; costs += fee; orders += 1
                pos[t] = pos.get(t, 0.0) + bv/px
        curve.append((d, eq(i, False)))
    peak = -1; mdd = 0.0
    for _, e in curve:
        peak = max(peak, e); mdd = min(mdd, e/peak - 1.0 if peak > 0 else 0.0)
    return {"final": round(curve[-1][1], 2), "max_dd_pct": round(mdd*100, 2),
            "orders": orders, "costs": round(costs, 2), "equity_curve": curve}

def spy_net(mkt, sd, ed, pot0=100.0):
    i0 = next(i for i, d in enumerate(mkt.cal) if d >= sd); i1 = max(i for i, d in enumerate(mkt.cal) if d <= ed)
    sh = (pot0*(1-COST))/mkt.op(BENCH, i0)
    return round(sh*mkt.cp(BENCH, i1)*(1-COST) - FEE, 2)

def dist(curve):
    me = {}
    for d, e in curve: me[d[:7]] = e
    ks = sorted(me); rets = [me[b]/me[a]-1 for a, b in zip(ks, ks[1:])]
    if not rets: return {}
    s = sorted(rets); n = len(s)
    med = s[n//2] if n % 2 else (s[n//2-1]+s[n//2])/2
    streak = cur_s = 0
    for r in rets:
        cur_s = cur_s + 1 if r <= 0 else 0; streak = max(streak, cur_s)
    peak = -1; since = longest = 0
    for _, e in curve:
        if e >= peak: peak = e; since = 0
        else: since += 1
        longest = max(longest, since)
    return {"periods": n, "median_pct": round(med*100, 2),
            "pct_positive": round(100*sum(1 for r in rets if r > 0)/n, 1),
            "best_pct": round(max(rets)*100, 2), "worst_pct": round(min(rets)*100, 2),
            "longest_losing_streak_mo": streak, "longest_days_between_highs": longest,
            "avg_pct_secondary": round(sum(rets)/n*100, 2),
            "monthly_rets": [round(r*100, 2) for r in rets]}

CHAMP = {"CONT": 544.47, "VAL": 288.05, "DECADE": 667.35}

def main():
    roa_obs = load_roa()
    print("ROA obs per name:", {t: len(roa_obs[t]) for t in UNIVERSE}, flush=True)
    mkt = Mkt()
    out = {"family": "basket-roa-gate", "program": "v13-best-rules",
           "spec": "monthly top5, score=0.5*pctrank(ROA PIT)+0.5*pctrank(12-1 mom), 200d filter, no floor",
           "roads": {}, "placebos": {}}
    blend = {}
    for road, (sd, ed) in ROADS.items():
        r = simulate(mkt, roa_obs, sd, ed, "blend"); blend[road] = r
        h = simulate(mkt, roa_obs, sd, ed, "host")
        out["roads"][road] = {"blend_final": r["final"], "blend_max_dd_pct": r["max_dd_pct"],
                              "blend_orders": r["orders"], "blend_costs": r["costs"],
                              "host_control_final": h["final"], "host_control_max_dd_pct": h["max_dd_pct"],
                              "spy_net_price_only": spy_net(mkt, sd, ed),
                              "equity_curve": r["equity_curve"]}
        print(road, "blend", r["final"], r["max_dd_pct"], "| host", h["final"], h["max_dd_pct"], flush=True)
        finals = []
        for seed in range(1, 21):
            p = simulate(mkt, roa_obs, sd, ed, "placebo", seed=seed); finals.append(p["final"])
        beaten = sum(1 for v in finals if r["final"] > v); sf = sorted(finals)
        out["placebos"][road] = {"finals": finals, "median": sf[10], "best": sf[-1], "worst": sf[0],
                                 "blend_beats_n_of_20": beaten}
        print(road, "placebo median", sf[10], "beats", beaten, "/20", flush=True)
    out["distribution_decade_monthly"] = dist(blend["DECADE"]["equity_curve"])
    # Confirmation only if a champion is beaten on any road
    beaten_roads = [r for r in ROADS if blend[r]["final"] > CHAMP[r]]
    out["champion_beaten_roads"] = beaten_roads
    if beaten_roads:
        folds = {}
        for y in range(2017, 2027):
            sd = f"{y}-01-01"; ed = "2026-11-20" if y == 2026 else f"{y}-12-31"
            a = simulate(mkt, roa_obs, sd, ed, "blend"); b = simulate(mkt, roa_obs, sd, ed, "host")
            folds[str(y)] = {"blend": a["final"], "host": b["final"], "win_vs_host": a["final"] > b["final"]}
        halves = {}
        for nm, (sd, ed) in {"H1": ("2016-11-21","2021-12-31"), "H2": ("2022-01-01","2026-11-20")}.items():
            a = simulate(mkt, roa_obs, sd, ed, "blend"); b = simulate(mkt, roa_obs, sd, ed, "host")
            halves[nm] = {"blend": a["final"], "host": b["final"], "win_vs_host": a["final"] > b["final"]}
        out["confirmation"] = {"folds_vs_host": folds,
                               "fold_wins_vs_host": sum(1 for v in folds.values() if v["win_vs_host"]),
                               "halves_vs_host": halves}
        print("CONFIRMATION run:", out["confirmation"], flush=True)
    with open(os.path.join(HERE, "results.json"), "w") as f: json.dump(out, f, indent=1)
    print("saved results.json")

if __name__ == "__main__": main()
