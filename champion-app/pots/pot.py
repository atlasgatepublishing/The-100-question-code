"""Pot: one strategy's own $100, its cash, positions and full trade log.

PAPER / REPLAY ONLY. No live-broker order endpoints, no real-money capability.

Rules (DESIGN.md + adopted v9 protection):
  * Hard budget: a pot can only spend its OWN cash. No borrowing, no top-ups.
  * Fractional shares allowed.
  * Program costs, exactly as in the backtests: 0.10% of trade value per side,
    plus a flat $0.01 per SELL ORDER (backtest constant SELL_FEE = 0.01,
    "per sell order" -- momentum-basket-honest.py:67 etc.). NOTE: the task
    brief paraphrased this as "$0.01/share"; the backtest code on disk is
    unambiguous that it is $0.01 per sell order, so that is what runs here.
  * Cash is charged the SAME cent-rounded amounts the ledger records, so
    cash and ledger always reconcile (QA Area 1, M2).
  * Every state change is persisted atomically to app/state/<pot_id>.json
    (unique temp file + os.replace). Pot.load() restores the exact state.
    A failed save rolls the in-memory mutation back, so memory and disk
    never diverge (QA Area 1, C4).

QA hardening (Area 1, 2026-11-21): buy/sell/liquidate share one validation
guard (positive, finite shares and price; valid ISO trade date; a sell may
never drive cash negative); equity() compares UNROUNDED values against the
floor and raises on a missing/non-positive price for a held symbol instead
of silently valuing at cost; load() fully validates the saved state
(StateCorrupt on anything off, cross-pot pot_id mismatch refused); pot_id
is restricted to a plain identifier so it can never escape the state dir;
save() writes strict JSON (allow_nan=False), keeps a .bak of the previous
good file, uses a unique temp name, and refuses to overwrite state that
another Pot object saved since this one loaded (stale-object guard).
"""
from __future__ import annotations
import copy, json, math, os, re, threading, uuid
from datetime import date
from pathlib import Path
from .ledger import Ledger, Trade
from .protection import ProtectionState

COST_RATE = 0.001      # 0.10% per side
SELL_FEE = 0.01        # flat, per sell order (backtests)
STATE_DIR = Path(__file__).resolve().parent.parent / "state"
SCHEMA_VERSION = 1
_POT_ID_RE = re.compile(r"[a-z0-9_]{1,64}")  # used with fullmatch (R2-L2: "$" allowed a trailing newline)
_SAVE_LOCKS: dict[str, threading.Lock] = {}
_SAVE_LOCKS_GUARD = threading.Lock()
# R2-M2 (residual closed in the final QA pass): the highest
# save_generation this PROCESS has loaded or saved per state path. A
# byte-identical manual restore of a .bak makes the file's content
# match a stale object's token again (classic ABA) — but it cannot
# rewind this registry, so a save that would silently erase a newer
# generation is refused, and a load that sees a rewound file is
# flagged on the object (rolled_back_detected). Cross-process ABA
# remains bounded by the .bak/generation record on disk alone.
_PATH_GENERATIONS: dict[str, int] = {}
_PATH_GENERATIONS_LOCK = threading.Lock()


def _note_generation(path: Path, gen: int) -> None:
    with _PATH_GENERATIONS_LOCK:
        key = str(path)
        if gen > _PATH_GENERATIONS.get(key, -1):
            _PATH_GENERATIONS[key] = gen


def _known_generation(path: Path) -> int:
    with _PATH_GENERATIONS_LOCK:
        return _PATH_GENERATIONS.get(str(path), -1)

class InsufficientFunds(Exception): pass
class PotHalted(Exception): pass
class StateCorrupt(Exception):
    """Saved pot state is missing, malformed, or fails validation (H7)."""
class StaleStateError(Exception):
    """Another Pot object saved newer state for this pot id (C5)."""

def _validate_pot_id(pot_id) -> str:
    if not isinstance(pot_id, str) or not _POT_ID_RE.fullmatch(pot_id):
        raise ValueError(f"pot_id must be a plain identifier [a-z0-9_] of 1-64 chars, got {pot_id!r}")
    return pot_id

def _finite(value, field_name) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field_name} must be a finite number, got {value!r}")
    return float(value)

def _finite_positive(value, field_name) -> float:
    v = _finite(value, field_name)
    if v <= 0: raise ValueError(f"{field_name} must be positive, got {value!r}")
    return v

