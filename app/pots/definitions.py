"""The pots. PAPER / REPLAY ONLY -- no real-money capability.

The original seven pots, plus the Horizon Picker pots added for App v2
(2026-11-23): Quality-Momentum at four cadences, N-F3 Paying in Stock at
two horizon cadences, and -- only while its gated engine file exists on
disk -- Accruals at 2 holdings. Every pot is a SEPARATE $100 pot.

Per Terry's final build slate (2026-11-21): three promoted pots run as
SEPARATE $100 pots (never blended), two candidate lanes for the paper trial,
one quarantined penny-lottery pot, and one track-only AI-infrastructure watch.
There is deliberately NO "Pot 2 / free money" pot anywhere in this app.
SPY shadow: use data.loaders.ReplayLoader.spy_shadow() beside every pot, and
Pot.spy_shadow_value() below for a running mark.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from .pot import Pot

# Accruals engine is gated separately: its pot is registered ONLY while
# the engine file exists on disk, so this module still loads (and the
# rest of the registry still works) when the port is excluded.
_ACCRUALS_ENGINE = Path(__file__).resolve().parent.parent / "engines" / "accruals.py"

@dataclass
class PotDefinition:
    pot_id: str; name: str; kind: str  # promoted | candidate | lottery | track_only
    start_balance: float = 100.0
    selection_cadence: str = "quarterly"  # daily | weekly | biweekly | monthly | quarterly | semiannual | annual | none
    description: str = ""
    track_only: bool = False
    fixed_positions: dict = field(default_factory=dict)  # symbol -> (dollars, entry_price, entry_date)

# --- penny-lottery filters (DESIGN.md, Terry's decision 2026-11-20 ~22:05) ---
# Rationale: Eraker & Ready's study of 11,260 OTC stocks found a median return
# of -97% and only ~1.2% rising 10x+, with typical spreads ~10% -- one round
# trip can eat most of a -15% loss budget before the stock even moves. So this
# pot is quarantined, listed-only, and every filter below is mandatory.
PENNY_MAX_PRICE = 5.00            # exchange-listed sub-$5 only; OTC/Pink excluded
                                  # because the free paper broker does not support
                                  # OTC at all and may liquidate names that become OTC.
PENNY_MIN_AVG_DOLLAR_VOLUME = 250_000.0  # enough real trading that an exit plausibly exists
PENNY_MAX_SPREAD_PCT = 0.05       # quoted spread cap: a 10% spread burns the budget pre-move
PENNY_MAX_POSITION_PCT = 0.20     # small tickets spread across names; no single penny sinks the pot

def penny_price_ok(price: float) -> bool:
    """Listed sub-$5 only (caller must also confirm an exchange listing)."""
    return 0 < price < PENNY_MAX_PRICE
def penny_liquidity_ok(avg_daily_dollar_volume: float) -> bool:
    return avg_daily_dollar_volume >= PENNY_MIN_AVG_DOLLAR_VOLUME
def penny_spread_ok(bid: float, ask: float) -> bool:
    if bid<=0 or ask<=0 or ask<bid: return False
    mid=(bid+ask)/2
    return ((ask-bid)/mid) <= PENNY_MAX_SPREAD_PCT if mid else False
def penny_entry_ok(price, avg_daily_dollar_volume, bid, ask, *, listed_on_major_exchange: bool,
                   sec_filings_current: bool, order_type: str) -> tuple[bool,str]:
    """All mandatory DESIGN.md entry filters. Limit orders ONLY, never market."""
    if not listed_on_major_exchange: return False, "not exchange-listed (OTC/Pink excluded)"
    if not penny_price_ok(price): return False, "price not in (0, $5)"
    if not penny_liquidity_ok(avg_daily_dollar_volume): return False, "average daily dollar volume too low -- no plausible exit"
    if not penny_spread_ok(bid, ask): return False, "quoted spread wider than the 5% cap"
    if not sec_filings_current: return False, "SEC filings not current"
    if order_type.lower()!="limit": return False, "limit orders only, never market orders"
    return True, "ok"
def penny_can_average_down(existing_shares: float) -> bool:
    """No averaging down, no adding to a loser -- ever (DESIGN.md)."""
    return False

AI_WATCH_POSITIONS = {  # $20 each, entries at 2026-11-20 prices given in the brief
    "MU":   (20.0, 594.51), "MRVL": (20.0, 122.28), "TER": (20.0, 204.78),
    "AMAT": (20.0, 302.63), "POWL": (20.0, 148.18),
}

POT_DEFINITIONS: list[PotDefinition] = [
    PotDefinition("champion","Champion — Value + Momentum (V+M)","promoted",selection_cadence="quarterly",
        description="Promoted #1. Quarterly selection, top-5 equal weight, value+momentum. Backtest finals (honest run): $544.47 continuous / $288.05 validation."),
    PotDefinition("lazy_prices","Lazy Prices","promoted",selection_cadence="quarterly",
        description="Promoted. Quarterly top-5 by 10-K language similarity (Cohen-Malloy-Nguyen). $504.34 / $324.12."),
    PotDefinition("momentum_basket","Momentum Basket","promoted",selection_cadence="monthly",
        description="Promoted. Monthly top-5 by 12-1 momentum, 200-day eligibility. $439.45 / $208.27."),
    PotDefinition("candidate_nf3","Candidate — N-F3 Paying in Stock","candidate",selection_cadence="quarterly",
        description="Candidate lane for the forward paper trial only (not adopted). SBC-intensity deceleration. $505.43 / $289.53."),
    PotDefinition("candidate_switch_b","Candidate — Midpoint Switch B","candidate",selection_cadence="quarterly",
        description="Candidate lane only: champion first, switch to blend at the midpoint. Passed its bar at candidate grade; earns a paper-trial lane, not adoption."),
    PotDefinition("penny_lottery","Penny Lottery (simulation only)","lottery",selection_cadence="monthly",
        description="Quarantined $100 simulation pot. Listed sub-$5 only, min dollar-volume + max-spread filters, limit orders only, no averaging down. In pennies the -15% floor is a target, not a guarantee -- gaps/no-bid can jump through it."),
    PotDefinition("ai_watch","AI Watch — tracking only","track_only",selection_cadence="none", start_balance=100.0,
        track_only=True, fixed_positions={s:(d,p,"2026-11-20") for s,(d,p) in AI_WATCH_POSITIONS.items()},
        description="TRACK-ONLY: $20 each in MU, MRVL, TER, AMAT, POWL at 2026-11-20 entries, buy-and-hold. NO floor actions, NO trading. Labeled 'tracking only' everywhere it appears."),
    # --- Horizon Picker pots (App v2, Terry's slate 2026-11-23) ---
    # Separate $100 pots, never blended. See picker.py for the buckets
    # and the plain-words fences shown before selection.
    PotDefinition("qm_daily","Candidate — Quality-Momentum (Daily)","candidate",selection_cadence="daily",
        description="Candidate (horizon crown). Daily selection, Quality-Momentum. Decade final $847.62, luck 20/20, worst fall -32.1%. Floor: v9 house rules as tested."),
    PotDefinition("qm_weekly","Candidate — Quality-Momentum (Weekly)","candidate",selection_cadence="weekly",
        description="Candidate (confirmed). Weekly selection, Quality-Momentum. Decade final $1,164.49, worst fall -32.1%."),
    PotDefinition("qm_biweekly","Candidate — Quality-Momentum (Bi-Weekly)","candidate",selection_cadence="biweekly",
        description="Candidate. Every-two-weeks selection, Quality-Momentum. Decade final $1,096.12, luck 14/20 -- a pass, but a thin one."),
    PotDefinition("qm_monthly","Candidate — Quality-Momentum (Monthly)","candidate",selection_cadence="monthly",
        description="Candidate. Monthly selection, Quality-Momentum. Decade final $1,097.93, luck 13/20 -- the thinnest pass in the record."),
    PotDefinition("nf3_horizon_quarterly","Candidate — N-F3 Paying in Stock (Every 3 Months)","candidate",selection_cadence="quarterly",
        description="Candidate (invented rule -- candidate ceiling). Quarterly horizon form, N-F3 Paying in Stock. Decade final $737.97, luck 20/20, worst fall -31.5%. Distinct from candidate_nf3, the original candidate lane."),
    PotDefinition("nf3_horizon_semiannual","Candidate — N-F3 Paying in Stock (Every 6 Months)","candidate",selection_cadence="semiannual",
        description="Candidate (invented rule -- candidate ceiling). Semiannual horizon form, N-F3 Paying in Stock. Decade final $848.79, luck 17/20, worst fall -29.3%."),
]
# Accruals at 2 holdings: registered ONLY if the gated engine port is on
# disk (guarded existence check -- this module must load without it).
# FLOOR-FREE exactly as tested: no -15% floor can honestly exist in this
# form; picker.py carries the plain-words warning shown before selection.
if _ACCRUALS_ENGINE.exists():
    POT_DEFINITIONS.append(
        PotDefinition("accruals_2","Candidate — Accruals at 2 Holdings","candidate",selection_cadence="annual",
            description="Variant-candidate. Annual selection, accruals at 2 holdings. Decade-window final $1,487.30, worst fall -33.5%. FLOOR-FREE exactly as tested -- runs with NO -15% safety floor."))
BY_ID={d.pot_id:d for d in POT_DEFINITIONS}
assert not any("pot_2" in d.pot_id or "free_money" in d.pot_id for d in POT_DEFINITIONS), "No Pot 2 / free-money pot is allowed"

def build_pot(defn: PotDefinition, state_dir=None, start_date: str|None=None) -> Pot:
    # H3 (QA Area 1): never silently reset a pot that already has saved
    # state -- load and return it instead of wiping its progress/ledger.
    from pathlib import Path
    from .pot import STATE_DIR
    sd = Path(state_dir) if state_dir else STATE_DIR
    # R2-M1: a surviving .bak also proves the pot existed -- load (which
    # recovers from it) instead of minting a fresh $100 pot over its history.
    if (sd / f"{defn.pot_id}.json").exists() or (sd / f"{defn.pot_id}.json.bak").exists():
        return Pot.load(defn.pot_id, state_dir=sd)
    pot=Pot(defn.pot_id, defn.name, start_balance=defn.start_balance, start_date=start_date,
            track_only=defn.track_only, state_dir=state_dir,
            meta={"kind":defn.kind,"selection_cadence":defn.selection_cadence,"description":defn.description})
    if defn.track_only and defn.fixed_positions:
        # Record the fixed tracking positions directly (no trading engine involved).
        spent=0.0
        for sym,(dollars,price,entry_date) in defn.fixed_positions.items():
            shares=dollars/price; pot.positions[sym]={"shares":shares,"avg_cost":price}
            pot.last_prices[sym]=price; spent+=dollars
            from .ledger import Trade
            pot.ledger.add(Trade(entry_date,sym,"buy",shares,price,round(dollars,2),0.0,round(-dollars,2),"track_only_entry"))
        pot.cash=round(pot.start_balance-spent,2)
    pot.save(); return pot

def build_all_pots(state_dir=None, start_date: str|None=None) -> dict[str,Pot]:
    return {d.pot_id: build_pot(d, state_dir=state_dir, start_date=start_date) for d in POT_DEFINITIONS}
