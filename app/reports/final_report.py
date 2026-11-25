"""Final (end-of-run) report — DESIGN.md final-report spec.

Produced when a run ends: $1,000,000 finish line, Terry's stop, or the
-15% floor. Simulation context only. Same pot-state interface as the
daily report (see ``_common.py``).

Run directly for a labelled SAMPLE output:
    python3 app/reports/final_report.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _common import (GOAL, ReportDataError, closed_trades, esc, estimated_taxes,
                         max_drawdown_pct, money, pct, pct_plain, require_finite,
                         require_keys, sample_pot_states, sanitize_json, spy_shadow,
                         validated_curve, validated_positions, validated_trades,
                         versioned_write_pair, win_stats)
else:
    from ._common import (GOAL, ReportDataError, closed_trades, esc, estimated_taxes,
                          max_drawdown_pct, money, pct, pct_plain, require_finite,
                          require_keys, sample_pot_states, sanitize_json, spy_shadow,
                          validated_curve, validated_positions, validated_trades,
                          versioned_write_pair, win_stats)

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def _daily_changes(curve: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for prev, cur in zip(curve, curve[1:]):
        out.append({"date": cur["date"], "change": round(float(cur["balance"]) - float(prev["balance"]), 2)})
    return out


def _trading_days(curve: list[dict[str, Any]]) -> int:
    """QA M-6: trading days derived from the DATED curve points, not
    ``len(curve) - 1``: the count of weekdays (Mon–Fri) after the first
    dated point up to and including the last dated point. A 2-point curve
    spanning 19 calendar days therefore reports the ~14 trading days in
    that span instead of "1". Falls back to point intervals when dates
    are unparseable."""
    dates = []
    for pt in curve:
        try:
            dates.append(date.fromisoformat(str(pt["date"])))
        except (ValueError, KeyError, TypeError):
            continue
    if len(dates) < 2:
        return max(len(curve) - 1, 0)
    first, last = min(dates), max(dates)
    days, d = 0, first
    from datetime import timedelta
    while d < last:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days += 1
    return days


def build_final_report(state: dict[str, Any], end_reason: str = "Terry pressed stop",
                       end_date: str | None = None, sample: bool = False) -> dict[str, Any]:
    # QA M-12: required keys / dates validated up front, with names.
    require_keys(state, ("pot_id", "start_date", "start_balance", "balance"), "final report")
    pid = state["pot_id"]
    start_bal = require_finite(state["start_balance"], "start_balance", pid)
    final_bal = require_finite(state["balance"], "balance", pid)
    try:
        start_d = date.fromisoformat(str(state["start_date"]))
    except ValueError:
        raise ReportDataError(f"final report: start_date is not a valid ISO date: "
                              f"{state['start_date']!r} (pot {pid})") from None
    curve = sorted(state.get("equity_curve", []), key=lambda p: str(p["date"]))
    try:
        end_d = date.fromisoformat(end_date) if end_date else (
            date.fromisoformat(str(curve[-1]["date"])) if curve else start_d)
    except ValueError:
        raise ReportDataError(f"final report: end_date is not a valid ISO date: "
                              f"{end_date!r} (pot {pid})") from None
    if end_d < start_d:
        raise ReportDataError(f"final report: end_date {end_d} is before start_date "
                              f"{start_d} (pot {pid})")
    # R2-M4: positions/trades/curve validated finite up front; the report
    # is built from the VALIDATED copies.
    state = {**state, "positions": validated_positions(state),
             "trades": validated_trades(state),
             "equity_curve": validated_curve(state)}
    curve = sorted(state["equity_curve"], key=lambda p: str(p["date"]))
    ws = win_stats(state)
    changes = _daily_changes(curve)
    by_stock: dict[str, float] = defaultdict(float)
    by_strategy: dict[str, float] = defaultdict(float)
    default_strategy = str(state.get("strategy") or state.get("name") or pid)
    for t in closed_trades(state):
        # QA M-12: a closed trade with no symbol groups under UNKNOWN
        # instead of crashing the whole report.
        by_stock[str(t.get("symbol") or "UNKNOWN").upper()] += float(t["pnl"])
        by_strategy[str(t.get("strategy") or default_strategy)] += float(t["pnl"])
    fees_from_trades = sum(float(t.get("fees", 0.0) or 0.0) for t in state.get("trades", []))
    # R2-L9: profit split by episode — episode 2 begins at each recorded
    # restart date, so the second chance Terry restarted the pot for can
    # be read on its own. Absent restart dates, the key is omitted.
    restart_dates = sorted(str(d)[:10] for d in (state.get("restart_dates") or []))
    by_episode: dict[str, float] = defaultdict(float)
    if restart_dates:
        for t in closed_trades(state):
            ep = 1 + sum(1 for rd in restart_dates if str(t.get("date")) >= rd)
            by_episode[str(ep)] += float(t["pnl"])
    return {
        "report": "final", "sample": sample,
        "label": "SAMPLE — fabricated demo data" if sample else "LIVE STATE",
        "simulation_only": True,
        "pot_id": pid, "name": state.get("name", pid),
        # QA M-6: status/episode/strategy carried through.
        "status": state.get("status"), "episode": state.get("episode"),
        "halted_on": state.get("halted_on"), "track_only": bool(state.get("track_only", False)),
        "strategy": state.get("strategy"),
        "end_reason": end_reason, "start_date": str(state["start_date"]),
        "end_date": end_d.isoformat(),
        "duration_calendar_days": (end_d - start_d).days,
        "duration_trading_days": _trading_days(curve),
        "start_balance": start_bal, "final_balance": final_bal,
        "total_gain": round(final_bal - start_bal, 2),
        # QA H-4: same zero-denominator guard the daily report already had.
        "total_gain_pct": (round(100.0 * (final_bal - start_bal) / start_bal, 2)
                           if start_bal else None),
        "distance_to_goal_at_end": round(GOAL - final_bal, 2),
        "total_trades": len(state.get("trades", [])), "closed_trades": ws["closed"],
        "win_rate_pct": ws["win_rate_pct"], "avg_win": ws["avg_win"], "avg_loss": ws["avg_loss"],
        "biggest_win": ws["biggest_win"], "biggest_loss": ws["biggest_loss"],
        "best_day": max(changes, key=lambda c: c["change"]) if changes else None,
        "worst_day": min(changes, key=lambda c: c["change"]) if changes else None,
        "max_drawdown_pct": max_drawdown_pct(curve),
        "total_costs": round(require_finite(state.get("total_costs", fees_from_trades),
                                            "total_costs", pid), 2),
        "estimated_taxes": estimated_taxes(state),
        "estimated_taxes_note": "ESTIMATE only (short-term gains x pot tax rate). Not tax advice.",
        "profit_by_stock": {k: round(v, 2) for k, v in sorted(by_stock.items())},
        "profit_by_episode": ({k: round(v, 2) for k, v in sorted(by_episode.items())}
                              if restart_dates else None),
        "profit_by_strategy": {k: round(v, 2) for k, v in sorted(by_strategy.items())},
        "full_trade_log": state.get("trades", []),
        "spy_shadow": spy_shadow(state),
        "watcher_actions": state.get("watcher_actions", []),
        "news_actions": state.get("news_actions", []),
    }


def _fmt_day(d: dict[str, Any] | None) -> str:
    """QA L-2: best/worst day renders as '2026-11-13 (−$4.60)', not a raw dict."""
    if not d:
        return "—"
    return f"{esc(d.get('date'))} ({money(d.get('change'))})"


def render_markdown(r: dict[str, Any]) -> str:
    lines = [f"# Final Report — {esc(r['name'])}", ""]
    if r["sample"]:
        lines += ["> **SAMPLE — fabricated demo data, not a real run.**", ""]
    status_bits = []
    if r.get("status"):
        status_bits.append(f"status {esc(r['status'])}")
    if r.get("episode"):
        status_bits.append(f"episode {r['episode']}")
    if r.get("halted_on"):
        status_bits.append(f"halted {esc(r['halted_on'])}")
    lines += [f"Simulation only. **End reason:** {esc(r['end_reason'])}", ""]
    if status_bits:
        lines += [f"- **Status:** {' · '.join(status_bits)}"]
    lines += [f"- **Duration:** {r['duration_calendar_days']} calendar days / {r['duration_trading_days']} trading days "
              f"({r['start_date']} → {r['end_date']})",
              f"- **Result:** {money(r['start_balance'])} → {money(r['final_balance'])} "
              f"({money(r['total_gain'])}, {pct(r['total_gain_pct'])}); "
              f"{money(r['distance_to_goal_at_end'])} short of $1,000,000",
              f"- **Trades:** {r['total_trades']} total / {r['closed_trades']} closed; "
              f"win rate {f"{r['win_rate_pct']:.2f}%" if r['win_rate_pct'] is not None else '—'}",
              f"- **Avg win / avg loss:** {money(r['avg_win'])} / {money(r['avg_loss'])}",
              f"- **Biggest win / loss:** {money(r['biggest_win'])} / {money(r['biggest_loss'])}",
              f"- **Best / worst day:** {_fmt_day(r['best_day'])} / {_fmt_day(r['worst_day'])}",
              f"- **Max drawdown:** {pct_plain(r['max_drawdown_pct'])}",
              f"- **Total costs/fees:** {money(r['total_costs'])}; "
              f"**estimated taxes:** {money(r['estimated_taxes'])} (*estimate only*)", ""]
    if r["spy_shadow"]:
        sp = r["spy_shadow"]
        lines += [f"**SPY shadow (same dollars & dates):** {money(sp['shadow_balance'])} ({pct(sp['total_gain_pct'])}).", ""]
    if r.get("watcher_actions") or r.get("news_actions"):
        lines += ["**Watcher / news actions:**"]
        lines += [f"- Watcher: {esc(a)}" for a in r.get("watcher_actions", [])]
        lines += [f"- News: {esc(a)}" for a in r.get("news_actions", [])]
        lines.append("")
    lines += ["## Profit by stock", ""]
    lines += [f"- {esc(k)}: {money(v)}" for k, v in r["profit_by_stock"].items()] or ["- None"]
    if r.get("profit_by_episode"):
        lines += ["", "## Profit by episode", ""]
        lines += [f"- Episode {esc(k)}: {money(v)}" for k, v in r["profit_by_episode"].items()]
    lines += ["", "## Profit by strategy", ""]
    lines += [f"- {esc(k)}: {money(v)}" for k, v in r["profit_by_strategy"].items()] or ["- None"]
    lines += ["", "## Full trade log", "", "| Date | Symbol | Side | Shares | Price | Amount | P&L | Fees |",
              "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {esc(t.get('date'))} | {esc(t.get('symbol'))} | {esc(t.get('side'))} | {t.get('shares')} | "
              f"{money(t.get('price'))} | {money(t.get('amount'))} | "
              f"{money(t.get('pnl')) if t.get('pnl') is not None else '—'} | {money(t.get('fees'))} |"
              for t in r["full_trade_log"]]
    lines.append("")
    return "\n".join(lines)


def write_final_report(state: dict[str, Any], end_reason: str = "Terry pressed stop",
                       end_date: str | None = None, sample: bool = False,
                       output_dir: str | Path | None = None) -> dict[str, str]:
    r = build_final_report(state, end_reason, end_date, sample=sample)
    out = Path(output_dir) if output_dir else OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    # R2-L6: the filename stem is sanitised — a pot_id like '../evil'
    # from a hand-built state dict must not reach the path raw.
    import re as _re
    safe_pid = _re.sub(r"[^A-Za-z0-9_-]+", "_", str(r["pot_id"]))
    stem = f"final-{safe_pid}-{r['end_date']}"
    # QA H-6: sanitised + allow_nan=False. QA M-7 + R2-M8: paired writes.
    json_text = json.dumps(sanitize_json(r), indent=2, allow_nan=False)
    md_path, json_path = versioned_write_pair(
        out / f"{stem}.md", render_markdown(r),
        out / f"{stem}.json", json_text)
    return {"markdown": str(md_path), "json": str(json_path)}


if __name__ == "__main__":
    demo = sample_pot_states()[0]
    paths = write_final_report(demo, end_reason="SAMPLE demo — Terry pressed stop (fabricated)",
                               end_date="2026-11-21", sample=True)
    print("SAMPLE final report written:")
    print(paths["markdown"]); print(paths["json"])