def _validate_trade_date(on_date, field_name="on_date") -> str:
    if not isinstance(on_date, str):
        raise ValueError(f"{field_name} must be an ISO date string, got {on_date!r}")
    try:
        return date.fromisoformat(on_date).isoformat()
    except ValueError:
        raise ValueError(f"{field_name} is not a valid ISO date: {on_date!r}") from None

def _save_lock(key: str) -> threading.Lock:
    with _SAVE_LOCKS_GUARD:
        return _SAVE_LOCKS.setdefault(key, threading.Lock())

class Pot:
    def __init__(self, pot_id: str, name: str, start_balance: float=100.0,
                 start_date: str|None=None, track_only: bool=False,
                 state_dir: Path|None=None, protection: ProtectionState|None=None,
                 cash: float|None=None, positions: dict|None=None,
                 ledger: Ledger|None=None, meta: dict|None=None):
        _validate_pot_id(pot_id)
        sb = _finite_positive(start_balance, "start_balance")
        if start_date is not None: _validate_trade_date(start_date, "start_date")
        if cash is not None and _finite(cash, "cash") < 0:
            raise ValueError(f"cash must be >= 0, got {cash!r}")
        # R2-C1: track_only must be a REAL bool -- bool("false") is True and
        # bool(0) is False, so coercing a mistyped value silently flipped
        # the floor off (or made the watch pot tradable).
        if not isinstance(track_only, bool):
            raise ValueError(f"track_only must be a boolean, got {track_only!r}")
        clean_positions = {}
        for sym, pos in (positions or {}).items():
            if not isinstance(sym, str) or not sym:
                raise ValueError(f"position symbol must be a non-empty string, got {sym!r}")
            if not isinstance(pos, dict) or "shares" not in pos or "avg_cost" not in pos:
                raise ValueError(f"position {sym!r} must have shares and avg_cost")
            sh = _finite_positive(pos["shares"], f"position {sym} shares")
            ac = _finite(pos["avg_cost"], f"position {sym} avg_cost")
            if ac < 0: raise ValueError(f"position {sym} avg_cost must be >= 0")
            clean_positions[sym] = {"shares": sh, "avg_cost": ac}
        self.pot_id=pot_id; self.name=name
        self.start_balance=sb
        self.start_date=start_date
        self.track_only=track_only
        self.cash=float(sb if cash is None else cash)
        self.positions: dict[str,dict]=clean_positions  # sym -> {shares, avg_cost}
        self.ledger=ledger or Ledger()
        self.meta=dict(meta) if meta else {}
        self.protection=protection or ProtectionState(
            episode_start_balance=sb, episode_start_date=start_date)
        self.state_dir=Path(state_dir) if state_dir else STATE_DIR
        # copy (L3): never mutate the caller's meta dict
        raw_last_prices = self.meta.pop("last_prices", {})
        if not isinstance(raw_last_prices, dict):
            raise ValueError(f"last_prices must be an object, got {raw_last_prices!r}")
        # R2-L4: last_prices validated HERE, not at first valuation --
        # a string/negative/NaN mark must fail at construction/load.
        self.last_prices: dict[str,float]={}
        for sym, px in raw_last_prices.items():
            if not isinstance(sym, str) or not sym:
                raise ValueError(f"last_prices symbol must be a non-empty string, got {sym!r}")
            self.last_prices[sym]=_finite_positive(px, f"last_prices[{sym}]")
        self._disk_token: str|None=None  # content this object loaded/last saved
        self._save_generation: int=0     # monotonic save counter persisted in state (R2-M2)
        self.rolled_back_detected: bool=False  # set by load() on a rewound file (R2-M2)
        self.recovered_from_bak: bool=False  # set by load() when the .bak saved us (R2-M1)

    # ---- valuation ----
    def _unrounded_equity(self, prices: dict[str,float]|None=None) -> float:
        p = prices if prices is not None else self.last_prices
        total=self.cash
        for sym,pos in self.positions.items():
            if sym not in p:
                raise ValueError(f"{self.pot_id}: no price supplied for held symbol {sym}; refusing to value at cost")
            px=_finite_positive(p[sym], f"price for {sym}")
            total+=pos["shares"]*px
        return total

    def equity(self, prices: dict[str,float]|None=None) -> float:
        return round(self._unrounded_equity(prices),2)

    # ---- trading (simulation fills at a supplied price) ----
    def _require_active(self):
        if self.track_only: raise PotHalted(f"{self.pot_id} is track-only; trading is disabled")
        if self.protection.status not in ("active",):
            if self.protection.status=="ended": raise PotHalted(f"{self.pot_id} ended permanently ({self.protection.ended_reason})")
            if self.protection.status=="waiting_restart": raise PotHalted(f"{self.pot_id} is in its 90-day cash wait until {self.protection.restart_eligible_date}")
            raise PotHalted(f"{self.pot_id} has unknown protection status {self.protection.status!r}")

    @staticmethod
    def _validate_order(shares, price, on_date):
        sh=_finite_positive(shares, "shares"); px=_finite_positive(price, "price")
        return sh, px, _validate_trade_date(on_date)

    # Snapshot/restore so a failed save rolls the mutation back (C4).
    def _snapshot_state(self):
        return (self.cash, copy.deepcopy(self.positions), list(self.ledger.trades),
                copy.deepcopy(self.protection), dict(self.last_prices))
    def _restore_state(self, snap):
        self.cash, self.positions, trades, self.protection, self.last_prices = snap
        self.ledger.trades = trades

    @staticmethod
    def _validate_symbol(symbol) -> str:
        # R2-L5: a non-string symbol used to die later with a raw
        # AttributeError (or trade under a bytes key); refuse it cleanly.
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError(f"symbol must be a non-empty string, got {symbol!r}")
        return symbol.upper()

    def buy(self, symbol: str, shares: float, price: float, on_date: str, reason: str="") -> Trade:
        self._require_active(); symbol=self._validate_symbol(symbol)
        shares, price, on_date = self._validate_order(shares, price, on_date)
        gross_r=round(shares*price,2); cost_r=round(shares*price*COST_RATE,2); total_r=round(gross_r+cost_r,2)
        if total_r > self.cash + 1e-9:
            raise InsufficientFunds(f"{self.pot_id}: need ${total_r:.2f}, has ${self.cash:.2f} (hard budget)")
        snap=self._snapshot_state()
        try:
            self.cash=round(self.cash-total_r,10)
            pos=self.positions.get(symbol, {"shares":0.0,"avg_cost":0.0})
            new_shares=pos["shares"]+shares
            pos["avg_cost"]=round((pos["shares"]*pos["avg_cost"]+shares*price)/new_shares,10) if new_shares else 0.0
            pos["shares"]=new_shares; self.positions[symbol]=pos; self.last_prices[symbol]=price
            t=Trade(on_date,symbol,"buy",shares,price,gross_r,cost_r,round(-total_r,2),reason)
            self.ledger.add(t); self.save(); return t
        except Exception:
            self._restore_state(snap); raise

    def buy_value(self, symbol: str, dollars: float, price: float, on_date: str, reason: str="") -> Trade:
        """Buy as close to `dollars` of value as the hard budget allows (fractional)."""
        d=_finite_positive(dollars, "dollars"); px=_finite_positive(price, "price")
        return self.buy(symbol, d/px, px, on_date, reason)

    def sell(self, symbol: str, shares: float, price: float, on_date: str, reason: str="") -> Trade:
        self._require_active(); symbol=self._validate_symbol(symbol)
        shares, price, on_date = self._validate_order(shares, price, on_date)
        pos=self.positions.get(symbol)
        if not pos or shares > pos["shares"]+1e-9: raise ValueError(f"{self.pot_id}: cannot sell {shares} of {symbol}; holds {pos['shares'] if pos else 0}")
        gross_r=round(shares*price,2); cost_r=round(shares*price*COST_RATE+SELL_FEE,2); net_r=round(gross_r-cost_r,2)
        if net_r < 0 or self.cash + net_r < -1e-9:
            raise ValueError(f"{self.pot_id}: sell net proceeds ${net_r:.2f} would drive cash negative; refused")
        snap=self._snapshot_state()
        try:
            self.cash=round(self.cash+net_r,10)
            pos["shares"]=round(pos["shares"]-shares,10)
            if pos["shares"]<=1e-12: del self.positions[symbol]
            self.last_prices[symbol]=price
            t=Trade(on_date,symbol,"sell",shares,price,gross_r,cost_r,net_r,reason)
            self.ledger.add(t); self.save(); return t
        except Exception:
            self._restore_state(snap); raise

    def _liquidate_impl(self, prices: dict[str,float], on_date: str,
                        reason: str="halt_liquidation") -> list[Trade]:
        """Mutation-only liquidation (NO save). Callers own persistence, so
        a halt composes liquidation + protection update + ONE save (R2-C2).

        Every held symbol must have a finite positive price (H5), checked
        BEFORE anything is sold, so a bad price cannot half-liquidate.
        R2-H1: if total fees exceed total proceeds (a dust position in a
        wiped-out pot), the halt must still complete -- cash is floored at
        $0 and the shortfall is absorbed into the final liquidation trade's
        net (and noted in its reason), so cash and ledger still reconcile
        to the cent. An ordinary sell() keeps its H6 refusal; only the
        halt's own liquidation may absorb."""
        plan=[]
        for sym in list(self.positions):
            if sym not in prices:
                raise ValueError(f"{self.pot_id}: no liquidation price for held symbol {sym}; refusing to invent one")
            px=_finite_positive(prices[sym], f"liquidation price for {sym}")
            pos=self.positions[sym]
            gross_r=round(pos["shares"]*px,2); cost_r=round(pos["shares"]*px*COST_RATE+SELL_FEE,2)
            plan.append([sym,pos,px,gross_r,cost_r,round(gross_r-cost_r,2),reason])
        if plan:
            shortfall=-(self.cash + sum(p[5] for p in plan))
            if shortfall > 1e-9:
                plan[-1][5]=round(plan[-1][5]+shortfall,2)
                plan[-1][6]=f"{reason} [fee shortfall ${shortfall:.2f} absorbed at liquidation; cash floored at $0]"
        out=[]
        for sym,pos,px,gross_r,cost_r,net_r,rsn in plan:
            self.cash=round(self.cash+net_r,10)
            t=Trade(on_date,sym,"sell",pos["shares"],px,gross_r,cost_r,net_r,rsn)
            self.ledger.add(t); out.append(t); del self.positions[sym]; self.last_prices[sym]=px
        return out

    def liquidate(self, prices: dict[str,float], on_date: str, reason: str="halt_liquidation") -> list[Trade]:
        """Sell everything at supplied prices and persist. Bypasses the
        active check (it IS the halt action). One snapshot, one save: a
        failed save rolls everything back (C4)."""
        on_date=_validate_trade_date(on_date)
        snap=self._snapshot_state()
        try:
            out=self._liquidate_impl(prices, on_date, reason)
            self.save(); return out
        except Exception:
            self._restore_state(snap); raise

    # ---- daily protection cycle ----
    def on_daily_close(self, on_date: str, prices: dict[str,float],
                       is_selection_date: bool=False) -> str:
        """Update marks; restart if due; else halt-check on closing equity.
        Returns: 'restarted' | 'halt' | 'ended' | 'ok' | 'waiting' | 'track_only'.

        All inputs are validated before any mutation (M3/C2): the date must
        be a valid ISO date, every supplied price finite positive, and the
        floor comparison uses UNROUNDED equity (M1). A failed save rolls
        the whole close back (C4)."""
        on_date=_validate_trade_date(on_date)
        clean_prices={}
        for sym, px in (prices or {}).items():
            clean_prices[sym]=_finite_positive(px, f"price for {sym}")
        snap=self._snapshot_state()
        try:
            self.last_prices.update(clean_prices)
            if self.track_only: self.save(); return "track_only"
            if self.protection.status=="waiting_restart":
                if self.protection.is_restart_due(on_date, is_selection_date):
                    if self.cash > 0:
                        self.protection.do_restart(on_date, self.cash, is_selection_date=is_selection_date)
                        self.save(); return "restarted"
                    # R2-H2: a pot wiped out to exactly $0.00 has nothing to
                    # restart with. End the run in a stable state instead of
                    # raising on every close forever.
                    self.protection.status="ended"
                    self.protection.ended_reason="wiped_out_zero_balance"
                    self.save(); return "ended"
                self.save(); return "waiting"
            if self.protection.status=="ended": self.save(); return "ended"
            if self.protection.status!="active":
                raise StateCorrupt(f"{self.pot_id}: unknown protection status {self.protection.status!r}")
            eq=self._unrounded_equity(clean_prices)
            if self.protection.check_close(on_date, eq)=="halt":
                equity_at_close=self.protection.halt_balance
                # R2-C2: liquidation WITHOUT its own save -- the halt is
                # protection update + liquidation + the single save below,
                # so a failed save rolls back memory AND leaves disk
                # untouched. (Previously liquidate() saved mid-close and a
                # failed second save left disk halted, memory active, and
                # the next trade silently erased the halt.)
                if self.positions: self._liquidate_impl(clean_prices, on_date)
                # liquidation proceeds are the halt balance going forward;
                # the triggering close is kept separately (M8)
                self.protection.halt_balance=round(self.cash,2)
                if self.protection.halts:
                    self.protection.halts[-1]["balance"]=round(self.cash,2)
                    self.protection.halts[-1]["equity_at_close"]=equity_at_close
                    self.protection.halts[-1]["liquidation_proceeds"]=round(self.cash,2)
                self.save(); return "ended" if self.protection.status=="ended" else "halt"
            self.save(); return "ok"
        except Exception:
            self._restore_state(snap); raise

    # ---- persistence (atomic: unique temp + rename) ----
    def state_path(self) -> Path: return self.state_dir/f"{self.pot_id}.json"
    def to_dict(self) -> dict:
        return {"schema_version":SCHEMA_VERSION, "save_generation":self._save_generation,
            "pot_id":self.pot_id,"name":self.name,"start_balance":self.start_balance,
            "start_date":self.start_date,"track_only":self.track_only,"cash":self.cash,
            "positions":self.positions,"ledger":self.ledger.to_list(),
            "protection":self.protection.to_dict(),
            "meta":{**self.meta,"last_prices":self.last_prices}}
    def save(self) -> Path:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        path=self.state_path()
        with _save_lock(str(path)):
            if path.exists():
                current=path.read_bytes()
                # R2-H3: an object that never loaded this pot's state may
                # not clobber the file -- the constructor path bypassed the
                # stale guard entirely because its token was None.
                if self._disk_token is None:
                    raise StaleStateError(
                        f"{self.pot_id}: state already exists on disk and this object never "
                        "loaded it; refusing to overwrite (load first)")
                if current != self._disk_token.encode():
                    raise StaleStateError(
                        f"{self.pot_id}: state on disk changed since this object loaded it; "
                        "refusing to overwrite another object's trades (reload first)")
                # R2-M2/ABA: content matches our token, but this process
                # has seen a NEWER generation of this file than the one
                # now on disk — the file was rolled back byte-for-byte
                # (e.g. a .bak restored over it). Refuse: saving would
                # silently erase the newer object's trades.
                try:
                    disk_gen = json.loads(current).get("save_generation")
                except Exception:
                    disk_gen = None
                if isinstance(disk_gen, int) and not isinstance(disk_gen, bool) \
                        and _known_generation(path) > disk_gen:
                    raise StaleStateError(
                        f"{self.pot_id}: state file was rolled back to generation "
                        f"{disk_gen}, but generation {_known_generation(path)} was "
                        "already saved in this process; refusing to erase it "
                        "(reload first)")
                # keep the previous good file as a backup (H7)
                bak=path.with_suffix(".json.bak")
                tmp_bak=path.with_name(f"{self.pot_id}.{os.getpid()}.{uuid.uuid4().hex}.bak.tmp")
                tmp_bak.write_bytes(current); os.replace(tmp_bak, bak)
            # R2-M2: a persisted monotonic generation makes a rolled-back
            # file VISIBLE at load time (generation lower than the .bak's).
            self._save_generation += 1
            try:
                # allow_nan=False (M4): a non-finite state fails HERE, never on disk.
                text=json.dumps(self.to_dict(), indent=1, sort_keys=True, allow_nan=False)
                tmp=path.with_name(f"{self.pot_id}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
                try:
                    tmp.write_text(text); os.replace(tmp, path)  # atomic rename, same filesystem
                finally:
                    if tmp.exists(): tmp.unlink()
            except Exception:
                self._save_generation -= 1; raise
            self._disk_token=text
            _note_generation(path, self._save_generation)
        return path
    @classmethod
    def _from_raw(cls, raw: str, pot_id: str, d: Path, disk_token: str|None) -> "Pot":
        try:
            data=json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            raise StateCorrupt(f"{pot_id}: state file is not valid JSON: {e}") from e
        _validate_state(data, pot_id)
        try:
            pot=cls(pot_id=data["pot_id"], name=data["name"], start_balance=data["start_balance"],
                start_date=data.get("start_date"), track_only=data.get("track_only",False),
                state_dir=d, cash=data["cash"], positions=data["positions"],
                ledger=Ledger.from_list(data["ledger"]),
                protection=ProtectionState.from_dict(data["protection"]), meta=data.get("meta") or {})
        except StateCorrupt:
            raise
        except Exception as e:
            raise StateCorrupt(f"{pot_id}: saved state failed validation: {type(e).__name__}: {e}") from e
        pot._disk_token=disk_token
        gen=data.get("save_generation")
        pot._save_generation=gen if isinstance(gen,int) and not isinstance(gen,bool) and gen>=0 else 0
        # R2-M2/ABA visibility: a file rewound below a generation this
        # process already saw is flagged on the loaded object.
        path = d / f"{pot_id}.json"
        pot.rolled_back_detected = _known_generation(path) > pot._save_generation
        _note_generation(path, pot._save_generation)
        return pot

    @classmethod
    def load(cls, pot_id: str, state_dir: Path|None=None) -> "Pot":
        _validate_pot_id(pot_id)
        d=Path(state_dir) if state_dir else STATE_DIR
        main=d/f"{pot_id}.json"; bak=d/f"{pot_id}.json.bak"
        raw=None; main_error=None
        if main.exists():
            try:
                raw=main.read_text()
            except FileNotFoundError:
                raw=None  # raced deletion: fall through to the .bak
            except (UnicodeDecodeError, OSError) as e:
                # R2-L1: typed errors, never raw UnicodeDecodeError /
                # IsADirectoryError escaping to the caller.
                main_error=StateCorrupt(f"{pot_id}: state file unreadable: {type(e).__name__}: {e}")
        if raw is not None:
            try:
                return cls._from_raw(raw, pot_id, d, disk_token=raw)
            except StateCorrupt as e:
                main_error=e
        # R2-M1: the .bak is a real recovery path. A corrupt/missing main
        # falls back to the last known-good file, loudly (recovered_from_bak),
        # instead of bricking the pot -- or worse, letting build_pot mint a
        # fresh $100 pot over a halted pot's history.
        if bak.exists():
            try:
                bak_raw=bak.read_text()
            except (UnicodeDecodeError, OSError):
                bak_raw=None
            if bak_raw is not None:
                try:
                    pot=cls._from_raw(bak_raw, pot_id, d, disk_token=raw)
                    pot.recovered_from_bak=True
                    return pot
                except StateCorrupt:
                    pass
        if main_error is not None:
            raise main_error
        raise FileNotFoundError(f"{pot_id}: no state file at {main}")
    def snapshot(self) -> dict:
        """Canonical comparable snapshot (used by the persistence test).
        Excludes save_generation: it changes on every save by design, so
        including it would make a load/save round-trip never compare equal."""
        d = json.loads(json.dumps(self.to_dict(), sort_keys=True))
        d.pop("save_generation", None)
        return d

def _validate_state(data, requested_pot_id: str) -> None:
    """Full schema validation of a loaded state dict (C3/H2/H7).

    Raises StateCorrupt on anything missing, mistyped, non-finite, or
    inconsistent. Unknown top-level fields are tolerated (forward compat)."""
    if not isinstance(data, dict):
        raise StateCorrupt(f"{requested_pot_id}: state must be a JSON object, got {type(data).__name__}")
    # R2-M4: the version stamp is CHECKED -- a file written by a newer app
    # (version 2, 999, "1") must not be silently traded on by this one.
    # (Absent = a legacy pre-versioning file, accepted.)
    if "schema_version" in data:
        v=data["schema_version"]
        if isinstance(v, bool) or not isinstance(v, int) or v != SCHEMA_VERSION:
            raise StateCorrupt(f"{requested_pot_id}: unsupported schema_version {v!r} (this app writes {SCHEMA_VERSION})")
    if "save_generation" in data:
        g=data["save_generation"]
        if isinstance(g, bool) or not isinstance(g, int) or g < 0:
            raise StateCorrupt(f"{requested_pot_id}: save_generation must be a non-negative integer, got {g!r}")
    # R2-C1: track_only must be a real boolean when present.
    if "track_only" in data and not isinstance(data["track_only"], bool):
        raise StateCorrupt(f"{requested_pot_id}: track_only must be a boolean, got {data['track_only']!r}")
    for field_name in ("pot_id","name","start_balance","cash","positions","ledger","protection"):
        if field_name not in data:
            raise StateCorrupt(f"{requested_pot_id}: state is missing required field {field_name!r}")
    if data["pot_id"] != requested_pot_id:
        raise StateCorrupt(
            f"pot_id mismatch: file for {requested_pot_id!r} contains pot_id {data['pot_id']!r}; refusing cross-pot load")
    if not isinstance(data["name"], str):
        raise StateCorrupt(f"{requested_pot_id}: name must be a string")
    if _state_num(data["start_balance"], "start_balance", requested_pot_id) <= 0:
        raise StateCorrupt(f"{requested_pot_id}: start_balance must be positive")
    cash = data["cash"]
    if cash is None:
        raise StateCorrupt(f"{requested_pot_id}: cash is null; refusing to substitute the start balance")
    if _state_num(cash, "cash", requested_pot_id) < 0:
        raise StateCorrupt(f"{requested_pot_id}: cash must be >= 0, got {cash!r}")
    if not isinstance(data["positions"], dict):
        raise StateCorrupt(f"{requested_pot_id}: positions must be an object")
    for sym, pos in data["positions"].items():
        if not isinstance(pos, dict) or "shares" not in pos or "avg_cost" not in pos:
            raise StateCorrupt(f"{requested_pot_id}: position {sym!r} must have shares and avg_cost")
        if _state_num(pos["shares"], f"position {sym} shares", requested_pot_id) <= 0:
            raise StateCorrupt(f"{requested_pot_id}: position {sym} shares must be positive")
        if _state_num(pos["avg_cost"], f"position {sym} avg_cost", requested_pot_id) < 0:
            raise StateCorrupt(f"{requested_pot_id}: position {sym} avg_cost must be >= 0")
    if not isinstance(data["ledger"], list):
        raise StateCorrupt(f"{requested_pot_id}: ledger must be a list")
    if not isinstance(data["protection"], dict):
        raise StateCorrupt(f"{requested_pot_id}: protection must be an object")
    prot = data["protection"]
    if prot.get("status") not in ("active","waiting_restart","ended"):
        raise StateCorrupt(f"{requested_pot_id}: protection status must be active/waiting_restart/ended, got {prot.get('status')!r}")
    if isinstance(prot.get("episode"), bool) or prot.get("episode") not in (1, 2):
        raise StateCorrupt(f"{requested_pot_id}: protection episode must be 1 or 2, got {prot.get('episode')!r}")
    if "episode_start_balance" not in prot:
        raise StateCorrupt(f"{requested_pot_id}: protection is missing episode_start_balance")
    esb = _state_num(prot["episode_start_balance"], "episode_start_balance", requested_pot_id)
    if esb < 0 or (esb == 0 and prot.get("restart_balance") != 0):
        raise StateCorrupt(f"{requested_pot_id}: episode_start_balance must be positive, got {esb!r}")
    # R2-M3: cross-field consistency -- the floor base is not a free
    # variable. Episode 1's base IS the start balance; episode 2's base IS
    # the restart balance. Round 1's tamper (base 10000 on a $100 pot ->
    # an $8,500 floor) passed every per-field check; it fails this one.
    if prot.get("episode") == 1 and abs(esb - float(data["start_balance"])) > 0.005:
        raise StateCorrupt(
            f"{requested_pot_id}: episode-1 episode_start_balance {esb!r} does not equal "
            f"start_balance {data['start_balance']!r}; refusing a rewritten floor")
    if prot.get("episode") == 2:
        rb = prot.get("restart_balance")
        if rb is None:
            raise StateCorrupt(f"{requested_pot_id}: episode 2 requires restart_balance")
        if _state_num(rb, "restart_balance", requested_pot_id) < 0:
            raise StateCorrupt(f"{requested_pot_id}: restart_balance must be >= 0, got {rb!r}")
        if abs(esb - float(rb)) > 0.005:
            raise StateCorrupt(
                f"{requested_pot_id}: episode-2 episode_start_balance {esb!r} does not equal "
                f"restart_balance {rb!r}; refusing a rewritten floor")

def _state_num(value, field_name, pot_id) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise StateCorrupt(f"{pot_id}: {field_name} must be a finite number, got {value!r}")
    return float(value)

def spy_shadow_value(start_balance: float, spy_start_price: float, spy_current_price: float) -> float:
    """Running SPY shadow mark: same dollars, buy-and-hold SPY (DESIGN.md benchmark)."""
    sb=_finite_positive(start_balance, "start_balance")
    start=_finite_positive(spy_start_price, "spy_start_price")
    cur=_finite_positive(spy_current_price, "spy_current_price")
    return round(sb * cur / start, 2)
