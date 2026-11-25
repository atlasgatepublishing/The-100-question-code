"""Shared helpers for daily / final reports (simulation context only).

POT STATE INPUT INTERFACE (the clean contract both reports consume)
-------------------------------------------------------------------
A pot state is a plain dict::

    {
      "pot_id": "champion",                 # required
      "name": "V+M Champion",               # optional, defaults to pot_id
      "start_date": "2026-01-05",           # ISO date, required
      "start_balance": 100.00,              # required
      "balance": 118.42,                    # current balance, required
      "prev_balance": 116.90,               # prior close (day P&L); optional
      "cash": 20.00,                        # optional
      "total_costs": 1.87,                  # cumulative fees/slippage $; optional
      "tax_rate": 0.22,                     # optional, default 0.22 (estimate)
      "positions": [ {"symbol","shares","avg_cost","current_price",
                      "market_value","unrealized_pl"} ],
      "trades":    [ {"date","symbol","side","shares","price","amount",
                      "pnl",      # realised P&L on sells/closes, else None
                      "fees"} ],
      "equity_curve": [ {"date","balance"} ],   # chronological
      "spy": {"start_price": 600.0, "current_price": 640.0},
      "watcher_actions": [str, ...],        # what watcher flagged / pot response
      "news_actions": [str, ...],
    }

SPY shadow: same starting dollars parked in SPY on ``start_date``;
``spy_shadow_balance = start_balance * current_price / start_price``.
"""
from __future__ import annotations

import html
import math
import re
import sys
from typing import Any

GOAL = 1_000_000.00
DEFAULT_TAX_RATE = 0.22  # labelled estimate only — not tax advice


class ReportDataError(ValueError):
    """Pot-state data cannot be reported honestly (missing/non-finite)."""


def money(x: float | None) -> str:
    return "—" if x is None else f"${x:,.2f}"


def pct(x: float | None) -> str:
    return "—" if x is None else f"{x:+.2f}%"


def pct_plain(x: float | None) -> str:
    """Percent without a forced '+' — for drawdown, where '+0.00%' for a
    never-down pot was misleading (QA M-5)."""
    return "—" if x is None else f"{x:.2f}%"


_CONTROL_CHARS = re.compile(
    "[\\x00-\\x08\\x0b-\\x1f\\x7f\\u202a-\\u202e\\u2066-\\u2069\\ufeff]")


def esc(text: Any) -> str:
    """Escape untrusted text for Markdown report generation (QA H-3).

    Applied at GENERATION time to watcher/news action text, position
    symbols and any other free-text field: HTML is entity-escaped
    (``<script>`` becomes inert text), ``|`` is escaped so it cannot
    forge table columns, and newlines / leading ``#`` are neutralised so
    text cannot break out of a table row or inject a heading.

    R2-H3: Markdown link/image syntax is defanged too (``[text](url)``
    used to render as a live phishing link and ``![x](url)`` as an
    embedded tracking image), bidi/control characters are stripped
    (RTL-override spoofing), and output is length-capped.
    """
    s = "" if text is None else str(text)
    s = html.escape(s, quote=False)
    s = _CONTROL_CHARS.sub("", s)
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    s = s.replace("|", "\\|")
    s = s.replace("[", "\\[").replace("]", "\\]")
    s = re.sub(r"^\s*#+\s*", "", s)
    return s.strip()[:500]


