"""Alpaca broker adapter -- the ONLY module that can place an order.

Isolated in data/ on purpose: engines and pots never see a broker. The
adapter is selected by trading mode (data/mode.py):

  * PAPER mode -> https://paper-api.alpaca.markets, using the user's own
    Alpaca PAPER keys from config.local.json.
  * LIVE mode  -> https://api.alpaca.markets, using the user's own Alpaca
    LIVE keys from the same file. Live is reachable only when the mode
    module's fail-safe check passes (mode set to live AND live keys
    present and well-formed); otherwise from_config() returns the paper
    client.

Every order passes mode.orders_permitted() first, with the config
RE-RESOLVED at submit time: a client built while live refuses to trade
if the user has since switched back to paper, removed/rotated the keys,
or the effective mode no longer matches the client's mode. While STOP
ALL is set, submit_order() raises before any network call is made.
Submission is serialised against STOP ALL through mode.order_gate():
a stop either lands before the order's final gate check (order refused,
zero broker calls) or waits until the in-flight order completes.
Stopping never liquidates -- this adapter exposes no "sell everything"
path, and the dashboard's STOP ALL only sets the flag.

Every order carries a client_order_id (a uuid by default; a caller may
supply its own for safe retries), so a retry after a timeout cannot
silently duplicate an order at the broker. A transport failure during
submit raises AlpacaError with outcome_unknown=True: the order may or
may not have reached Alpaca, and open orders must be checked before
retrying.

Standard library only (urllib), so it runs anywhere the dashboard runs.
Keys travel only in request headers to Alpaca's own endpoint; they are
never logged, never put in URLs, and never shown in reprs or errors --
any error text the adapter emits (broker bodies, wrapped transport
exceptions) is scrubbed of this client's key/secret values first.
"""
from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from . import mode as _mode

PAPER_BASE = "https://paper-api.alpaca.markets"
LIVE_BASE = "https://api.alpaca.markets"

_ORDER_TYPES = ("market", "limit", "stop", "stop_limit", "trailing_stop")
_TIME_IN_FORCE = ("day", "gtc", "opg", "cls", "ioc", "fok")
_SYMBOL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.\-]{0,14}$")

_STOP_MSG = ("STOP ALL is set: the engine is stopped and no orders will "
             "be placed. Positions are untouched; resume from the "
             "dashboard when ready.")


class AlpacaError(RuntimeError):
    """Broker/adapter failure. `outcome_unknown` is True when a submit
    may have reached the broker despite the error (timeout, reset):
    check open orders before retrying -- a blind retry can duplicate."""

    def __init__(self, message: str, *, outcome_unknown: bool = False):
        super().__init__(message)
        self.outcome_unknown = outcome_unknown


def _default_transport(method: str, url: str, headers: dict,
                       body: bytes | None) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


