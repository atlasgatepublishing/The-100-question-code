"""Hard caps layer (design gate 6.5, DECISIONS.md ruling 2).

Checked twice: once when the order list is built (check_order_list)
and once inside the submission wrapper, per order, immediately before
the order is sent (check_single_order). No order that would breach a
cap is submitted; the refusal is audit logged by the caller.

The caps:
  * Pot ceiling: the user sets their pot size in config
    ("champion_pot_size"); the shipped hard ceiling is $10,000 per
    pot. The ceiling is a constant in this file, not a user setting:
    raising it is a code change and a new release, never a
    configuration toggle. A config asking for more is refused.
  * Exactly five positions at most.
  * 20 percent of pot equity in any one name, measured on the
    position's value after the order.
  * Market orders with day time in force only (the live path's shape,
    design gate 6.8): long only, no margin, no options, no shorting.
    A sell may never exceed the value actually held in that name.
"""
from __future__ import annotations

import math

POT_CEILING = 10_000.0       # shipped hard ceiling, dollars per pot
DEFAULT_POT_SIZE = 100.0     # the book's pot, when the user sets none
MAX_POSITIONS = 5
POSITION_CAP_FRACTION = 0.20
_WEIGHT_TOLERANCE = 0.005    # half a cent of slack for price movement
                             # between the check and the fill


class CapsError(ValueError):
    """A cap refusal. The order (or the whole list) must not be sent."""


def _finite_positive(v, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) \
            or not math.isfinite(float(v)) or float(v) <= 0:
        raise CapsError(f"{what} must be a positive finite number, got {v!r}")
    return float(v)


def pot_size_from_config(cfg: dict) -> float:
    """The user's pot size, validated against the shipped ceiling."""
    cfg = cfg if isinstance(cfg, dict) else {}
    raw = cfg.get("champion_pot_size", DEFAULT_POT_SIZE)
    size = _finite_positive(raw, "champion_pot_size")
    if size > POT_CEILING:
        raise CapsError(
            f"champion_pot_size ${size:,.2f} exceeds this app's shipped "
            f"hard ceiling of ${POT_CEILING:,.2f} per pot. Lower the pot "
            f"size in config.local.json; the ceiling itself can only "
            f"change in a new release of the app.")
    return size


def _validate_order_shape(order: dict) -> None:
    if not isinstance(order, dict):
        raise CapsError(f"order must be an object, got {order!r}")
    sym = order.get("symbol")
    if not isinstance(sym, str) or not sym.strip():
        raise CapsError(f"order symbol must be a non-empty string, got {sym!r}")
    if order.get("side") not in ("buy", "sell"):
        raise CapsError(f"order side must be 'buy' or 'sell', got {order.get('side')!r}")
    _finite_positive(order.get("notional"), f"order notional for {sym}")
    otype = order.get("order_type", "market")
    if otype != "market":
        raise CapsError(
            f"only market orders are permitted in this app (got "
            f"{otype!r} for {sym}); limit, stop and options orders are "
            f"outside the champion's tested shape")
    tif = order.get("time_in_force", "day")
    if tif != "day":
        raise CapsError(
            f"only day time in force is permitted (got {tif!r} for {sym})")


def _apply(order: dict, held: dict[str, float]) -> dict[str, float]:
    out = dict(held)
    sym = order["symbol"].strip().upper()
    n = float(order["notional"])
    if order["side"] == "buy":
        out[sym] = out.get(sym, 0.0) + n
    else:
        out[sym] = out.get(sym, 0.0) - n
        if out[sym] < -_WEIGHT_TOLERANCE:
            raise CapsError(
                f"sell of ${n:,.2f} of {sym} exceeds the value held "
                f"(${held.get(sym, 0.0):,.2f}); shorting is not permitted")
        if out[sym] <= _WEIGHT_TOLERANCE:
            out.pop(sym, None)
    return out


def _check_resulting(resulting: dict[str, float], pot_equity: float,
                     pot_size: float) -> None:
    if pot_equity > pot_size + _WEIGHT_TOLERANCE:
        raise CapsError(
            f"pot value ${pot_equity:,.2f} exceeds the user's pot size "
            f"${pot_size:,.2f}; the app will not trade a pot larger "
            f"than the size its owner set")
    if len(resulting) > MAX_POSITIONS:
        raise CapsError(
            f"the order list would leave {len(resulting)} positions; "
            f"the champion holds exactly {MAX_POSITIONS} at most")
    cap_dollars = POSITION_CAP_FRACTION * pot_equity
    for sym, val in resulting.items():
        if val > cap_dollars + _WEIGHT_TOLERANCE:
            raise CapsError(
                f"{sym} would be ${val:,.2f} of a ${pot_equity:,.2f} "
                f"pot ({val / pot_equity:.1%}), over the 20 percent "
                f"position cap")


def check_order_list(orders: list[dict], held_values: dict[str, float],
                     pot_equity: float, pot_size: float) -> list[dict]:
    """First check: the whole list, applied in order. Returns the list
    unchanged when every cap holds; raises CapsError on the first
    breach. `held_values` maps symbol to current dollar value;
    `pot_equity` is the pot's total value the orders are sized
    against."""
    equity = _finite_positive(pot_equity, "pot equity")
    size = _finite_positive(pot_size, "pot size")
    if size > POT_CEILING:
        raise CapsError(f"pot size ${size:,.2f} exceeds the shipped "
                        f"ceiling of ${POT_CEILING:,.2f}")
    resulting = {str(k).strip().upper(): _finite_positive(v, f"held value for {k}")
                 for k, v in (held_values or {}).items() if float(v) > 0}
    for order in orders or []:
        _validate_order_shape(order)
        resulting = _apply(order, resulting)
    _check_resulting(resulting, equity, size)
    return list(orders or [])


def check_single_order(order: dict, held_values: dict[str, float],
                       pot_equity: float, pot_size: float) -> dict:
    """Second check: one order, inside the submission wrapper,
    immediately before it is sent. Same rules as the list check."""
    check_order_list([order], held_values, pot_equity, pot_size)
    return order
