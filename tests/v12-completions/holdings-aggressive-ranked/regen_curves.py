#!/usr/bin/env python3
"""Regenerate DECADE equity curves for winner + native counts only
(the curves.pkl sidecar was clobbered by a failed-load chunk save;
single real runs, no placebos — cheap). Winners are by summed finals
across each family's roads, computed from results.json here so the
choice is mechanical. Output: dist_curves.pkl (tmp + atomic rename).
Simulation only."""
import importlib.util, json, os, pickle, sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
V12 = os.path.join(BT, "v12-completions")
sys.path.insert(0, HERE)
import run_sweep as R

res = json.load(open(os.path.join(HERE, "results.json")))

def winner(fam, prefix):
    totals = {}
    for k, c in res["families"][fam]["cells"].items():
        if k.startswith(prefix + "|") and str(c["count"]) in ("1", "2", "3", "5", "8", "10"):
            totals[str(c["count"])] = totals.get(str(c["count"]), 0) + c["final"]
    return max(totals, key=totals.get), {k: round(v, 2) for k, v in totals.items()}

curves = {}
jobs = []  # (curve_key, family, prefix, native)

# ---- v0 (both protections, DECADE) ----
data0 = R.v0_load()
for prot in ("era", "house"):
    w, tot = winner("v0-aggressive", prot)
    print("v0", prot, "totals", tot, "winner", w, flush=True)
    for n in {int(w), 2}:
        r = R.v0_run(data0, "2016-11-21", "2026-11-20", n, prot)
        curves[f"v0-aggressive|{prot}|DECADE|{n}"] = r["curve"]
        assert abs(r["final"] - res["families"]["v0-aggressive"]["cells"]
                   [f"{prot}|DECADE|{n}"]["final"]) < 0.005, (prot, n, r["final"])

# ---- v2 (original + house chassis, DECADE) ----
m2 = R.load_module("aggv2_engine2", os.path.join(BT, "v2", "aggressive-v2.py"))
D2 = m2.load_data()
class SimN(m2.Sim):
    def __init__(self, D, cal, count, **kw):
        super().__init__(D, cal, **kw); self.count = count
    def risk_fraction(self):
        dd = (self.peak - self.prev_equity) / self.peak if self.peak > 0 else 0.0
        if dd >= 0.10: return 0.0025, 1
        if dd >= 0.05: return 0.005, self.count
        return m2.BASE_RISK, self.count
sys.path.insert(0, os.path.join(BT, "v10-retest", "aggressive-v2"))
import sweep_aggressive_v2 as sw2
class CadN(sw2.CadenceSim):
    def __init__(self, D, cal, cad, count, **kw):
        super().__init__(D, cal, cad, **kw); self.count = count
    def risk_fraction(self):
        dd = (self.peak - self.prev_equity) / self.peak if self.peak > 0 else 0.0
        if dd >= 0.10: return 0.0025, 1
        if dd >= 0.05: return 0.005, self.count
        return sw2.BASE_RISK, self.count
cal2 = m2.calendar(D2, "2016-11-21", "2026-11-20")
cad2 = sw2.cadence_dates(cal2, "daily")
for prot in ("original", "house"):
    w, tot = winner("aggressive-v2", prot)
    print("v2", prot, "totals", tot, "winner", w, flush=True)
    for n in {int(w), 2}:
        if prot == "original":
            sim = SimN(D2, cal2, n, mode="v2").run()
            curves[f"aggressive-v2|original|DECADE|{n}"] = [
                [d, round(e, 4)] for d, e in sim.equity_curve]
            fin = sim.stats()["final_balance"]
        else:
            sim = CadN(D2, cal2, cad2, n).run()
            curves[f"aggressive-v2|house|DECADE|{n}"] = [
                [d, round(e, 4)] for d, e in sim.equity_curve]
            fin = sim.stats()["final"]
        assert abs(fin - res["families"]["aggressive-v2"]["cells"]
                   [f"{prot}|DECADE|{n}"]["final"]) < 0.005, (prot, n, fin)

# ---- v3 (house + original, base + combo, DECADE on v3 cache) ----
sys.path.insert(0, os.path.join(BT, "v10-retest", "aggressive-v3"))
import sweep_aggressive_v3 as sw3
m3 = sw3.m
BASE = dict(m3.BASE_CFG)
COMBO = dict(m3.BASE_CFG); COMBO.update({"atr_mult": 1.0, "base_risk": 0.02})
m3.DATA = os.path.join(BT, "v3", "data")
D3 = m3.load_data()
cal3 = m3.calendar(D3, "2016-11-21", "2026-11-20")
cad3 = sw3.cadence_dates(cal3, "daily")
for prot in ("house", "original"):
    for cname, cfg0 in (("base", BASE), ("combo", COMBO)):
        prefix = f"{prot}|{cname}"
        w, tot = winner("aggressive-v3", prefix)
        print("v3", prefix, "totals", tot, "winner", w, flush=True)
        for n in {int(w), 2}:
            cfg = dict(cfg0); cfg["max_positions"] = n
            if prot == "house":
                sim = sw3.CadenceSim(D3, cal3, cfg, cad3).run()
                fin = sim.stats()["final"]
            else:
                sim = m3.Sim(D3, cal3, cfg).run()
                fin = sim.stats()["final_balance"]
            curves[f"aggressive-v3|{prefix}|DECADE|{n}"] = [
                [d, round(e, 4)] for d, e in sim.equity_curve]
            assert abs(fin - res["families"]["aggressive-v3"]["cells"]
                       [f"{prefix}|DECADE|{n}"]["final"]) < 0.005, (prefix, n, fin)

# ---- H4 (winner = native = 5, DECADE) ----
hw = R.load_module("hw_v12b", os.path.join(V12, "high-winrate-lab",
                                           "high-winrate-lab-v12.py"))
E = hw.E
E.CACHE_DIR = os.path.join(BT, "v2", "tournament-data")
raw = {sym: E.load_symbol(sym) for sym in E.UNIVERSE}
mkt = E.Market(E.align_frames(raw))
cfg = {k: v for k, v in E.SHAPES["H4"].items() if k != "label"}
dates, positions = mkt.window(date(2016, 11, 21), date(2026, 11, 20))
kw = dict(cfg); kw["max_positions"] = 5
pf, _ = hw.run_shape_daily(mkt, "H4", dates, positions, 100.0, **kw)
st = hw.cell_stats(pf, dates[0], dates[-1])
assert abs(st["final"] - 171.12) < 0.005, st["final"]
curves["high-winrate-lab-H4|house|DECADE|5"] = st["equity_curve"]
print("H4 DECADE 5 curve ok", st["final"], flush=True)

import time
tmp = os.path.join(HERE, "dist_curves.pkl.tmp")
for attempt in range(30):
    try:
        with open(tmp, "wb") as f:
            pickle.dump(curves, f)
        os.replace(tmp, os.path.join(HERE, "dist_curves.pkl"))
        break
    except PermissionError:
        print("write EPERM, retry", attempt, flush=True)
        time.sleep(2)
print("saved dist_curves.pkl with", len(curves), "curves", flush=True)
