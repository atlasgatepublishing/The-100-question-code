"""Horizon Picker registry proof (App v2).

Run:  python3 -m test_picker   (from app/)  or  python3 test_picker.py
PAPER / REPLAY ONLY.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import picker
from picker import (
    BUCKETS, FLOOR_FREE_WARNING, THREE_DAY_NOTE,
    all_offerings, available_offerings, bucket_names, champion_offering,
    default_bucket, default_offering, get_bucket, offering_available,
)
from pots.definitions import BY_ID as POT_BY_ID, POT_DEFINITIONS

EXPECTED_BUCKETS = [
    "Daily", "3 Days", "Weekly", "Bi-Weekly", "Monthly",
    "Every 3 Months", "Every 6 Months", "Yearly", "Long",
]


def main():
    # 1. Every bucket exists, with Terry's exact names, in order.
    assert bucket_names() == EXPECTED_BUCKETS, bucket_names()
    assert [b.name for b in BUCKETS] == EXPECTED_BUCKETS
    for name in EXPECTED_BUCKETS:
        bucket = get_bucket(name)
        assert bucket.name == name and bucket.offerings, name
    print(f"buckets ok: {bucket_names()}")

    # 2. Every offering carries a tier and plain-words fence text,
    #    shown before selection -- plus an engine module + form.
    for off in all_offerings():
        assert off.tier and off.tier.strip(), off.offering_id
        assert off.fence_text and len(off.fence_text) >= 40, off.offering_id
        assert off.engine_module and off.engine_form, off.offering_id
        assert off.pot_id, off.offering_id
    print(f"offerings ok: {[o.offering_id for o in all_offerings()]}")

    # 3. The 3 Days bucket carries its honest note -- and never presents
    #    the borrowed daily system as a 3-day strategy.
    three = get_bucket("3 Days")
    assert three.note == THREE_DAY_NOTE
    assert "No system in the tested record works on a 3-day rhythm" in three.note
    off3 = three.default_offering
    assert off3.note == THREE_DAY_NOTE and THREE_DAY_NOTE in off3.fence_text
    assert off3.borrowed_from_bucket == "Daily"
    assert off3.engine_form == "daily" and off3.cadence == "daily"
    print("3 Days honest note ok: daily system borrowed, labelled as such")

    # 4. Floor-incompatible offerings carry floor_free=True and a warning.
    floor_free = [o for o in all_offerings() if o.floor_free]
    assert floor_free, "expected at least one floor-free offering"
    for off in floor_free:
        assert off.warning and "NO -15% safety floor" in off.warning, off.offering_id
        assert off.warning in off.fence_text, off.offering_id
    for off in all_offerings():
        if not off.floor_free:
            assert not off.warning or "NO -15%" not in off.warning, off.offering_id
    accruals = [o for o in all_offerings() if o.offering_id == "accruals_2"]
    assert len(accruals) == 1 and accruals[0].floor_free is True
    assert accruals[0].warning == FLOOR_FREE_WARNING
    assert accruals[0].tier == "VARIANT-CANDIDATE"
    assert accruals[0].finals["decade_window"] == 1487.30
    assert accruals[0].worst_fall_pct == -33.5
    print(f"floor-free ok: {[o.offering_id for o in floor_free]}")

    # 5. Accruals is conditional on engines/accruals.py existing on disk,
    #    in BOTH the picker registry and the pot definitions.
    engine_on_disk = (Path(__file__).resolve().parent / "engines" / "accruals.py").exists()
    assert offering_available(accruals[0]) == engine_on_disk
    yearly_available = available_offerings("Yearly")
    assert (len(yearly_available) == 1) == engine_on_disk, yearly_available
    assert ("accruals_2" in POT_BY_ID) == engine_on_disk
    assert ("accruals_2" in [d.pot_id for d in POT_DEFINITIONS]) == engine_on_disk
    print(f"accruals conditional ok: engine_on_disk={engine_on_disk}, "
          f"yearly_available={[o.offering_id for o in yearly_available]}")

    # 6. The Champion is the Long bucket's default -- the app's default.
    assert default_bucket().name == "Long"
    champ = champion_offering()
    assert champ is default_offering("Long")
    assert champ.pot_id == "champion" and champ.is_default
    assert champ.tier == "PROMOTED" and not champ.floor_free
    assert champ.finals == {"continuous": 544.47, "validation": 288.05,
                            "long_17y": 1415.62}, champ.finals
    print("champion ok: Long bucket default, PROMOTED, $544.47 / $288.05, "
          "17-year road $1,415.62")

    # 7. Headline record checks for the rest of the slate.
    by_id = {o.offering_id: o for o in all_offerings()}
    assert by_id["qm_daily"].finals["decade"] == 847.62
    assert by_id["qm_daily"].luck_score == "20/20"
    assert by_id["qm_daily"].worst_fall_pct == -32.1
    assert by_id["qm_weekly"].finals["decade"] == 1164.49
    assert by_id["qm_biweekly"].finals["decade"] == 1096.12
    assert "14/20" in by_id["qm_biweekly"].fence_text
    assert "thin" in by_id["qm_biweekly"].fence_text
    assert by_id["qm_monthly"].finals["decade"] == 1097.93
    assert "13/20" in by_id["qm_monthly"].fence_text
    assert "thinnest pass" in by_id["qm_monthly"].fence_text
    assert by_id["momentum_basket"].tier == "PROMOTED"
    assert by_id["momentum_basket"].finals == {"continuous": 439.45,
                                                "validation": 208.27}
    assert by_id["nf3_horizon_quarterly"].finals["decade"] == 737.97
    assert "invented rule" in by_id["nf3_horizon_quarterly"].fence_text
    assert by_id["lazy_prices"].tier == "PROMOTED"
    assert by_id["lazy_prices"].finals == {"continuous": 504.34,
                                           "validation": 324.12}
    assert by_id["nf3_horizon_semiannual"].finals["decade"] == 848.79
    assert by_id["nf3_horizon_semiannual"].luck_score == "17/20"
    # Multi-offering buckets keep both offerings.
    assert len(get_bucket("Monthly").offerings) == 2
    assert len(get_bucket("Every 3 Months").offerings) == 2
    print("headline finals + fences ok")

    # 8. New pot definitions exist, are separate $100 candidate pots,
    #    and the original seven are unchanged. No Pot 2 anywhere.
    expected_new = {
        "qm_daily": "daily", "qm_weekly": "weekly",
        "qm_biweekly": "biweekly", "qm_monthly": "monthly",
        "nf3_horizon_quarterly": "quarterly",
        "nf3_horizon_semiannual": "semiannual",
    }
    for pot_id, cadence in expected_new.items():
        defn = POT_BY_ID[pot_id]
        assert defn.kind == "candidate" and defn.selection_cadence == cadence, pot_id
        assert defn.start_balance == 100.0 and defn.description, pot_id
    for pot_id in ("champion", "lazy_prices", "momentum_basket",
                   "candidate_nf3", "candidate_switch_b", "penny_lottery",
                   "ai_watch"):
        assert pot_id in POT_BY_ID, pot_id
    assert not any("pot_2" in d.pot_id or "free_money" in d.pot_id
                   for d in POT_DEFINITIONS)
    assert not any("pot_2" in o.offering_id or "free_money" in o.offering_id
                   for o in all_offerings())
    print(f"pots ok: {len(POT_DEFINITIONS)} definitions, no Pot 2")

    # 9. available_offerings() with no argument never leaks a
    #    conditional offering whose engine is missing.
    for off in available_offerings():
        assert offering_available(off), off.offering_id
    print("PICKER TEST PASSED")


if __name__ == "__main__":
    main()