class AlpacaClient:
    """One client per account type. Construct via from_config()."""

    def __init__(self, account_mode: str, key_id: str, secret: str,
                 transport=None, stop_check=None, state_dir=None,
                 config_path=None, cfg_snapshot: dict | None = None):
        if account_mode not in (_mode.PAPER, _mode.LIVE):
            raise ValueError(f"unknown account mode: {account_mode!r}")
        if stop_check is not None and state_dir is None:
            # R2-N5: a custom stop_check pointing at one state dir while
            # the order gate serialises against another (the default)
            # would silently break the STOP ALL interlock. Refuse the
            # ambiguous combination outright.
            raise ValueError(
                "pass state_dir together with stop_check, so the stop "
                "flag the client reads and the order gate it serialises "
                "against are the same state directory")
        label = "LIVE" if account_mode == _mode.LIVE else "PAPER"
        if not _mode.valid_key_id(key_id) or not _mode.valid_secret(secret):
            raise AlpacaError(
                f"no valid Alpaca {label} keys in config.local.json "
                "(missing, blank, or malformed) -- refusing to build a client")
        self.mode = account_mode
        self.base = LIVE_BASE if account_mode == _mode.LIVE else PAPER_BASE
        self._key_id = key_id
        self._secret = secret
        self._transport = transport or _default_transport
        self._stop_check = stop_check or (lambda: _mode.is_stopped(state_dir))
        self._state_dir = Path(state_dir) if state_dir else None
        self._config_path = Path(config_path) if config_path else None
        self._cfg_snapshot = dict(cfg_snapshot) if isinstance(cfg_snapshot, dict) else None
        self._built_epoch = _mode.config_write_epoch()
        # Sticky revocation latch (R2-N2/N3): set the first time any
        # config write through data.mode stops permitting this client;
        # never cleared -- only a rebuilt client trades again.
        self._revoked = False
        # In-process record of client_order_ids already submitted by
        # this client (R2-N7): a caller reusing one is refused locally
        # instead of relying on broker-side dedup (unverified).
        self._used_order_ids: set[str] = set()
        # Extra values scrubbed from error text: BOTH accounts' pairs
        # from the config this client was built from (R2-N4c).
        self._scrub_extra: set[str] = set()
        # The SECRET subset of the scrub set, for the fragment tripwire.
        self._scrub_secrets: set[str] = {secret}

    def __repr__(self):
        return (f"AlpacaClient(mode={self.mode!r}, base={self.base!r}, "
                f"keys='set')")  # key material is never shown

    @classmethod
    def from_config(cls, cfg: dict | None = None, transport=None,
                    state_dir: Path | None = None,
                    config_path: Path | None = None) -> "AlpacaClient":
        """Build the client for the EFFECTIVE mode (fail-safe: paper).

        With cfg=None the config is read from config_path (default:
        config.local.json) and re-read from that same path at submit
        time. With an explicit cfg dict, the dict is snapshotted and
        re-validated at submit time, and config writes made through
        data.mode (enable_live/disable_live) for this client's key id
        are also honoured.
        """
        if cfg is None:
            cfg = _mode.load_config_strict(config_path)
            snap_path = Path(config_path) if config_path else _mode.CONFIG_PATH
        else:
            cfg = cfg if isinstance(cfg, dict) else {}
            snap_path = Path(config_path) if config_path else None
        eff = _mode.effective_mode(cfg)
        # No explicit stop_check: the constructor's default reads
        # is_stopped(state_dir) -- the same state dir the gate uses --
        # so from_config clients are coherent by construction (R2-N5).
        if eff == _mode.LIVE:
            k, s = _mode.live_keys(cfg)
            client = cls(_mode.LIVE, k, s, transport=transport,
                         state_dir=state_dir, config_path=snap_path,
                         cfg_snapshot=cfg)
        else:
            k, s = _mode.paper_keys(cfg)
            client = cls(_mode.PAPER, k, s, transport=transport,
                         state_dir=state_dir, config_path=snap_path,
                         cfg_snapshot=cfg)
        # R2-N4c: scrub BOTH accounts' key material from error text --
        # a broker error echoing the other account's keys must not leak.
        for pair in (_mode.live_keys(cfg), _mode.paper_keys(cfg)):
            client._scrub_extra.update(v for v in pair if v)
            if pair[1]:
                client._scrub_secrets.add(pair[1])
        return client

    # -- secret hygiene --------------------------------------------------------
    def _scrub(self, text) -> str:
        """Remove key material from text BEFORE any truncation (R2-N4):
        truncating first leaked all but the last characters of a secret
        (the visible prefix was never equal to the full value). Also
        removes the other account's pair and URL-encoded forms."""
        s = str(text)
        values = {self._key_id, self._secret} | self._scrub_extra
        for v in sorted((v for v in values if v), key=len, reverse=True):
            s = s.replace(v, "***")
            s = s.replace(urllib.parse.quote(v, safe=""), "***")
            s = s.replace(urllib.parse.quote_plus(v, safe=""), "***")
        # Fragment tripwire (R2-N4 residual): a secret broken up inside
        # a message (e.g. split by a newline in a transport exception)
        # can never match the exact-substring passes above, yet its
        # pieces reassemble trivially. If any 8-character run of a
        # SECRET survives in the text, the whole text is unsafe to
        # surface -- replace it wholesale.
        for v in self._scrub_secrets:
            if v and len(v) >= 8 and any(v[i:i + 8] in s
                                         for i in range(len(v) - 7)):
                return ("[error text withheld: it contained fragments "
                        "of credential material]")
        return s

    # -- plumbing ------------------------------------------------------------
    def _request(self, method: str, path: str, payload: dict | None = None):
        if self.base not in (PAPER_BASE, LIVE_BASE):
            raise AlpacaError(
                "order/request refused: broker endpoint is not on the "
                "allowed list (only the two official Alpaca hosts are "
                "permitted)")
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"APCA-API-KEY-ID": self._key_id,
                   "APCA-API-SECRET-KEY": self._secret,
                   "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        is_submit = method == "POST" and path.startswith("/v2/orders")
        try:
            raw = self._transport(method, self.base + path, headers, body)
        except Exception as e:
            # Wrap (never propagate raw): the exception text may contain
            # anything, including echoed headers -- scrub before surfacing.
            raise AlpacaError(
                self._scrub(
                    f"Alpaca {method} {path} transport error "
                    f"({type(e).__name__}: {e})"
                    + (" -- SUBMIT OUTCOME UNKNOWN: the order may have "
                       "reached Alpaca. Check open orders before retrying."
                       if is_submit else "")),
                outcome_unknown=is_submit) from None
        try:
            status, text = raw
        except Exception:
            raise AlpacaError(
                f"Alpaca {method} {path}: malformed transport response",
                outcome_unknown=is_submit) from None
        if isinstance(status, bool) or not isinstance(status, int):
            raise AlpacaError(
                f"Alpaca {method} {path}: malformed transport status {status!r}",
                outcome_unknown=is_submit)
        if text is None:
            text = ""
        elif isinstance(text, bytes):
            text = text.decode("utf-8", "replace")
        elif not isinstance(text, str):
            text = str(text)
        if not (200 <= status < 300):
            # Only 2xx is success (3xx included in errors). Broker bodies
            # are scrubbed of key material BEFORE truncation (R2-N4a):
            # truncating first left the secret's visible prefix intact.
            raise AlpacaError(self._scrub(
                f"Alpaca {method} {path} -> HTTP {status}: {text}")[:400])
        if not text.strip():
            return {}
        try:
            return json.loads(text)
        except Exception:
            raise AlpacaError(self._scrub(
                f"Alpaca {method} {path} -> HTTP {status} with a non-JSON "
                f"response body: {text}")[:300],
                outcome_unknown=is_submit) from None

    # -- read endpoints --------------------------------------------------------
    def account(self) -> dict:
        return self._request("GET", "/v2/account")

    def positions(self) -> list:
        return self._request("GET", "/v2/positions")

    def open_orders(self) -> list:
        return self._request("GET", "/v2/orders?status=open&limit=100")

    # -- submit gate -----------------------------------------------------------
    def _config_permits(self, cfg: dict) -> bool:
        """True when `cfg` still resolves to this client's mode AND keys."""
        if _mode.effective_mode(cfg) != self.mode:
            return False
        keys = (_mode.live_keys(cfg) if self.mode == _mode.LIVE
                else _mode.paper_keys(cfg))
        return keys == (self._key_id, self._secret)

    def _check_revocation(self) -> None:
        """Sticky revocation (R2-N2/N3): once ANY config write through
        data.mode after this client was built stops permitting it, the
        client is revoked for good -- a later live write cannot
        resurrect it (only a freshly built client trades). Applies to
        dict-built AND directly-constructed clients (both carry a key
        id and a build epoch); file-backed clients re-read their file
        instead. A hand edit to a file no client is bound to remains
        unobservable -- the documented limit."""
        if self._config_path is not None:
            return  # file-backed clients re-read the file itself
        if self._revoked:
            raise AlpacaError(
                "order refused: this client was revoked when live mode "
                "was disabled or the keys changed after it was built. "
                "Rebuild the client from the current config.")
        for written in _mode.config_writes_for_key(self._key_id,
                                                   self._built_epoch):
            if not self._config_permits(written):
                self._revoked = True
                raise AlpacaError(
                    "order refused: this client was revoked when live "
                    "mode was disabled or the keys changed after it was "
                    "built. Rebuild the client from the current config.")

    def _fresh_config(self) -> dict | None:
        """Config to re-validate against at submit time, or None for a
        directly-constructed client with no config source (stop-check
        only -- such a client cannot observe mode changes).

        R2-N5 mitigation: a client without its own config path ALSO
        consults the installation's config.local.json when that file
        carries this client's key id -- the realistic single-install
        case -- so a hand-edited mode change or a disable_live() on the
        real file is honoured. A client whose key appears in no config
        anywhere remains stop-check only (documented limit)."""
        if self._config_path is not None:
            return _mode.load_config_strict(self._config_path)
        disk = _mode.load_config_strict()
        if disk and _mode._carries_key(disk, self._key_id):
            return disk
        if self._cfg_snapshot is not None:
            newer = _mode.latest_written_config_for_key(
                self._key_id, self._built_epoch)
            return newer if newer is not None else dict(self._cfg_snapshot)
        return None

    def _gate_check(self) -> None:
        """mode.orders_permitted() + stale-client re-resolution."""
        self._check_revocation()
        fresh = self._fresh_config()
        if fresh is None:
            if self._stop_check():
                raise AlpacaError(_STOP_MSG)
            return
        allowed, reason = _mode.orders_permitted(fresh, state_dir=self._state_dir)
        if not allowed:
            if _mode.is_stopped(self._state_dir) or "STOP" in reason:
                raise AlpacaError(self._scrub(_STOP_MSG + f" ({reason})"))
            raise AlpacaError(self._scrub(f"order refused by the mode gate: {reason}"))
        eff = _mode.effective_mode(fresh)
        if eff != self.mode:
            raise AlpacaError(self._scrub(
                f"order refused: the trading mode changed after this client "
                f"was built (client is {self.mode}, current effective mode "
                f"is {eff}). Rebuild the client from the current config."))
        keys = (_mode.live_keys(fresh) if self.mode == _mode.LIVE
                else _mode.paper_keys(fresh))
        if keys != (self._key_id, self._secret):
            raise AlpacaError(
                "order refused: the Alpaca keys in the config changed after "
                "this client was built. Rebuild the client from the current "
                "config.")

    def _stopped_now(self) -> bool:
        if self._cfg_snapshot is None and self._config_path is None:
            return bool(self._stop_check())
        return _mode.is_stopped(self._state_dir)

    # -- the one order path ----------------------------------------------------
    def submit_order(self, symbol: str, side: str, qty: float | None = None,
                     notional: float | None = None, order_type: str = "market",
                     time_in_force: str = "day",
                     limit_price: float | None = None,
                     stop_price: float | None = None,
                     client_order_id: str | None = None) -> dict:
        """Place one order. Refuses -- before any network call -- while
        STOP ALL is set or the mode gate no longer permits this client.
        There is deliberately no bulk/liquidate helper."""
        # ---- validation (adapter-side; the broker is not the validator) ----
        if not isinstance(symbol, str) or not _SYMBOL_RE.match(symbol.strip()):
            raise ValueError(f"symbol must be a non-empty ticker string, got {symbol!r}")
        symbol = symbol.strip().upper()
        if side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
        if (qty is None) == (notional is None):
            raise ValueError("pass exactly one of qty / notional")

        def _pos(v, name):
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or not math.isfinite(v) or v <= 0:
                raise ValueError(f"{name} must be a positive number, got {v!r}")
            return v

        if qty is not None:
            _pos(qty, "qty")
        else:
            _pos(notional, "notional")
        if order_type not in _ORDER_TYPES:
            raise ValueError(f"order_type must be one of {_ORDER_TYPES}, got {order_type!r}")
        if time_in_force not in _TIME_IN_FORCE:
            raise ValueError(f"time_in_force must be one of {_TIME_IN_FORCE}, got {time_in_force!r}")
        if limit_price is not None:
            _pos(limit_price, "limit_price")
        if stop_price is not None:
            _pos(stop_price, "stop_price")
        if order_type in ("limit", "stop_limit") and limit_price is None:
            raise ValueError(f"{order_type} orders require limit_price")
        if order_type in ("stop", "stop_limit") and stop_price is None:
            raise ValueError(f"{order_type} orders require stop_price")
        if order_type in ("market", "trailing_stop") and limit_price is not None:
            raise ValueError(f"{order_type} orders do not take a limit_price")
        if order_type in ("market", "limit", "trailing_stop") and stop_price is not None:
            raise ValueError(f"{order_type} orders do not take a stop_price")
        if client_order_id is None:
            client_order_id = str(uuid.uuid4())
        elif not isinstance(client_order_id, str) \
                or not (1 <= len(client_order_id) <= 128) \
                or any(not (0x21 <= ord(c) <= 0x7E) for c in client_order_id):
            # R2-N7: visible ASCII only -- no padding, spaces, NUL,
            # newlines or unicode look-alikes in an idempotency key.
            raise ValueError(
                "client_order_id must be 1-128 visible ASCII characters "
                "(no whitespace or control characters)")
        if client_order_id in self._used_order_ids:
            # R2-N7: refuse a local duplicate instead of relying on
            # broker-side dedup, which could not be verified without a
            # real account.
            raise ValueError(
                "client_order_id was already submitted by this client; "
                "refusing a possible duplicate order")

        payload: dict = {"symbol": symbol, "side": side,
                         "type": order_type, "time_in_force": time_in_force,
                         "client_order_id": client_order_id}
        if qty is not None:
            payload["qty"] = str(qty)
        else:
            payload["notional"] = str(notional)
        if limit_price is not None:
            payload["limit_price"] = str(limit_price)
        if stop_price is not None:
            payload["stop_price"] = str(stop_price)

        # ---- gate + submit, serialised against STOP ALL ----
        # Holding mode.order_gate() across the final check AND the
        # transport call means set_stopped() cannot land in between:
        # the stop either completed before _gate_check() (order refused,
        # zero broker calls) or waits and lands right after this order
        # completes. It cannot recall an order the broker has accepted.
        with _mode.order_gate(self._state_dir):
            # _gate_check() is the mode.orders_permitted() gate, run on a
            # freshly re-resolved config (see _fresh_config/_gate_check).
            self._gate_check()
            if self._stopped_now():  # re-check immediately before transport
                raise AlpacaError(_STOP_MSG)
            # Burn the id only now: a gate refusal above never submitted
            # anything, so the caller may retry with the same id after
            # resuming. From here the outcome may be unknown on error,
            # so the id must never be reused.
            self._used_order_ids.add(client_order_id)
            result = self._request("POST", "/v2/orders", payload)

        if isinstance(result, dict):
            # Surface fill state explicitly: a partial fill must be
            # visible to callers, not buried in a raw broker dict.
            result.setdefault("status", "unknown")
            result.setdefault("filled_qty", "0")
            result.setdefault("client_order_id", client_order_id)
        return result
