#!/usr/bin/env python3
"""Block runner for the crypto-baskets holdings sweep.

NOTE (environment): in this session Python file writes are blocked
(EPERM) while stdout to the exec capture works. Each block therefore
PRINTS one JSON chunk between @@BLOCK@@ / @@END@@ markers; the parent
assembles results.json from the captured chunks. All computation is
identical to run_sweep.py (same engines, same integrity asserts).
Usage: python3 run_blocks.py <block>
Blocks: A-grid-<stag> A-plc-<stag> B-grid-<cad> B-plc-<cad> C-grid C-plc
        keystats:<family>:<cell-spec>...  (period stats + monthly curve)
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_sweep as S
from sweep_common import period_stats

CB, PIT, DOM = S.CB, S.PIT, S.DOM
WINDOWS, COUNTS, SEEDS = S.WINDOWS, S.COUNTS, S.SEEDS
nkey = S.nkey

def emit(name, obj):
    sys.stdout.write("@@BLOCK " + name + "@@\n")
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.write("@@END@@\n")
    sys.stdout.flush()

def summA(r):
    return S.cb_summ(r, keep_curve=False)

def summPIT(rr):
    return {k: v for k, v in rr.items() if k not in ("curve", "picks_log")}

def summDOM(rr):
    return {k: v for k, v in rr.items() if k not in ("curve", "states_log")}

# ---------------- A ----------------
def loadA():
    with open(os.path.join(CB.V4DATA, "snapshots.json")) as f:
        snaps = json.load(f)
    sbd = []
    for month in sorted(snaps):
        info = snaps[month]; sd = info["snapshot_date"]
        sd = f"{sd[:4]}-{sd[4:6]}-{sd[6:8]}"
        ids = [c["cmc_id"] for c in info["top20"]]
        rk = {c["cmc_id"]: c["rank"] for c in info["top20"]}
        sbd.append((sd, ids, rk))
    sbd.sort()
    reg = CB.build_registry(snaps)
    return sbd, CB.Market(reg)

SORTS = {"mom7d": ("momentum", 7), "mom14d": ("momentum", 14),
         "mom21d": ("momentum", 21), "mom28d": ("momentum", 28),
         "size-truncated": ("size", None)}

def block_A_grid(stag):
    sbd, mkt = loadA()
    r = S.cb_simulate(mkt, sbd, *WINDOWS["full"], "momentum", horizon=21, n_hold="QUINTILE")
    assert abs(r.final - 2677.25) < 0.02, r.final
    sk, h = SORTS[stag]
    out = {"runs": {}, "quintile_native": {}, "btc_hold": {}}
    for w, (sd, ed) in WINDOWS.items():
        b, bdd = CB.btc_hold(mkt, sd, ed)
        out["btc_hold"][w] = {"final": round(b, 2), "max_dd_pct": round(bdd * 100, 2)}
    for cad in ("weekly", "monthly"):
        for ruleset in ("native", "v9"):
            for w, (sd, ed) in WINDOWS.items():
                rq = S.cb_simulate(mkt, sbd, sd, ed, sk, horizon=h, cadence=cad,
                                   ruleset=ruleset, n_hold="QUINTILE")
                out["quintile_native"][f"{stag}|{cad}|{ruleset}|{w}"] = summA(rq)
                for n in COUNTS:
                    rr = S.cb_simulate(mkt, sbd, sd, ed, sk, horizon=h, cadence=cad,
                                       ruleset=ruleset, n_hold=n)
                    out["runs"][f"{stag}|{cad}|{ruleset}|{w}|n={nkey(n)}"] = summA(rr)
    emit(f"A-grid-{stag}", out)

def block_A_plc(stag):
    sbd, mkt = loadA()
    sk, h = SORTS[stag]
    out = {"placebos": {}}
    # ranked finals needed for placebo block: recompute ranked weekly native
    ranked = {}
    for w in ("full", "validation"):
        sd, ed = WINDOWS[w]
        for n in COUNTS:
            rr = S.cb_simulate(mkt, sbd, sd, ed, sk, horizon=h, cadence="weekly",
                               ruleset="native", n_hold=n)
            ranked[(w, n)] = rr.final
    for w in ("full", "validation"):
        sd, ed = WINDOWS[w]
        for n in COUNTS:
            finals = []
            for seed in SEEDS:
                rr = S.cb_simulate(mkt, sbd, sd, ed, sk, horizon=h, cadence="weekly",
                                   ruleset="native", mode="placebo", seed=seed, n_hold=n)
                finals.append(rr.final)
            out["placebos"][f"{stag}|weekly|native|{w}|n={nkey(n)}"] = \
                S.placebo_block(ranked[(w, n)], finals)
    emit(f"A-plc-{stag}", out)

# ---------------- B ----------------
def loadB():
    reg = PIT.load_registry(); weekly = PIT.load_weekly()
    return PIT.Market(reg, weekly)

def block_B_grid(cad):
    mkt = loadB()
    rb = S.pit_simulate(mkt, *WINDOWS["full"], "monthly", "nofloor", S.PIT_COST, n_hold=5)
    assert abs(rb["final"] - 1235.94) < 0.02, rb["final"]
    out = {"runs": {}, "btc_hold": {}}
    out["btc_hold"] = {w: {k: PIT.btc_hold(mkt, sd, ed, 0.006)[k]
                           for k in ("final", "max_dd_pct")}
                       for w, (sd, ed) in WINDOWS.items()}
    for ruleset in ("nofloor", "v9"):
        rs = "native" if ruleset == "nofloor" else "v9"
        for w, (sd, ed) in WINDOWS.items():
            for n in COUNTS:
                rr = S.pit_simulate(mkt, sd, ed, cad, ruleset, S.PIT_COST, n_hold=n)
                out["runs"][f"{cad}|{rs}|{w}|n={nkey(n)}"] = summPIT(rr)
    emit(f"B-grid-{cad}", out)

def block_B_plc(cad):
    mkt = loadB()
    out = {"placebos": {}}
    ranked = {}
    for w in ("full", "validation"):
        sd, ed = WINDOWS[w]
        for n in COUNTS:
            rr = S.pit_simulate(mkt, sd, ed, cad, "nofloor", S.PIT_COST, n_hold=n)
            ranked[(w, n)] = rr["final"]
    for w in ("full", "validation"):
        sd, ed = WINDOWS[w]
        for n in COUNTS:
            finals = []
            for seed in SEEDS:
                rr = S.pit_simulate(mkt, sd, ed, cad, "nofloor", S.PIT_COST,
                                    mode="placebo", seed=seed, n_hold=n)
                finals.append(rr["final"])
            out["placebos"][f"{cad}|native|{w}|n={nkey(n)}"] = \
                S.placebo_block(ranked[(w, n)], finals)
    emit(f"B-plc-{cad}", out)

# ---------------- C ----------------
def loadC():
    reg = DOM.load_registry()
    with open(os.path.join(S.HERE, "..", "crypto-basket-pit", "data",
                           "weekly_snapshots.json")) as f:
        weekly = json.load(f)
    dk, dom = DOM.load_dominance()
    return DOM.Market(reg, weekly), dk, dom

def block_C_grid():
    mkt, dk, dom = loadC()
    rc = S.dom_simulate(mkt, dk, dom, *WINDOWS["full"], n_cap="ALL")
    assert abs(rc["final"] - 1306.49) < 0.02, rc["final"]
    out = {"runs": {}, "btc_hold": {}, "ew_hold": {},
           "avg_full_alt_basket_size": rc["avg_full_alt_basket"]}
    for w, (sd, ed) in WINDOWS.items():
        bh = DOM.btc_hold(mkt, sd, ed)
        out["btc_hold"][w] = {k: bh[k] for k in ("final", "max_dd_pct")}
        ew = DOM.simulate(mkt, dk, dom, sd, ed, mode="ew")
        out["ew_hold"][w] = {k: ew[k] for k in ("final", "max_dd_pct")}
    for ruleset, rs in (("nofloor", "native"), ("v9", "v9")):
        for w, (sd, ed) in WINDOWS.items():
            for n in COUNTS:
                rr = S.dom_simulate(mkt, dk, dom, sd, ed, ruleset=ruleset, n_cap=n)
                out["runs"][f"{rs}|{w}|n={nkey(n)}"] = summDOM(rr)
    emit("C-grid", out)

def block_C_plc():
    mkt, dk, dom = loadC()
    out = {"placebos": {}}
    for w in ("full", "validation"):
        sd, ed = WINDOWS[w]
        base = S.dom_simulate(mkt, dk, dom, sd, ed, n_cap="ALL")
        log = base["states_log"]
        freq = {s: sum(1 for x in log if x["state"] == s) / len(log)
                for s in ("BTC", "LARGE", "ALT")}
        for n in COUNTS:
            rk = S.dom_simulate(mkt, dk, dom, sd, ed, n_cap=n)["final"]
            finals = []
            for seed in SEEDS:
                rr = S.dom_simulate(mkt, dk, dom, sd, ed, mode="placebo",
                                    seed=seed, state_freq=freq, n_cap=n)
                finals.append(rr["final"])
            blk = S.placebo_block(rk, finals)
            blk["state_freq"] = {k: round(v, 3) for k, v in freq.items()}
            out["placebos"][f"native|{w}|n={nkey(n)}"] = blk
    emit("C-plc", out)

# ---------------- keystats ----------------
def monthly_curve(curve):
    months = {}
    for d, e in curve:
        months[d[:7]] = [d, e]
    return [months[k] for k in sorted(months)]

def block_keystats(specs):
    """specs: comma list of
       A:<stag>:<cad>:<ruleset>:<window>:<n|QUINTILE>
       B:<cad>:<ruleset(native|v9)>:<window>:<n>
       C:<ruleset(native|v9)>:<window>:<n>  """
    out = {}
    needA = any(s.startswith("A:") for s in specs)
    needB = any(s.startswith("B:") for s in specs)
    needC = any(s.startswith("C:") for s in specs)
    if needA: sbdA, mktA = loadA()
    if needB: mktB = loadB()
    if needC: mktC, dkC, domC = loadC()
    for spec in specs:
        p = spec.split(":")
        if p[0] == "A":
            _, stag, cad, ruleset, w, n = p
            sk, h = SORTS[stag]
            sd, ed = WINDOWS[w]
            nh = "QUINTILE" if n == "QUINTILE" else ("ALL" if n == "ALL" else int(n))
            r = S.cb_simulate(mktA, sbdA, sd, ed, sk, horizon=h, cadence=cad,
                              ruleset=ruleset, n_hold=nh)
            curve = [[d, round(e, 4)] for d, e in r.curve]
            out[spec] = {"final": round(r.final, 2),
                         "period_stats_monthly": period_stats(curve),
                         "monthly_curve": monthly_curve(curve)}
        elif p[0] == "B":
            _, cad, rs, w, n = p
            sd, ed = WINDOWS[w]
            nh = "ALL" if n == "ALL" else int(n)
            rr = S.pit_simulate(mktB, sd, ed, cad, "nofloor" if rs == "native" else "v9",
                                S.PIT_COST, n_hold=nh)
            out[spec] = {"final": rr["final"],
                         "period_stats_monthly": period_stats(rr["curve"]),
                         "monthly_curve": monthly_curve(rr["curve"])}
        elif p[0] == "C":
            _, rs, w, n = p
            sd, ed = WINDOWS[w]
            nh = "ALL" if n == "ALL" else int(n)
            rr = S.dom_simulate(mktC, dkC, domC, sd, ed,
                                ruleset="nofloor" if rs == "native" else "v9", n_cap=nh)
            out[spec] = {"final": rr["final"],
                         "period_stats_monthly": period_stats(rr["curve"]),
                         "monthly_curve": monthly_curve(rr["curve"])}
    emit("keystats", out)

if __name__ == "__main__":
    blk = sys.argv[1]
    if blk.startswith("A-grid-"): block_A_grid(blk[7:])
    elif blk.startswith("A-plc-"): block_A_plc(blk[6:])
    elif blk.startswith("B-grid-"): block_B_grid(blk[7:])
    elif blk.startswith("B-plc-"): block_B_plc(blk[6:])
    elif blk == "C-grid": block_C_grid()
    elif blk == "C-plc": block_C_plc()
    elif blk.startswith("keystats:"): block_keystats(blk[9:].split(","))
    else: raise SystemExit(f"unknown block {blk}")
