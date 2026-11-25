"""Persistence proof: build -> trade -> force halt -> save -> load -> compare.

Run:  python3 -m pots.test_persistence   (from app/)  or  python3 pots/test_persistence.py
All time logic is date-based: the restart date must equal halt_date + 90 days
no matter when this process (or any later one) runs.
PAPER / REPLAY ONLY.

DERIVED APP ADAPTATION (recorded in BUILD-REPORT.md): the persistence
proof below is the frozen test, unchanged. The definitions smoke
check at the end asserted the frozen app's 14-pot slate; this app
ships one pot, so the smoke check asserts the one-pot slate instead.
"""
import sys, tempfile
from datetime import date, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pots.pot import Pot
from pots.definitions import build_all_pots, POT_DEFINITIONS

def main():
    with tempfile.TemporaryDirectory() as td:
        sd = Path(td)
        pot = Pot("champion", "Champion — Value + Momentum (V+M)", start_balance=100.0,
                  start_date="2026-01-05", state_dir=sd)
        pot.buy_value("AAPL", 50.0, 100.0, "2026-01-05", "initial")
        pot.buy_value("MSFT", 30.0, 200.0, "2026-01-05", "initial")
        assert pot.on_daily_close("2026-01-06", {"AAPL": 101.0, "MSFT": 201.0}) == "ok"
        # Force a halt: crash marks so closing equity <= $85 floor -> liquidation.
        result = pot.on_daily_close("2026-02-02", {"AAPL": 40.0, "MSFT": 80.0})
        assert result == "halt", result
        assert pot.protection.status == "waiting_restart"
        assert pot.positions == {}, "halt must liquidate"
        halt_date = pot.protection.halt_date
        expected_eligible = (date.fromisoformat(halt_date) + timedelta(days=90)).isoformat()
        assert pot.protection.restart_eligible_date == expected_eligible, (
            pot.protection.restart_eligible_date, expected_eligible)
        before = pot.snapshot()
        pot.save()
        assert (sd / "champion.json").exists()
        assert not (sd / "champion.json.tmp").exists(), "temp file must be renamed away"

        fresh = Pot.load("champion", state_dir=sd)
        after = fresh.snapshot()
        assert before == after, "loaded state differs from saved state"
        # Field-by-field, explicitly:
        assert fresh.cash == pot.cash and fresh.positions == pot.positions
        assert fresh.ledger.to_list() == pot.ledger.to_list()
        assert fresh.protection.episode == 1 and fresh.protection.halt_date == halt_date
        assert fresh.protection.restart_eligible_date == expected_eligible
        # Restart eligibility is a pure function of the SAVED halt date:
        # not due the day before eligibility even on a selection date,
        # due on the first selection date on/after it.
        day_before = (date.fromisoformat(expected_eligible) - timedelta(days=1)).isoformat()
        assert fresh.on_daily_close(day_before, {}, is_selection_date=True) == "waiting"
        assert fresh.on_daily_close(expected_eligible, {}, is_selection_date=False) == "waiting"
        assert fresh.on_daily_close(expected_eligible, {}, is_selection_date=True) == "restarted"
        assert fresh.protection.episode == 2
        assert fresh.protection.floor == round(fresh.protection.episode_start_balance * 0.85, 10)
        reloaded = Pot.load("champion", state_dir=sd)
        assert reloaded.protection.episode == 2 and reloaded.protection.restart_date == expected_eligible
        print(f"halt_date={halt_date} restart_eligible={expected_eligible} "
              f"cash_after_halt=${fresh.cash:.2f} episode2_floor=${fresh.protection.floor:.2f} "
              f"trades={fresh.ledger.trade_count} costs=${fresh.ledger.total_costs:.2f}")

    # Definitions smoke check (adapted): the derived app's slate is
    # exactly one pot, the champion, quarterly cadence, no Pot 2.
    with tempfile.TemporaryDirectory() as td:
        pots = build_all_pots(state_dir=Path(td))
        assert len(pots) == len(POT_DEFINITIONS) == 1, \
            f"expected the one-pot champion slate, got {len(pots)}"
        assert "champion" in pots
        assert not any("pot_2" in k or "free" in k for k in pots)
        champ = pots["champion"]
        assert not champ.track_only and champ.start_balance == 100.0
        assert champ.protection.floor == 85.0
        print(f"definitions ok: {sorted(pots)} | champion floor=${champ.protection.floor:.2f}")
    print("PERSISTENCE TEST PASSED")

if __name__ == "__main__":
    main()
