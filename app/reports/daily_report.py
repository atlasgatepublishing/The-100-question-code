"""Daily report — Terry's per-pot daily report (DESIGN.md).

Writes ``app/reports/output/YYYY-MM-DD.md`` and ``.json``.
Simulation context only. Down days are reported, not hidden.

Run directly for a labelled SAMPLE demo:
    python3 -m app.reports.daily_report        (from ~/workspace/stock-app)
    python3 app/reports/daily_report.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # direct-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _common import (GOAL, ReportDataError, esc, estimated_taxes, max_drawdown_pct,
                         money, pct, pct_plain, require_finite, require_keys,
                         sample_pot_states, sanitize_json, spy_shadow, validated_curve,
                         validated_positions, validated_trades, versioned_write_pair, win_stats)
else:
    from ._common import (GOAL, ReportDataError, esc, estimated_taxes, max_drawdown_pct,
                          money, pct, pct_plain, require_finite, require_keys,
                          sample_pot_states, sanitize_json, spy_shadow, validated_curve,
                          validated_positions, validated_trades, versioned_write_pair, win_stats)

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def build_daily_report(pot_states: list[dict[str, Any]], report_date: str | None = None,
                       sample: bool = False) -> dict[str, Any]:
    day = report_date or date.today().isoformat()
    try:
        date.fromisoformat(str(day))
    except ValueError:
        raise ReportDataError(f"daily report: report_date is not a valid ISO date: {day!r}") from None
    pots = []
    for s in pot_states:
        # QA M-12/H-6: required keys and finite numbers, validated up front.
        require_keys(s, ("pot_id", "start_balance", "balance"), "daily report")
        pid = s["pot_id"]
        start = require_finite(s["start_balance"], "start_balance", pid)
        bal = require_finite(s["balance"], "balance", pid)
        # QA M-15: prev_balance absent means "no prior close supplied" —
        # day gain is reported as unavailable (with a first_day flag when
        # the report date IS the pot's start date), never silently
        # replaced by the lifetime gain.
        has_prev = s.get("prev_balance") is not None
        prev = require_finite(s["prev_balance"], "prev_balance", pid) if has_prev else None
        # R2-M4: positions/trades/curve validated finite up front, and the
        # report is built from the VALIDATED copies (never the raw state).
        s = {**s, "positions": validated_positions(s),
             "trades": validated_trades(s), "equity_curve": validated_curve(s)}
        trades = s.get("trades", [])
        today = [t for t in trades if str(t.get("date")) == day]
        ws, spy = win_stats(s), spy_shadow(s)
        pots.append({
            "pot_id": pid, "name": s.get("name", pid),
            # QA M-6: status/episode travel with the pot state.
            "status": s.get("status"), "episode": s.get("episode"),
            "halted_on": s.get("halted_on"), "track_only": bool(s.get("track_only", False)),
            "strategy": s.get("strategy"),
            "balance": round(bal, 2),
            "cash": (round(require_finite(s["cash"], "cash", pid), 2)
                     if s.get("cash") is not None else None),
            "day_gain": round(bal - prev, 2) if has_prev else None,
            "day_gain_pct": (round(100.0 * (bal - prev) / prev, 2) if prev else None) if has_prev else None,
            "day_gain_available": has_prev,
            "first_day": (not has_prev) and str(s.get("start_date") or "") == day,
            "total_gain": round(bal - start, 2),
            "total_gain_pct": round(100.0 * (bal - start) / start, 2) if start else None,
            "trades_today": len(today), "trades_total": len(trades),
            "closed_trades": ws["closed"], "win_rate_pct": ws["win_rate_pct"],
            "positions": s.get("positions", []),
            "max_drawdown_pct": max_drawdown_pct(s.get("equity_curve", [])),
            "total_costs": round(require_finite(s.get("total_costs", 0.0), "total_costs", pid), 2),
            "estimated_taxes": estimated_taxes(s),
            "estimated_taxes_note": "ESTIMATE only (short-term gains x pot tax rate). Not tax advice.",
            "watcher_actions": s.get("watcher_actions", []),
            "news_actions": s.get("news_actions", []),
            "distance_to_goal": round(GOAL - bal, 2), "goal": GOAL,
            "spy_shadow": spy,
        })
    return {"report": "daily", "date": day, "sample": sample,
            "label": "SAMPLE — fabricated demo data" if sample else "LIVE STATE",
            "simulation_only": True, "pots": pots}


def render_markdown(report: dict[str, Any]) -> str:
    lines = [f"# Daily Report — {report['date']}", ""]
    if report["sample"]:
        lines += ["> **SAMPLE — fabricated demo data, not a real run.**", ""]
    lines += ["Simulation only. Down days are reported, not hidden.", ""]
    for p in report["pots"]:
        # QA H-3: every free-text field is escaped at generation (esc()).
        status_bits = []
        if p.get("status"):
            status_bits.append(f"status {esc(p['status'])}")
        if p.get("episode"):
            status_bits.append(f"episode {p['episode']}")
        if p.get("halted_on"):
            status_bits.append(f"halted {esc(p['halted_on'])}")
        if p.get("track_only"):
            status_bits.append("track-only")
        lines += [f"## {esc(p['name'])} (`{esc(p['pot_id'])}`)", ""]
        if status_bits:
            lines += [f"- **Status:** {' · '.join(status_bits)}"]
        lines += [f"- **Balance:** {money(p['balance'])} (cash {money(p['cash'])})",
                  f"- **Today:** {money(p['day_gain'])} ({pct(p['day_gain_pct'])})"
                  if p["day_gain_available"] else
                  "- **Today:** — (no prior close supplied"
                  + ("; first day)" if p["first_day"] else ")"),
                  f"- **Total:** {money(p['total_gain'])} ({pct(p['total_gain_pct'])})",
                  f"- **Trades:** {p['trades_today']} today / {p['trades_total']} total "
                  f"({p['closed_trades']} closed, win rate {f"{p['win_rate_pct']:.2f}%" if p['win_rate_pct'] is not None else '—'})",
                  f"- **Worst drawdown so far:** {pct_plain(p['max_drawdown_pct'])}",
                  f"- **Total costs/fees:** {money(p['total_costs'])}",
                  f"- **Estimated taxes:** {money(p['estimated_taxes'])} — *estimate only, not tax advice*",
                  f"- **Distance to $1,000,000:** {money(p['distance_to_goal'])} remaining", ""]
        lines.append("**Positions:**")
        if p["positions"]:
            lines += ["| Symbol | Shares | Avg cost | Price | Value | Unrealised P&L |",
                      "|---|---|---|---|---|---|"]
            lines += [f"| {esc(q.get('symbol'))} | {q['shares']} | {money(q.get('avg_cost'))} | "
                      f"{money(q.get('current_price'))} | {money(q.get('market_value'))} | "
                      f"{money(q.get('unrealized_pl'))} |" for q in p["positions"]]
        else:
            lines.append("- None (all cash)")
        lines.append("")
        if p["spy_shadow"]:
            sp = p["spy_shadow"]
            lines += [f"**SPY shadow (same dollars & dates):** {money(sp['shadow_balance'])} "
                      f"({pct(sp['total_gain_pct'])}) vs pot {money(p['balance'])}.", ""]
        lines += ["**Watcher / news actions today:**"]
        lines += [f"- Watcher: {esc(a)}" for a in p["watcher_actions"]] or ["- Watcher: none"]
        lines += [f"- News: {esc(a)}" for a in p["news_actions"]] or ["- News: none"]
        lines.append("")
    return "\n".join(lines)


def write_daily_report(pot_states: list[dict[str, Any]], report_date: str | None = None,
                       sample: bool = False, output_dir: str | Path | None = None) -> dict[str, str]:
    report = build_daily_report(pot_states, report_date, sample=sample)
    out = Path(output_dir) if output_dir else OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    # QA H-6: sanitised + allow_nan=False — no bare NaN/Infinity tokens.
    clean = sanitize_json(report)
    json_text = json.dumps(clean, indent=2, allow_nan=False)
    # QA M-7 + R2-M8: versioned writes — the .md/.json pair versions
    # TOGETHER, so a base-name pair always describes the same state.
    md_path, json_path = versioned_write_pair(
        out / f"{report['date']}.md", render_markdown(report),
        out / f"{report['date']}.json", json_text)
    return {"markdown": str(md_path), "json": str(json_path)}


if __name__ == "__main__":
    paths = write_daily_report(sample_pot_states(), report_date="2026-11-21", sample=True)
    print("SAMPLE daily report written:")
    print(paths["markdown"]); print(paths["json"])
