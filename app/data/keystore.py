"""Encrypted key storage via Windows DPAPI (stdlib only).

Wraps values as "dpapi:" + base64 ciphertext. On Windows the real
implementation uses ctypes against crypt32.CryptProtectData /
CryptUnprotectData, bound to the current Windows user -- no password,
no third-party crypto, and NO homemade cryptography.

On non-Windows (or when DPAPI is unavailable) protect/unprotect raise
KeystoreUnavailable unless a test provider has been injected with
_set_provider_for_tests(). A test provider is a pair of callables
str -> str (plaintext -> opaque blob string, and back); protect_text
adds the "dpapi:" prefix around whatever blob the provider returns.

This module imports ONLY the standard library and nothing from
mode/loaders, to avoid import cycles.
"""
from __future__ import annotations

import base64
import sys

PREFIX = "dpapi:"


class KeystoreUnavailable(Exception):
    """Raised when encrypted storage cannot be performed here."""


_test_protect = None
_test_unprotect = None


def _set_provider_for_tests(protect_fn, unprotect_fn):
    """Test hook: inject (or clear, with None/None) a simulated provider."""
    global _test_protect, _test_unprotect
    _test_protect = protect_fn
    _test_unprotect = unprotect_fn


def available() -> bool:
    if _test_protect is not None and _test_unprotect is not None:
        return True
    if sys.platform == "win32":
        try:
            import ctypes
            _ = ctypes.windll.crypt32  # noqa: F841
            return True
        except Exception:
            return False
    return False


_UNAVAILABLE_MSG = (
    "Encrypted key storage is not available on this computer. It uses "
    "Windows DPAPI, which protects keys with your Windows account, so "
    "it only works on Windows under your own user account. On this "
    "system the keys stay in the plain config file protected only by "
    "the file permissions."
)


# ---------------------------------------------------------------------------
# Windows DPAPI via ctypes
# ---------------------------------------------------------------------------
def _dpapi_protect(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    ok = crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise KeystoreUnavailable(_UNAVAILABLE_MSG)
    try:
        out = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        return out
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    in_buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(in_buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    CRYPTPROTECT_UI_FORBIDDEN = 0x1
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None,
        CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise KeystoreUnavailable(
            "These keys are encrypted for a different Windows user or "
            "machine and cannot be opened here.")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def protect_text(s: str) -> str:
    if not isinstance(s, str):
        raise TypeError("protect_text expects a string")
    if _test_protect is not None:
        blob = _test_protect(s)
        if isinstance(blob, bytes):
            blob = base64.b64encode(blob).decode("ascii")
        blob = str(blob)
        return blob if blob.startswith(PREFIX) else PREFIX + blob
    if sys.platform == "win32" and available():
        raw = _dpapi_protect(s.encode("utf-8"))
        return PREFIX + base64.b64encode(raw).decode("ascii")
    raise KeystoreUnavailable(_UNAVAILABLE_MSG)


def unprotect_text(tok: str) -> str:
    if not isinstance(tok, str) or not tok.startswith(PREFIX):
        raise KeystoreUnavailable("Value is not an encrypted (dpapi:) value.")
    blob = tok[len(PREFIX):]
    if _test_unprotect is not None:
        out = _test_unprotect(blob)
        if isinstance(out, bytes):
            return out.decode("utf-8")
        return str(out)
    if sys.platform == "win32" and available():
        try:
            raw = base64.b64decode(blob.encode("ascii"), validate=True)
        except Exception as e:
            raise KeystoreUnavailable(
                "These keys are encrypted for a different Windows user or "
                "machine and cannot be opened here.") from e
        return _dpapi_unprotect(raw).decode("utf-8")
    raise KeystoreUnavailable(_UNAVAILABLE_MSG)
