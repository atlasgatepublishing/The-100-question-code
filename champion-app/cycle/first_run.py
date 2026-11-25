"""First run setup: the user's own Alpaca paper keys (new code).

The flow the design requires (Section 5.2): each user opens their own
Alpaca account and generates their own paper key pair, then enters
the keys by their own hand on their own machine. This module writes
those keys into config.local.json (the only place keys live), sets
the mode to paper, and then encrypts the keys at rest through
data.mode's DPAPI path when encrypted storage is available on the
machine (Windows). On a machine without DPAPI the keys stay in the
config protected by the file permissions the mode module sets, and
the result says so plainly.

Keys are never printed, never logged, and never returned by any
function here: status output is present or not set, only.
"""
from __future__ import annotations

from pathlib import Path

from data import mode as _mode


def setup_paper_keys(key_id: str, secret: str,
                     config_path=None) -> tuple[bool, str]:
    """Store the user's own Alpaca PAPER key pair and set paper mode.

    Returns (ok, plain-language message). Refuses malformed keys
    before touching the file, refuses to overwrite a config that
    cannot be parsed, and never enables live mode."""
    if not _mode.valid_key_id(key_id or ""):
        return False, ("That key id does not look like an Alpaca key id "
                       "(unexpected length or characters). Copy the key "
                       "id exactly as Alpaca issued it. Nothing was saved.")
    if not _mode.valid_secret(secret or ""):
        return False, ("That secret key does not look like an Alpaca "
                       "secret key (unexpected length or characters). "
                       "Copy it exactly as Alpaca issued it. Nothing was "
                       "saved.")
    p = Path(config_path) if config_path else _mode.CONFIG_PATH
    cfg, problem = _mode._parse_config(p)
    if problem is not None:
        return False, (f"Setup was NOT saved: {problem} The config file "
                       f"was left untouched.")
    cfg["alpaca_paper_key_id"] = key_id
    cfg["alpaca_paper_secret_key"] = secret
    cfg["trading_mode"] = "paper"
    try:
        _mode._save_config(cfg, p)
    except Exception as e:
        return False, f"Setup was NOT saved ({type(e).__name__}: {e})."
    ok, msg = _mode.encrypt_config_keys(p)
    if ok:
        return True, ("Paper keys saved, trading mode set to PAPER, and "
                      "the keys were encrypted at rest for your Windows "
                      "account. " + msg)
    return True, ("Paper keys saved and trading mode set to PAPER. "
                  "Encrypted at rest storage was not applied: " + msg +
                  " The config file's permissions were restricted "
                  "instead; keep config.local.json private.")


def first_run_status(config_path=None) -> dict:
    """What a first run screen needs. Contains NO key values, ever."""
    p = Path(config_path) if config_path else _mode.CONFIG_PATH
    cfg, problem = _mode._parse_config(p)
    st = _mode.mode_status(cfg)
    return {"config_present": p.exists(),
            "config_problem": problem,
            "paper_keys_present": st["paper_keys_present"],
            "live_keys_present": st["live_keys_present"],
            "effective_mode": st["effective_mode"],
            "stopped": st["stopped"]}
