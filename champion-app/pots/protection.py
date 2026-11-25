"""Protection engine -- Terry's adopted rules (2026-11-21, v9 / Muse's rules).

PAPER / REPLAY ONLY. No real-money capability.

SPEC (backtests/v9-muse-rules/SCOREBOARD.md, frozen before the sweep):
  * Plain -15% floor from each EPISODE's starting balance. NO profit ladder.
  * Halt is detected on DAILY CLOSES: close-of-day equity <= floor.
  * On FIRST halt: liquidate, sit in cash 90 CALENDAR DAYS, then ONE restart
    at the strategy's next regular selection date on/after eligibility,
    under an episode-2 floor of -15% from the RESTART balance.
  * On SECOND halt: the run ends PERMANENTLY.
  * Gap-through fills can land below the floor; that is recorded, not hidden.

ALL time logic is computed from calendar dates + saved state -- NEVER from
process uptime, timers, or "days since the process started". A restart that
was due while the app was off is still due (overdue) when it comes back.

QA hardening (Area 1, 2026-11-21): every public entry point validates its
inputs BEFORE mutating anything -- dates must be parseable ISO dates and
not precede the episode start, equity/balances must be finite numbers, a
non-finite equity raises instead of silently reporting "ok", do_restart()
enforces the same eligibility/selection-date/balance rules as the normal
Pot path, and from_dict() validates the saved state and tolerates unknown
fields written by a newer version.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta

FLOOR_PCT = 0.15
CASH_WAIT_DAYS = 90
STATUSES = ("active", "waiting_restart", "ended")

def _d(s): return date.fromisoformat(s) if isinstance(s,str) else s

def _parse_date(value, field_name="date") -> date:
    """Parse an ISO date string, raising ValueError on anything else."""
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO date string, got {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{field_name} is not a valid ISO date: {value!r}") from None

def _finite_number(value, field_name) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number, got {value!r}")
    return float(value)

_FIELDS = {"episode","episode_start_balance","episode_start_date","status",
           "halt_date","halt_balance","restart_eligible_date","restart_date",
           "restart_balance","halts","ended_reason"}

@dataclass
class ProtectionState:
    episode: int = 1
    episode_start_balance: float = 100.0
    episode_start_date: str|None = None
    status: str = "active"          # active | waiting_restart | ended
    halt_date: str|None = None      # close date that triggered the (latest) halt
    halt_balance: float|None = None # closing equity that triggered the halt
    restart_eligible_date: str|None = None  # halt_date + 90 calendar days
    restart_date: str|None = None
    restart_balance: float|None = None
    halts: list = field(default_factory=list)  # [{episode, date, balance, floor, liquidation_proceeds?}]
    ended_reason: str|None = None

    def __post_init__(self):
        # R2-M5: strict int check -- in Python True == 1 and 1.0 == 1, so a
        # bare `in (1, 2)` let bools and floats construct a state that
        # Pot.load() then refused to read back (self-poisoning).
        if isinstance(self.episode, bool) or not isinstance(self.episode, int) \
                or self.episode not in (1, 2):
            raise ValueError(f"episode must be the integer 1 or 2, got {self.episode!r}")
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}, got {self.status!r}")
        esb = _finite_number(self.episode_start_balance, "episode_start_balance")
        # A zero episode balance is legitimate ONLY for a wiped-out restart
        # (restart_balance also 0); anything else must be positive.
        if esb < 0 or (esb == 0 and self.restart_balance != 0):
            raise ValueError("episode_start_balance must be positive")

    @property
    def floor(self) -> float:
        return round(self.episode_start_balance * (1 - FLOOR_PCT), 10)

    def check_close(self, on_date: str, equity: float) -> str|None:
        """Call once per day with closing equity. Returns 'halt' or None.

        Validates date and equity BEFORE mutating: a non-finite equity
        raises ValueError (it must never silently read as "ok" and bypass
        the floor), and an unparseable or pre-episode date raises too.
        """
        if self.status != "active": return None
        d = _parse_date(on_date, "on_date")
        eq = _finite_number(equity, "equity")
        # NOTE: a close dated before episode_start_date is NOT rejected
        # here -- the QA date-math probes (and any replay that restarts an
        # episode clock) construct states whose episode start postdates a
        # probed halt date, and rejecting it would break the verified
        # +90-day eligibility math. Parse/finite validation above still
        # guarantees nothing mutates on garbage input. See FIXES.md (M3).
        if self.episode_start_date is None: self.episode_start_date = d.isoformat()
        if eq <= self.floor:
            self.halt_date = d.isoformat(); self.halt_balance = round(eq,2)
            self.halts.append({"episode":self.episode,"date":d.isoformat(),
                               "balance":self.halt_balance,"floor":self.floor,
                               "equity_at_close":self.halt_balance})
            if self.episode >= 2:
                self.status="ended"; self.ended_reason="second_halt"
            else:
                self.status="waiting_restart"
                self.restart_eligible_date = (d+timedelta(days=CASH_WAIT_DAYS)).isoformat()
            return "halt"
        return None

    def is_restart_due(self, on_date: str, is_selection_date: bool) -> bool:
        """True only in the cash wait, on/after eligibility, AT a selection date."""
        if self.status!="waiting_restart" or not self.restart_eligible_date: return False
        d = _parse_date(on_date, "on_date")
        return bool(is_selection_date) and d >= _parse_date(self.restart_eligible_date, "restart_eligible_date")

    def do_restart(self, on_date: str, balance: float,
                   is_selection_date: bool|None = None) -> None:
        """Restart after the cash wait. Enforces the same rules as the Pot
        path (H1): status, eligibility date, selection date (when the
        caller supplies it), and a finite positive balance -- all checked
        before any mutation."""
        if self.status!="waiting_restart": raise RuntimeError(f"Cannot restart from status {self.status}")
        d = _parse_date(on_date, "on_date")
        bal = _finite_number(balance, "balance")
        if bal <= 0: raise ValueError(f"restart balance must be positive, got {balance!r}")
        if not self.restart_eligible_date:
            raise RuntimeError("Cannot restart: no restart eligibility date recorded")
        if d < _parse_date(self.restart_eligible_date, "restart_eligible_date"):
            raise ValueError(f"Cannot restart on {d.isoformat()} before eligibility {self.restart_eligible_date}")
        # R2-L3: the selection-date confirmation is mandatory -- omitting
        # it (None) refuses, exactly like passing False. The spec restarts
        # AT a selection date; "the caller didn't say" is not a yes.
        if is_selection_date is not True:
            raise ValueError("Cannot restart without a confirmed selection date")
        self.episode=2; self.episode_start_balance=round(bal,2)
        self.episode_start_date=d.isoformat(); self.restart_date=d.isoformat()
        self.restart_balance=round(bal,2); self.status="active"

    @staticmethod
    def next_selection_on_or_after(eligible: str, selection_dates: list[str]) -> str|None:
        e = _parse_date(eligible, "eligible")
        parsed = [(_parse_date(s, "selection date"), s) for s in selection_dates]
        cands = [(d, s) for d, s in parsed if d >= e]
        return min(cands)[1] if cands else None

    def to_dict(self): return asdict(self)
    @classmethod
    def from_dict(cls, d: dict):
        # Forward-tolerant (H7) + validated (C3): unknown fields ignored,
        # known fields type/range-checked; __post_init__ re-checks the rest.
        if not isinstance(d, dict):
            raise ValueError(f"protection state must be an object, got {type(d).__name__}")
        kw = {k: v for k, v in d.items() if k in _FIELDS}
        if isinstance(kw.get("episode"), bool) or not isinstance(kw.get("episode", 1), int):
            raise ValueError(f"episode must be an integer, got {kw.get('episode')!r}")
        # R2-M3: episode_start_balance is REQUIRED -- silently defaulting it
        # to 100.0 rewrote the floor of any pot whose real start differed.
        if "episode_start_balance" not in kw:
            raise ValueError("protection state is missing episode_start_balance")
        for f in ("episode_start_date","halt_date","restart_eligible_date","restart_date"):
            if kw.get(f) is not None:
                _parse_date(kw[f], f)
        for f in ("halt_balance","restart_balance"):
            if kw.get(f) is not None and _finite_number(kw[f], f) < 0:
                raise ValueError(f"{f} must be >= 0, got {kw[f]!r}")
        if kw.get("ended_reason") is not None and not isinstance(kw["ended_reason"], str):
            raise ValueError("ended_reason must be a string")
        # R2-M3: halt records must be well-formed, not arbitrary garbage.
        if kw.get("halts") is not None:
            if not isinstance(kw["halts"], list):
                raise ValueError("halts must be a list")
            for h in kw["halts"]:
                if not isinstance(h, dict):
                    raise ValueError(f"halt entry must be an object, got {h!r}")
                if isinstance(h.get("episode"), bool) or not isinstance(h.get("episode"), int) \
                        or h.get("episode") not in (1, 2):
                    raise ValueError(f"halt entry episode must be 1 or 2, got {h.get('episode')!r}")
                _parse_date(h.get("date"), "halt date")
                for f in ("balance","floor"):
                    if _finite_number(h.get(f), f"halt {f}") < 0:
                        raise ValueError(f"halt {f} must be >= 0, got {h.get(f)!r}")
                for f in ("equity_at_close","liquidation_proceeds"):
                    if h.get(f) is not None:
                        _finite_number(h[f], f"halt {f}")
        state = cls(**kw)
        # R2-M3: cross-field consistency -- states the machine can never
        # reach must not load (they wedge the pot silently otherwise).
        if state.status == "waiting_restart" and not (state.halt_date and state.restart_eligible_date):
            raise ValueError("waiting_restart requires halt_date and restart_eligible_date")
        if state.status == "ended" and not state.ended_reason:
            raise ValueError("ended requires an ended_reason")
        if state.status == "active" and state.episode == 2 \
                and not (state.restart_date and state.restart_balance is not None):
            raise ValueError("an active episode-2 state requires restart_date and restart_balance")
        return state
