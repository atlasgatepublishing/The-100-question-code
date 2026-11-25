"""Dashboard password hashing (Phase A, research E2).

Stdlib only: PBKDF2-HMAC-SHA256 with a random 16-byte salt and
200,000 iterations. No default credentials exist anywhere -- a password
hash only appears in config.local.json when the owner sets one.
"""
import base64
import hashlib
import hmac
import secrets

_ITERATIONS = 200_000
_SALT_BYTES = 16


def hash_password(password):
    """(salt_b64, hash_b64) for `password` (str)."""
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    salt = secrets.token_bytes(_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return (base64.b64encode(salt).decode("ascii"),
            base64.b64encode(dk).decode("ascii"))


def store_credentials(config_path, owner_name, password, base_config=None):
    """First-run setup helper (W5-C): write the owner's name and a salted
    PBKDF2 password hash into the JSON config at `config_path`.

    The plaintext password is NEVER stored -- only the salt and hash
    produced by hash_password(). Existing config keys are preserved
    (pass `base_config` to start from an already-loaded config instead
    of re-reading the file). Writes atomically (temp file + replace).
    Returns the updated config dict.
    """
    import json
    import os
    from pathlib import Path

    p = Path(config_path)
    cfg = dict(base_config) if isinstance(base_config, dict) else {}
    if base_config is None and p.exists():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                cfg = existing
        except Exception:
            cfg = {}
    salt_b64, hash_b64 = hash_password(password)
    cfg["dashboard_owner_name"] = str(owner_name)
    cfg["dashboard_password_salt"] = salt_b64
    cfg["dashboard_password_hash"] = hash_b64
    cfg["dashboard_auth_enabled"] = True
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
        tmp.replace(p)
    finally:
        if tmp.exists():
            tmp.unlink()
    return cfg


def verify_password(password, salt_b64, hash_b64):
    """Constant-time check; False (never raises) on any malformed input."""
    try:
        if not isinstance(password, str) or not isinstance(salt_b64, str) \
                or not isinstance(hash_b64, str):
            return False
        salt = base64.b64decode(salt_b64.encode("ascii"), validate=True)
        expected = base64.b64decode(hash_b64.encode("ascii"), validate=True)
        if not salt or not expected:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False
