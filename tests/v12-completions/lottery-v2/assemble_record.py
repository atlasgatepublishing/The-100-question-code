#!/usr/bin/env python3
"""lottery-v2 v12 — carry-forward record assembly.

NO new backtest is run here. This script reads the prior program record
(read-only) and emits this folder's results.json: the family's complete
existing record, each number tagged with its source.

Why no run: lottery-v2's frozen house spec IS its only form (house design,
no published form — see CONSTRUCTION-SPEC.md), and the only run v12 could
add, the OTC-habitat run, is blocked by the missing free PIT OTC archive
(see HUNT-LOG.md).
"""
import json, pathlib

ROOT = pathlib.Path.home() / "workspace/stock-app/backtests"
v10 = json.loads((ROOT / "v10-retest/lottery-v2/results.json").read_text())

cells = {}
for cad, c in v10["cells"].items():
    cells[cad] = {
        "final": c["final"], "cagr_pct": c["cagr_pct"], "max_dd_pct": c["max_dd_pct"],
        "costs_total": c["costs"], "costs_spread": c["costs_spread"], "costs_fees": c["costs_fees"],
        "orders": c["orders"], "halts": c["halts"], "placebos_beaten_of_20": c["placebo_beaten"],
    }

record = {
    "family": "lottery-v2",
    "program": "v12-completions",
    "form": "HOUSE DESIGN — Terry's own second-generation penny lottery pot. No published form exists; nothing constructed in v12. The frozen v2 house spec is its only form (CONSTRUCTION-SPEC.md).",
    "v12_run_made": False,
    "v12_run_blocker": "OTC-habitat run blocked: no free point-in-time daily price/volume archive for the full OTCBB/Pink universe including zeroed/delisted names exists. Authoritative archive is OTC Markets Group historical files (paid, $500-$1,000/mo per file type + $1,500 connectivity). See HUNT-LOG.md.",
    "record": {
        "v0_original": {
            "source": "backtests/v2/lottery-v2.md (v0 vs v2 comparison table)",
            "window": "2025-11-21 -> 2026-11-20", "start": 100.0,
            "final": 84.04, "return_pct": -15.96, "ended": "2026-03-13 (floor)",
            "round_trips": 32, "win_rate_pct": 34.4, "total_costs": 23.36,
            "max_dd_pct": -24.37, "gap_through_stops": 3, "zero_cost_twin": 122.82,
            "note": "v0 is the predecessor design ($5M volume bar, all ranked names up to 5 positions at 20% tickets, -10%/+25% exits), carried here because the task's record spans v0/v2/v10/v11. v0's zero-cost twin made money (+22.82%); its costed form did not — friction was v0's killer, which is what v2 was designed to attack.",
        },
        "v2_original": {
            "source": "backtests/v2/lottery-v2.md; reproduced to the cent in v10 (orig_run/)",
            "window": "2025-11-21 -> 2026-11-20", "start": 100.0,
            "variant_A_final": 82.89, "variant_B_final": 82.89,
            "return_pct": -17.11, "halt": "closed $83.43 on 2026-03-12 at/below the $85 ladder floor; liquidated next open 2026-03-13",
            "round_trips": 16, "win_rate_pct": 25.0, "total_costs": 9.27,
            "max_dd_pct": -24.12, "gap_through_stops": 1, "zero_cost_twin": 85.18,
            "zero_cost_twin_note": "The zero-cost twin ALSO lost money ($85.18, halted 2026-03-23): unlike v0, v2's picks lost before costs. Costs were cut from $23.36 (v0) to $9.27 and the pot still died sooner in dollars — the cost attack worked on friction and the picks were the problem.",
            "spy_gross_same_window": 105.31,
            "variant_B_note": "B (SPY<200d entry block) trade-for-trade identical to A: SPY first closed below its 200-day on 2026-03-19, after both variants halted 2026-03-13.",
        },
        "v3_relation": {
            "source": "backtests/v10-retest/lottery/RESULTS.md",
            "note": "v3 is the separate 'lottery' family row (PIT listed sub-$5 universe, 16-config book, headline E4+N3: design $98.65 / validation $84.17, both reproduced 16/16 in v10). It is Terry's later redesign, NOT lottery-v2, and is not duplicated here; it is recorded because it is the same pot lineage. Its verdict was the same: no demonstrated edge.",
        },
        "v10_integrity": {
            "source": "backtests/v10-retest/lottery-v2/RESULTS.md + results.json",
            "status": "REPRODUCED — untouched original backtests/v2/lottery-v2.py re-run in orig_run/ against the original cache reproduced every published number to the cent (A $82.89, B $82.89, twin $85.18, costs $9.27, halt 2026-03-13, SPY $105.31).",
        },
        "v10_decade_sweep": {
            "source": "backtests/v10-retest/lottery-v2/RESULTS.md + results.json",
            "road": "DECADE 2016-11-21 -> 2026-11-20, $100/cell, v9 plain-floor protection (ladder replaced per v10 SPEC, stated), 20-seed random-pick placebos per cell",
            "spy_decade_final": 367.80,
            "cells": cells,
            "headline": "No cadence beat SPY. Only semiannual finished above $100 ($120.11) and it sat BELOW its own placebo median ($124.28). Native daily: $69.02 after two halts. Biweekly beat 20/20 twins and still lost 30% — signal and random alike bleed on this road.",
        },
        "v11_verdict": {
            "source": "backtests/v11-native-rules/lottery-v2/NATIVE-SPEC.md + RESULTS.md",
            "verdict": "UNBUILDABLE-NATIVE — no published native form exists (house design), and its evidence counterpart lives in the OTC habitat: untradeable on Alpaca (listed only) and unreplayable on free PIT data. v11 carried the v10 number: $82.89 vs SPY $105.31, zero-cost twin $85.18.",
        },
    },
    "habitat_evidence": {
        "source": "Eraker & Ready, JFE 2015 (11,260 OTCBB/Pink stocks, 2000-2008); Ang, Shtauber & Tetlock, NBER WP 19309",
        "median_otc_total_return_pct": -97, "pct_negative": 83, "pct_lost_over_95": 52,
        "typical_relative_spread_pct": 10,
        "note": "The listed form was charged 2%/side; the native habitat's documented spreads are ~5x that per side. A habitat change makes the documented economics worse, not better.",
    },
    "bias_notes": [
        "SURVIVORSHIP (flatters): the 71-name candidate list was assembled in Nov 2026 from names known then; names that died/delisted earlier are missing. Every carried number is flattered by an unknown amount — and the design still lost on every road.",
        "Yahoo returned no decade data for SAVA, SDIG, GREE, MULN, NKLA, GOEV, TEF, NGD — excluded everywhere, documented, never patched.",
        "The floor in a penny book is a target, not a guarantee: v10 monthly cell triggered at $84.52 and liquidated at $77.59 the next open (March 2020 gap).",
    ],
    "verdict_v12": "RECORD STANDS AS DOCUMENTED — see RESULTS.md.",
}

out = pathlib.Path(__file__).parent / "results.json"
out.write_text(json.dumps(record, indent=1))
print("wrote", out)
