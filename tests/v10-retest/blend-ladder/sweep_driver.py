#!/usr/bin/env python3
"""v10 cadence sweep driver for blend-ladder: ladder cells + plain twins."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_sweep as RS

HERE = os.path.dirname(os.path.abspath(__file__))
START, END = "2016-11-21", "2026-11-20"

def cell_payload(cadence, r, plain):
    halts = r["halts"]
    return {
        "slug": "blend-ladder", "cadence": cadence,
        "window": [START, END], "start_cash": 100.0,
        "overlay": "Millennium sleeve ladder ON (halve -5% / bench -7.5% / "
                   "restore at 97.5% of bench peak; daily close checks) + "
                   "v9 plain -15% episode pot floor with 90-day restart",
        "final": round(r["final"], 2),
        "cagr_pct": round(r["cagr"] * 100, 2),
        "max_dd_pct": round(-r["maxdd"] * 100, 2),
        "costs": round(r["costs"], 2),
        "orders": r["orders"],
        "orders_note": r["orders_note"],
        "halts": halts,
        "restart": any(h.get("restart_date") for h in halts),
        "second_halt": len(halts) >= 2,
        "ladder_events": [{"date": d, "sleeve": s, "action": a,
                           "ladder_driven": True}
                          for d, s, a in r["events"]],
        "ladder_counts": r["counts"],
        "plain_twin": {
            "final": round(plain["final"], 2),
            "cagr_pct": round(plain["cagr"] * 100, 2),
            "max_dd_pct": round(-plain["maxdd"] * 100, 2),
            "costs": round(plain["costs"], 2),
            "orders": plain["orders"],
            "halts": plain["halts"],
            "note": "same cadence cell, same v9 pot floor, Millennium "
                    "ladder OFF — the control the ladder is judged against",
        },
        "ladder_delta_vs_plain": round(r["final"] - plain["final"], 2),
        "placebo_beaten": None,
        "placebo_note": "filled by run_placebos.py",
        "placebo_twins": [],
        "equity_curve": [[d, round(v, 4)] for d, v in r["curve"]],
        "plain_twin_equity_curve": [[d, round(v, 4)] for d, v in plain["curve"]],
    }

def main():
    os.makedirs(os.path.join(HERE, "cells"), exist_ok=True)
    for cad in RS.CADENCES:
        r = RS.run_pot_v10(START, END, 100.0, cad, True)
        p = RS.run_pot_v10(START, END, 100.0, cad, False)
        payload = cell_payload(cad, r, p)
        with open(os.path.join(HERE, "cells", cad + ".json"), "w") as f:
            json.dump(payload, f, indent=1)
        print(f"{cad}: ladder=${r['final']:.2f} plain=${p['final']:.2f} "
              f"maxDD={-r['maxdd']*100:.2f}% orders={r['orders']} "
              f"costs=${r['costs']:.2f} halts={len(r['halts'])} "
              f"ladder_events={len(r['events'])}", flush=True)

if __name__ == "__main__":
    main()
