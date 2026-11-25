#!/usr/bin/env python3
"""Final merge for the ranked-aggressive holdings sweep.
Recomputes the winner/native DECADE equity curves IN-PROCESS (same jobs
as regen_curves.py; every final asserted against results.json), computes
the daily per-period distributions from them, merges the v0 confirmation
(confirm_v0.json) and the per-family verdicts into results.json, and
writes results.json via tmp + retry + atomic rename. The dist_curves.pkl
sidecar is NOT loaded (pickle is never unpickled here). Simulation only."""
import json, os, sys, time
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BT = os.path.expanduser("~/workspace/stock-app/backtests")
V12 = os.path.join(BT, "v12-completions")
sys.path.insert(0, HERE)
import run_sweep as R

res = json.load(open(os.path.join(HERE, "results.json")))
confirm = json.load(open(os.path.join(HERE, "confirm_v0.json")))
res["families"]["v0-aggressive"]["confirmation_house"] = confirm

def winner(fam, prefix):
    totals = {}
    for k, c in res["families"][fam]["cells"].items():
        if k.startswith(prefix + "|") and str(c["count"]) in ("1", "2", "3", "5", "8", "10"):
            totals[str(c["count"])] = totals.get(str(c["count"]), 0) + c["final"]
    return max(totals, key=totals.get), {k: round(v, 2) for k, v in totals.items()}

curves = {}
# v0
data0 = R.v0_load()
for prot in ("era", "house"):
    w, tot = winner("v0-aggressive", prot)
    res["families"]["v0-aggressive"].setdefault("road_totals", {})[prot] = {
        "totals": tot, "winner_by_sum": w}
    for n in {int(w), 2}:
        r = R.v0_run(data0, "2016-11-21", "2026-11-20", n, prot)
        assert abs(r["final"] - res["families"]["v0-aggressive"]["cells"]
                   [f"{prot}|DECADE|{n}"]["final"]) < 0.005
        curves[f"v0-aggressive|{prot}|DECADE|{n}"] = r["curve"]
# v2
m2 = R.load_module("aggv2_engine3", os.path.join(BT, "v2", "aggressive-v2.py"))
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
    res["families"]["aggressive-v2"].setdefault("road_totals", {})[prot] = {
        "totals": tot, "winner_by_sum": w}
    for n in {int(w), 2}:
        if prot == "original":
            sim = SimN(D2, cal2, n, mode="v2").run(); fin = sim.stats()["final_balance"]
        else:
            sim = CadN(D2, cal2, cad2, n).run(); fin = sim.stats()["final"]
        assert abs(fin - res["families"]["aggressive-v2"]["cells"]
                   [f"{prot}|DECADE|{n}"]["final"]) < 0.005
        curves[f"aggressive-v2|{prot}|DECADE|{n}"] = [
            [d, round(e, 4)] for d, e in sim.equity_curve]
# v3
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
        res["families"]["aggressive-v3"].setdefault("road_totals", {})[prefix] = {
            "totals": tot, "winner_by_sum": w}
        for n in {int(w), 2}:
            cfg = dict(cfg0); cfg["max_positions"] = n
            if prot == "house":
                sim = sw3.CadenceSim(D3, cal3, cfg, cad3).run(); fin = sim.stats()["final"]
            else:
                sim = m3.Sim(D3, cal3, cfg).run(); fin = sim.stats()["final_balance"]
            assert abs(fin - res["families"]["aggressive-v3"]["cells"]
                       [f"{prefix}|DECADE|{n}"]["final"]) < 0.005
            curves[f"aggressive-v3|{prefix}|DECADE|{n}"] = [
                [d, round(e, 4)] for d, e in sim.equity_curve]
# H4
hw = R.load_module("hw_v12c", os.path.join(V12, "high-winrate-lab",
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
assert abs(st["final"] - 171.12) < 0.005
curves["high-winrate-lab-H4|house|DECADE|5"] = st["equity_curve"]
w, tot = winner("high-winrate-lab-H4", "house")
res["families"]["high-winrate-lab-H4"].setdefault("road_totals", {})["house"] = {
    "totals": tot, "winner_by_sum": w}

res["period_distributions_DECADE"] = {
    k: R.period_distribution(v) for k, v in curves.items()}
res["curves_DECADE_winner_and_native"] = curves
res["verdicts"] = {
    "v0-aggressive": {
        "era_form": "COUNT DOESN'T MATTER — the ladder floor kills nearly every "
                    "count on nearly every road at ~$84-100; VAL count 1 ($124.40) "
                    "is a single-road ladder accident (one name rode to the $125 "
                    "floor step), not a count effect",
        "house_form": "MORE IS BETTER — counts 3, 5, 8, 10 (and ALL, = 10) beat "
                      "native 2 on all four roads and ALL FOUR CONFIRMED on "
                      "different years (folds 8/10, 6/10, 7/10, 7/10; both "
                      "half-windows won) = VARIANT-CANDIDATEs of the house form. "
                      "FENCE: every variant still LOSES money on every long road "
                      "(best house final anywhere $95.00) and beats 10/20 "
                      "placebos at best — wider counts lose less because the "
                      "1/N sizing bleeds less through v9's two halts",
        "family": "COUNT DOESN'T MATTER (era, its frozen form) / MORE IS BETTER "
                  "(house form, confirmed but still dead)"},
    "aggressive-v2": {
        "family": "COUNT DOESN'T MATTER — both protection forms produce "
                  "IDENTICAL grids (no halt at any count on any road, ladder "
                  "never engaged); finals span only $88.41-$104.93 across all "
                  "counts and roads; no count beats native 2 on all roads; "
                  "native 2 is within ~1% of the best DECADE cell"},
    "aggressive-v3": {
        "family": "COUNT DOESN'T MATTER — in most cells the cap stops binding "
                  "at 3 (1 entry/day + fast exits rarely hold more), so counts "
                  "5/8/10/ALL are literally identical; no count beats native 2 "
                  "on all roads in either config under house rules; the one big "
                  "gap (COMBO house CONT: count 3 $93.52 vs count 5 $71.99) is "
                  "a v9 halt-path accident, and the original-protection form "
                  "shows no such gap ($84.57 vs $84.97)"},
    "high-winrate-lab": {
        "H1_H2_H3": "NOT-APPLICABLE — no cross-sectional ranking (qualifiers "
                    "fill free slots in fixed universe order); caps are "
                    "concurrency risk limits, not ranked top-N selections",
        "H4": "NATIVE COUNT BEST — count 5 wins all three roads ($171.12 "
              "DECADE 20/20 placebos, $170.11 CONT 20/20, $121.93 VAL 15/20); "
              "win rate stays ~59-62% at every count — the count changes the "
              "money, not the win-rate costume"}}
tmp = os.path.join(HERE, "results.json.tmp")
for attempt in range(30):
    try:
        with open(tmp, "w") as f:
            json.dump(res, f, indent=1)
        os.replace(tmp, os.path.join(HERE, "results.json"))
        break
    except PermissionError:
        print("write EPERM, retry", attempt, flush=True)
        time.sleep(2)
print("merged results.json; distributions for", len(curves), "curves", flush=True)
for k, v in res["period_distributions_DECADE"].items():
    print(k, v, flush=True)
