"""Aggregate per-pot state files into the dashboard's combined state file.

Each Pot persists itself to state/<pot_id>.json after every change
(pots/pot.py). The dashboard reads a single combined document with a
"pots" list, so this script converts the per-pot snapshots into
state/app_state.json. Run it any time (run.py does it automatically
before serving the dashboard). Pure file I/O -- no trading, no network.

Balance shown = cash + positions marked at each pot's last recorded
prices (avg cost when no later price exists). Status is taken from the
saved protection state, so what the dashboard shows after a shutdown is
exactly where the last shutdown left off.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path


class AdapterDataError(ValueError):
    """A saved pot's ledger/positions cannot be adapted honestly
    (QA R2-H2/R2-M2). Per-pot isolation in load_report_states()/main()
    turns this into a skipped pot with a named warning, never invented
    numbers and never a failure for every other pot (R2-M3)."""

APP_DIR = Path(__file__).resolve().parent
STATE_DIR = APP_DIR / "state"
OUT = STATE_DIR / "app_state.json"
REPORT_OUT = STATE_DIR / "report_state.json"

# DERIVED APP ADAPTATION (recorded in BUILD-REPORT.md): the frozen
# file mapped seven pots onto dashboard demo ids. This app has one
# pot; the map keeps only the champion's entry.
ID_MAP = {
    "champion": "vm",
}
STRATEGY = {
    "vm": "Champion — value + momentum, quarterly",
}


def pot_status(d: dict) -> str:
    if d.get("track_only"):
        return "tracking only"
    prot = d.get("protection") or {}
    st = prot.get("status", "active")
    if st == "ended":
        return "ended"
    if st == "waiting_restart":
        return "halted"
    if int(prot.get("episode", 1)) >= 2:
        return "episode 2"
    return "running"


def convert(d: dict) -> dict:
    pid = ID_MAP.get(d["pot_id"], d["pot_id"])
    prices = (d.get("meta") or {}).get("last_prices") or {}
    holdings, mkt = [], 0.0
    for sym, pos in sorted((d.get("positions") or {}).items()):
        px = float(prices.get(sym, pos.get("avg_cost", 0.0)))
        val = round(float(pos["shares"]) * px, 2)
        mkt += val
        holdings.append({"ticker": sym, "price": px, "value": val,
                         "change_pct": 0.0, "shares": pos["shares"]})
    prot = d.get("protection") or {}
    return {
        "id": pid,
        "name": d.get("name", pid),
        "strategy": STRATEGY.get(pid, ""),
        "status": pot_status(d),
        "start": d.get("start_balance", 100.0),
        "balance": round(float(d.get("cash", 0.0)) + mkt, 2),
        "cash": round(float(d.get("cash", 0.0)), 2),
        "day_usd": 0.0, "day_pct": 0.0,
        "episode": int(prot.get("episode", 1)),
        "floor": round(float(prot.get("episode_start_balance", d.get("start_balance", 100.0))) * 0.85, 2),
        "halted_on": prot.get("halt_date"),
        "restart_on": prot.get("restart_eligible_date"),
        "holdings": holdings,
        "trades": [],
    }


def _row_num(row: dict, field_name: str, idx: int, pot_id: str) -> float:
    """Strict numeric field for the adapter (R2-M2): present, a real
    number (not bool/str), finite — or a named AdapterDataError. The
    adapter is the trust boundary for saved state files; it validates
    like pots/ledger.py's Trade.from_dict instead of defaulting."""
    if field_name not in row or row[field_name] is None:
        raise AdapterDataError(
            f"pot {pot_id}: ledger row {idx} is missing '{field_name}'")
    v = row[field_name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise AdapterDataError(
            f"pot {pot_id}: ledger row {idx} field '{field_name}' is not a number: {v!r}")
    f = float(v)
    if not math.isfinite(f):
        raise AdapterDataError(
            f"pot {pot_id}: ledger row {idx} field '{field_name}' is not finite: {v!r}")
    return f


def _report_trades(ledger_rows: list[dict], pot_id: str = "?"):
    """Convert ledger rows to report trades (QA H-5, hardened Round 2).

    The ledger's Trade rows carry date/symbol/side/shares/price/gross/
    cost/net — no pnl/fees — while the reports select closed trades on
    ``pnl`` and read ``fees``. Realised P&L is therefore derived here by
    replaying the ledger in order with AVERAGE-COST accounting consistent
    with pots/pot.py's avg_cost tracking: a position's cost basis is its
    buys' gross PLUS their buy costs; each sell's pnl is its net proceeds
    (gross − sell cost, the ledger's own ``net``) minus the sold shares'
    share of that basis.

    Round 2 hardening:
      * R2-M2 — every row is validated like Trade.from_dict (required
        fields, real finite numbers, side in {buy, sell}, gross
        consistent with shares x price). No silent defaults.
      * R2-H2 — a sell larger than the shares actually held raises
        AdapterDataError. The old code priced uncovered sells at zero
        basis and booked the full proceeds as profit.
      * R2-M1 — when a sell fully closes a position, its pnl absorbs
        the accumulated cent-rounding residue, so a fully liquidated
        position's summed pnl equals its exact cash gain to the cent.

    Returns a list of report trades carrying a ``.book`` attribute —
    book maps symbol -> {"shares", "basis"} for positions still open
    (cost-inclusive; R2-M10). The list return keeps the pre-Round-2
    call shape for every existing caller.
    """
    book: dict[str, dict[str, float]] = {}
    out: list[dict] = []
    for idx, row in enumerate(ledger_rows or []):
        if not isinstance(row, dict):
            raise AdapterDataError(f"pot {pot_id}: ledger row {idx} is not an object")
        sym_raw = row.get("symbol")
        if not isinstance(sym_raw, str) or not sym_raw.strip():
            raise AdapterDataError(f"pot {pot_id}: ledger row {idx} has no symbol")
        sym = sym_raw.strip().upper()
        side = str(row.get("side", "")).strip().lower()
        if side not in ("buy", "sell"):
            raise AdapterDataError(
                f"pot {pot_id}: ledger row {idx} side must be 'buy' or 'sell', got {row.get('side')!r}")
        d_raw = row.get("date")
        try:
            date.fromisoformat(str(d_raw)[:10])
        except (ValueError, TypeError):
            raise AdapterDataError(
                f"pot {pot_id}: ledger row {idx} date is not a valid ISO date: {d_raw!r}") from None
        shares = _row_num(row, "shares", idx, pot_id)
        price = _row_num(row, "price", idx, pot_id)
        cost = _row_num(row, "cost", idx, pot_id)
        if shares <= 0 or price <= 0 or cost < 0:
            raise AdapterDataError(
                f"pot {pot_id}: ledger row {idx} has non-positive shares/price or negative cost")
        if "gross" in row and row["gross"] is not None:
            gross = _row_num(row, "gross", idx, pot_id)
            expected = shares * price
            if abs(gross - expected) > max(0.02, 0.005 * expected):
                raise AdapterDataError(
                    f"pot {pot_id}: ledger row {idx} gross {gross} is inconsistent "
                    f"with shares x price {expected:.2f}")
        else:
            gross = round(shares * price, 2)
        pnl = None
        pos = book.setdefault(sym, {"shares": 0.0, "basis": 0.0,
                                    "cycle_basis": 0.0, "cycle_proceeds": 0.0,
                                    "cycle_booked": 0.0})
        if side == "buy":
            pos["basis"] += gross + cost
            pos["cycle_basis"] += gross + cost
            pos["shares"] += shares
        else:
            if shares > pos["shares"] + 1e-9:
                raise AdapterDataError(
                    f"pot {pot_id}: ledger row {idx} sells {shares} {sym} but only "
                    f"{pos['shares']} held — uncovered sell; refusing to invent profit")
            net = gross - cost
            pos["cycle_proceeds"] += net
            remaining = pos["shares"] - shares
            if remaining <= 1e-9:
                # Full close: this sell's pnl is whatever makes the whole
                # cycle sum to (total proceeds − total basis) exactly,
                # absorbing the cent-rounding residue (R2-M1).
                pnl = round(pos["cycle_proceeds"] - pos["cycle_basis"] - pos["cycle_booked"], 2)
                pos["shares"], pos["basis"] = 0.0, 0.0
                pos["cycle_basis"], pos["cycle_proceeds"], pos["cycle_booked"] = 0.0, 0.0, 0.0
            else:
                unit_basis = pos["basis"] / pos["shares"]
                pnl = round(net - shares * unit_basis, 2)
                pos["cycle_booked"] += pnl
                pos["basis"] -= shares * unit_basis
                pos["shares"] = remaining
        out.append({
            "date": str(d_raw)[:10], "symbol": sym, "side": side,
            "shares": shares, "price": price,
            "amount": round(gross, 2), "pnl": pnl, "fees": round(cost, 2),
        })
    result = _TradeList(out)
    result.book = book
    return result


class _TradeList(list):
    """A trade list with the adapter's closing book attached (.book)."""
    book: dict = {}


def pot_to_report_state(d: dict) -> dict:
    """THE Pot → report-state adapter (QA H-5).

    Takes a saved pot snapshot (the dict pots/pot.py persists) and emits
    the exact pot-state contract reports/_common.py documents — real
    trades with realised pnl + fees, positions, status and episode — so
    the daily/final reports report a real running pot's true closed-trade
    count, win rate, costs and estimated taxes. ``prev_balance`` and
    ``equity_curve`` are included only when the pot's meta carries them;
    when absent the daily report honestly marks day gain unavailable
    (QA M-15) instead of substituting the lifetime gain.
    """
    pid = d["pot_id"]
    prices = (d.get("meta") or {}).get("last_prices") or {}
    # R2-M9: a track-only pot never trades — its ledger rows are the
    # tracking positions being recorded, and its reports must show no
    # trades. The book is still replayed (it also validates the rows).
    adapted = _report_trades(d.get("ledger") or [], pot_id=str(pid))
    book = adapted.book
    track_only = bool(d.get("track_only", False))
    trades = [] if track_only else list(adapted)
    positions, mkt = [], 0.0
    for sym, pos in sorted((d.get("positions") or {}).items()):
        shares = float(pos["shares"])
        avg_cost = float(pos.get("avg_cost", 0.0))
        px = float(prices.get(sym, avg_cost))
        val = round(shares * px, 2)
        mkt += val
        # R2-M10: unrealised P&L uses the SAME cost-inclusive basis as
        # realised P&L (the adapter book's remaining basis), so realised
        # + unrealised reconciles to balance − start. Falls back to the
        # saved price-only average when the book has no such position.
        held = book.get(sym)
        if held and held["shares"] > 1e-12 and abs(held["shares"] - shares) <= 1e-6:
            unit_basis = held["basis"] / held["shares"]
            positions.append({
                "symbol": sym, "shares": shares, "avg_cost": round(unit_basis, 4),
                "current_price": px, "market_value": val,
                "unrealized_pl": round(val - held["basis"], 2),
            })
        else:
            positions.append({
                "symbol": sym, "shares": shares, "avg_cost": avg_cost,
                "current_price": px, "market_value": val,
                "unrealized_pl": round(shares * (px - avg_cost), 2),
            })
    prot = d.get("protection") or {}
    meta = d.get("meta") or {}
    # R2-L9: restart dates let the final report split profit by episode.
    restart_dates = sorted(
        str(h["restart_date"])[:10] for h in (prot.get("halts") or [])
        if isinstance(h, dict) and h.get("restart_date"))
    state: dict = {
        "pot_id": pid,
        "name": d.get("name", pid),
        "strategy": STRATEGY.get(ID_MAP.get(pid, pid), ""),
        "status": pot_status(d),
        "episode": int(prot.get("episode", 1)),
        "halted_on": prot.get("halt_date"),
        "restart_dates": restart_dates,
        "track_only": track_only,
        "start_date": d.get("start_date"),
        "start_balance": float(d.get("start_balance", 100.0)),
        "balance": round(float(d.get("cash", 0.0)) + mkt, 2),
        "cash": round(float(d.get("cash", 0.0)), 2),
        "total_costs": round(sum(t["fees"] for t in trades), 2),
        "positions": positions,
        "trades": trades,
        "watcher_actions": list(meta.get("watcher_actions") or []),
        "news_actions": list(meta.get("news_actions") or []),
    }
    if meta.get("prev_balance") is not None:
        state["prev_balance"] = float(meta["prev_balance"])
    if meta.get("equity_curve"):
        state["equity_curve"] = list(meta["equity_curve"])
    if meta.get("tax_rate") is not None:
        state["tax_rate"] = meta["tax_rate"]
    if meta.get("spy"):
        state["spy"] = meta["spy"]
    return state


def load_report_states(state_dir: Path | None = None) -> list[dict]:
    """All saved pots as report-ready states (QA H-5).

    R2-M3: per-pot isolation — one corrupt pot file is skipped with a
    named stderr warning; it can no longer take every other pot's
    reports down with it."""
    sd = Path(state_dir) if state_dir else STATE_DIR
    states = []
    for f in sorted(sd.glob("*.json")):
        if f.name in (OUT.name, REPORT_OUT.name):
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if isinstance(d, dict) and "pot_id" in d:
            try:
                states.append(pot_to_report_state(d))
            except Exception as e:
                print(f"WARNING: skipping pot file {f.name} for reports: "
                      f"{type(e).__name__}: {e}", file=sys.stderr)
    return states


def main() -> Path:
    pots, report_pots = [], []
    for f in sorted(STATE_DIR.glob("*.json")):
        if f.name in (OUT.name, REPORT_OUT.name):
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        if isinstance(d, dict) and "pot_id" in d:
            # R2-M3: the two conversions fail independently — a pot that
            # cannot be adapted for reports still reaches the dashboard,
            # and vice versa, each with a named warning.
            try:
                pots.append(convert(d))
            except Exception as e:
                print(f"WARNING: skipping pot file {f.name} for the dashboard: "
                      f"{type(e).__name__}: {e}", file=sys.stderr)
            try:
                report_pots.append(pot_to_report_state(d))
            except Exception as e:
                print(f"WARNING: skipping pot file {f.name} for reports: "
                      f"{type(e).__name__}: {e}", file=sys.stderr)
    if not pots:
        # No saved pots yet: write nothing, so the dashboard stays in its
        # clearly-labeled replay/demo mode instead of claiming live state.
        if OUT.exists():
            OUT.unlink()
        if REPORT_OUT.exists():
            REPORT_OUT.unlink()
        print("sync_state: no saved pots yet — dashboard stays in replay/demo mode")
        return OUT
    OUT.write_text(json.dumps({"pots": pots}, indent=1))
    # QA H-5: report-ready state (real trades/pnl/fees/status/episode)
    # for reports/daily_report.py + reports/final_report.py.
    REPORT_OUT.write_text(json.dumps({"pots": report_pots}, indent=1))
    print(f"sync_state: wrote {OUT} with {len(pots)} pot(s)")
    print(f"sync_state: wrote {REPORT_OUT} with {len(report_pots)} report-ready pot(s)")
    return OUT


if __name__ == "__main__":
    main()
