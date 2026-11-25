"""Order preview with explicit confirmation (design gate 6.7).

A preview is one list: symbol, side, notional, latest price,
estimated resulting weight, and the cap check result, shown before
any order is sent. The cycle builds the preview and stops. Paper mode
proceeds only on the user's run command (the confirmation call);
live mode requires the same explicit confirmation of the preview.
An unconfirmed preview expires and sends nothing: previews carry a
creation time and a 15 minute life, are saved to
state/last_preview.json, and a confirmation must name the preview's
id and arrive inside its life, or it is refused and the refusal is
audit logged by the caller.

Integrity (adversarial fix step, attack P1): the saved preview
carries a keyed integrity value (HMAC-SHA256) over its full contents,
including its expiry, keyed by a per install secret kept in a
SEPARATE file (state/preview_key.txt, created on first use). Editing
the saved preview file, extending expires_at included, breaks the
integrity value and the confirmation is refused: the 15 minute life
cannot be extended by editing the file that states it. The cycle
additionally rebuilds the order list from CURRENT prices at
confirmation time and refuses if it differs from the previewed list
order for order, so a stale preview cannot be confirmed against
moved prices either.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

PREVIEW_FILE = "last_preview.json"
PREVIEW_KEY_FILE = "preview_key.txt"
PREVIEW_TTL = timedelta(minutes=15)


class PreviewError(ValueError):
    """A confirmation that cannot be honoured (unknown, superseded,
    tampered, or expired preview). Nothing is sent."""


def _key_path(state_dir) -> Path:
    return Path(state_dir) / PREVIEW_KEY_FILE


def _load_or_create_key(state_dir) -> bytes:
    """The per install preview key. Stored apart from the preview
    file itself, so editing last_preview.json cannot recompute the
    integrity value. Created once, on first use."""
    p = _key_path(state_dir)
    try:
        raw = p.read_text(encoding="utf-8").strip()
        key = bytes.fromhex(raw)
        if len(key) >= 16:
            return key
    except Exception:
        pass
    key = os.urandom(32)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(key.hex(), encoding="utf-8")
        tmp.replace(p)
    finally:
        if tmp.exists():
            tmp.unlink()
    return key


def _integrity_of(preview: dict, key: bytes) -> str:
    body = {k: v for k, v in preview.items()
            if k not in ("integrity", "_source_dir")}
    canon = json.dumps(body, allow_nan=False, sort_keys=True)
    return hmac.new(key, canon.encode("utf-8"), hashlib.sha256).hexdigest()


def build_preview(orders: list[dict], mode: str,
                  prices: dict[str, float], held_values: dict[str, float],
                  pot_equity: float, caps_ok: bool) -> dict:
    """Shape the order list for display. `prices` are the latest
    prices the notionals were sized from; resulting weights are
    estimates at those prices, labelled as estimates."""
    rows = []
    resulting = dict(held_values or {})
    for o in orders:
        sym = str(o["symbol"]).strip().upper()
        n = float(o["notional"])
        if o["side"] == "buy":
            resulting[sym] = resulting.get(sym, 0.0) + n
        else:
            resulting[sym] = resulting.get(sym, 0.0) - n
            if resulting[sym] <= 0.005:
                resulting.pop(sym, None)
        rows.append({
            "symbol": sym, "side": o["side"], "notional": round(n, 2),
            "latest_price": prices.get(sym),
            "est_resulting_value": round(resulting.get(sym, 0.0), 2),
            "est_resulting_weight": (round(resulting.get(sym, 0.0) / pot_equity, 4)
                                     if pot_equity else None),
        })
    now = datetime.now()
    return {"preview_id": uuid.uuid4().hex,
            "created_at": now.isoformat(timespec="seconds"),
            "expires_at": (now + PREVIEW_TTL).isoformat(timespec="seconds"),
            "mode": mode, "orders": rows, "caps_ok": bool(caps_ok),
            "pot_equity": round(float(pot_equity), 2)}


def save_preview(preview: dict, state_dir) -> Path:
    """Stamp the preview with its keyed integrity value and save it
    atomically. The stamped copy is what is written (and returned via
    the file); the caller's dict gains the integrity field too."""
    key = _load_or_create_key(state_dir)
    preview.pop("_source_dir", None)
    preview["integrity"] = _integrity_of(preview, key)
    p = Path(state_dir) / PREVIEW_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(preview, indent=1), encoding="utf-8")
        tmp.replace(p)
    finally:
        if tmp.exists():
            tmp.unlink()
    return p


def load_preview(state_dir) -> dict | None:
    p = Path(state_dir) / PREVIEW_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    # In memory only (never written back by save_preview, and excluded
    # from the integrity value): where this preview was loaded from,
    # so require_confirmation can find the key that seals it even when
    # the caller does not pass the directory explicitly.
    data["_source_dir"] = str(Path(state_dir))
    return data


def require_confirmation(preview: dict | None, preview_id: str | None,
                         now: datetime | None = None,
                         state_dir=None) -> dict:
    """Validate a confirmation against the saved preview. Returns the
    preview when the confirmation is good; raises PreviewError
    otherwise (nothing may be sent).

    The integrity value is verified FIRST, whenever the preview's
    state directory is known (the cycle always passes it; a caller
    that cannot name the directory gets the legacy field checks
    only, and the cycle is the only path that can submit). A preview
    whose contents were edited after it was saved, expiry included,
    is refused as tampered."""
    if preview is None:
        raise PreviewError("no order preview is on record; run the "
                           "cycle to build one before confirming")
    if not preview_id or preview_id != preview.get("preview_id"):
        raise PreviewError("the confirmation does not name the current "
                           "preview; nothing was sent")
    if state_dir is None:
        state_dir = preview.get("_source_dir")
    if state_dir is not None:
        key = _load_or_create_key(state_dir)
        stored = preview.get("integrity")
        if not isinstance(stored, str) \
                or not hmac.compare_digest(stored,
                                           _integrity_of(preview, key)):
            raise PreviewError("the saved preview fails its integrity "
                               "check (it was edited after it was "
                               "shown); run the cycle again to build a "
                               "fresh one. Nothing was sent.")
    now = now or datetime.now()
    try:
        expires = datetime.fromisoformat(preview["expires_at"])
    except Exception:
        raise PreviewError("the saved preview has no readable expiry; "
                           "nothing was sent") from None
    if now > expires:
        raise PreviewError("this preview has expired (previews live "
                           "15 minutes); run the cycle again to build "
                           "a fresh one. Nothing was sent.")
    if not preview.get("caps_ok"):
        raise PreviewError("this preview failed its cap check; nothing "
                           "was sent")
    return preview
