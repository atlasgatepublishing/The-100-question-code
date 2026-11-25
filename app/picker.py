"""Horizon Picker registry -- App v2 (PAPER / REPLAY ONLY).

Terry's final slate (2026-11-23): users CHOOSE a strategy BY HOLDING
PERIOD. The buckets are exactly as he named them:

    Daily | 3 Days | Weekly | Bi-Weekly | Monthly | Every 3 Months |
    Every 6 Months | Yearly | Long

Every offering carries its tier and a plain-words fence text that must
be shown BEFORE selection -- the fences are part of the record (source:
TOP-BY-HORIZON.md 2nd ed. / TOP-BY-CLASS.md) and are never softened
here. Pots stay separate $100 pots, never blended. There is NO Pot 2 /
free-money pot anywhere in this app.

Engine availability: most offerings name the engine module + form they
will run when their engine is wired in. ONE offering is conditional by
design -- Accruals at 2 holdings (Yearly bucket) is exposed only when
``engines/accruals.py`` exists on disk, because that port is gated
separately. ``available_offerings()`` applies that filter; the full
registry (``BUCKETS`` / ``all_offerings()``) always contains it so its
fence and floor warning can be inspected and tested.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

_APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Exact warning carried by every floor-incompatible offering.
FLOOR_FREE_WARNING = (
    "This one runs with NO -15% safety floor, exactly as it was tested "
    "-- a floor cannot honestly exist in this form. Its worst fall was -33.5%."
)

# The honest note for the 3 Days bucket: no native 3-day system exists.
THREE_DAY_NOTE = (
    "No system in the tested record works on a 3-day rhythm. "
    "This is the daily system -- the closest tested form."
)

V9_FLOOR_STATUS = "v9 house rules as tested (-15% floor, 90-day halt, one restart)"


def _engine_file_exists(module_name: str) -> bool:
    """True if app/engines/<module_name>.py exists on disk."""
    return os.path.exists(os.path.join(_APP_DIR, "engines", f"{module_name}.py"))


@dataclass(frozen=True)
class Offering:
    """One selectable strategy inside a bucket."""

    offering_id: str
    strategy_name: str
    engine_module: str          # e.g. "vm", "nf3", "lazy_prices"
    engine_form: str            # e.g. "daily", "weekly", "quarterly"
    tier: str                   # PROMOTED | CANDIDATE... | VARIANT-CANDIDATE
    fence_text: str             # plain words, shown BEFORE selection
    pot_id: str = ""            # pots.definitions pot this offering runs as
    cadence: str = ""           # selection cadence of the pot
    finals: dict = field(default_factory=dict)  # published finals, $ per $100 pot
    worst_fall_pct: float | None = None         # e.g. -32.1
    luck_score: str = ""                        # e.g. "20/20", "" if none published
    floor_status: str = V9_FLOOR_STATUS
    floor_free: bool = False
    warning: str = ""           # required non-empty when floor_free is True
    note: str = ""              # extra honest note (e.g. the 3 Days note)
    is_default: bool = False    # the bucket's default offering
    borrowed_from_bucket: str = ""  # set when this is another bucket's system
    requires_engine_module: str = ""  # if set, available only if that engine file exists

    @property
    def engine(self) -> str:
        """'module:form' shorthand for the engine + form pair."""
        return f"{self.engine_module}:{self.engine_form}"


@dataclass(frozen=True)
class Bucket:
    """A holding-period bucket, named exactly as Terry named it."""

    bucket_id: str
    name: str                   # Terry's exact name
    offerings: tuple = ()
    note: str = ""              # bucket-level honest note, if any

    @property
    def default_offering(self):
        for off in self.offerings:
            if off.is_default:
                return off
        return self.offerings[0] if self.offerings else None


# --------------------------------------------------------------------------
# Offerings (registry content from the completed record)
# --------------------------------------------------------------------------

_QM_DAILY_FENCE = (
    "Candidate -- the horizon crown for the daily rhythm, not a promoted pot. "
    "Quality-Momentum in its daily form finished the 10-year road at $847.62 "
    "on a $100 pot, beat all 20 random twin pots (luck score 20/20), and its "
    "worst fall along the way was -32.1%. It runs under the v9 house rules "
    "exactly as tested, including the -15% safety floor."
)
_QM_WEEKLY_FENCE = (
    "Candidate -- confirmed. Quality-Momentum in its weekly form finished "
    "the 10-year road at $1,164.49 on a $100 pot, the biggest certified "
    "stock print of the sweep, and its worst fall was -32.1%. It runs under "
    "the v9 house rules exactly as tested, including the -15% safety floor."
)
_QM_BIWEEKLY_FENCE = (
    "Candidate. Quality-Momentum in its every-two-weeks form finished the "
    "10-year road at $1,096.12 on a $100 pot. Its luck score is 14/20 -- a "
    "pass, but a thin one: about 3 random pots in 10 did as well or better "
    "by luck alone. It runs under the v9 house rules exactly as tested, "
    "including the -15% safety floor."
)
_QM_MONTHLY_FENCE = (
    "Candidate. Quality-Momentum in its monthly form finished the 10-year "
    "road at $1,097.93 on a $100 pot. Its luck score is 13/20 -- the "
    "thinnest pass in the record: 7 of 20 random twin pots did as well or "
    "better by luck alone. It runs under the v9 house rules exactly as "
    "tested, including the -15% safety floor."
)

BUCKETS: list[Bucket] = [
    Bucket("daily", "Daily", offerings=(
        Offering(
            offering_id="qm_daily", strategy_name="Quality-Momentum",
            engine_module="quality_momentum", engine_form="daily",
            tier="CANDIDATE (horizon crown)", fence_text=_QM_DAILY_FENCE,
            pot_id="qm_daily", cadence="daily",
            finals={"decade": 847.62}, worst_fall_pct=-32.1,
            luck_score="20/20", is_default=True,
        ),
    )),
    Bucket("3_days", "3 Days", note=THREE_DAY_NOTE, offerings=(
        Offering(
            offering_id="qm_daily_for_3_days", strategy_name="Quality-Momentum",
            engine_module="quality_momentum", engine_form="daily",
            tier="CANDIDATE (horizon crown)",
            fence_text=THREE_DAY_NOTE + " " + _QM_DAILY_FENCE,
            pot_id="qm_daily", cadence="daily",
            finals={"decade": 847.62}, worst_fall_pct=-32.1,
            luck_score="20/20", note=THREE_DAY_NOTE,
            is_default=True, borrowed_from_bucket="Daily",
        ),
    )),
    Bucket("weekly", "Weekly", offerings=(
        Offering(
            offering_id="qm_weekly", strategy_name="Quality-Momentum",
            engine_module="quality_momentum", engine_form="weekly",
            tier="CANDIDATE (confirmed)", fence_text=_QM_WEEKLY_FENCE,
            pot_id="qm_weekly", cadence="weekly",
            finals={"decade": 1164.49}, worst_fall_pct=-32.1,
            luck_score="20/20", is_default=True,
        ),
    )),
    Bucket("bi_weekly", "Bi-Weekly", offerings=(
        Offering(
            offering_id="qm_biweekly", strategy_name="Quality-Momentum",
            engine_module="quality_momentum", engine_form="biweekly",
            tier="CANDIDATE", fence_text=_QM_BIWEEKLY_FENCE,
            pot_id="qm_biweekly", cadence="biweekly",
            finals={"decade": 1096.12}, worst_fall_pct=-36.2,
            luck_score="14/20", is_default=True,
        ),
    )),
    Bucket("monthly", "Monthly", offerings=(
        Offering(
            offering_id="qm_monthly", strategy_name="Quality-Momentum",
            engine_module="quality_momentum", engine_form="monthly",
            tier="CANDIDATE", fence_text=_QM_MONTHLY_FENCE,
            pot_id="qm_monthly", cadence="monthly",
            finals={"decade": 1097.93}, worst_fall_pct=-35.5,
            luck_score="13/20", is_default=True,
        ),
        Offering(
            offering_id="momentum_basket", strategy_name="Momentum Basket",
            engine_module="momentum_basket", engine_form="monthly",
            tier="PROMOTED",
            fence_text=(
                "Promoted. Momentum Basket re-picks monthly: top-5 by 12-1 "
                "momentum with a 200-day eligibility rule. Its published "
                "finals are $439.45 / $208.27 on a $100 pot. It runs under "
                "the v9 house rules exactly as tested, including the -15% "
                "safety floor."
            ),
            pot_id="momentum_basket", cadence="monthly",
            finals={"continuous": 439.45, "validation": 208.27},
        ),
    )),
    Bucket("every_3_months", "Every 3 Months", offerings=(
        Offering(
            offering_id="nf3_horizon_quarterly",
            strategy_name="N-F3 Paying in Stock",
            engine_module="nf3_horizon", engine_form="quarterly",
            tier="CANDIDATE (invented rule -- candidate ceiling)",
            fence_text=(
                "Candidate -- and that is its ceiling. Paying in Stock is "
                "an invented rule, not a published system, so it can never "
                "be more than a candidate on this record. In its "
                "every-3-months horizon form it finished the 10-year road "
                "at $737.97 on a $100 pot, beat all 20 random twin pots "
                "(luck score 20/20), and its worst fall was -31.5%. It "
                "runs under the v9 house rules exactly as tested, "
                "including the -15% safety floor."
            ),
            pot_id="nf3_horizon_quarterly", cadence="quarterly",
            finals={"decade": 737.97}, worst_fall_pct=-31.5,
            luck_score="20/20", is_default=True,
        ),
        Offering(
            offering_id="lazy_prices", strategy_name="Lazy Prices",
            engine_module="lazy_prices", engine_form="quarterly",
            tier="PROMOTED",
            fence_text=(
                "Promoted. Lazy Prices re-picks every 3 months: top-5 by "
                "10-K language similarity (Cohen-Malloy-Nguyen). Its "
                "published finals are $504.34 / $324.12 on a $100 pot. It "
                "runs under the v9 house rules exactly as tested, "
                "including the -15% safety floor."
            ),
            pot_id="lazy_prices", cadence="quarterly",
            finals={"continuous": 504.34, "validation": 324.12},
        ),
    )),
    Bucket("every_6_months", "Every 6 Months", offerings=(
        Offering(
            offering_id="nf3_horizon_semiannual",
            strategy_name="N-F3 Paying in Stock",
            engine_module="nf3_horizon", engine_form="semiannual",
            tier="CANDIDATE (invented rule -- candidate ceiling)",
            fence_text=(
                "Candidate -- and that is its ceiling. Paying in Stock is "
                "an invented rule, not a published system, so it can never "
                "be more than a candidate on this record. In its "
                "twice-a-year horizon form it finished the 10-year road "
                "at $848.79 on a $100 pot, with a luck score of 17/20, and "
                "its worst fall was -29.3%. It runs under the v9 house "
                "rules exactly as tested, including the -15% safety floor."
            ),
            pot_id="nf3_horizon_semiannual", cadence="semiannual",
            finals={"decade": 848.79}, worst_fall_pct=-29.3,
            luck_score="17/20", is_default=True,
        ),
    )),
    Bucket("yearly", "Yearly", offerings=(
        Offering(
            offering_id="accruals_2", strategy_name="Accruals at 2 holdings",
            engine_module="accruals", engine_form="annual",
            tier="VARIANT-CANDIDATE",
            fence_text=(
                "Variant-candidate only. This is a 2-holding variant of "
                "the accruals system -- just two stocks at a time, so it "
                "is concentrated and can swing hard. On its decade window "
                "it finished at $1,487.30 on a $100 pot, and its worst "
                "fall was -33.5%. " + FLOOR_FREE_WARNING
            ),
            pot_id="accruals_2", cadence="annual",
            finals={"decade_window": 1487.30}, worst_fall_pct=-33.5,
            floor_status="floor-free, exactly as tested (no -15% floor)",
            floor_free=True, warning=FLOOR_FREE_WARNING,
            is_default=True, requires_engine_module="accruals",
        ),
    )),
    Bucket("long", "Long", offerings=(
        Offering(
            offering_id="champion", strategy_name="Champion -- Value + Momentum",
            engine_module="vm", engine_form="quarterly",
            tier="PROMOTED",
            fence_text=(
                "Promoted -- the app's default and centerpiece. The "
                "champion picks every 3 months: top-5, equal weight, by "
                "value plus momentum. Its published finals are $544.47 / "
                "$288.05 on a $100 pot, and over the full 17-year road it "
                "finished at $1,415.62. It runs under the v9 house rules "
                "exactly as tested, including the -15% safety floor."
            ),
            pot_id="champion", cadence="quarterly",
            finals={"continuous": 544.47, "validation": 288.05,
                    "long_17y": 1415.62},
            is_default=True,
        ),
    )),
]

BUCKET_NAMES: list[str] = [b.name for b in BUCKETS]
BY_ID: dict[str, Bucket] = {b.bucket_id: b for b in BUCKETS}
BY_NAME: dict[str, Bucket] = {b.name: b for b in BUCKETS}

assert not any("pot_2" in o.offering_id or "free_money" in o.offering_id
               for b in BUCKETS for o in b.offerings), \
    "No Pot 2 / free-money pot is allowed"


# --------------------------------------------------------------------------
# Registry API (for the dashboard worker)
# --------------------------------------------------------------------------

def bucket_names() -> list[str]:
    """Terry's exact bucket names, in picker order."""
    return list(BUCKET_NAMES)


