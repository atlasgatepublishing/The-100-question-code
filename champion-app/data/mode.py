"""Trading mode (paper / live) and the engine STOP ALL control.

This module is the single place that decides whether the app may trade
with real money. The safety shape is deliberate:

  * Mode lives in the user's local config file (config.local.json, the
    same file that holds their own API keys): "trading_mode": "paper"
    (the default) or "live". Keys are NEVER in code and NEVER logged;
    this module only ever reports whether keys are present, never values.
  * FAIL SAFE, NEVER FAIL LIVE: the effective mode is "live" only when
    the config says "live" AND the user's own Alpaca LIVE keys are
    present AND well-formed in that same config. A config that asks for
    live without (valid) live keys resolves to PAPER, and mode_status()
    explains why. A config file that cannot be parsed, is not a JSON
    object, or contains duplicate keys also resolves to PAPER, with the
    reason surfaced -- never a raw exception.
  * Enabling live requires an explicit typed confirmation phrase
    (CONFIRMATION_PHRASE) submitted through the dashboard -- no single
    click can do it. The phrase must match EXACTLY, character for
    character: no surrounding whitespace is trimmed, and non-string
    input is refused cleanly. See enable_live().
  * STOP ALL is a persisted flag kept in TWO files in the state dir
    (state/engine_control.json plus a redundant marker,
    state/engine_control.stopped.json). The engine is stopped if
    EITHER file says stopped, and a control file that exists but
    cannot be read/parsed, or has the wrong shape, fails CLOSED
    (treated as stopped). Only an explicit resume (set_stopped(False))
    clears both files. Deleting one file while stopped therefore does
    NOT silently resume the engine; deleting both files by hand is a
    deliberate manual reset that no code can distinguish from a fresh
    install. While stopped, the broker adapter refuses to place ANY
    order, in any mode. Stopping never liquidates anything: positions
    stay exactly where they are, in the user's own broker account.
  * Order submission and STOP ALL are serialised with order_gate():
    a stop either lands before an order's final gate check (and the
    order is refused) or waits until the in-flight order completes.
    See order_gate() for the exact guarantee and its limits.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from datetime import datetime
from pathlib import Path

try:  # POSIX file lock for cross-process serialisation; optional.
    import fcntl
except Exception:  # pragma: no cover - non-POSIX platforms
    fcntl = None

from .loaders import CONFIG_PATH, _cfg_key, load_config  # noqa: F401  (load_config re-exported for compatibility)

try:
    from . import keystore as _keystore
except Exception:  # pragma: no cover
    _keystore = None  # type: ignore

try:
    from . import redact as _redact
except Exception:  # pragma: no cover
    _redact = None  # type: ignore

# --- Environment-variable key override (A4) --------------------------------
# A non-empty env value wins over the file value. Canonical lowercase
# config names are what the returned dict carries.
ENV_KEY_MAP = {
    "ALPACA_PAPER_KEY_ID": "alpaca_paper_key_id",
    "ALPACA_PAPER_SECRET_KEY": "alpaca_paper_secret_key",
    "ALPACA_LIVE_KEY_ID": "alpaca_live_key_id",
    "ALPACA_LIVE_SECRET_KEY": "alpaca_live_secret_key",
}

# Every config field that may hold key material (all name variants).
_ALL_KEY_FIELDS = ()
# (filled in after the *_NAMES tuples are defined below)


def _env_override_active() -> bool:
    return any(bool(os.environ.get(k)) for k in ENV_KEY_MAP)


def _apply_env_overrides(cfg: dict) -> dict:
    for env_name, cfg_name in ENV_KEY_MAP.items():
        v = os.environ.get(env_name)
        if v:  # non-empty only; empty env is ignored
            cfg[cfg_name] = v
    return cfg


def _redact_provider_secrets():
    try:
        cfg = load_config_strict()
        vals = []
        vals.extend(paper_keys(cfg))
        vals.extend(live_keys(cfg))
        vals.append(_cfg_key(cfg, "tiingo_api_key", "TIINGO_API_KEY"))
        return [v for v in vals if v]
    except Exception:
        return []


if _redact is not None:
    try:
        _redact.set_secret_provider(_redact_provider_secrets)
    except Exception:
        pass

APP_DIR = Path(__file__).resolve().parent.parent
STATE_DIR = APP_DIR / "state"
CONTROL_FILE = "engine_control.json"
STOP_MARKER_FILE = "engine_control.stopped.json"

PAPER = "paper"
LIVE = "live"

# The exact phrase the user must type to enable live mode. Shown on the
# enable screen itself; it is an acknowledgment, not a password.
CONFIRMATION_PHRASE = "I UNDERSTAND THIS TRADES REAL MONEY"

PAPER_KEY_NAMES = ("alpaca_paper_key_id", "ALPACA_PAPER_KEY_ID",
                   "alpaca_paper_api_key_id", "ALPACA_PAPER_API_KEY_ID")
PAPER_SECRET_NAMES = ("alpaca_paper_secret_key", "ALPACA_PAPER_SECRET_KEY",
                      "alpaca_paper_api_secret", "ALPACA_PAPER_API_SECRET")
LIVE_KEY_NAMES = ("alpaca_live_key_id", "ALPACA_LIVE_KEY_ID",
                  "alpaca_live_api_key_id", "ALPACA_LIVE_API_KEY_ID")
LIVE_SECRET_NAMES = ("alpaca_live_secret_key", "ALPACA_LIVE_SECRET_KEY",
                     "alpaca_live_api_secret", "ALPACA_LIVE_API_SECRET")

_ALL_KEY_FIELDS = tuple(dict.fromkeys(
    PAPER_KEY_NAMES + PAPER_SECRET_NAMES + LIVE_KEY_NAMES + LIVE_SECRET_NAMES
    + ("tiingo_api_key", "TIINGO_API_KEY")))

# Plausible Alpaca credential shapes. Real Alpaca key ids are
# alphanumeric; secrets may also contain a few punctuation characters.
# These checks reject blank/whitespace, 1-character, symbol-garbage and
# absurdly long values BEFORE live mode can be enabled -- they are a
# sanity gate, not a substitute for the broker's own authentication.
_KEY_ID_RE = re.compile(r"[A-Za-z0-9]{8,128}")
_SECRET_RE = re.compile(r"[A-Za-z0-9_\-/+=.]{8,512}")


def valid_key_id(value) -> bool:
    # fullmatch (R2-N6): a "$"-anchored match accepted a trailing newline,
    # so a key id containing "\n" validated and reached an HTTP header.
    return isinstance(value, str) and bool(_KEY_ID_RE.fullmatch(value))


def valid_secret(value) -> bool:
    return isinstance(value, str) and bool(_SECRET_RE.fullmatch(value))


def _valid_pair(key_id: str, secret: str) -> bool:
    return valid_key_id(key_id) and valid_secret(secret)


# ----------------------------------------------------------------------------
# Config loading -- strict, fail-safe, never raises on bad content
# ----------------------------------------------------------------------------
class _DuplicateKey(ValueError):
    pass


def _no_duplicate_pairs(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise _DuplicateKey(k)
        out[k] = v
    return out


def _parse_config(path: Path | None = None) -> tuple[dict, str | None]:
    """(config dict, problem). Any problem -> ({}, plain-language reason).

    Absent file is NOT a problem ({} , None). A present-but-unreadable,
    unparseable, duplicate-keyed, or non-object config IS a problem and
    fails safe to an empty (paper) config with the reason surfaced.
    """
    p = Path(path) if path else CONFIG_PATH
    try:
        if not p.exists():
            return {}, None
        raw = p.read_bytes()
    except Exception:
        return {}, ("config.local.json exists but could not be read, so the "
                    "app is running in PAPER mode. Fix or replace the file.")
    try:
        text = raw.decode("utf-8-sig")
    except Exception:
        return {}, ("config.local.json is not valid UTF-8 text, so the app "
                    "is running in PAPER mode. Fix or replace the file.")
    try:
        data = json.loads(text, object_pairs_hook=_no_duplicate_pairs)
    except _DuplicateKey:
        return {}, ("config.local.json contains a duplicate key, which is "
                    "ambiguous, so the app is running in PAPER mode. Remove "
                    "the duplicate entry.")
    except Exception:
        return {}, ("config.local.json is not valid JSON, so the app is "
                    "running in PAPER mode. Fix the file -- it was left "
                    "untouched.")
    if not isinstance(data, dict):
        return {}, ("config.local.json must contain a JSON object ({...}), "
                    "so the app is running in PAPER mode. Fix the file -- "
                    "it was left untouched.")
    # Encrypted-at-rest keys (A2/A3): dpapi: values are decrypted in
    # memory only. Any failure fails safe to PAPER, like any other
    # config problem -- never a raw exception, never partial keys.
    for field in _ALL_KEY_FIELDS:
        v = data.get(field)
        if isinstance(v, str) and v.startswith("dpapi:"):
            try:
                if _keystore is None:
                    raise RuntimeError("keystore unavailable")
                data[field] = _keystore.unprotect_text(v)
            except Exception:
                return {}, ("config.local.json holds keys that are "
                            "encrypted for a different Windows user or "
                            "machine, so they cannot be opened here and "
                            "the app is running in PAPER mode. On the "
                            "Windows account that encrypted them, open "
                            "the config and re-save the keys, or replace "
                            "them with plain keys on this machine.")
    _apply_env_overrides(data)
    return data, None


def load_config_strict(path: Path | None = None) -> dict:
    """Config dict for `path` (default config.local.json); {} on any problem."""
    return _parse_config(path)[0]


def config_problem(path: Path | None = None) -> str | None:
    """Plain-language reason the config could not be used, or None."""
    return _parse_config(path)[1]


def _guard(cfg) -> dict:
    """Any non-dict config value is treated as an empty (paper) config."""
    return cfg if isinstance(cfg, dict) else {}


# Registry of config writes made through this module. Lets a broker
# client built from an in-memory dict notice that enable/disable_live
# has since rewritten the config for its own key id (see alpaca.py).
_write_lock = threading.Lock()
_config_write_epoch = 0
_config_writes: list[tuple[int, str, dict]] = []


def _note_config_write(path, cfg: dict) -> None:
    global _config_write_epoch
    with _write_lock:
        _config_write_epoch += 1
        # R2-N2: NO eviction cap. The old 8-entry window let a revocation
        # (disable_live) be forgotten after 8 unrelated writes, and a stale
        # client traded live again. The registry is in-process bookkeeping
        # for a single-user app; it grows by one small dict per mode change.
        _config_writes.append((_config_write_epoch, str(path), dict(cfg)))


def config_write_epoch() -> int:
    with _write_lock:
        return _config_write_epoch


def _carries_key(cfg: dict, key_id: str) -> bool:
    for names in (LIVE_KEY_NAMES, PAPER_KEY_NAMES):
        if _cfg_key(cfg, *names) == key_id:
            return True
    return False


def config_writes_for_key(key_id: str, after_epoch: int) -> list[dict]:
    """ALL configs written via this module after `after_epoch` that carry
    `key_id` as one of its Alpaca key ids, oldest first (R2-N2/N3).

    The broker adapter uses this for STICKY revocation: if ANY of these
    writes no longer permits the client's mode+keys, the client is
    revoked for good -- a later live write (even to an unrelated file,
    R2-N3) cannot resurrect it. Only a freshly built client trades."""
    if not key_id:
        return []
    with _write_lock:
        writes = list(_config_writes)
    return [dict(cfg) for epoch, _p, cfg in writes
            if epoch > after_epoch and _carries_key(cfg, key_id)]


def latest_written_config_for_key(key_id: str, after_epoch: int) -> dict | None:
    """Most recent config written via this module after `after_epoch`
    that carries `key_id` as one of its Alpaca key ids, or None."""
    found = config_writes_for_key(key_id, after_epoch)
    return found[-1] if found else None


# ----------------------------------------------------------------------------
# Keys and mode resolution
# ----------------------------------------------------------------------------
def paper_keys(cfg: dict) -> tuple[str, str]:
    """(key_id, secret) for the Alpaca PAPER account; '' when unset."""
    cfg = _guard(cfg)
    return (_cfg_key(cfg, *PAPER_KEY_NAMES), _cfg_key(cfg, *PAPER_SECRET_NAMES))


def live_keys(cfg: dict) -> tuple[str, str]:
    """(key_id, secret) for the Alpaca LIVE account; '' when unset."""
    cfg = _guard(cfg)
    return (_cfg_key(cfg, *LIVE_KEY_NAMES), _cfg_key(cfg, *LIVE_SECRET_NAMES))


def has_paper_keys(cfg: dict) -> bool:
    k, s = paper_keys(cfg)
    return _valid_pair(k, s)


def has_live_keys(cfg: dict) -> bool:
    k, s = live_keys(cfg)
    return _valid_pair(k, s)


def _key_problem(cfg: dict, which: str) -> str | None:
    """Reason keys are present-but-malformed, or None."""
    k, s = live_keys(cfg) if which == LIVE else paper_keys(cfg)
    if k and s and not _valid_pair(k, s):
        return (f"Alpaca {which.upper()} keys are present in config.local.json "
                "but do not look like valid Alpaca credentials (unexpected "
                "length or characters), so they are treated as missing. "
                "Re-copy the key id and secret key exactly as Alpaca issued "
                "them.")
    if bool(k) != bool(s):
        return (f"Only one of the Alpaca {which.upper()} key id / secret key "
                "is present in config.local.json; both are required.")
    return None


def live_key_problem(cfg: dict) -> str | None:
    return _key_problem(_guard(cfg), LIVE)


def paper_key_problem(cfg: dict) -> str | None:
    return _key_problem(_guard(cfg), PAPER)


def configured_mode(cfg: dict) -> str:
    """What the config asks for: 'live' only on the exact token 'live'.

    Case-insensitive ('LIVE' counts), but no whitespace tolerance:
    ' live ' is NOT live. Anything else -- including non-strings and a
    non-dict config -- is paper.
    """
    v = _guard(cfg).get("trading_mode")
    return LIVE if isinstance(v, str) and v.lower() == LIVE else PAPER


def effective_mode(cfg: dict) -> str:
    """The mode the app actually runs in. Fails safe to paper."""
    cfg = _guard(cfg)
    if configured_mode(cfg) == LIVE and has_live_keys(cfg):
        return LIVE
    return PAPER


def harden_config_permissions(path) -> bool:
    """Best-effort restrictive permissions on a config file (A1).

    POSIX: chmod 0600. Windows: icacls restricting the file to the
    current user (inheritance removed), 5s timeout. Never raises;
    returns True only when the hardening command succeeded.
    """
    p = Path(path)
    try:
        if sys.platform == "win32":
            user = os.environ.get("USERNAME") or ""
            if not user:
                return False
            r = subprocess.run(
                ["icacls", str(p), "/inheritance:r", "/grant:r", f"{user}:F"],
                capture_output=True, timeout=5)
            return r.returncode == 0
        os.chmod(p, 0o600)
        return True
    except Exception:
        return False


# --- Git tracked-config tripwire (D2) --------------------------------------
_git_cache: dict = {}


def config_tracked_by_git(path: Path | None = None) -> bool:
    """True iff the config file is tracked by git.

    Cheap check: `git ls-files --error-unmatch -- <name>` in the file's
    directory. Any error (no git, no repo, missing file) is False.
    Cached per (path, mtime).
    """
    p = Path(path) if path else CONFIG_PATH
    try:
        if not p.exists():
            return False
        mtime = p.stat().st_mtime_ns
    except Exception:
        return False
    key = (str(p), mtime)
    if key in _git_cache:
        return _git_cache[key]
    result = False
    try:
        if shutil.which("git"):
            r = subprocess.run(
                ["git", "-C", str(p.parent), "ls-files", "--error-unmatch",
                 "--", p.name],
                capture_output=True, timeout=5)
            result = (r.returncode == 0)
    except Exception:
        result = False
    _git_cache[key] = result
    return result


def _existing_key_storage_is_dpapi(p: Path) -> bool:
    try:
        if not p.exists():
            return False
        raw = json.loads(p.read_bytes().decode("utf-8-sig"))
        return isinstance(raw, dict) and raw.get("key_storage") == "dpapi"
    except Exception:
        return False


def encrypt_config_keys(path: Path | None = None) -> tuple[bool, str]:
    """Wrap an existing config's plaintext keys with DPAPI storage.

    Refuses with a plain message when encrypted storage is unavailable
    on this machine (e.g. not Windows / no provider)."""
    p = Path(path) if path else CONFIG_PATH
    if _keystore is None or not _keystore.available():
        return False, ("Encrypted key storage is not available on this "
                       "computer. It uses Windows DPAPI and only works "
                       "on Windows under your own user account, so the "
                       "config was left unchanged.")
    cfg, problem = _parse_config(path)
    if problem is not None:
        return False, f"Could not encrypt the keys: {problem} The config was left unchanged."
    try:
        if not p.exists():
            return False, "No config file was found, so there are no keys to encrypt."
    except Exception:
        pass
    cfg["key_storage"] = "dpapi"
    try:
        _save_config(cfg, path)
    except Exception as e:
        return False, f"Could not encrypt the keys: {e}"
    return True, ("Keys in config.local.json are now stored encrypted "
                  "with Windows DPAPI for your Windows account.")


def _save_config(cfg: dict, path: Path | None = None) -> None:
    """Write config back atomically, preserving every other key."""
    p = Path(path) if path else CONFIG_PATH
    # Encrypted storage (A2/A3): if this config (or the file already on
    # disk) asks for dpapi storage, wrap key fields before writing. A
    # protect failure raises a clear error -- plaintext is never
    # written silently in place of the requested encryption. The
    # in-process write registry keeps the PLAINTEXT cfg, so broker
    # clients built from it keep working (see _note_config_write).
    write_cfg = cfg
    if cfg.get("key_storage") == "dpapi" or _existing_key_storage_is_dpapi(p):
        if _keystore is None:
            raise RuntimeError(
                "Encrypted key storage was requested but is not "
                "available on this computer, so the config was NOT "
                "written (the keys were not saved in plain text).")
        write_cfg = dict(cfg)
        write_cfg["key_storage"] = "dpapi"
        for field in _ALL_KEY_FIELDS:
            v = write_cfg.get(field)
            if isinstance(v, str) and v and not v.startswith("dpapi:"):
                try:
                    write_cfg[field] = _keystore.protect_text(v)
                except Exception as e:
                    raise RuntimeError(
                        "Encrypted key storage failed, so the config "
                        "was NOT written (the keys were not saved in "
                        f"plain text): {e}") from e
    # Unique temp name (Round 2, undetermined-race item): two processes
    # writing the same config shared one fixed .tmp name, so one writer
    # could replace the file with the other's content mid-write.
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(write_cfg, indent=2) + "\n")
        tmp.replace(p)
    finally:
        if tmp.exists():
            tmp.unlink()
    harden_config_permissions(p)
    _note_config_write(p, cfg)


def enable_live(phrase: str, path: Path | None = None) -> tuple[bool, str]:
    """Switch the installation to LIVE. Returns (ok, plain-language message).

    Refuses -- leaving the config untouched and the app in paper -- unless
    the typed phrase matches CONFIRMATION_PHRASE EXACTLY (character for
    character, no trimming; non-string input is refused) AND the user's
    own well-formed live keys are present in a readable, unambiguous
    config.
    """
    if not isinstance(phrase, str) or phrase != CONFIRMATION_PHRASE:
        return False, ("Live mode was NOT enabled: the confirmation phrase "
                       "did not match exactly. The app stays in PAPER mode.")
    cfg, problem = _parse_config(path)
    if problem is not None:
        return False, (f"Live mode was NOT enabled: {problem} "
                       "The config file was left untouched.")
    if config_tracked_by_git(path):
        return False, ("Live mode was NOT enabled: config.local.json "
                       "is tracked by git — keys must never be committed; "
                       "remove it from the repo and regenerate the keys, "
                       "then try again. The app stays in PAPER mode.")
    if not has_live_keys(cfg):
        kp = live_key_problem(cfg)
        if kp is not None:
            return False, f"Live mode was NOT enabled: {kp} The app stays in PAPER mode."
        return False, ("Live mode was NOT enabled: no Alpaca LIVE keys were "
                       "found in config.local.json. Add your own live key id "
                       "and secret key there first. The app stays in PAPER "
                       "mode -- it will never fail live.")
    cfg["trading_mode"] = LIVE
    _save_config(cfg, path)
    return True, ("LIVE mode enabled. This app can now place REAL orders in "
                  "your own Alpaca brokerage account. The paper-first path "
                  "is still the recommended one -- see the Trading Mode page.")


def disable_live(path: Path | None = None) -> tuple[bool, str]:
    """Switch the installation back to PAPER.

    Never destroys data: a present-but-unreadable / unparseable /
    ambiguous config is left byte-for-byte untouched and an error is
    surfaced (the effective mode already fails safe to paper for such a
    file). A missing config is a no-op -- no file is created.
    """
    p = Path(path) if path else CONFIG_PATH
    try:
        exists = p.exists()
    except Exception:
        exists = False
    if not exists:
        return True, ("No config file was found, so the app is already in "
                      "PAPER mode. No file was created.")
    cfg, problem = _parse_config(path)
    if problem is not None:
        return False, (f"Could not edit the config to switch back to PAPER: "
                       f"{problem} The file was left untouched. Note the app "
                       f"already fails safe to PAPER while the config cannot "
                       f"be read.")
    cfg["trading_mode"] = PAPER
    _save_config(cfg, path)
    return True, "Switched back to PAPER mode. No real orders can be placed."


# ----------------------------------------------------------------------------
# STOP ALL -- persisted engine stop flag (state/engine_control.json +
# redundant marker state/engine_control.stopped.json). FAILS CLOSED.
# ----------------------------------------------------------------------------
def _control_path(state_dir: Path | None = None) -> Path:
    return (Path(state_dir) if state_dir else STATE_DIR) / CONTROL_FILE


def _marker_path(state_dir: Path | None = None) -> Path:
    return (Path(state_dir) if state_dir else STATE_DIR) / STOP_MARKER_FILE


def _read_control_file(p: Path) -> tuple[bool | None, str | None, str | None]:
    """(stopped, stopped_at, problem) for one control file.

    stopped is None when the file is absent. A present file that cannot
    be parsed, is not a JSON object, or whose "stopped" value is not a
    real boolean is a problem -- callers must fail closed.
    """
    try:
        if not p.exists():
            # A control path whose parent exists but is not a directory
            # can never be read or written -- that is a broken state
            # dir, not a fresh one: fail closed.
            if p.parent.exists() and not p.parent.is_dir():
                return None, None, f"{p.name} is unreachable (state path is not a directory)"
            return None, None, None
        raw = p.read_bytes()
    except Exception:
        return None, None, f"{p.name} exists but could not be read"
    try:
        # R2-N1: the same duplicate-rejecting hook as the config parser --
        # {"stopped": true, "stopped": false} must fail CLOSED, not
        # resolve last-wins and silently un-stop the engine.
        d = json.loads(raw.decode("utf-8-sig"),
                       object_pairs_hook=_no_duplicate_pairs)
    except Exception:
        return None, None, f"{p.name} is not valid JSON"
    if not isinstance(d, dict) or not isinstance(d.get("stopped"), bool):
        return None, None, (f"{p.name} has an unexpected shape "
                            f"('stopped' must be true or false)")
    return d["stopped"], d.get("stopped_at"), None


def stop_info(state_dir: Path | None = None) -> dict:
    """{'stopped': bool, 'stopped_at': iso str | None, 'problem': str|None}.

    FAILS CLOSED: stopped is True if either control file says stopped,
    or if either control file is present but unreadable / malformed.
    """
    stopped = False
    stopped_at = None
    problems = []
    for p in (_control_path(state_dir), _marker_path(state_dir)):
        st, at, problem = _read_control_file(p)
        if problem is not None:
            problems.append(problem)
            stopped = True  # fail closed
        elif st is True:
            stopped = True
            stopped_at = stopped_at or at
    return {"stopped": stopped, "stopped_at": stopped_at,
            "problem": "; ".join(problems) if problems else None}


def is_stopped(state_dir: Path | None = None) -> bool:
    return stop_info(state_dir)["stopped"]


# ----------------------------------------------------------------------------
# Serialisation between STOP ALL and order submission
# ----------------------------------------------------------------------------
_GATE_LOCK = threading.RLock()


@contextlib.contextmanager
def order_gate(state_dir: Path | None = None):
    """Serialise order submission against STOP ALL.

    Guarantee (for callers that go through this module): while a caller
    holds the gate, set_stopped() blocks, and while set_stopped() runs,
    gated order submission blocks. So a stop either (a) completes before
    the order's final gate check -- the order is then refused with zero
    broker calls -- or (b) waits until the in-flight order's broker call
    has finished, and lands immediately after. What this CANNOT do is
    recall an order the broker has already accepted, and it cannot stop
    a process that edits the control files directly or never takes the
    gate; the redundant marker + fail-closed reads cover file damage,
    not a hostile local process. The lock file lives in the system temp
    dir (keyed by state dir) so taking the gate never writes into the
    installation.
    """
    with _GATE_LOCK:
        fh = None
        if fcntl is not None:
            try:
                key = hashlib.sha256(
                    str(_control_path(state_dir).parent.resolve()).encode()
                ).hexdigest()[:16]
                fh = open(Path(tempfile.gettempdir()) / f"stockapp-gate-{key}.lock", "a+")
                fcntl.flock(fh, fcntl.LOCK_EX)
            except Exception:
                if fh is not None:
                    fh.close()
                fh = None  # threading lock above still serialises this process
        try:
            yield
        finally:
            if fh is not None:
                try:
                    fcntl.flock(fh, fcntl.LOCK_UN)
                except Exception:
                    pass
                fh.close()


def set_stopped(stopped: bool, state_dir: Path | None = None) -> dict:
    """Persist the stop flag to BOTH control files. Stopping NEVER
    liquidates anything. Only set_stopped(False) -- an explicit resume --
    clears both files. Serialised against order submission via
    order_gate(): a stop requested mid-order waits for that order to
    finish, then lands."""
    with order_gate(state_dir):
        info = {"stopped": bool(stopped),
                "stopped_at": datetime.now().isoformat(timespec="seconds") if stopped else None}
        try:
            for p in (_control_path(state_dir), _marker_path(state_dir)):
                p.parent.mkdir(parents=True, exist_ok=True)
                tmp = p.with_name(f"{p.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
                try:
                    tmp.write_text(json.dumps(info, indent=1))
                    tmp.replace(p)
                finally:
                    if tmp.exists():
                        tmp.unlink()
        except OSError as e:
            raise RuntimeError(f"could not persist the STOP ALL state: {e}") from e
        return info


def orders_permitted(cfg: dict | None = None,
                     state_dir: Path | None = None) -> tuple[bool, str]:
    """Single gate every order must pass. Returns (allowed, reason).

    This IS the gate the broker adapter's submit path calls (with a
    freshly re-resolved config) -- see data/alpaca.py submit_order().
    """
    st = stop_info(state_dir)
    if st["problem"] is not None:
        return False, (f"engine is STOPPED (STOP ALL): the stop control file "
                       f"could not be verified ({st['problem']}), so no orders "
                       f"will be placed until it is repaired or the user "
                       f"resumes the engine from the dashboard")
    if st["stopped"]:
        return False, ("engine is STOPPED (STOP ALL) -- no orders will be "
                       "placed until the user resumes it from the dashboard")
    default_path = cfg is None
    cfg = _guard(cfg) if cfg is not None else load_config_strict()
    if default_path and configured_mode(cfg) == LIVE and config_tracked_by_git():
        return False, ("orders are NOT permitted: config.local.json is "
                       "tracked by git — keys must never be committed; "
                       "remove it from the repo and regenerate the keys. "
                       "The app is failing safe to paper.")
    if configured_mode(cfg) == LIVE and effective_mode(cfg) != LIVE:
        kp = live_key_problem(cfg)
        detail = kp if kp is not None else "no valid Alpaca LIVE keys were found"
        return False, (f"live mode is requested in config.local.json but is "
                       f"not active ({detail}), so the app is failing safe to "
                       f"paper and orders are NOT permitted until live is "
                       f"properly enabled or the mode is set back to paper")
    return True, "ok"


def mode_status(cfg: dict | None = None,
                state_dir: Path | None = None) -> dict:
    """Everything the dashboard needs. Contains NO key values, ever."""
    cfg_problem = None
    if cfg is None:
        cfg, cfg_problem = _parse_config()
    else:
        cfg = _guard(cfg)
    conf = configured_mode(cfg)
    eff = effective_mode(cfg)
    problem = cfg_problem
    if conf == LIVE and eff != LIVE:
        kp = live_key_problem(cfg)
        if kp is not None:
            problem = problem or kp
        elif problem is None:
            problem = ("Live mode is set in config.local.json but no Alpaca LIVE "
                       "keys were found there, so the app is running in PAPER "
                       "mode. Add your own live keys to enable live trading -- "
                       "the app fails safe to paper, never live.")
    st = stop_info(state_dir)
    tracked = config_tracked_by_git()
    if tracked and eff == LIVE:
        line = ("config.local.json is tracked by git — keys must never "
                "be committed; remove it from the repo and regenerate "
                "the keys.")
        problem = f"{problem} {line}" if problem else line
    return {
        "configured_mode": conf,
        "effective_mode": eff,
        "is_live": eff == LIVE,
        "paper_keys_present": has_paper_keys(cfg),
        "live_keys_present": has_live_keys(cfg),
        "env_override_active": _env_override_active(),
        "config_tracked_by_git": tracked,
        "problem": problem,
        "control_problem": st["problem"],
        "stopped": st["stopped"],
        "stopped_at": st["stopped_at"],
        "confirmation_phrase": CONFIRMATION_PHRASE,
    }