def require_finite(value: Any, field_name: str, pot_id: Any = "?") -> float:
    """QA H-6: non-finite numbers are rejected at report build, never
    serialised as bare NaN/Infinity JSON tokens."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ReportDataError(f"pot {pot_id}: field '{field_name}' is not a number: {value!r}") from None
    if not math.isfinite(f):
        raise ReportDataError(f"pot {pot_id}: field '{field_name}' is not finite: {value!r}")
    return f


def sanitize_json(obj: Any, _path: str = "report") -> Any:
    """Recursively convert any remaining non-finite float to None with a
    stderr warning, so ``json.dumps(..., allow_nan=False)`` never fails
    and no bare NaN/Infinity token is ever written (QA H-6)."""
    if isinstance(obj, float) and not math.isfinite(obj):
        print(f"WARNING: non-finite value at {_path} converted to null in report JSON", file=sys.stderr)
        return None
    if isinstance(obj, dict):
        return {k: sanitize_json(v, f"{_path}.{k}") for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize_json(v, f"{_path}[]") for v in obj]
    return obj


def validated_tax_rate(state: dict[str, Any]) -> float:
    """QA M-11: tax_rate must be a number in [0, 1]; out-of-range values
    are clamped with a warning, non-numbers raise a clear error.
    R2-L7: bools and numeric strings are NOT numbers here — float(True)
    silently became a 100% rate and float("0.22") silently coerced."""
    raw = state.get("tax_rate", DEFAULT_TAX_RATE)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ReportDataError(f"pot {state.get('pot_id', '?')}: tax_rate is not a number: {raw!r}")
    rate = float(raw)
    if not math.isfinite(rate):
        raise ReportDataError(f"pot {state.get('pot_id', '?')}: tax_rate is not finite: {raw!r}")
    if rate < 0.0 or rate > 1.0:
        clamped = min(max(rate, 0.0), 1.0)
        print(f"WARNING: tax_rate {rate} outside [0, 1] for pot "
              f"{state.get('pot_id', '?')}; clamped to {clamped}", file=sys.stderr)
        return clamped
    return rate


def require_keys(state: dict[str, Any], keys: tuple[str, ...], where: str) -> None:
    """QA M-12: missing required fields fail up front, with the field named."""
    for k in keys:
        if k not in state or state[k] is None:
            raise ReportDataError(f"{where}: pot state is missing required field '{k}' "
                                  f"(pot_id={state.get('pot_id', '?')!r})")


def closed_trades(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in state.get("trades", []) if t.get("pnl") is not None]


def win_stats(state: dict[str, Any]) -> dict[str, Any]:
    """Win/loss statistics. QA L-1 (now documented): a break-even close
    (pnl == 0) is NEITHER a win nor a loss — it is counted separately in
    ``breakevens`` and excluded from avg/biggest loss (previously a
    scratch trade silently set avg_loss to $0.00 and cut the win rate's
    denominator story). Win rate remains wins / all closed trades."""
    closed = closed_trades(state)
    wins = [float(t["pnl"]) for t in closed if float(t["pnl"]) > 0]
    losses = [float(t["pnl"]) for t in closed if float(t["pnl"]) < 0]
    breakevens = [float(t["pnl"]) for t in closed if float(t["pnl"]) == 0]
    return {
        "closed": len(closed), "wins": len(wins), "losses": len(losses),
        "breakevens": len(breakevens),
        "win_rate_pct": (100.0 * len(wins) / len(closed)) if closed else None,
        "avg_win": (sum(wins) / len(wins)) if wins else None,
        "avg_loss": (sum(losses) / len(losses)) if losses else None,
        "biggest_win": max(wins) if wins else None,
        "biggest_loss": min(losses) if losses else None,
        "realized_pl": sum(float(t["pnl"]) for t in closed),
    }


def max_drawdown_pct(equity_curve: list[dict[str, Any]]) -> float | None:
    peak, worst = None, 0.0
    for pt in equity_curve:
        b = float(pt["balance"])
        peak = b if peak is None else max(peak, b)
        if peak:
            worst = min(worst, 100.0 * (b - peak) / peak)
    # QA M-5: round like every other field in the report JSON.
    return round(worst, 2) if equity_curve else None


def estimated_taxes(state: dict[str, Any]) -> float:
    """Short-term gains estimate: tax rate x net realised gains (floor 0).

    ESTIMATE ONLY, labelled as such in every report. Not tax advice.
    """
    net = win_stats(state)["realized_pl"]
    return round(max(net, 0.0) * validated_tax_rate(state), 2)


def spy_shadow(state: dict[str, Any]) -> dict[str, Any] | None:
    spy = state.get("spy") or {}
    sp, cp = spy.get("start_price"), spy.get("current_price")
    # QA M-4: non-positive prices (either side) mean no honest shadow —
    # previously a negative start price produced a −$100 / −200% shadow.
    if sp is None or cp is None:
        return None
    try:
        sp_f, cp_f = float(sp), float(cp)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(sp_f) and math.isfinite(cp_f)) or sp_f <= 0 or cp_f <= 0:
        return None
    start = require_finite(state.get("start_balance"), "start_balance", state.get("pot_id"))
    if start == 0:
        return None
    bal = start * float(cp) / float(sp)
    return {"start_price": float(sp), "current_price": float(cp),
            "shadow_balance": round(bal, 2),
            "total_gain": round(bal - start, 2),
            "total_gain_pct": round(100.0 * (bal - start) / start, 2)}


def validated_positions(state: dict[str, Any]) -> list[dict[str, Any]]:
    """R2-M4/R2-H3: position numeric fields are validated finite at
    report build (previously only balance/cash/start/total_costs were),
    so a NaN market_value can no longer render as $nan in Markdown
    while the JSON copy silently nulls it — and a string 'shares' can
    no longer reach the raw Markdown column unescaped."""
    pid = state.get("pot_id", "?")
    out = []
    for i, q in enumerate(state.get("positions", []) or []):
        if not isinstance(q, dict):
            raise ReportDataError(f"pot {pid}: position {i} is not an object")
        q = dict(q)
        for f in ("shares", "avg_cost", "current_price", "market_value", "unrealized_pl"):
            if q.get(f) is not None:
                q[f] = require_finite(q[f], f"positions[{i}].{f}", pid)
        out.append(q)
    return out


def validated_trades(state: dict[str, Any]) -> list[dict[str, Any]]:
    """R2-M4: trade numeric fields validated finite at report build —
    a NaN pnl used to be counted as a closed trade and poison win
    stats, taxes and profit-by-stock with NaN."""
    pid = state.get("pot_id", "?")
    out = []
    for i, t in enumerate(state.get("trades", []) or []):
        if not isinstance(t, dict):
            raise ReportDataError(f"pot {pid}: trade {i} is not an object")
        t = dict(t)
        for f in ("shares", "price", "amount", "fees"):
            if t.get(f) is not None:
                t[f] = require_finite(t[f], f"trades[{i}].{f}", pid)
        if t.get("pnl") is not None:
            t["pnl"] = require_finite(t["pnl"], f"trades[{i}].pnl", pid)
        out.append(t)
    return out


def validated_curve(state: dict[str, Any]) -> list[dict[str, Any]]:
    """R2-M4: equity-curve balances validated finite at report build —
    an Inf point used to make max_drawdown_pct silently report 0.00%."""
    pid = state.get("pot_id", "?")
    out = []
    for i, pt in enumerate(state.get("equity_curve", []) or []):
        if not isinstance(pt, dict) or pt.get("balance") is None:
            raise ReportDataError(f"pot {pid}: equity_curve[{i}] has no balance")
        pt = dict(pt)
        pt["balance"] = require_finite(pt["balance"], f"equity_curve[{i}].balance", pid)
        out.append(pt)
    return out


def versioned_write_pair(md_path: Any, md_text: str, json_path: Any, json_text: str):
    """R2-M8: a report is a UNIT — the .md and .json are versioned
    TOGETHER. The pair takes the smallest version suffix (base, -v2,
    -v3, …) at which BOTH files are absent or already identical, so a
    base-name .md/.json pair always describes the same state (the old
    per-file versioning forked them: md at base, json at -v2)."""
    from pathlib import Path
    md_p, js_p = Path(md_path), Path(json_path)

    def _versioned(p: Path, n: int) -> Path:
        return p if n == 1 else p.with_name(f"{p.stem}-v{n}{p.suffix}")

    n = 1
    while True:
        m_cand, j_cand = _versioned(md_p, n), _versioned(js_p, n)
        m_ok = not m_cand.exists() or m_cand.read_text(encoding="utf-8") == md_text
        j_ok = not j_cand.exists() or j_cand.read_text(encoding="utf-8") == json_text
        if m_ok and j_ok:
            m_cand.write_text(md_text, encoding="utf-8")
            j_cand.write_text(json_text, encoding="utf-8")
            if n > 1:
                print(f"NOTE: report pair already exists with different content; "
                      f"wrote {m_cand.name} + {j_cand.name} instead (history preserved)",
                      file=sys.stderr)
            return m_cand, j_cand
        n += 1


def versioned_write(path: Any, content: str) -> Any:
    """QA M-7 — report history is never silently destroyed.

    Choice (documented): if ``path`` already exists with IDENTICAL
    content, it is rewritten in place (idempotent re-run). If it exists
    with DIFFERENT content, the new report is written to the next
    versioned sibling (``name-v2.md``, ``name-v3.md``, …) and the
    original is left untouched — a re-run after a data fix, or a mistaken
    re-run, can no longer erase the original record the permanent
    scoreboard depends on.
    """
    from pathlib import Path
    p = Path(path)
    if not p.exists():
        p.write_text(content, encoding="utf-8")
        return p
    if p.read_text(encoding="utf-8") == content:
        p.write_text(content, encoding="utf-8")
        return p
    n = 2
    while True:
        cand = p.with_name(f"{p.stem}-v{n}{p.suffix}")
        if not cand.exists() or cand.read_text(encoding="utf-8") == content:
            cand.write_text(content, encoding="utf-8")
            print(f"NOTE: {p.name} already exists with different content; "
                  f"wrote {cand.name} instead (history preserved)", file=sys.stderr)
            return cand
        n += 1


def sample_pot_states() -> list[dict[str, Any]]:
    """Fabricated-but-labelled sample pot states for the demo run."""
    return [
        {
            "pot_id": "sample-champion", "name": "SAMPLE — V+M Champion (fabricated demo data)",
            "start_date": "2026-11-02", "start_balance": 100.00, "balance": 112.40,
            "prev_balance": 110.85, "cash": 31.40, "total_costs": 0.94, "tax_rate": 0.22,
            "positions": [
                {"symbol": "NVDA", "shares": 0.25, "avg_cost": 172.00, "current_price": 186.00,
                 "market_value": 46.50, "unrealized_pl": 3.50},
                {"symbol": "MSFT", "shares": 0.067, "avg_cost": 500.00, "current_price": 515.00,
                 "market_value": 34.50, "unrealized_pl": 1.00},
            ],
            "trades": [
                {"date": "2026-11-03", "symbol": "AAPL", "side": "buy", "shares": 0.2, "price": 270.0, "amount": 54.0, "pnl": None, "fees": 0.05},
                {"date": "2026-11-10", "symbol": "AAPL", "side": "sell", "shares": 0.2, "price": 285.0, "amount": 57.0, "pnl": 2.95, "fees": 0.05},
                {"date": "2026-11-12", "symbol": "NVDA", "side": "buy", "shares": 0.25, "price": 172.0, "amount": 43.0, "pnl": None, "fees": 0.04},
                {"date": "2026-11-16", "symbol": "MSFT", "side": "buy", "shares": 0.067, "price": 500.0, "amount": 33.5, "pnl": None, "fees": 0.03},
                {"date": "2026-11-21", "symbol": "AMD", "side": "buy", "shares": 0.1, "price": 200.0, "amount": 20.0, "pnl": None, "fees": 0.02},
                {"date": "2026-11-21", "symbol": "AMD", "side": "sell", "shares": 0.1, "price": 208.0, "amount": 20.8, "pnl": 0.78, "fees": 0.02},
            ],
            "equity_curve": [
                {"date": "2026-11-02", "balance": 100.00}, {"date": "2026-11-09", "balance": 103.20},
                {"date": "2026-11-13", "balance": 98.60}, {"date": "2026-11-18", "balance": 108.10},
                {"date": "2026-11-20", "balance": 110.85}, {"date": "2026-11-21", "balance": 112.40},
            ],
            "spy": {"start_price": 680.00, "current_price": 701.50},
            "watcher_actions": ["SAMPLE: NVDA Form 4 cluster buying flagged (priority) — display only, no trade originated by watcher."],
            "news_actions": ["SAMPLE: NVDA 8-K item 2.02 (earnings) — info flag, earnings-window note shown."],
        },
        {
            "pot_id": "sample-lottery", "name": "SAMPLE — Penny Lottery (fabricated demo data)",
            "start_date": "2026-11-02", "start_balance": 100.00, "balance": 91.25,
            "prev_balance": 92.00, "cash": 91.25, "total_costs": 1.35, "tax_rate": 0.22,
            "positions": [],
            "trades": [
                {"date": "2026-11-05", "symbol": "XYZS", "side": "buy", "shares": 10, "price": 2.40, "amount": 24.0, "pnl": None, "fees": 0.10},
                {"date": "2026-11-21", "symbol": "XYZS", "side": "sell", "shares": 10, "price": 1.55, "amount": 15.5, "pnl": -8.60, "fees": 0.10},
            ],
            "equity_curve": [
                {"date": "2026-11-02", "balance": 100.00}, {"date": "2026-11-10", "balance": 96.40},
                {"date": "2026-11-21", "balance": 91.25},
            ],
            "spy": {"start_price": 680.00, "current_price": 701.50},
            "watcher_actions": ["SAMPLE: XYZS insider CEO open-market purchase flagged — display only."],
            "news_actions": ["SAMPLE: XYZS 8-K item 4.01 (auditor change) — high severity, 'pause new buys suggested' shown."],
        },
    ]
