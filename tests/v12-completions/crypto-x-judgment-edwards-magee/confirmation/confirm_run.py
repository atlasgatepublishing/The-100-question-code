import json, os, sys, statistics
# Confirmation re-run: frozen form copied VERBATIM from the family folder's run.py.
# Validation: the script first re-runs the FULL 2015-2026 window and checks it
# reproduces the primary run's BTC finals exactly before any sub-window counts.
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "workspace/stock-app/backtests/v12-completions", "crypto-x-judgment-edwards-magee"))
from engine import load_coins, run_position, btc_hold, max_dd, period_stats, shifted_placebo_beaten, COST

def pos_edwards_magee(rows):
    """JUDGMENT-CONSTRUCTED subset: resistance breakout (close above prior 60-day high after a >=10% base) long; exit on close below prior 60-day low channel or 8% stop handled by channel exit. Plus double-bottom: two equal lows within 3% separated by >=20 bars, buy break of intervening high."""
    cl=[r["c"] for r in rows]; n=len(cl); pos=[0]*n; state=0
    for i in range(60,n):
        hi=max(cl[i-60:i]); lo=min(cl[i-60:i])
        if state==0 and cl[i]>hi and (hi-lo)/lo>=0.10: state=1
        elif state==1 and cl[i]<lo: state=0
        pos[i]=state
    return pos
POS_FN = pos_edwards_magee
PRIMARY = {"native_final": 29621.23, "house_final": 34140.24, "btc_hold_final": 19356.25}

WINDOWS = [
    ("W1_2015-2018", "2015-01-01", "2018-12-31", True),
    ("W2_2019-2022", "2019-01-01", "2022-12-31", True),
    ("W3_2023-2026", "2023-01-01", "2026-11-22", True),
    ("W4_midcycle_2017H2-2021H1", "2017-07-01", "2021-06-30", False),
    ("W5_2020-2023", "2020-01-01", "2023-12-31", False),
]

def run_window(rows):
    pos = POS_FN(rows)
    dn, en = run_position(rows, pos, house=False)
    dh, eh = run_position(rows, pos, house=True)
    db, eb = btc_hold(rows)
    beaten, medp = shifted_placebo_beaten(rows, pos, en[-1])
    return {
        "bars": len(rows), "window": [rows[0]["d"], rows[-1]["d"]],
        "invested_days": int(sum(pos)),
        "native_final": round(en[-1], 2), "native_max_dd_pct": round(max_dd(en)*100, 1),
        "house_final": round(eh[-1], 2), "house_max_dd_pct": round(max_dd(eh)*100, 1),
        "btc_hold_final": round(eb[-1], 2),
        "native_beats_hold": bool(en[-1] > eb[-1]),
        "house_beats_hold": bool(eh[-1] > eb[-1]),
        "placebo_beaten_of_20": beaten, "placebo_median_final": medp,
        "monthly_periods_native": period_stats(dn, en),
    }

coins = load_coins()
cid, rows = coins["BTC"]
# --- replication check on the full primary window ---
full = run_window(rows)
rep = {k: (full[k] == PRIMARY[k]) for k in PRIMARY}
print("REPLICATION full-window vs primary:", full["native_final"], full["house_final"], full["btc_hold_final"], rep)
assert all(rep.values()), "Frozen form does NOT reproduce the primary run - STOP"

out = {"family": "crypto-x-judgment-edwards-magee", "label": "JUDGMENT-CONSTRUCTED", "cost_per_side": COST,
       "replication_check_full_window": {"got": {k: full[k] for k in PRIMARY}, "primary": PRIMARY, "match": rep},
       "windows": {}}
for name, s, e, indep in WINDOWS:
    sub = [r for r in rows if s <= r["d"] <= e]
    w = run_window(sub)
    w["independent_window"] = indep
    out["windows"][name] = w
    print(name, w["window"], "native", w["native_final"], "house", w["house_final"],
          "hold", w["btc_hold_final"], "beats", w["native_beats_hold"], "placebo", w["placebo_beaten_of_20"])
outdir = os.path.dirname(os.path.abspath(__file__))
json.dump(out, open(os.path.join(outdir, "confirmation_results.json"), "w"), indent=1)
print("WROTE", os.path.join(outdir, "confirmation_results.json"))