def all_buckets() -> list[Bucket]:
    """Every bucket, in picker order (full registry, unfiltered)."""
    return list(BUCKETS)


def get_bucket(name_or_id: str) -> Bucket:
    """Look up a bucket by Terry's exact name ('Bi-Weekly') or by id
    ('bi_weekly'). Raises KeyError if there is no such bucket."""
    if name_or_id in BY_NAME:
        return BY_NAME[name_or_id]
    if name_or_id in BY_ID:
        return BY_ID[name_or_id]
    raise KeyError(f"no such bucket: {name_or_id!r}")


def all_offerings() -> list[Offering]:
    """Every offering in the full registry, bucket order preserved --
    including conditional offerings whose engine is not on disk yet."""
    return [o for b in BUCKETS for o in b.offerings]


def offering_available(offering: Offering) -> bool:
    """True if the offering may be shown as selectable right now.
    Only offerings with ``requires_engine_module`` set are conditional:
    they are available only while app/engines/<module>.py exists."""
    if offering.requires_engine_module:
        return _engine_file_exists(offering.requires_engine_module)
    return True


def available_offerings(bucket: str | Bucket | None = None) -> list[Offering]:
    """Selectable offerings, filtered on engine availability.

    With no argument: every available offering across all buckets.
    With a bucket name/id (or a Bucket): that bucket's available
    offerings -- possibly empty (e.g. Yearly while engines/accruals.py
    has not landed)."""
    buckets = [get_bucket(bucket) if isinstance(bucket, str) else bucket] \
        if bucket is not None else list(BUCKETS)
    return [o for b in buckets for o in b.offerings if offering_available(o)]


def available_buckets() -> list[Bucket]:
    """Buckets that have at least one available offering right now."""
    return [b for b in BUCKETS if any(offering_available(o) for o in b.offerings)]


def default_offering(bucket: str | Bucket) -> Offering | None:
    """The bucket's default offering (first marked is_default, else the
    first offering). This is the FULL-registry default; check
    offering_available() before presenting a conditional one."""
    b = get_bucket(bucket) if isinstance(bucket, str) else bucket
    return b.default_offering


def default_bucket() -> Bucket:
    """The app's home bucket: Long, whose default is the Champion."""
    return BY_ID["long"]


def champion_offering() -> Offering:
    """The Champion offering -- the Long bucket's default."""
    return BY_ID["long"].default_offering
