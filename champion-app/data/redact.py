"""Redaction filter (D1): secrets never reach logs, errors, diagnostics.

Stdlib only; imports nothing from mode/loaders (provider pattern, to
avoid cycles). Callers register secret values directly, and/or install
a provider callback that returns the current secrets on demand.

scrub_text replaces every registered/provider secret AND its URL-encoded
(quote / quote_plus) forms with "***". Callers must scrub BEFORE any
truncation -- truncating first can leave a secret's prefix intact.

Fragment tripwire: if any 8-character run of a registered secret
(length >= 8) survives the exact passes (e.g. the secret was split by a
newline inside an exception), the whole text is withheld behind a
fixed string rather than surfaced in pieces.
"""
from __future__ import annotations

import logging
import urllib.parse

WITHHELD = "[text withheld: it contained fragments of credential material]"

_registry: set[str] = set()
_provider = None
_filter_installed = False


def register_secret(v) -> None:
    if isinstance(v, str) and v:
        _registry.add(v)


def set_secret_provider(fn) -> None:
    global _provider
    _provider = fn


def _all_secrets() -> list[str]:
    out = set(_registry)
    if _provider is not None:
        try:
            vals = _provider() or []
        except Exception:
            vals = []
        for v in vals:
            if isinstance(v, str) and v:
                out.add(v)
    return sorted(out, key=len, reverse=True)


def scrub_text(text) -> str:
    s = str(text)
    secrets = _all_secrets()
    for v in secrets:
        if v in s:
            s = s.replace(v, "***")
        for enc in (urllib.parse.quote(v, safe=""),
                    urllib.parse.quote_plus(v, safe="")):
            if enc != v and enc in s:
                s = s.replace(enc, "***")
    for v in secrets:
        if len(v) >= 8 and any(v[i:i + 8] in s for i in range(len(v) - 7)):
            return WITHHELD
    return s


class _RedactFilter(logging.Filter):
    def filter(self, record):  # noqa: A003 - logging API name
        try:
            rendered = record.getMessage()
        except Exception:
            return True
        scrubbed = scrub_text(rendered)
        if scrubbed != rendered:
            record.msg = scrubbed
            record.args = ()
        return True


def install_log_filter() -> bool:
    """Attach the scrubbing filter to the root logger (idempotent)."""
    global _filter_installed
    root = logging.getLogger()
    for f in root.filters:
        if isinstance(f, _RedactFilter):
            _filter_installed = True
            return True
    root.addFilter(_RedactFilter())
    _filter_installed = True
    return True
