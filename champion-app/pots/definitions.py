"""The pot. One pot only: the Champion.

DERIVED APP ADAPTATION of the frozen companion app's definitions.py
(recorded in BUILD-REPORT.md): the frozen file defined 14 pots. This
app ships exactly one strategy, so the copy keeps exactly one
definition, the champion (quarterly cadence), plus the SPY shadow,
which is a benchmark and not a pot (use
data.loaders.ReplayLoader.spy_shadow() beside the pot in replay, and
Pot.spy_shadow_value() for a running mark). Every other definition,
the penny lottery rule functions, and the AI Watch fixed positions
were removed in the copy, per the design's exclusion list: code that
is not in the folder cannot be switched on by accident.

There is deliberately NO "Pot 2 / free money" pot anywhere in this
app; the assertion below keeps the frozen build's guarantee.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from .pot import Pot


@dataclass
class PotDefinition:
    pot_id: str; name: str; kind: str  # promoted | candidate | lottery | track_only
    start_balance: float = 100.0
    selection_cadence: str = "quarterly"  # daily | weekly | biweekly | monthly | quarterly | semiannual | annual | none
    description: str = ""
    track_only: bool = False
    fixed_positions: dict = field(default_factory=dict)  # symbol -> (dollars, entry_price, entry_date)


POT_DEFINITIONS: list[PotDefinition] = [
    PotDefinition("champion", "Champion — Value + Momentum (V+M)", "promoted", selection_cadence="quarterly",
        description="The book's champion. Quarterly selection, top-5 equal weight, value+momentum. Backtest finals (honest run): $544.47 continuous / $288.05 validation."),
]
BY_ID = {d.pot_id: d for d in POT_DEFINITIONS}
assert not any("pot_2" in d.pot_id or "free_money" in d.pot_id for d in POT_DEFINITIONS), "No Pot 2 / free-money pot is allowed"


def build_pot(defn: PotDefinition, state_dir=None, start_date: str | None = None) -> Pot:
    # H3 (QA Area 1): never silently reset a pot that already has saved
    # state -- load and return it instead of wiping its progress/ledger.
    from pathlib import Path
    from .pot import STATE_DIR
    sd = Path(state_dir) if state_dir else STATE_DIR
    # R2-M1: a surviving .bak also proves the pot existed -- load (which
    # recovers from it) instead of minting a fresh pot over its history.
    if (sd / f"{defn.pot_id}.json").exists() or (sd / f"{defn.pot_id}.json.bak").exists():
        return Pot.load(defn.pot_id, state_dir=sd)
    pot = Pot(defn.pot_id, defn.name, start_balance=defn.start_balance, start_date=start_date,
              track_only=defn.track_only, state_dir=state_dir,
              meta={"kind": defn.kind, "selection_cadence": defn.selection_cadence,
                    "description": defn.description})
    pot.save()
    return pot


def build_all_pots(state_dir=None, start_date: str | None = None) -> dict[str, Pot]:
    return {d.pot_id: build_pot(d, state_dir=state_dir, start_date=start_date) for d in POT_DEFINITIONS}
