#!/usr/bin/env python3
"""
Atlas Gate — AI Stock App Dashboard
Local-only web dashboard. Python standard library ONLY (no pip installs).
Run:  python dashboard/server.py     ->  http://localhost:8765

Reads live state from ../state/ and reports from ../reports/output/.
When those are empty it falls back to clearly-labeled DEMO data built from
the published backtest finals ("replay record").
"""
import hmac
import json
import math
import os
import random
import secrets
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, quote

BASE = Path(__file__).resolve().parent
APP_DIR = BASE.parent
STATE_DIR = APP_DIR / "state"

# Trading mode (paper/live) lives in data/mode.py -- the single fail-safe
# gate for real money. If it cannot be imported, the dashboard assumes
# PAPER and says so; it never assumes live.
sys.path.insert(0, str(APP_DIR))
try:
    from data import mode as _tmode
except Exception:
    _tmode = None

# Phase A (D1/console): scrub helper from data/redact.py (built by the
# data partition). If it is unavailable, console errors print the
# exception TYPE only -- never a repr that could carry a secret.
try:
    from data import redact as _redact
except Exception:
    _redact = None

def _scrub_exc(e):
    if _redact is not None:
        try:
            return _redact.scrub_text(repr(e))
        except Exception:
            return type(e).__name__
    return type(e).__name__

# Phase A (E2): dashboard password verification (dashboard/auth.py).
sys.path.insert(0, str(BASE))
try:
    import auth as _auth
except Exception:
    try:
        from dashboard import auth as _auth  # type: ignore
    except Exception:
        _auth = None

# W5-A: Horizon Picker registry (picker.py at the app root, built by a
# parallel worker). Contract: picker.BUCKETS (ordered bucket names) and
# picker.available_offerings() -> {bucket: [offering, ...]}. If the
# module is not present yet, the picker page still renders every bucket
# (from DEFAULT_BUCKETS) with an honest "not available yet" note.
try:
    import picker as _picker
except Exception:
    try:
        from app import picker as _picker  # type: ignore
    except Exception:
        _picker = None

# W5-B: bank-CD shadow benchmark (data/cd_shadow.py, built by a parallel
# worker). Contract: cd_shadow.series(start_date, end_date,
# start_cash=100.0) -> [[date, value], ...] or None when the CD
# benchmark data is not available. Absent module == not available.
try:
    from data import cd_shadow as _cd_shadow
except Exception:
    _cd_shadow = None

VERSION = "1.2.0"
EXPOSURE_BANNER = ("THIS DASHBOARD IS EXPOSED ON THE NETWORK \u2014 anyone who can "
                   "reach this address can attempt to log in. Keep the password "
                   "strong; prefer an SSH tunnel.")

def trading_status():
    fallback = {"configured_mode": "paper", "effective_mode": "paper",
                "is_live": False, "paper_keys_present": False,
                "live_keys_present": False,
                "problem": "Trading-mode module unavailable -- assuming PAPER.",
                "stopped": False, "stopped_at": None,
                "confirmation_phrase": "I UNDERSTAND THIS TRADES REAL MONEY"}
    if _tmode is None:
        return fallback
    try:
        return _tmode.mode_status()
    except Exception:
        return fallback
REPORTS_DIR = APP_DIR / "reports" / "output"
TEMPLATES_DIR = BASE / "templates"


def _parse_port():
    """R2-N7: a non-numeric or out-of-range DASHBOARD_PORT must produce
    one clean line at startup, never a traceback."""
    raw = os.environ.get("DASHBOARD_PORT", "8765")
    try:
        p = int(raw)
    except (TypeError, ValueError):
        return None
    return p if 1 <= p <= 65535 else None


PORT = _parse_port()

# R2-N2 + Phase A (E1/E4): the dashboard serves loopback names by
# default. A request whose Host is anything else (the DNS-rebinding
# shape) is refused outright. The allowlist extends ONLY with the
# deliberately configured remote host / specific bind IP (see
# _allowed_hosts()).
_BASE_ALLOWED_HOSTS = {"127.0.0.1", "localhost", "::1"}
_ALLOWED_HOSTS = set(_BASE_ALLOWED_HOSTS)  # back-compat name

def _load_cfg():
    if _tmode is None:
        return {}
    try:
        return _tmode.load_config_strict() or {}
    except Exception:
        return {}

def _is_loopback_bind(bind):
    b = str(bind or "").strip().lower()
    return b in ("localhost", "::1") or b.startswith("127.")

# Effective bind for THIS process; main() sets it from config. Default
# is loopback, so an import/test context is always the safe shape.
EFFECTIVE_BIND = "127.0.0.1"

def resolve_bind(cfg=None):
    """(bind, refusal) -- Phase A (E1). Non-loopback is honoured ONLY
    with dashboard_allow_remote_exposure exactly true AND a dashboard
    password hash set; otherwise a clean one-line refusal."""
    cfg = _load_cfg() if cfg is None else cfg
    bind = cfg.get("dashboard_bind") or "127.0.0.1"
    if not isinstance(bind, str) or not bind.strip():
        bind = "127.0.0.1"
    bind = bind.strip()
    if _is_loopback_bind(bind):
        return bind, None
    if cfg.get("dashboard_allow_remote_exposure") is not True:
        return None, ("Dashboard could not start: dashboard_bind requests a non-loopback "
                      "address but dashboard_allow_remote_exposure is not true in "
                      "config.local.json. Set it to true and set a dashboard password, "
                      "or bind 127.0.0.1 and use an SSH tunnel.")
    if not cfg.get("dashboard_password_hash"):
        return None, ("Dashboard could not start: dashboard_bind requests a non-loopback "
                      "address but no dashboard password is set in config.local.json "
                      "(dashboard_password_hash / dashboard_password_salt). Set a dashboard "
                      "password first, or bind 127.0.0.1 and use an SSH tunnel.")
    return bind, None

def _allowed_hosts():
    hosts = set(_BASE_ALLOWED_HOSTS)
    cfg = _load_cfg()
    rh = cfg.get("dashboard_remote_host")
    if isinstance(rh, str) and rh.strip():
        h = rh.strip()
        if h.startswith("["):
            h = h[1:].split("]", 1)[0]
        elif ":" in h:
            h = h.rsplit(":", 1)[0]
        hosts.add(h.lower())
    bind = cfg.get("dashboard_bind")
    if isinstance(bind, str) and bind.strip() and not _is_loopback_bind(bind) \
            and bind.strip() not in ("0.0.0.0", "::"):
        hosts.add(bind.strip().lower())
    if not _is_loopback_bind(EFFECTIVE_BIND) and EFFECTIVE_BIND not in ("0.0.0.0", "::"):
        hosts.add(EFFECTIVE_BIND.lower())
    return hosts

def _auth_required(cfg=None):
    """Phase A (E2): required when a password hash exists AND
    (dashboard_auth_enabled is true OR the effective bind is
    non-loopback)."""
    cfg = _load_cfg() if cfg is None else cfg
    if not cfg.get("dashboard_password_hash"):
        return False
    if cfg.get("dashboard_auth_enabled") is True:
        return True
    return not _is_loopback_bind(EFFECTIVE_BIND)

# ----------------------------------------------------------------------------
# W5-C: first-run owner setup (Terry's spec, 2026-11-22). Credentials
# exist iff a dashboard password hash is stored. The setup page is
# reachable ONLY while no credentials exist; once set, it closes
# permanently. A pristine install (no config.local.json at all) is
# presented with the setup page for every page request until setup is
# done; an existing config without a password keeps the Phase A
# behaviour (open on loopback) plus a visible setup link, so older
# installs and the existing test suites are not locked out.
# ----------------------------------------------------------------------------
def _credentials_exist(cfg=None):
    cfg = _load_cfg() if cfg is None else cfg
    return bool(cfg.get("dashboard_password_hash"))

def _owner_name(cfg=None):
    cfg = _load_cfg() if cfg is None else cfg
    name = cfg.get("dashboard_owner_name")
    return name if isinstance(name, str) else ""

def _first_run_unconfigured():
    """True on a pristine install: no credentials AND no config file."""
    try:
        if CONFIG_LOCAL_PATH.exists():
            return False
    except Exception:
        return False
    return not _credentials_exist()

# ---- failed-login lockout (E2): 10 failures / 10 min -> 5 min lockout.
# NOTE (owner-DoS tradeoff, see CHANGES.md): the counter is global, so
# an attacker who can reach the login page can lock the owner out too.
_LOGIN_LOCK = threading.Lock()
_LOGIN_FAILURES = []
_LOGIN_LOCK_UNTIL = 0.0

def _login_locked():
    with _LOGIN_LOCK:
        return time.time() < _LOGIN_LOCK_UNTIL

def _login_record_failure():
    global _LOGIN_LOCK_UNTIL
    now = time.time()
    with _LOGIN_LOCK:
        _LOGIN_FAILURES[:] = [t for t in _LOGIN_FAILURES if now - t < 600]
        _LOGIN_FAILURES.append(now)
        if len(_LOGIN_FAILURES) >= 10:
            _LOGIN_LOCK_UNTIL = now + 300
            _LOGIN_FAILURES.clear()

def _login_record_success():
    with _LOGIN_LOCK:
        _LOGIN_FAILURES.clear()

# ----------------------------------------------------------------------------
# POST security (F2) + Phase A (E3): a PER-SESSION CSRF token is embedded
# in every form and verified against the CURRENT session on every
# state-changing POST; a token from one session never validates in
# another. Origin/Referer and Host checks remain as further layers.
# ----------------------------------------------------------------------------
_SESSIONS = {}
_SESSIONS_LOCK = threading.Lock()
_LOCAL = threading.local()

def _new_session():
    sid = secrets.token_urlsafe(32)
    sess = {"csrf": secrets.token_urlsafe(32), "authenticated": False}
    with _SESSIONS_LOCK:
        if len(_SESSIONS) > 1000:
            _SESSIONS.pop(next(iter(_SESSIONS)))
        _SESSIONS[sid] = sess
    return sid, sess

def _session_cookie_header(sid):
    parts = [f"ag_session={sid}", "HttpOnly", "SameSite=Lax", "Path=/"]
    if os.environ.get("AG_DASHBOARD_BEHIND_TLS") == "1":
        parts.append("Secure")
    return "; ".join(parts)

def csrf_field():
    sess = getattr(_LOCAL, "session", None)
    token = sess["csrf"] if sess else ""
    return f'<input type="hidden" name="csrf_token" value="{token}">'

def _current_csrf():
    sess = getattr(_LOCAL, "session", None)
    return sess["csrf"] if sess else ""

def _is_authenticated():
    sess = getattr(_LOCAL, "session", None)
    return bool(sess and sess.get("authenticated"))

# One-time server-side flash messages (F10): POST handlers store the real
# message here and redirect with an opaque id, so /mode never reflects
# arbitrary ?msg= text as an official alert.
_FLASH = {}

def _flash_put(msg, kind):
    fid = uuid.uuid4().hex
    _FLASH[fid] = (msg, kind)
    if len(_FLASH) > 64:  # bound memory; oldest are simply dropped
        _FLASH.pop(next(iter(_FLASH)))
    return fid

def _flash_take(fid):
    if fid:
        return _FLASH.pop(fid, ("", ""))
    return ("", "")

# Serialises dashboard-originated mode writes (F4 dashboard side): a
# double-clicked STOP ALL queues behind the first click instead of racing
# the shared write in data/mode.py.
_MODE_LOCK = threading.Lock()

KNOWN_PAGE_PATHS = ("/", "/index.html", "/pot", "/watcher", "/reports",
                    "/report", "/mode", "/panic", "/login", "/picker", "/setup")

# W5-A: Terry's horizon order. Used only as the fallback when picker.py
# (which owns the canonical BUCKETS list) is unavailable.
DEFAULT_BUCKETS = ["Daily", "3 Days", "Weekly", "Bi-Weekly", "Monthly",
                   "Every 3 Months", "Every 6 Months", "Yearly", "Long"]

CONFIG_LOCAL_PATH = APP_DIR / "config.local.json"
MAX_POST_BODY = 1_000_000  # bytes; mode forms are a few hundred bytes
GOAL = 1_000_000.0
START_CAPITAL = 100.0
FLOOR_PCT = 0.85  # Claude's rules (v9): plain -15% floor from starting balance

# ----------------------------------------------------------------------------
# Published backtest finals (replay record) — $100 start, validation-quoted
# ----------------------------------------------------------------------------
DEMO_FINALS = [
    # id,        name,                    strategy,                                   status,          final
    ("vm",       "Value + Momentum",      "Champion — value + momentum, quarterly",   "running",       544.47),
    ("lazy",     "Lazy Prices",           "Promoted — lazy prices trend",               "running",       504.34),
    ("basket",   "Momentum Basket",       "Promoted — cross-sectional momentum basket", "running",       439.45),
    ("nf3",      "N-F3 Blend Sleeve",     "Candidate lane — V+M x N-F3",                "tracking only", 505.43),
    ("switchb",  "Midpoint Switch B",     "Candidate lane — champion to blend switch",  "tracking only", 549.43),
]
SPY_FINAL = 313.62

DEMO_HOLDINGS = {
    "vm":     [("NVDA", 412.80, 1.84), ("AVGO", 388.15, 0.92), ("META", 301.44, -0.63),
               ("MSFT", 268.90, 0.41), ("COST", 198.25, 0.18)],
    "lazy":   [("QQQ", 512.36, 0.74), ("SPY", 388.10, 0.52), ("GLD", 214.55, -0.21),
               ("TLT", 96.40, 0.09)],
    "basket": [("AMD", 168.22, 2.31), ("AVGO", 344.70, 0.92), ("ANET", 118.45, 1.12),
               ("SMCI", 41.86, -1.47), ("MRVL", 88.30, 0.66)],
    "nf3":    [("NVDA", 412.80, 1.84), ("LLY", 812.44, 0.35), ("AVGO", 344.70, 0.92)],
    "switchb":[("MSFT", 428.15, 0.41), ("NVDA", 412.80, 1.84), ("COST", 987.60, 0.18),
               ("WMT", 168.92, -0.34)],
}

DEMO_TRADES = [
    ("2025-11-14", "NVDA", "BUY",  0.412, 187.42, None),
    ("2025-11-14", "COST", "BUY",  0.201, 912.08, None),
    ("2025-10-31", "XOM",  "SELL", 0.388, 118.64, 14.22),
    ("2025-10-31", "HD",   "SELL", 0.512, 402.17, -6.85),
    ("2025-10-03", "AVGO", "BUY",  0.288, 342.55, None),
    ("2025-09-19", "META", "BUY",  0.194, 585.20, None),
    ("2025-08-29", "UNH",  "SELL", 0.441, 301.90, 9.41),
]

DEMO_WATCHER = [
    ("PRIORITY", "Insider — Form 4", "NVDA", "Director open-market purchase, cluster of 2 filers", "2025-11-19", "Cluster buys are the strongest Form 4 signal class in testing."),
    ("",         "Insider — Form 4", "COST", "Officer sale under a pre-scheduled 10b5-1 plan", "2025-11-18", "Scheduled-plan sales carry little signal. Radar only."),
    ("PRIORITY", "Activist — 13D",   "ANET", "Activist stake disclosed at 6.2%, 5 business days after crossing", "2025-11-17", "13D is an event signal; confirm against trend before any action."),
    ("",         "Fund — 13F",       "META", "Large fund increased position in quarterly 13F", "2025-11-15", "13F data is 45-135 days stale. Context only, never a trigger."),
    ("",         "Congress — STOCK Act", "MSFT", "House member purchase disclosed, $15k-$50k range", "2025-11-12", "30-45 day disclosure lag, amount ranges only. Weakest signal class tested."),
    ("",         "Insider — Form 4", "AMD",  "CEO sale, non-plan, single filer", "2025-11-10", "Single-filer sales are weak evidence. No action implied."),
]

# ----------------------------------------------------------------------------
# Formatting helpers — tabular numerals handled in CSS; values formatted here
# ----------------------------------------------------------------------------
def money(v):
    sign = "-" if v < 0 else ""
    return f"{sign}${abs(v):,.2f}"

def money_signed(v):
    return ("+" if v >= 0 else "-") + f"${abs(v):,.2f}"

def pct(v, signed=True):
    s = f"{abs(v):.2f}%"
    return (("+" if v >= 0 else "-") + s) if signed else s

def cls(v):
    return "gain" if v > 0 else ("loss" if v < 0 else "flat")

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))

# ----------------------------------------------------------------------------
# Deterministic demo equity curves (monthly, 2016-01 .. 2025-12, 120 points)
# ----------------------------------------------------------------------------
def make_curve(final, seed, start=START_CAPITAL, months=120):
    rng = random.Random(seed)
    target = math.log(final / start)
    pts, val = [], start
    drift = target / months
    for i in range(months):
        shock = rng.gauss(0, 0.045)
        # mild drawdown episodes so curves look like real equity paths
        if i in (28, 29, 52, 74, 75):
            shock -= rng.uniform(0.03, 0.09)
        val *= math.exp(drift + shock - (val / start - 1) * 0.0)
        pts.append(round(val, 2))
    # rescale smoothly so the path ends exactly on the published final
    ratio = final / pts[-1]
    pts = [round(p * (ratio ** ((i + 1) / months)), 2) for i, p in enumerate(pts)]
    pts[-1] = final
    labels = []
    y, m = 2016, 1
    for _ in range(months):
        labels.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return labels, pts

def demo_state():
    labels, spy_curve = make_curve(SPY_FINAL, seed=99)
    pots = []
    total_day = 0.0
    for idx, (pid, name, strat, status, final) in enumerate(DEMO_FINALS):
        _, curve = make_curve(final, seed=1000 + idx * 17)
        rng = random.Random(500 + idx)
        day_pct = round(rng.uniform(-0.9, 1.6), 2)
        day_usd = round(final * day_pct / 100.0, 2)
        total_day += day_usd
        holdings = []
        remaining = final
        raw = DEMO_HOLDINGS[pid]
        for j, (tkr, price, chg) in enumerate(raw):
            val = round(final * (0.32 - j * 0.05), 2) if j < len(raw) - 1 else round(remaining, 2)
            val = max(val, 8.0)
            remaining -= val
            holdings.append({"ticker": tkr, "price": price, "value": val,
                             "change_pct": chg, "shares": round(val / price, 3)})
        cash = round(final - sum(h["value"] for h in holdings), 2)
        pots.append({
            "id": pid, "name": name, "strategy": strat, "status": status,
            "start": START_CAPITAL, "balance": final, "curve": curve,
            "day_pct": day_pct, "day_usd": day_usd,
            "total_pct": round((final / START_CAPITAL - 1) * 100, 2),
            "vs_spy_pct": round((final / SPY_FINAL - 1) * 100, 2),
            "floor": round(START_CAPITAL * FLOOR_PCT, 2), "episode": 1,
            "halted_on": None, "restart_on": None, "cash": cash,
            "holdings": holdings,
            "trades": [{"date": d, "ticker": t, "side": s, "shares": sh,
                        "price": pr, "pnl": pnl} for (d, t, s, sh, pr, pnl) in DEMO_TRADES],
        })
    total = round(sum(p["balance"] for p in pots), 2)
    return {
        "mode": "demo", "labels": labels, "spy_curve": spy_curve,
        "spy_final": SPY_FINAL, "pots": pots,
        "total_balance": total, "total_day_usd": round(total_day, 2),
        "total_day_pct": round(total_day / total * 100, 2) if total else 0.0,
        "total_start": START_CAPITAL * len(pots),
        "updated_at": None,
        "watcher_sample": True,
        "state_warnings": [],
        "watcher": [{"priority": bool(p), "kind": k, "ticker": t, "title": ti,
                     "date": d, "note": n} for (p, k, t, ti, d, n) in DEMO_WATCHER],
    }

# ----------------------------------------------------------------------------
# Live state loading (../state/*.json) — graceful, schema-tolerant
# ----------------------------------------------------------------------------
def _num(v):
    """A real, FINITE JSON number (not bool/str) as float, else None.
    R2-N3: Python's json accepts NaN/Infinity literals; those used to
    pass through and render as $nan/$inf (and made /api/state emit
    invalid JSON)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if math.isfinite(f) else None

_MAX_FIELD = 200        # chars kept from any state-file string field
_MAX_ENTRIES = 500      # holdings/trades entries kept per pot
_MAX_CURVE = 2000       # equity-curve points kept per pot
_MAX_WARNINGS = 20      # state-file warnings shown (rest summarised)
_MAX_STATE_BYTES = 10_000_000  # state files larger than this are ignored

def _txt(v, default=""):
    return v if isinstance(v, str) else default

def _validate_pot(lp, warnings):
    """Schema-defensive pot validation (F5/F6). Returns a clean pot dict
    built ONLY from the live record -- never overlaid on the replay/demo
    pot, so a live pot with no curve/holdings/trades of its own shows none
    of the demo ones -- or None (entry skipped, warning recorded)."""
    if not isinstance(lp, dict):
        warnings.append("Skipped a malformed pot entry in the state file "
                        "(not an object). The rest of the dashboard is unaffected.")
        return None
    pid = lp.get("id")
    bal = _num(lp.get("balance"))
    if not isinstance(pid, str) or not pid or bal is None:
        warnings.append("Skipped a malformed pot entry in the state file "
                        "(missing id or non-numeric balance). The rest of "
                        "the dashboard is unaffected.")
        return None
    def warn(what):
        warnings.append(f"Pot {pid!r} in the state file had a malformed {what}; "
                        f"it was corrected or dropped. The rest of the "
                        f"dashboard is unaffected.")

    def cap_txt(v, default=""):
        s = _txt(v, default)
        if len(s) > _MAX_FIELD:
            warn("over-long text field (truncated)")
            return s[:_MAX_FIELD]
        return s
    start = _num(lp.get("start"))
    if start is None or start <= 0:
        if "start" in lp:
            warn("starting balance")
        start = START_CAPITAL
    floor = _num(lp.get("floor"))
    if floor is None:
        if "floor" in lp:
            warn("floor")
        floor = round(start * FLOOR_PCT, 2)
    if "status" in lp and not isinstance(lp.get("status"), str):
        warn("status")
    holdings = []
    if isinstance(lp.get("holdings"), list):
        if len(lp["holdings"]) > _MAX_ENTRIES:
            warn("holdings list (truncated)")
            lp = {**lp, "holdings": lp["holdings"][:_MAX_ENTRIES]}
        for h in lp["holdings"]:
            if not isinstance(h, dict) or not isinstance(h.get("ticker"), str):
                warn("holding entry")
                continue
            vals = [_num(h.get(k)) for k in ("price", "value", "change_pct", "shares")]
            if any(v is None for v in vals):
                warn("holding entry")
                continue
            holdings.append({"ticker": h["ticker"][:_MAX_FIELD], "price": vals[0],
                             "value": vals[1], "change_pct": vals[2], "shares": vals[3]})
    elif "holdings" in lp:
        warn("holdings list")
    trades = []
    if isinstance(lp.get("trades"), list):
        if len(lp["trades"]) > _MAX_ENTRIES:
            warn("trades list (truncated)")
            lp = {**lp, "trades": lp["trades"][:_MAX_ENTRIES]}
        for t in lp["trades"]:
            if not isinstance(t, dict):
                warn("trade entry")
                continue
            sh, pr = _num(t.get("shares")), _num(t.get("price"))
            if sh is None or pr is None:
                warn("trade entry")
                continue
            pnl = t.get("pnl")
            trades.append({"date": _txt(t.get("date"))[:_MAX_FIELD],
                           "ticker": _txt(t.get("ticker"))[:_MAX_FIELD],
                           "side": _txt(t.get("side"))[:_MAX_FIELD],
                           "shares": sh, "price": pr,
                           "pnl": _num(pnl) if pnl is not None else None})
    elif "trades" in lp:
        warn("trades list")
    curve = []
    if isinstance(lp.get("curve"), list):
        vals = [_num(v) for v in lp["curve"][:_MAX_CURVE]]
        if vals and all(v is not None for v in vals):
            curve = vals
        elif vals:
            warn("equity curve")
    elif "curve" in lp:
        warn("equity curve")
    ep = lp.get("episode")
    return {
        "id": pid[:_MAX_FIELD], "name": cap_txt(lp.get("name"), pid),
        "strategy": cap_txt(lp.get("strategy")),
        "status": cap_txt(lp.get("status"), "running"),
        "start": start, "balance": bal, "curve": curve,
        "day_pct": _num(lp.get("day_pct")) or 0.0,
        "day_usd": _num(lp.get("day_usd")) or 0.0,
        "total_pct": round((bal / start - 1) * 100, 2),
        "vs_spy_pct": round((bal / SPY_FINAL - 1) * 100, 2),
        "floor": floor,
        "episode": ep if isinstance(ep, int) and not isinstance(ep, bool) else 1,
        "halted_on": lp.get("halted_on") if isinstance(lp.get("halted_on"), str) else None,
        "restart_on": lp.get("restart_on") if isinstance(lp.get("restart_on"), str) else None,
        "cash": _num(lp.get("cash")) or 0.0,
        "holdings": holdings, "trades": trades,
    }

def _validate_watcher(items):
    out = []
    if isinstance(items, list):
        for w in items[:_MAX_ENTRIES]:
            if isinstance(w, dict):
                out.append({"priority": bool(w.get("priority")),
                            "kind": _txt(w.get("kind"), "Filing")[:_MAX_FIELD],
                            "ticker": _txt(w.get("ticker"))[:_MAX_FIELD],
                            "title": _txt(w.get("title"))[:_MAX_FIELD],
                            "date": _txt(w.get("date"))[:_MAX_FIELD],
                            "note": _txt(w.get("note"))[:_MAX_FIELD]})
    return out

def load_state():
    """Never raises (F5): an unparseable or malformed state file degrades
    to the labeled replay record plus a visible warning, and /mode and
    STOP ALL keep working."""
    candidates = []
    if STATE_DIR.is_dir():
        candidates = sorted(STATE_DIR.glob("*.json"))
    oversize_seen = False
    for f in candidates:
        try:
            # R2-N4: never read/parse an unbounded state file per request.
            if f.stat().st_size > _MAX_STATE_BYTES:
                oversize_seen = True
                continue
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and "pots" in data:
            warnings = []
            raw_pots = data["pots"]
            if not isinstance(raw_pots, list):
                warnings.append("The state file's \"pots\" entry is malformed "
                                "(not a list) and was ignored. Showing the "
                                "replay record until the state file is fixed.")
                raw_pots = []
            live_pots = []
            for lp in raw_pots:
                pot = _validate_pot(lp, warnings)
                if pot is not None:
                    live_pots.append(pot)
            if len(warnings) > _MAX_WARNINGS:
                # R2-N4: one warning per bad entry flooded every page.
                extra = len(warnings) - _MAX_WARNINGS
                warnings = warnings[:_MAX_WARNINGS] + [
                    f"Plus {extra} further state-file warning(s), suppressed."]
            st = demo_state()  # base shape (labels, SPY curve, totals)
            st["state_warnings"] = warnings
            try:
                st["updated_at"] = datetime.fromtimestamp(f.stat().st_mtime)
            except Exception:
                st["updated_at"] = None
            if live_pots:
                st["mode"] = "live"
                st["pots"] = live_pots
                # F6: watcher/curves come from the live record only. No
                # watcher key in the file means NO watcher items -- never
                # the demo feed presented as real.
                st["watcher"] = _validate_watcher(data.get("watcher"))
                st["watcher_sample"] = False
            st["total_balance"] = round(sum(p["balance"] for p in st["pots"]), 2)
            st["total_day_usd"] = round(sum(p.get("day_usd", 0.0) for p in st["pots"]), 2)
            st["total_day_pct"] = round(st["total_day_usd"] / st["total_balance"] * 100, 2) if st["total_balance"] else 0.0
            st["total_start"] = sum(p["start"] for p in st["pots"])
            return st
    st = demo_state()
    st["state_files_seen"] = len(candidates)
    if oversize_seen:
        st["state_warnings"] = [
            "A state file larger than 10 MB was ignored (size sanity cap). "
            "Showing the replay record until the state file is fixed."]
    return st

def _contained_report_path(f):
    """F1: the resolved real path of a report candidate, or None unless it
    is a regular file physically inside reports/output/. Symlinks that
    escape the directory (or point anywhere else) are refused."""
    try:
        if f.is_symlink():
            return None
        resolved = f.resolve()
        if not resolved.is_relative_to(REPORTS_DIR.resolve()):
            return None
        if resolved.name == "config.local.json":
            return None
        if not resolved.is_file():
            return None
        # R2-N1: a HARDLINK is not a symlink and its path resolves inside
        # reports/output/, yet it IS the config file (same inode) -- the
        # Round 1 check served the live secret verbatim. Refuse any
        # multi-link file, and any file sharing the config's inode.
        info = resolved.stat()
        if info.st_nlink > 1:
            return None
        cfg = APP_DIR / "config.local.json"
        try:
            if cfg.exists():
                ci = cfg.stat()
                if (ci.st_dev, ci.st_ino) == (info.st_dev, info.st_ino):
                    return None
        except Exception:
            pass
        return resolved
    except Exception:
        return None

def _report_is_sample(f, resolved):
    """F12: a shipped/sample report is tagged SAMPLE in the list."""
    if "sample" in f.name.lower():
        return True
    if f.suffix.lower() == ".json":
        try:
            data = json.loads(resolved.read_text(encoding="utf-8", errors="replace"))
            return isinstance(data, dict) and data.get("sample") is True
        except Exception:
            return False
    return False

def load_reports():
    """Reports from ../reports/output/ (.json, .md, .html). Demo list if empty."""
    out = []
    if REPORTS_DIR.is_dir():
        for f in sorted(REPORTS_DIR.iterdir(), reverse=True):
            if f.suffix.lower() not in (".json", ".md", ".html", ".txt"):
                continue
            if f.name.lower() == "readme.txt":
                continue  # F12: a readme is not a report
            resolved = _contained_report_path(f)
            if resolved is None:
                continue  # F1: symlink / outside the reports directory
            out.append({"id": f"{f.stem}-{f.suffix.lower().lstrip('.')}", "name": f.name,
                        "path": resolved,
                        "date": datetime.fromtimestamp(resolved.stat().st_mtime).strftime("%Y-%m-%d"),
                        "demo": False, "sample": _report_is_sample(f, resolved)})
    if out:
        return out
    base = datetime(2025, 11, 21)
    demo = []
    for i in range(7):
        d = base - timedelta(days=i)
        if d.weekday() < 5:
            demo.append({"id": f"demo-{d.strftime('%Y-%m-%d')}",
                         "name": f"Daily report — {d.strftime('%Y-%m-%d')}",
                         "path": None, "date": d.strftime("%Y-%m-%d"), "demo": True})
    return demo

def build_alerts(st):
    alerts = []
    tr = st.get("trading") or {}
    if tr.get("is_live"):
        alerts.append(("halt", "LIVE MODE — REAL MONEY. Orders placed by this app execute in your "
                               "own Alpaca brokerage account with real funds. The v9 protections "
                               "apply unchanged. STOP ALL is in the banner above and on the "
                               "Trading Mode page."))
    if tr.get("stopped"):
        alerts.append(("halt", "ENGINE STOPPED (STOP ALL)"
                               + (f" — set {esc(tr['stopped_at'])}." if tr.get("stopped_at") else ".")
                               + " No orders will be placed. Positions were NOT sold; manage "
                                 "them in your broker."))
    if tr.get("problem"):
        alerts.append(("warn", "TRADING MODE — " + esc(tr["problem"])))
    for w in st.get("state_warnings") or []:
        alerts.append(("warn", "STATE FILE — " + esc(w)))
    if st["mode"] == "live":
        for p in st["pots"]:
            if not p.get("curve"):
                alerts.append(("info", f"NO HISTORY YET — {esc(p['name'])} has no equity "
                                       f"curve in the live state file, so its chart shows "
                                       f"the SPY benchmark only, not a replay curve."))
    if st["mode"] == "demo":
        alerts.append(("notice", "REPLAY RECORD — showing demo data generated from the published "
                                 "backtest finals. No live state files found in ../state/."))
    if st.get("updated_at"):
        age_h = (datetime.now() - st["updated_at"]).total_seconds() / 3600
        if age_h > 26:
            alerts.append(("warn", f"STALE DATA — state last written {age_h:.0f}h ago "
                                   f"({st['updated_at'].strftime('%Y-%m-%d %H:%M')})."))
    for p in st["pots"]:
        floor = p["floor"]
        if p["status"] == "halted":
            msg = f"HALTED — {esc(p['name'])} hit its floor ({money(floor)})."
            if p.get("restart_on"):
                msg += f" Restart scheduled {esc(p['restart_on'])} (episode 2, fresh -15% floor)."
            alerts.append(("halt", msg))
        elif p["status"] == "ended":
            alerts.append(("halt", f"ENDED — {esc(p['name'])} reached its second halt. Run closed."))
        elif p["balance"] <= floor * 1.10:
            alerts.append(("warn", f"FLOOR PROXIMITY — {esc(p['name'])} is within 10% of its "
                                   f"{money(floor)} floor (balance {money(p['balance'])})."))
        if p["status"] == "tracking only":
            alerts.append(("info", f"TRACKING ONLY — {esc(p['name'])} is a candidate lane in the "
                                   f"paper trial. No capital allocated."))
    return alerts

# ----------------------------------------------------------------------------
# Shared CSS (embedded into every template — fully offline, no CDN)
# ----------------------------------------------------------------------------
CSS = """
:root, html[data-theme="dark"]{
  --bg:#0a0d12; --bg2:#0e1219; --surface:#12161f; --surface2:#171c28; --surface-muted:#0d1118;
  --border:#232b3a; --border-soft:#1a2130;
  --text:#e8ecf2; --muted:#8d99ad; --faint:#5d6a80;
  --accent:#5b8cff; --accent-soft:rgba(91,140,255,.12);
  --gain:#2ebd85; --loss:#e5484d; --flat:#8d99ad;
  --warn-bg:rgba(224,165,60,.10); --warn-border:rgba(224,165,60,.45); --warn-text:#e0a53c;
  --halt-bg:rgba(229,72,77,.10); --halt-border:rgba(229,72,77,.5);
  --notice-bg:rgba(91,140,255,.08); --notice-border:rgba(91,140,255,.4);
  --shadow:0 8px 28px rgba(0,0,0,.45);
  --mono:ui-monospace,"SF Mono","Cascadia Mono",Consolas,"Roboto Mono",monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,"Helvetica Neue",Arial,sans-serif;
}
html[data-theme="light"]{
  --bg:#f4f6f9; --bg2:#eceff4; --surface:#ffffff; --surface2:#f7f9fc; --surface-muted:#eef1f6;
  --border:#d7dee8; --border-soft:#e3e8f0;
  --text:#131a26; --muted:#5a6779; --faint:#8b96a8;
  --accent:#2456d6; --accent-soft:rgba(36,86,214,.08);
  --gain:#0e9f6e; --loss:#d92d20; --flat:#5a6779;
  --warn-bg:rgba(181,121,10,.08); --warn-border:rgba(181,121,10,.4); --warn-text:#9a6a06;
  --halt-bg:rgba(217,45,32,.06); --halt-border:rgba(217,45,32,.4);
  --notice-bg:rgba(36,86,214,.06); --notice-border:rgba(36,86,214,.35);
  --shadow:0 8px 28px rgba(19,26,38,.10);
}
*{box-sizing:border-box;margin:0;padding:0}
html{color-scheme:dark} html[data-theme="light"]{color-scheme:light}
body{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:14px;line-height:1.5;
  -webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}
a{color:var(--accent);text-decoration:none} a:hover{text-decoration:underline}
.num{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}
.mono{font-family:var(--mono);letter-spacing:.02em}
.gain{color:var(--gain)} .loss{color:var(--loss)} .flat{color:var(--flat)}
.muted{color:var(--muted)} .small{font-size:12px} .faint{color:var(--faint)}
/* header */
header.topbar{position:sticky;top:0;z-index:20;background:var(--bg2);border-bottom:1px solid var(--border)}
.topbar-in{max-width:1440px;margin:0 auto;padding:0 24px;height:56px;display:flex;align-items:center;gap:28px}
.brand{display:flex;align-items:baseline;gap:10px;color:var(--text)}
.brand:hover{text-decoration:none}
.brand .mark{font-weight:700;font-size:16px;letter-spacing:-.01em}
.brand .sub{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.12em}
nav.main{display:flex;gap:4px;margin-left:8px}
nav.main a{color:var(--muted);padding:7px 12px;border-radius:6px;font-size:13.5px;font-weight:500}
nav.main a:hover{color:var(--text);text-decoration:none;background:var(--surface2)}
nav.main a.active{color:var(--text);background:var(--accent-soft)}
.topbar-right{margin-left:auto;display:flex;align-items:center;gap:14px}
.mode-pill{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;
  border:1px solid var(--notice-border);background:var(--notice-bg);color:var(--text);
  padding:4px 10px;border-radius:999px;white-space:nowrap}
.theme-btn{background:var(--surface);border:1px solid var(--border);color:var(--muted);
  border-radius:6px;padding:6px 12px;font-size:12.5px;cursor:pointer;font-family:var(--sans)}
.theme-btn:hover{color:var(--text)}
/* layout */
.wrap{max-width:1440px;margin:0 auto;padding:22px 24px 8px}
.grid-main{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:18px;align-items:start}
@media(max-width:1020px){.grid-main{grid-template-columns:1fr}}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;box-shadow:var(--shadow)}
.card-h{padding:14px 18px 10px;display:flex;align-items:baseline;justify-content:space-between;gap:12px}
.card-h h2{font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.09em;color:var(--muted)}
.card-b{padding:4px 18px 16px}
/* verdict row */
.verdict{display:flex;flex-wrap:wrap;gap:16px 44px;align-items:flex-end;padding:20px 22px}
.verdict .label{font-size:11.5px;font-weight:600;text-transform:uppercase;letter-spacing:.11em;color:var(--muted);margin-bottom:4px}
.verdict .big{font-size:44px;font-weight:700;letter-spacing:-.02em;line-height:1.05;font-variant-numeric:tabular-nums}
.verdict .day{font-size:19px;font-weight:600;font-variant-numeric:tabular-nums}
.verdict .stat .v{font-size:19px;font-weight:600}
.verdict .stat .l{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.09em}
/* alerts */
.alerts{display:flex;flex-direction:column;gap:8px;margin:14px 0 18px}
.alert{border:1px solid var(--border);border-left:3px solid var(--border);border-radius:8px;
  padding:10px 14px;font-size:13px;background:var(--surface)}
.alert.warn{background:var(--warn-bg);border-color:var(--warn-border);border-left-color:var(--warn-text)}
.alert.halt{background:var(--halt-bg);border-color:var(--halt-border);border-left-color:var(--loss)}
.alert.notice{background:var(--notice-bg);border-color:var(--notice-border);border-left-color:var(--accent)}
.alert.info{background:var(--surface-muted)}
.alert .tag{font-weight:700;font-size:11px;letter-spacing:.07em;margin-right:8px}
/* tables */
table{width:100%;border-collapse:collapse;font-size:13.5px}
th{font-size:11.5px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
  text-align:left;padding:10px 12px;border-bottom:1px solid var(--border);white-space:nowrap}
th.num,td.num{text-align:right}
td{padding:11px 12px;border-bottom:1px solid var(--border-soft);vertical-align:middle}
tbody tr:hover{background:var(--surface2)}
tbody tr:last-child td{border-bottom:none}
.pot-name{font-weight:600;color:var(--text);font-size:14px}
.pot-name:hover{color:var(--accent);text-decoration:none}
.status{display:inline-block;font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;
  padding:3px 8px;border-radius:999px;border:1px solid var(--border);color:var(--muted);white-space:nowrap}
.status.running{color:var(--text);border-color:var(--border)}
.status.halted,.status.ended{color:var(--loss);border-color:var(--halt-border)}
.status.tracking{color:var(--muted)}
.progress{height:5px;background:var(--surface-muted);border-radius:3px;overflow:hidden;min-width:90px}
.progress i{display:block;height:100%;background:var(--accent)}
/* watchlist rail */
.watch-item{display:flex;align-items:center;gap:10px;padding:10px 4px;border-bottom:1px solid var(--border-soft)}
.watch-item:last-child{border-bottom:none}
.watch-item .tkr{font-family:var(--mono);font-weight:600;font-size:13.5px;min-width:52px}
.watch-item .mid{flex:1;min-width:0}
.watch-item .nm{font-size:12px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.watch-item .vals{text-align:right}
.watch-item .vals .v{font-weight:600;font-size:13.5px}
.watch-item .vals .c{font-size:12px}
/* watcher feed */
.feed-item{padding:14px 18px;border-bottom:1px solid var(--border-soft)}
.feed-item:last-child{border-bottom:none}
.feed-top{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:4px}
.kind{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
  border:1px solid var(--border);border-radius:4px;padding:2px 7px}
.prio{font-size:11px;font-weight:700;letter-spacing:.07em;color:var(--warn-text);
  border:1px solid var(--warn-border);background:var(--warn-bg);border-radius:4px;padding:2px 7px}
.feed-title{font-weight:600;font-size:14px}
/* misc */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:18px}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.kpi .l{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.09em;font-weight:600}
.kpi .v{font-size:22px;font-weight:700;margin-top:3px}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12.5px;color:var(--muted)}
.legend .sw{display:inline-block;width:18px;height:0;border-top:3px solid;border-radius:2px;margin-right:6px;vertical-align:middle}
footer.honesty{max-width:1440px;margin:22px auto 0;padding:16px 24px 28px;border-top:1px solid var(--border);
  color:var(--muted);font-size:12.5px}
footer.honesty .persist{color:var(--text);font-weight:500;margin-bottom:6px}
.sample-tag{font-size:11px;font-weight:700;letter-spacing:.07em;border:1px solid var(--warn-border);
  background:var(--warn-bg);color:var(--warn-text);border-radius:4px;padding:2px 7px}
.report-body h3{font-size:15px;margin:16px 0 6px}
.report-body p{margin:6px 0;color:var(--text)}
.btn{display:inline-block;background:var(--surface2);border:1px solid var(--border);color:var(--text);
  padding:7px 14px;border-radius:7px;font-size:13px;font-weight:500}
.btn:hover{text-decoration:none;border-color:var(--accent)}
svg.chart{width:100%;height:auto;display:block}
/* trading mode (paper/live) */
.mode-pill.live{border-color:var(--halt-border);background:var(--halt-bg);color:var(--loss);font-weight:700}
.mode-banner{display:flex;align-items:center;gap:14px;flex-wrap:wrap;padding:10px 24px;
  font-size:13.5px;border-bottom:1px solid var(--border)}
.mode-banner.live{background:var(--halt-bg);border-color:var(--halt-border)}
.mode-banner.stopped{background:var(--warn-bg);border-color:var(--warn-border)}
.mode-banner .mb-title{font-weight:700;letter-spacing:.06em;text-transform:uppercase}
.mode-banner form{margin-left:auto}
.stop-btn{background:var(--loss);color:#fff;border:1px solid var(--halt-border);border-radius:7px;
  padding:8px 20px;font-size:13px;font-weight:700;letter-spacing:.05em;cursor:pointer;font-family:var(--sans)}
.stop-btn:hover{filter:brightness(1.1)}
.resume-btn{background:var(--surface);border:1px solid var(--border);color:var(--text);border-radius:7px;
  padding:8px 18px;font-size:13px;font-weight:600;cursor:pointer;font-family:var(--sans)}
.resume-btn:hover{border-color:var(--accent)}
.mode-big{font-size:30px;font-weight:700;letter-spacing:-.01em;margin:2px 0 12px}
.mode-big.live-big{color:var(--loss)}
.confirm-input{width:100%;max-width:540px;background:var(--surface2);border:1px solid var(--border);
  color:var(--text);border-radius:7px;padding:10px 12px;font-family:var(--mono);font-size:14px;margin:8px 0 12px}
.btn.danger{border-color:var(--halt-border);color:var(--loss);font-weight:700;cursor:pointer;font-family:var(--sans)}
.btn-row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
/* horizon picker (W5-A) */
.tier{display:inline-block;font-size:11px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;
  padding:3px 9px;border-radius:999px;border:1px solid var(--border);color:var(--muted);white-space:nowrap}
.tier-promoted{color:var(--gain);border-color:var(--gain)}
.tier-candidate{color:var(--warn-text);border-color:var(--warn-border);background:var(--warn-bg)}
.tier-variant-candidate{color:var(--accent);border-color:var(--notice-border);background:var(--notice-bg)}
.tier-default{color:var(--text);border-color:var(--accent);background:var(--accent-soft)}
.bucket{margin-bottom:18px}
.offering-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.offering-card{border:1px solid var(--border-soft);border-radius:8px;padding:14px;background:var(--surface2);
  display:flex;flex-direction:column;gap:8px}
.offering-card h3{font-size:16px;letter-spacing:-.01em}
.offering-card .fact{font-size:13px}
.offering-card .fact .l{color:var(--muted);font-size:11.5px;text-transform:uppercase;letter-spacing:.08em;font-weight:600}
.floor-free-banner{background:var(--halt-bg);border:1px solid var(--halt-border);border-left:3px solid var(--loss);
  border-radius:8px;padding:10px 12px;font-size:13px;font-weight:600}
.offering-note{font-size:12.5px;color:var(--muted)}
.offering-card form{margin-top:auto}
"""

THEME_JS = """
<script>
(function(){
  var saved = null;
  try { saved = localStorage.getItem('ag-theme'); } catch(e) {}
  if (saved) document.documentElement.setAttribute('data-theme', saved);
  window.agToggleTheme = function(){
    var cur = document.documentElement.getAttribute('data-theme') || 'dark';
    var next = cur === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('ag-theme', next); } catch(e) {}
    var b = document.getElementById('themeBtn');
    if (b) b.textContent = next === 'dark' ? 'Light theme' : 'Dark theme';
  };
  document.addEventListener('DOMContentLoaded', function(){
    var cur = document.documentElement.getAttribute('data-theme') || 'dark';
    var b = document.getElementById('themeBtn');
    if (b) b.textContent = cur === 'dark' ? 'Light theme' : 'Dark theme';
  });
})();
</script>
"""

CHART_COLORS = ["#5b8cff", "#b58cff", "#3fc1c9", "#e0a53c", "#7d8aa5", "#d97bb5"]

def svg_chart(pots, spy_curve, labels, width=880, height=320, pad_l=58, pad_r=14, pad_t=14, pad_b=30):
    series = [(p["name"], p["curve"], CHART_COLORS[i % len(CHART_COLORS)], False)
              for i, p in enumerate(pots) if p.get("curve")]
    series.append(("SPY (benchmark)", spy_curve, "#8d99ad", True))
    all_vals = [v for _, c, _, _ in series for v in c] + [100.0]
    lo, hi = min(all_vals) * 0.94, max(all_vals) * 1.05
    n = max(len(c) for _, c, _, _ in series)
    iw, ih = width - pad_l - pad_r, height - pad_t - pad_b
    def X(i): return pad_l + iw * (i / (n - 1 if n > 1 else 1))
    def Y(v): return pad_t + ih * (1 - (v - lo) / (hi - lo if hi > lo else 1))
    parts = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Pot performance versus SPY">']
    # gridlines + y labels (neutral grays — color is reserved for gain/loss & series identity)
    for frac in (0, 0.25, 0.5, 0.75, 1.0):
        v = lo + (hi - lo) * frac
        y = Y(v)
        parts.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width-pad_r}" y2="{y:.1f}" stroke="var(--border-soft)" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l-8}" y="{y+4:.1f}" text-anchor="end" font-size="11" fill="var(--faint)" font-family="var(--mono)">${v:,.0f}</text>')
    for i in range(0, n, 24):
        if i < len(labels):
            parts.append(f'<text x="{X(i):.1f}" y="{height-8}" text-anchor="middle" font-size="11" fill="var(--faint)">{esc(labels[i][:4])}</text>')
    parts.append(f'<line x1="{pad_l}" y1="{Y(100):.1f}" x2="{width-pad_r}" y2="{Y(100):.1f}" stroke="var(--faint)" stroke-width="1" stroke-dasharray="2 4"/>')
    for name, curve, color, dashed in series:
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(curve))
        dash = ' stroke-dasharray="6 4"' if dashed else ""
        wdt = "1.8" if dashed else "2.2"
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="{wdt}"{dash} stroke-linejoin="round"/>')
        parts.append(f'<circle cx="{X(len(curve)-1):.1f}" cy="{Y(curve[-1]):.1f}" r="3.2" fill="{color}"/>')
    parts.append("</svg>")
    legend = ['<div class="legend">']
    for name, curve, color, dashed in series:
        legend.append(f'<span><span class="sw" style="border-color:{color}"></span>{esc(name)}'
                      f' <span class="mono">{money(curve[-1])}</span></span>')
    legend.append("</div>")
    return "".join(parts), "".join(legend)

# ----------------------------------------------------------------------------
# Page assembly
# ----------------------------------------------------------------------------
def render(template_name, st, active, **kw):
    tpl = (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")
    tr = st.get("trading") or {}
    is_live = bool(tr.get("is_live"))
    is_stopped = bool(tr.get("stopped"))
    # The trading-mode pill is permanent and unmissable on every page.
    if is_live:
        mode_pill = '<span class="mode-pill live">LIVE — REAL MONEY</span>'
    else:
        mode_pill = '<span class="mode-pill">PAPER — SIMULATED MONEY</span>'
    if st["mode"] == "demo":
        mode_pill += ' <span class="mode-pill">Replay record — demo data</span>'
    if not _credentials_exist():
        # W5-C: no owner credentials yet -- the first-run setup page is
        # one click away from every page until it is completed.
        mode_pill += ' <a class="mode-pill" href="/setup">Set up dashboard login</a>'
    # Full-width banner: LIVE mode and/or STOP ALL, with the stop control.
    banner = ""
    if is_stopped:
        banner = f"""
<div class="mode-banner stopped"><span class="mb-title">Engine stopped — no orders will be placed</span>
<span>{'LIVE MODE — REAL MONEY. ' if is_live else ''}Positions were not sold; manage them in your broker.</span>
<form method="post" action="/mode/resume">{csrf_field()}<button class="resume-btn" type="submit">Resume engine</button></form></div>"""
    elif is_live:
        banner = f"""
<div class="mode-banner live"><span class="mb-title">Live mode — real money</span>
<span>This app can place real orders in your own Alpaca account.</span>
<form method="post" action="/mode/stop-all">{csrf_field()}<button class="stop-btn" type="submit">STOP ALL</button></form></div>"""
    if st.get("updated_at"):
        persist = (f"App state saved to disk · last write {st['updated_at'].strftime('%Y-%m-%d %H:%M')} "
                   f"· resumes after shutdown")
    elif st["mode"] == "demo":
        persist = ("App state saved to disk · resumes after shutdown — no live state files yet; "
                   "showing the replay record until the engine writes ../state/")
    else:
        persist = "App state saved to disk · resumes after shutdown"
    nav_items = [("/", "Overview"), ("/pot", "Pot Detail"), ("/picker", "Horizon Picker"), ("/watcher", "Watcher"), ("/reports", "Reports"), ("/mode", "Trading Mode"), ("/panic", "Key Leak Help")]
    nav = "".join(f'<a href="{h}" class="{"active" if a == active else ""}">{t}</a>'
                  for h, t, a in [(h, t, h) for h, t in nav_items])
    # fix active matching for pot detail subpages
    nav = "".join(
        f'<a href="{h}" class="{"active" if h == active else ""}">{t}</a>' for h, t in nav_items)
    header = f"""
<header class="topbar"><div class="topbar-in">
  <a class="brand" href="/"><span class="mark">Atlas Gate</span><span class="sub">AI Stock App</span></a>
  <nav class="main">{nav}</nav>
  <div class="topbar-right">
    {mode_pill}
    <button class="theme-btn" id="themeBtn" onclick="agToggleTheme()">Light theme</button>
  </div>
</div></header>{banner}"""
    if is_live:
        honesty = ("LIVE MODE — REAL MONEY: this app is connected to your own Alpaca brokerage "
                   "account and orders it places execute with real funds, at your own risk. "
                   "Backtest returns are flattered by survivorship bias: no free data stack is "
                   "bias-free, delisted names are under-represented, and live results should be "
                   "expected to run below the replay record. Past performance does not guarantee "
                   "future results. Watcher items are radar only and never place trades.")
    else:
        honesty = ("PAPER MODE — simulated money only: no real money is traded while the app is "
                   "in paper mode. Backtest returns are flattered by survivorship bias: no free "
                   "data stack is bias-free, delisted names are under-represented, and live "
                   "results should be expected to run below the replay record. Past performance "
                   "does not guarantee future results. Watcher items are radar only and never "
                   "place trades.")
    if is_stopped:
        honesty += " The engine is currently STOPPED (STOP ALL): no orders will be placed."
    # Phase A (F2): version / release-hash line so a tampered copy is
    # visible against the official release manifest.
    ver_line = None
    try:
        mf = APP_DIR / "release_manifest.json"
        if mf.exists():
            mdata = json.loads(mf.read_text(encoding="utf-8"))
            ver_line = (f"Atlas Gate AI Stock App v{mdata.get('version', VERSION)} "
                        f"\u00b7 build {str(mdata.get('manifest_sha256', ''))[:12]} "
                        f"\u00b7 check this copy: python run.py verify")
    except Exception:
        ver_line = None
    if not ver_line:
        ver_line = (f"Atlas Gate AI Stock App v{VERSION} \u00b7 development build "
                    f"(no release manifest)")
    footer = f"""
<footer class="honesty">
  <div class="persist">{esc(persist)}</div>
  <div>{honesty}</div>
  <div>{esc(ver_line)}</div>
</footer>"""
    if not _is_loopback_bind(EFFECTIVE_BIND):
        header = header + (f'\n<div class="mode-banner live"><span class="mb-title">'
                           f'{esc(EXPOSURE_BANNER)}</span></div>')
    # R2-N8: a flash stored by a POST (STOP ALL / Resume from the banner)
    # is shown on whatever page the redirect lands on, not only /mode.
    flash_html = st.get("flash_html") or ""
    if flash_html:
        header = header + f'\n<div class="alerts">{flash_html}</div>'
    out = tpl.replace("{{CSS}}", CSS).replace("{{THEME_JS}}", THEME_JS)
    out = out.replace("{{HEADER}}", header).replace("{{FOOTER}}", footer)
    for k, v in kw.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out

def alerts_html(st):
    alerts = build_alerts(st)
    if not alerts:
        return '<div class="alerts"><div class="alert info"><span class="tag">STATUS</span>All pots within normal bounds. No floor, halt, or data alerts.</div></div>'
    rows = []
    for kind, msg in alerts:
        tag = {"warn": "WARNING", "halt": "ALERT", "notice": "DATA", "info": "NOTE"}.get(kind, "NOTE")
        rows.append(f'<div class="alert {kind}"><span class="tag">{tag}</span>{msg}</div>')
    return '<div class="alerts">' + "".join(rows) + "</div>"

def status_pill(s):
    return f'<span class="status {esc(s.split()[0])}">{esc(s)}</span>'

# ----------------------------------------------------------------------------
# Pages
# ----------------------------------------------------------------------------
def page_overview(st):
    total_ret = (st["total_balance"] / st["total_start"] - 1) * 100 if st["total_start"] else 0
    spy_total = st["spy_final"] * len(st["pots"])
    vs_spy = (st["total_balance"] / spy_total - 1) * 100 if spy_total else 0
    dist = GOAL * len(st["pots"]) - st["total_balance"]
    chart, legend = svg_chart(st["pots"], st["spy_curve"], st["labels"])
    if st["mode"] == "live" and any(p.get("curve") for p in st["pots"]):
        # R2-N5: live curves carry values without dates; they are drawn
        # on the replay window's axis. Say so, on the chart itself.
        legend += (' <span class="sample-tag">NOTE — live pot curves are plotted on the '
                   'replay window\'s date axis (2016–2025): the state file carries values '
                   'without dates, so the shape is each pot\'s own but the dates are not</span>')
    rows = []
    for p in st["pots"]:
        d_goal = GOAL - p["balance"]
        prog = min(p["balance"] / GOAL * 100, 100)
        rows.append(f"""<tr>
          <td><a class="pot-name" href="/pot?id={esc(p['id'])}">{esc(p['name'])}</a>
              <div class="small muted">{esc(p['strategy'])}</div></td>
          <td>{status_pill(p['status'])}</td>
          <td class="num"><strong>{money(p['balance'])}</strong></td>
          <td class="num {cls(p['total_pct'])}">{pct(p['total_pct'])}</td>
          <td class="num {cls(p['day_pct'])}">{money_signed(p['day_usd'])} ({pct(p['day_pct'])})</td>
          <td class="num">{money(d_goal)}<div class="progress" title="{prog:.4f}% of goal"><i style="width:{max(prog,0.4):.2f}%"></i></div></td>
          <td class="num {cls(p['vs_spy_pct'])}">{pct(p['vs_spy_pct'])}</td></tr>""")
    # right rail: aggregate holdings watchlist (top positions across pots)
    agg = {}
    for p in st["pots"]:
        for h in p["holdings"]:
            a = agg.setdefault(h["ticker"], {"value": 0.0, "change_pct": h["change_pct"], "price": h["price"]})
            a["value"] += h["value"]
    watch = sorted(agg.items(), key=lambda kv: -kv[1]["value"])[:9]
    watch_rows = "".join(f"""<div class="watch-item"><span class="tkr">{esc(t)}</span>
        <div class="mid"><div class="nm">{money(a['price'])} / share</div></div>
        <div class="vals"><div class="v num">{money(a['value'])}</div>
        <div class="c num {cls(a['change_pct'])}">{pct(a['change_pct'])}</div></div></div>"""
        for t, a in watch)
    if st["mode"] == "demo":
        verdict_mode = "Replay record · published backtest finals"
    elif (st.get("trading") or {}).get("is_live"):
        verdict_mode = "Live state — LIVE MODE (real money)"
    else:
        verdict_mode = "Live paper-trading state"
    return render("overview.html", st, "/",
                  VERDICT_BALANCE=money(st["total_balance"]),
                  VERDICT_DAY_CLS=cls(st["total_day_pct"]),
                  VERDICT_DAY=f"{money_signed(st['total_day_usd'])} ({pct(st['total_day_pct'])}) today",
                  VERDICT_MODE=verdict_mode,
                  STAT_TOTAL_RETURN=pct(total_ret),
                  STAT_TOTAL_RETURN_CLS=cls(total_ret),
                  STAT_VS_SPY=pct(vs_spy), STAT_VS_SPY_CLS=cls(vs_spy),
                  STAT_POTS=str(len(st["pots"])),
                  STAT_DIST=money(dist),
                  ALERTS=alerts_html(st),
                  CHART=chart, LEGEND=legend,
                  POT_ROWS="".join(rows), WATCH_ROWS=watch_rows)

def benchmark_section(pot, st):
    """W5-B: this pot vs SPY vs a bank CD shadow over the same stretch.

    Consumes data.cd_shadow.series(start_date, end_date, start_cash)
    per its contract. When the module is missing, raises, or returns
    None, the section says plainly that the CD comparison is not yet
    available -- CD numbers are NEVER invented here.
    """
    heading = "This pot vs SPY vs what a bank CD would have done over the same stretch"
    start_cash = pot.get("start") or START_CAPITAL
    labels = st.get("labels") or []
    start_date = labels[0] if labels else ""
    end_date = labels[-1] if labels else ""
    # cd_shadow requires real ISO dates; the dashboard's curve labels
    # are YYYY-MM, so expand them (first day for the start, last day
    # for the end) before calling.
    def _iso(d, last=False):
        if isinstance(d, str) and len(d) == 7 and d[4] == "-":
            try:
                y, m = int(d[:4]), int(d[5:7])
                if last:
                    import calendar as _cal
                    return f"{d}-{_cal.monthrange(y, m)[1]:02d}"
                return f"{d}-01"
            except Exception:
                return d
        return d
    cd_start, cd_end = _iso(start_date), _iso(end_date, last=True)
    cd_series = None
    if _cd_shadow is not None:
        try:
            cd_series = _cd_shadow.series(cd_start, cd_end, start_cash=start_cash)
        except TypeError:
            try:
                cd_series = _cd_shadow.series(cd_start, cd_end)
            except Exception:
                cd_series = None
        except Exception:
            cd_series = None
    cd_final = None
    if isinstance(cd_series, (list, tuple)) and cd_series:
        try:
            last = cd_series[-1]
            v = _num(last[1])
            if v is not None:
                cd_final = v
        except Exception:
            cd_final = None
    spy_val = (st.get("spy_final") or SPY_FINAL) * start_cash / START_CAPITAL
    if cd_final is None:
        body = ('<p class="cd-unavailable">CD comparison not yet available.</p>'
                f'<p class="small muted">This pot: <strong>{money(pot["balance"])}</strong> · '
                f'SPY buy-and-hold over the same stretch: <strong>{money(spy_val)}</strong> '
                f'per {money(start_cash)} start. The bank CD shadow will appear here once '
                f'its data is available.</p>')
    else:
        rows = "".join([
            f'<tr><td><strong>{esc(pot["name"])}</strong> (this pot)</td>'
            f'<td class="num"><strong>{money(pot["balance"])}</strong></td>'
            f'<td class="num {cls(pot["total_pct"])}">{pct(pot["total_pct"])}</td></tr>',
            f'<tr><td>SPY (buy-and-hold benchmark)</td>'
            f'<td class="num"><strong>{money(spy_val)}</strong></td>'
            f'<td class="num {cls((spy_val / start_cash - 1) * 100)}">{pct((spy_val / start_cash - 1) * 100)}</td></tr>',
            f'<tr><td>Bank CD (shadow — what a bank CD would have done)</td>'
            f'<td class="num"><strong>{money(cd_final)}</strong></td>'
            f'<td class="num {cls((cd_final / start_cash - 1) * 100)}">{pct((cd_final / start_cash - 1) * 100)}</td></tr>',
        ])
        body = (f'<table><thead><tr><th>Over the same stretch ({esc(start_date)} to {esc(end_date)})</th>'
                f'<th class="num">Value of {money(start_cash)}</th><th class="num">Return</th></tr></thead>'
                f'<tbody>{rows}</tbody></table>')
    return (f'<section class="card" style="margin-bottom:18px" aria-label="Benchmarks: pot versus SPY versus bank CD">'
            f'<div class="card-h"><h2>{esc(heading)}</h2></div>'
            f'<div class="card-b">{body}</div></section>')

def page_pot(st, pot_id):
    pot = next((p for p in st["pots"] if p["id"] == pot_id), st["pots"][0] if st["pots"] else None)
    if pot is None:
        return render("pot.html", st, "/pot", POT_NAME="No pots", POT_STRATEGY="", POT_TABS="",
                      POT_STATUS="", KPI_BALANCE="—", KPI_RETURN="—", KPI_RETURN_CLS="flat",
                      KPI_VS_SPY="—", KPI_VS_SPY_CLS="flat", KPI_FLOOR="—", KPI_EPISODE="—",
                      FLOOR_NOTE="", CHART="", LEGEND="", POS_ROWS="", TRADE_ROWS="",
                      BENCHMARK_SECTION="")
    tabs = "".join(
        f'<a class="btn" style="{"border-color:var(--accent)" if p["id"] == pot["id"] else ""}" '
        f'href="/pot?id={esc(p["id"])}">{esc(p["name"])}</a>' for p in st["pots"])
    chart, legend = svg_chart([pot], st["spy_curve"], st["labels"])
    if not pot.get("curve"):
        # F6: never present the replay curve as this pot's own. The chart
        # above plots SPY only; say so plainly.
        legend += (' <span class="sample-tag">NO EQUITY HISTORY YET — this pot has no '
                   'curve of its own in the state file; chart shows the SPY benchmark only</span>')
    elif st["mode"] == "live":
        # R2-N5: same axis honesty as the overview chart.
        legend += (' <span class="sample-tag">NOTE — this live pot\'s curve is plotted on the '
                   'replay window\'s date axis (2016–2025): the state file carries values '
                   'without dates, so the shape is the pot\'s own but the dates are not</span>')
    floor_note = (f"Floor: {money(pot['floor'])} (plain −15% from the {money(pot['start'])} start, "
                  f"Claude's rules v9 — no profit ladder). Episode {pot['episode']} of max 2.")
    if pot["status"] == "halted":
        floor_note += f" Halted{f' on {esc(pot['halted_on'])}' if pot.get('halted_on') else ''}."
        if pot.get("restart_on"):
            floor_note += (f" Holdings liquidated; restart on {esc(pot['restart_on'])} after the "
                           f"90-day cash period, under a fresh episode-2 floor.")
    pos_rows = "".join(f"""<tr><td class="mono"><strong>{esc(h['ticker'])}</strong></td>
        <td class="num">{h['shares']:,.3f}</td><td class="num">{money(h['price'])}</td>
        <td class="num"><strong>{money(h['value'])}</strong></td>
        <td class="num {cls(h['change_pct'])}">{pct(h['change_pct'])}</td></tr>"""
        for h in pot["holdings"])
    pos_rows += (f'<tr><td class="muted">Cash</td><td></td><td></td>'
                 f'<td class="num">{money(pot["cash"])}</td><td></td></tr>')
    trade_rows = "".join(f"""<tr><td class="mono">{esc(t['date'])}</td>
        <td class="mono"><strong>{esc(t['ticker'])}</strong></td>
        <td>{esc(t['side'])}</td><td class="num">{t['shares']:,.3f}</td>
        <td class="num">{money(t['price'])}</td>
        <td class="num {cls(t['pnl']) if t['pnl'] is not None else 'flat'}">"""
        + (money_signed(t["pnl"]) if t["pnl"] is not None else "—") + "</td></tr>"
        for t in pot["trades"])
    return render("pot.html", st, "/pot",
                  POT_NAME=esc(pot["name"]), POT_STRATEGY=esc(pot["strategy"]), POT_TABS=tabs,
                  POT_STATUS=status_pill(pot["status"]),
                  KPI_BALANCE=money(pot["balance"]), KPI_RETURN=pct(pot["total_pct"]),
                  KPI_RETURN_CLS=cls(pot["total_pct"]), KPI_VS_SPY=pct(pot["vs_spy_pct"]),
                  KPI_VS_SPY_CLS=cls(pot["vs_spy_pct"]), KPI_FLOOR=money(pot["floor"]),
                  KPI_EPISODE=f"Episode {pot['episode']}", FLOOR_NOTE=esc(floor_note),
                  CHART=chart, LEGEND=legend, POS_ROWS=pos_rows, TRADE_ROWS=trade_rows,
                  BENCHMARK_SECTION=benchmark_section(pot, st))

def page_watcher(st):
    # F6: the SAMPLE tag follows the DATA, not the state mode -- demo/sample
    # watcher items keep their label even when live state is on screen.
    sample = ('<span class="sample-tag">SAMPLE DATA</span>'
              if st["mode"] == "demo" or st.get("watcher_sample") else "")
    items = []
    for w in st["watcher"]:
        prio = '<span class="prio">PRIORITY</span>' if w.get("priority") else ""
        items.append(f"""<div class="feed-item">
          <div class="feed-top"><span class="kind">{esc(w.get('kind','Filing'))}</span>{prio}
          <span class="mono"><strong>{esc(w.get('ticker',''))}</strong></span>
          <span class="small faint mono">{esc(w.get('date',''))}</span>{sample}</div>
          <div class="feed-title">{esc(w.get('title',''))}</div>
          <div class="small muted">{esc(w.get('note',''))}</div></div>""")
    return render("watcher.html", st, "/watcher",
                  FEED_ROWS="".join(items) or '<div class="feed-item muted">No watcher items.</div>',
                  SAMPLE_TAG=sample)

def page_reports(st, reports):
    rows = []
    for r in reports:
        if r["demo"]:
            tag = '<span class="sample-tag">REPLAY</span>'
        elif r.get("sample"):
            tag = '<span class="sample-tag">SAMPLE</span>'
        else:
            tag = ""
        rows.append(f"""<tr><td class="mono">{esc(r['date'])}</td>
          <td><a class="pot-name" href="/report?id={esc(r['id'])}">{esc(r['name'])}</a></td>
          <td>{tag}</td><td class="num"><a href="/report?id={esc(r['id'])}">View</a></td></tr>""")
    return render("reports.html", st, "/reports", REPORT_ROWS="".join(rows))

def page_report_detail(st, reports, rid):
    rep = next((r for r in reports if r["id"] == rid), reports[0] if reports else None)
    if rep is None:
        body, title, date = "<p>No reports available.</p>", "Reports", ""
    elif not rep["demo"] and rep["path"] is not None:
        title, date = rep["name"], rep["date"]
        # F1 defence in depth: re-verify containment at read time -- the
        # file could have been swapped for a symlink since listing.
        if _contained_report_path(rep["path"]) is None:
            body = "<p>Report not found.</p>"
            return render("report.html", st, "/reports", REPORT_TITLE=esc(title),
                          REPORT_DATE=esc(date), REPORT_BODY=body)
        try:
            raw = rep["path"].read_text(encoding="utf-8", errors="replace")
            if rep["path"].suffix.lower() == ".json":
                data = json.loads(raw)
                body = "<pre class='mono small' style='white-space:pre-wrap'>" + esc(json.dumps(data, indent=2)) + "</pre>"
            else:
                # F3: report content is DATA, never markup -- .html reports
                # are escaped exactly like .md/.txt, so a dropped .html file
                # cannot execute script in the dashboard origin.
                body = ("<pre class='mono small' style='white-space:pre-wrap;line-height:1.6'>"
                        + esc(raw) + "</pre>")
            if rep.get("sample"):
                body = '<p><span class="sample-tag">SAMPLE</span></p>' + body
        except Exception:
            body = "<p>Could not read this report file.</p>"
    else:
        title, date = rep["name"], rep["date"]
        rows = "".join(f"""<tr><td><strong>{esc(p['name'])}</strong></td>
            <td>{status_pill(p['status'])}</td><td class="num">{money(p['balance'])}</td>
            <td class="num {cls(p['total_pct'])}">{pct(p['total_pct'])}</td>
            <td class="num {cls(p['day_pct'])}">{money_signed(p['day_usd'])}</td>
            <td class="num {cls(p['vs_spy_pct'])}">{pct(p['vs_spy_pct'])}</td></tr>""" for p in st["pots"])
        body = f"""<p><span class="sample-tag">REPLAY RECORD</span></p>
        <h3>Balances at close</h3>
        <table><thead><tr><th>Pot</th><th>Status</th><th class="num">Balance</th>
        <th class="num">Total return</th><th class="num">Day change</th><th class="num">vs SPY</th></tr></thead>
        <tbody>{rows}</tbody></table>
        <h3>Notes</h3>
        <p>Total across pots: <strong>{money(st['total_balance'])}</strong> on
        {money(st['total_start'])} of starting capital. SPY buy-and-hold over the same replay
        window: {money(st['spy_final'])} per $100. Floors checked: no pot at or below its floor.
        Watcher produced radar items only; no trades were placed from watcher signals.</p>"""
    return render("report.html", st, "/reports", REPORT_TITLE=esc(title),
                  REPORT_DATE=esc(date), REPORT_BODY=body)

def page_mode(st, flash_id=""):
    # F10: only server-generated flash messages are shown; a ?msg= query
    # parameter is never reflected as an official alert.
    msg, kind = _flash_take(flash_id)
    tr = st.get("trading") or {}
    live = bool(tr.get("is_live"))
    phrase = tr.get("confirmation_phrase", "I UNDERSTAND THIS TRADES REAL MONEY")
    msg_block = ""
    if msg:
        mcls = "warn" if kind == "warn" else "notice"
        msg_block = (f'<div class="alerts"><div class="alert {mcls}">'
                     f'<span class="tag">MODE</span>{esc(msg)}</div></div>')
    def yn(b):
        return "Present" if b else "Not set"
    rows = "".join([
        f"<tr><td class='muted'>Mode set in config</td><td><strong>{esc((tr.get('configured_mode') or 'paper').upper())}</strong></td></tr>",
        f"<tr><td class='muted'>Mode actually running</td><td><strong>{'LIVE — REAL MONEY' if live else 'PAPER — SIMULATED MONEY'}</strong></td></tr>",
        f"<tr><td class='muted'>Alpaca paper keys</td><td>{yn(tr.get('paper_keys_present'))}</td></tr>",
        f"<tr><td class='muted'>Alpaca live keys</td><td>{yn(tr.get('live_keys_present'))}</td></tr>",
        f"<tr><td class='muted'>Engine (STOP ALL)</td><td>{'STOPPED' + (' since ' + esc(tr['stopped_at']) if tr.get('stopped_at') else '') if tr.get('stopped') else 'Running'}</td></tr>",
    ])
    if live:
        action = f"""<p style="max-width:78ch">The app is in <strong>LIVE</strong> mode. Switching back to
        paper stops real-money trading from this app; positions already held stay in your account.</p>
        <form method="post" action="/mode/disable-live" style="margin-top:12px">{csrf_field()}
          <button class="btn" type="submit">Switch back to PAPER mode</button></form>"""
    else:
        key_note = "" if tr.get("live_keys_present") else (
            '<p class="small" style="color:var(--warn-text);margin-bottom:10px">No Alpaca LIVE keys were '
            'found in <span class="mono">config.local.json</span>. Enabling will be refused until you add '
            'your own live key id and secret key there — the app fails safe to paper, never live.</p>')
        action = f"""{key_note}
        <p style="max-width:78ch">To enable live mode, type the confirmation phrase exactly as shown.
        This is a deliberate act, not a toggle: no single click can do it.</p>
        <form method="post" action="/mode/enable-live">{csrf_field()}
          <label class="small muted" for="phrase">Type exactly:</label>
          <div class="mono" style="font-size:15px;margin-top:2px">{esc(phrase)}</div>
          <input class="confirm-input" id="phrase" type="text" name="phrase" autocomplete="off"
                 spellcheck="false" placeholder="Type the phrase here">
          <div class="btn-row"><button class="btn danger" type="submit">Enable LIVE mode</button>
          <span class="small muted">Trades real money in your own Alpaca account.</span></div>
        </form>"""
    if tr.get("stopped"):
        stop_block = f"""<p><strong>Engine is STOPPED</strong>{(' since ' + esc(tr['stopped_at'])) if tr.get('stopped_at') else ''}.
        No orders will be placed in any mode.</p>
        <form method="post" action="/mode/resume" style="margin-top:10px">{csrf_field()}
          <button class="resume-btn" type="submit">Resume engine</button></form>"""
    else:
        stop_block = f"""<form method="post" action="/mode/stop-all">{csrf_field()}
          <button class="stop-btn" type="submit">STOP ALL</button></form>"""
    return render("mode.html", st, "/mode",
                  MSG_BLOCK=msg_block, ALERTS=alerts_html(st),
                  MODE_BIG="LIVE — REAL MONEY" if live else "PAPER — SIMULATED MONEY",
                  MODE_BIG_CLS="live-big" if live else "",
                  STATUS_ROWS=rows, ACTION_BLOCK=action, STOP_BLOCK=stop_block)

def page_not_found(st, what="page"):
    """F9/F14: a real 404 page (with the normal header/footer honesty
    chrome), never a silent substitution of another pot/report and never
    the overview page in disguise."""
    return render("report.html", st, "/reports",
                  REPORT_TITLE="Not found",
                  REPORT_DATE="",
                  REPORT_BODY=(f"<p>The requested {esc(what)} does not exist. "
                               f"Check the link, or use the navigation above.</p>"))

def page_login(st, error=""):
    err = ""
    if error:
        err = (f'<div class="alerts"><div class="alert warn"><span class="tag">LOGIN</span>'
               f'{esc(error)}</div></div>')
    owner = _owner_name()
    greeting = f"Welcome back, {esc(owner)}." if owner else ""
    return render("login.html", st, "/login", LOGIN_ERROR=err, CSRF_FIELD=csrf_field(),
                  OWNER_GREETING=greeting)

# ----------------------------------------------------------------------------
# W5-A: Horizon Picker page
# ----------------------------------------------------------------------------
def _offering_field(off, name, default=None):
    if isinstance(off, dict):
        return off.get(name, default)
    return getattr(off, name, default)

_FINALS_LABELS = {"decade": "10-year road", "decade_window": "10-year window",
                  "continuous": "Continuous", "validation": "Validation",
                  "long_17y": "17-year road"}

def _finals_text(off):
    """Published finals as display text, from either registry shape:
    the task contract's `finals_text` string, or the shipped registry's
    `finals` dict of {window: dollars per $100 pot}."""
    ft = _offering_field(off, "finals_text")
    if ft not in (None, ""):
        return str(ft)
    finals = _offering_field(off, "finals")
    if isinstance(finals, dict) and finals:
        parts = []
        for k, v in finals.items():
            label = _FINALS_LABELS.get(str(k), str(k).replace("_", " ").title())
            parts.append(f"{label}: {money(v)}" if isinstance(v, (int, float))
                         and not isinstance(v, bool) else f"{label}: {v}")
        return " · ".join(parts)
    if finals not in (None, ""):
        return str(finals)
    return None

def _normalise_offering(off):
    warning = _offering_field(off, "warning")
    return {
        "pot_id": _offering_field(off, "pot_id"),
        "name": _offering_field(off, "name") or _offering_field(off, "strategy_name"),
        "tier": _offering_field(off, "tier"),
        "finals_text": _finals_text(off),
        "worst_fall": (_offering_field(off, "worst_fall")
                       if _offering_field(off, "worst_fall") is not None
                       else _offering_field(off, "worst_fall_pct")),
        "fence": _offering_field(off, "fence_text") or _offering_field(off, "fence"),
        "floor_free": bool(_offering_field(off, "floor_free")),
        "warning": warning if warning not in (None, "") else None,
        "note": _offering_field(off, "note") or None,
        "is_default": bool(_offering_field(off, "is_default")),
        "bucket": _offering_field(off, "bucket"),
    }

def _picker_data():
    """(buckets, {bucket: {"note": str, "offerings": [normalised dicts]}}).

    Speaks BOTH registry shapes: the task contract (BUCKETS = ordered
    bucket-name strings; available_offerings() -> {bucket: [offering]})
    and the shipped picker.py (BUCKETS = Bucket objects with .name /
    .offerings / .note, BUCKET_NAMES, available_offerings() -> a flat
    list, or per-bucket via available_offerings(name)). Falls back to
    DEFAULT_BUCKETS with no offerings when the picker module is
    unavailable or misbehaves -- the page still renders every bucket
    and says so, rather than failing.
    """
    buckets = list(DEFAULT_BUCKETS)
    bucket_notes = {}
    raw_by_bucket = {}
    if _picker is not None:
        # --- bucket names, in order ---
        names = None
        try:
            names = list(_picker.BUCKET_NAMES)
        except Exception:
            names = None
        if not names:
            try:
                names = [b if isinstance(b, str) else getattr(b, "name", None)
                         for b in list(_picker.BUCKETS)]
            except Exception:
                names = None
        if names and all(isinstance(x, str) and x for x in names):
            buckets = names
        # --- bucket-level notes (Bucket objects) ---
        try:
            for b in list(_picker.BUCKETS):
                if not isinstance(b, str):
                    nm, nt = getattr(b, "name", None), getattr(b, "note", "")
                    if nm and nt:
                        bucket_notes[nm] = nt
        except Exception:
            pass
        # --- offerings ---
        raw = None
        try:
            raw = _picker.available_offerings()
        except Exception:
            raw = None
        if isinstance(raw, dict):
            raw_by_bucket = {k: list(v or []) for k, v in raw.items()}
        elif isinstance(raw, (list, tuple)):
            grouped = {}
            per_bucket_ok = False
            for bucket in buckets:
                try:
                    lst = _picker.available_offerings(bucket)
                except Exception:
                    lst = None
                if isinstance(lst, (list, tuple)):
                    grouped[bucket] = list(lst)
                    per_bucket_ok = True
            if per_bucket_ok:
                raw_by_bucket = grouped
            else:
                # Flat list with no per-bucket call: group by an
                # offering's own bucket field if it carries one.
                for off in raw:
                    grouped.setdefault(_offering_field(off, "bucket"), []).append(off)
                raw_by_bucket = grouped
    norm = {}
    for bucket in buckets:
        norm[bucket] = {"note": bucket_notes.get(bucket, ""),
                        "offerings": [_normalise_offering(o)
                                      for o in raw_by_bucket.get(bucket) or []]}
    return buckets, norm

def _tier_label(tier):
    """(display label, css class) -- PROMOTED / CANDIDATE /
    VARIANT-CANDIDATE are visually distinct."""
    t = str(tier or "").strip().lower().replace("_", "-").replace(" ", "-")
    if "variant" in t:
        return "VARIANT-CANDIDATE", "tier-variant-candidate"
    if "promot" in t:
        return "PROMOTED", "tier-promoted"
    if "candidate" in t:
        return "CANDIDATE", "tier-candidate"
    if t:
        return str(tier).strip().upper(), "tier-candidate"
    return "CANDIDATE", "tier-candidate"

def _worst_fall_text(v):
    if v is None or v == "":
        return "Not published yet"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return pct(float(v))
    return str(v)

def page_picker(st):
    buckets, offerings = _picker_data()
    active_ids = {p["id"] for p in st["pots"]}
    sections = []
    if _picker is None:
        sections.append('<div class="alerts"><div class="alert notice"><span class="tag">PICKER</span>'
                        'Horizon picker data is not available yet — the strategy registry '
                        'has not been installed. The horizons are listed below; offerings '
                        'will appear here once the registry is in place.</div></div>')
    for bucket in buckets:
        cards = []
        bucket_info = offerings.get(bucket) or {}
        bucket_note = bucket_info.get("note") if isinstance(bucket_info, dict) else ""
        for off in (bucket_info.get("offerings") if isinstance(bucket_info, dict)
                    else bucket_info) or []:
            label, tcls = _tier_label(off.get("tier"))
            badges = f'<span class="tier {tcls}">{esc(label)}</span>'
            if off.get("is_default"):
                badges += (' <span class="tier tier-default">APP DEFAULT</span>'
                           ' <span class="small muted">App default — the champion.</span>')
            pot_id = str(off.get("pot_id") or "")
            if pot_id and pot_id in active_ids:
                badges += ' <span class="status running">ACTIVE POT</span>'
            name = str(off.get("name") or pot_id or "Unnamed strategy")
            finals = off.get("finals_text")
            finals_html = esc(str(finals)) if finals not in (None, "") else "Not published yet"
            warning = off.get("warning")
            warn_html = ""
            if off.get("floor_free"):
                # Floor-free: the warning gets the red banner treatment,
                # the same visual language as the live-mode banner.
                wtxt = str(warning) if warning else (
                    "NO PROTECTION FLOOR — this offering runs without the usual "
                    "-15% floor. Losses are not stopped at the floor; the balance "
                    "can fall further than a floored pot's can.")
                warn_html = (f'<div class="floor-free-banner" role="alert">'
                             f'<span class="tag">WARNING — NO FLOOR</span> {esc(wtxt)}</div>')
            elif warning:
                warn_html = (f'<div class="alert warn"><span class="tag">WARNING</span>'
                             f'{esc(str(warning))}</div>')
            note = off.get("note")
            note_html = f'<p class="offering-note">{esc(str(note))}</p>' if note else ""
            fence = off.get("fence")
            fence_html = (f'<p class="fact"><span class="l">The fence — read before you select</span><br>'
                          f'{esc(str(fence))}</p>') if fence else ""
            # All facts come BEFORE the select control, per Terry's spec.
            cards.append(f"""<article class="offering-card">
              <div class="feed-top">{badges}</div>
              <h3>{esc(name)}</h3>
              <p class="fact"><span class="l">Published finals</span><br>{finals_html}</p>
              <p class="fact"><span class="l">Worst fall</span><br>{esc(_worst_fall_text(off.get('worst_fall')))}</p>
              {fence_html}{warn_html}{note_html}
              <form method="post" action="/picker/select">{csrf_field()}
                <input type="hidden" name="pot_id" value="{esc(pot_id)}">
                <input type="hidden" name="bucket" value="{esc(bucket)}">
                <button class="btn" type="submit">Select — start this as its own $100 pot</button>
              </form></article>""")
        if not cards:
            cards = ['<p class="muted">No offerings are available for this horizon yet.</p>']
        bucket_note_html = (f'<p class="offering-note" style="margin-bottom:12px">{esc(str(bucket_note))}</p>'
                            if bucket_note else "")
        sections.append(f"""<section class="card bucket" aria-label="Horizon: {esc(bucket)}">
          <div class="card-h"><h2>{esc(bucket)}</h2></div>
          <div class="card-b">{bucket_note_html}<div class="offering-grid">{''.join(cards)}</div></div></section>""")
    return render("picker.html", st, "/picker", PICKER_SECTIONS="".join(sections),
                  ALERTS=alerts_html(st))

def _activate_pot(pot_id, offering_name=None):
    """Create (or load, if it already exists) the separate $100 pot for
    an offering, reusing the pots machinery (pots/definitions.build_pot,
    which never silently resets an existing pot). Returns (ok, msg);
    never raises."""
    try:
        from pots import definitions as _defs
        defn = _defs.BY_ID.get(pot_id)
        if defn is None:
            defn = _defs.PotDefinition(
                pot_id, offering_name or pot_id, "candidate",
                description="Started from the Horizon Picker as its own $100 pot.")
        _defs.build_pot(defn, state_dir=STATE_DIR)
        return True, (f"Pot started: {offering_name or pot_id} is now its own separate "
                      f"$100 pot. Pots are never blended.")
    except Exception as e:
        return False, (f"That pot could not be started ({type(e).__name__}). "
                       f"Nothing was changed.")

# ----------------------------------------------------------------------------
# W5-C: first-run setup page
# ----------------------------------------------------------------------------
def page_setup(st, error=""):
    err = ""
    if error:
        err = (f'<div class="alerts"><div class="alert warn"><span class="tag">SETUP</span>'
               f'{esc(error)}</div></div>')
    return render("setup.html", st, "/setup", SETUP_ERROR=err, CSRF_FIELD=csrf_field())

def _save_setup_credentials(name, password):
    """Persist name + salted PBKDF2 hash to config.local.json, preserving
    every other config key. Returns (ok, message). The plaintext
    password is never written anywhere."""
    if _auth is None:
        return False, "Password hashing is unavailable, so setup cannot continue."
    if _tmode is not None:
        try:
            problem = _tmode.config_problem()
        except Exception:
            problem = None
        if problem is not None:
            return False, (f"Setup was NOT saved: {problem} The config file was "
                           f"left untouched.")
    cfg = _load_cfg()
    salt_b64, hash_b64 = _auth.hash_password(password)
    cfg["dashboard_owner_name"] = name
    cfg["dashboard_password_salt"] = salt_b64
    cfg["dashboard_password_hash"] = hash_b64
    cfg["dashboard_auth_enabled"] = True
    try:
        if _tmode is not None and hasattr(_tmode, "_save_config"):
            _tmode._save_config(cfg)
        else:
            _auth.store_credentials(CONFIG_LOCAL_PATH, name, password,
                                    base_config=_load_cfg())
    except Exception as e:
        return False, f"Setup was NOT saved ({type(e).__name__}). Nothing was changed."
    return True, "Setup complete."

def _panic_stop_block(st):
    tr = st.get("trading") or {}
    if tr.get("stopped"):
        return f"""<p><strong>Engine is STOPPED.</strong></p>
        <form method="post" action="/mode/resume" style="margin-top:10px">{csrf_field()}
          <button class="resume-btn" type="submit">Resume engine</button></form>"""
    return f"""<form method="post" action="/mode/stop-all">{csrf_field()}
      <button class="stop-btn" type="submit">STOP ALL</button></form>"""

def page_panic(st, verify_results=""):
    return render("panic.html", st, "/panic", ALERTS=alerts_html(st),
                  STOP_BLOCK=_panic_stop_block(st), CSRF_FIELD=csrf_field(),
                  VERIFY_RESULTS=verify_results)

def _panic_verify_results():
    """Per-account reachability with dummy-or-real keys. Never raises,
    never surfaces a secret or a raw traceback (Phase A, C1 step 4)."""
    rows = []
    try:
        cfg = _load_cfg()
        from data import alpaca as _alpaca
        from data import mode as _m
        for label, pair_fn in (("paper", _m.paper_keys), ("live", _m.live_keys)):
            kid, sec = pair_fn(cfg)
            if not kid or not sec:
                rows.append(f"<p><strong>{label.capitalize()} account:</strong> not set</p>")
                continue
            try:
                client = _alpaca.AlpacaClient(label, kid, sec)
                client.account()
                rows.append(f"<p><strong>{label.capitalize()} account:</strong> "
                            f"reachable \u2014 new keys work</p>")
            except Exception as e:
                summary = _scrub_exc(e)[:200]
                rows.append(f"<p><strong>{label.capitalize()} account:</strong> "
                            f"refused or unreachable ({esc(summary)})</p>")
    except Exception as e:
        summary = _scrub_exc(e)[:200]
        rows = [f"<p>Verification could not run: refused or unreachable ({esc(summary)})</p>"]
    return "".join(rows)

def _error_page():
    """F11: fixed generic text -- exception detail (which can carry
    absolute filesystem paths) goes to the server console only."""
    return ("<h1>Dashboard error</h1><p>Something went wrong rendering this "
            "page. The detail was logged on the server console.</p>")

# ----------------------------------------------------------------------------
# HTTP handler
# ----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "AtlasGateDashboard/1.0"
    sys_version = ""  # R2-N8: do not advertise the Python version

    def log_message(self, fmt, *args):
        pass  # quiet console

    def _host_ok(self):
        """R2-N2 + Phase A (E4): only allowlisted Host names are served."""
        host = (self.headers.get("Host") or "").strip()
        if host.startswith("["):
            name = host[1:].split("]", 1)[0]
        else:
            name = host.rsplit(":", 1)[0] if ":" in host else host
        return name.lower() in _allowed_hosts()

    def _ensure_session(self):
        """Phase A (E3): anonymous session on first response; the
        session (and its CSRF token) lives server-side, keyed by the
        ag_session cookie."""
        sid = None
        cookie = self.headers.get("Cookie") or ""
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("ag_session="):
                sid = part[len("ag_session="):].strip()
                break
        with _SESSIONS_LOCK:
            sess = _SESSIONS.get(sid) if sid else None
        if sess is None:
            sid, sess = _new_session()
            _LOCAL.needs_cookie = True
        else:
            _LOCAL.needs_cookie = False
        _LOCAL.sid = sid
        _LOCAL.session = sess
        return sess

    def _rotate_session(self):
        """Fixation defence (E2): a login gets a brand-new session id
        (and CSRF token); the old id is dead."""
        old = getattr(_LOCAL, "sid", None)
        sid, sess = _new_session()
        sess["authenticated"] = True
        if old:
            with _SESSIONS_LOCK:
                _SESSIONS.pop(old, None)
        _LOCAL.sid, _LOCAL.session = sid, sess
        _LOCAL.needs_cookie = True

    def _cookie_headers(self):
        if getattr(_LOCAL, "needs_cookie", False):
            self.send_header("Set-Cookie", _session_cookie_header(_LOCAL.sid))
            _LOCAL.needs_cookie = False

    def _refuse_host(self):
        self.close_connection = True
        self._send("<h1>Forbidden</h1><p>This dashboard only serves "
                   "requests addressed to localhost.</p>", code=403)

    def _send(self, html, code=200):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cookie_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if not self._host_ok():
                self._refuse_host()
                return
            self._ensure_session()
            u = urlparse(self.path)
            # W5-C: first-run setup routing. /setup is reachable ONLY
            # while no credentials exist; once set it is a plain 404.
            if u.path == "/setup":
                st0 = load_state(); st0["trading"] = trading_status()
                if _credentials_exist():
                    self._send(page_not_found(st0), code=404)
                    return
                self._send(page_setup(st0))
                return
            # W5-C: a pristine install (no config file, no credentials)
            # presents the setup page before anything else.
            if _first_run_unconfigured() and u.path != "/favicon.ico":
                if u.path == "/api/state":
                    body = json.dumps({"error": "setup required"}).encode("utf-8")
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self._cookie_headers()
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self._redirect("/setup")
                return
            # Phase A (E2): authentication gate.
            if _auth_required() and not _is_authenticated() \
                    and u.path not in ("/login", "/favicon.ico"):
                if u.path == "/api/state":
                    body = json.dumps({"error": "authentication required"}).encode("utf-8")
                    self.send_response(401)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self._cookie_headers()
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self._redirect("/login")
                return
            q = parse_qs(u.query, keep_blank_values=True)
            st = load_state()
            st["trading"] = trading_status()
            if u.path != "/mode" and "flash" in q:
                # R2-N8: consume the one-time flash on any landing page.
                msg, kind = _flash_take(q["flash"][0])
                if msg:
                    clsname = "warn" if kind == "warn" else "notice"
                    st["flash_html"] = (
                        f'<div class="alert {clsname}">{esc(msg)}</div>')
            if u.path in ("/", "/index.html"):
                self._send(page_overview(st))
            elif u.path == "/pot":
                if "id" in q:
                    pid = q["id"][0]
                    if not any(p["id"] == pid for p in st["pots"]):
                        self._send(page_not_found(st, "pot"), code=404)  # F9
                        return
                    self._send(page_pot(st, pid))
                else:
                    self._send(page_pot(st, ""))
            elif u.path == "/watcher":
                self._send(page_watcher(st))
            elif u.path == "/reports":
                self._send(page_reports(st, load_reports()))
            elif u.path == "/report":
                reports = load_reports()
                if "id" in q:
                    rid = q["id"][0]
                    if not any(r["id"] == rid for r in reports):
                        self._send(page_not_found(st, "report"), code=404)  # F9
                        return
                    self._send(page_report_detail(st, reports, rid))
                else:
                    self._send(page_report_detail(st, reports, ""))
            elif u.path == "/picker":
                self._send(page_picker(st))
            elif u.path == "/login":
                if not _credentials_exist():
                    # W5-C: no login exists yet -- entry starts at setup.
                    self._redirect("/setup")
                    return
                if not _auth_required() or _is_authenticated():
                    self._redirect("/")
                    return
                self._send(page_login(st))
            elif u.path == "/panic":
                self._send(page_panic(st))
            elif u.path == "/mode":
                self._send(page_mode(st, (q.get("flash") or [""])[0]))
            elif u.path == "/api/state":
                payload = {"mode": st["mode"], "total_balance": st["total_balance"],
                           "trading_mode": st["trading"]["effective_mode"],
                           "engine_stopped": st["trading"]["stopped"],
                           "pots": [{k: p[k] for k in ("id", "name", "status", "balance",
                                     "total_pct", "day_pct", "vs_spy_pct")} for p in st["pots"]],
                           "spy_final": st["spy_final"]}
                # R2-N3: allow_nan=False -- the API must always emit
                # spec-valid JSON (state numbers are finite-checked at
                # load; this is the belt-and-braces guarantee).
                body = json.dumps(payload, indent=2,
                                  allow_nan=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif u.path == "/favicon.ico":
                self.send_response(204); self.end_headers()
            else:
                self._send(page_not_found(st), code=404)
        except Exception as e:  # F11: detail to console, generic page to client
            print(f"dashboard error (GET {getattr(self, 'path', '?')}): {_scrub_exc(e)}",
                  file=sys.stderr, flush=True)
            try:
                self._send(_error_page(), code=500)
            except Exception:
                pass

    def _redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self._cookie_headers()
        self.end_headers()

    def _origin_ok(self):
        """F2: if the browser sent an Origin (or, failing that, a Referer),
        its host must be this dashboard's own Host. Non-browser clients
        send neither and are still held to the CSRF token check."""
        host = self.headers.get("Host") or ""
        for hdr in ("Origin", "Referer"):
            v = self.headers.get(hdr)
            if v:
                return urlparse(v).netloc == host
        return True

    def _run_mode_action(self, path, field):
        """Run one mode action under the dashboard lock (F4), retrying a
        transient write error and treating an already-applied end state
        as success, so duplicate POSTs are idempotent and never 500
        from this layer."""
        def attempt():
            if path == "/mode/enable-live":
                return _tmode.enable_live(field("phrase"))
            if path == "/mode/disable-live":
                return _tmode.disable_live()
            if path == "/mode/stop-all":
                _tmode.set_stopped(True)
                return True, ("Engine stopped. No orders will be placed in any mode. "
                              "Nothing was sold -- positions stay in your broker account "
                              "for you to manage.")
            _tmode.set_stopped(False)
            return True, "Engine resumed. Order placement is re-enabled for the current mode."

        def already_applied():
            try:
                s = _tmode.mode_status()
            except Exception:
                return False
            if path == "/mode/stop-all":
                return bool(s.get("stopped"))
            if path == "/mode/resume":
                return not s.get("stopped")
            if path == "/mode/disable-live":
                return s.get("configured_mode") == "paper"
            if path == "/mode/enable-live":
                return s.get("configured_mode") == "live"
            return False

        with _MODE_LOCK:
            last = None
            for i in range(3):
                try:
                    return attempt()
                except (FileNotFoundError, OSError) as e:
                    last = e
                    if already_applied():
                        return True, "Already applied — the requested state is already in effect."
                    time.sleep(0.05 * (i + 1))
            raise last

    def do_POST(self):
        """Trading-mode actions. Every refusal leaves the app in PAPER."""
        try:
            if not self._host_ok():
                self._refuse_host()
                return
            self._ensure_session()
            u = urlparse(self.path)
            if u.path not in ("/mode/enable-live", "/mode/disable-live",
                              "/mode/stop-all", "/mode/resume",
                              "/login", "/logout", "/panic/verify",
                              "/setup", "/picker/select"):
                st = load_state()
                st["trading"] = trading_status()
                self._send(page_not_found(st), code=404)
                return
            # W5-C: on a pristine install, setup is the only POST that
            # can change anything.
            if u.path != "/setup" and _first_run_unconfigured():
                self._redirect("/setup")
                return
            # Phase A (E2): unauthenticated POSTs (except /login and the
            # first-run /setup itself) change nothing.
            if u.path not in ("/login", "/setup") and _auth_required() \
                    and not _is_authenticated():
                self._redirect("/login")
                return
            # F2: cross-origin form posts cannot change mode or engine state.
            if not self._origin_ok():
                self.close_connection = True  # body unread; do not reuse socket
                self._send("<h1>Forbidden</h1><p>Cross-origin requests cannot "
                           "change trading mode or engine state.</p>", code=403)
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                self._send("<h1>Bad request</h1><p>Invalid Content-Length.</p>", code=400)
                return
            if length < 0 or length > 16_000_000:
                self.close_connection = True
                self._send("<h1>Bad request</h1><p>Request body too large.</p>", code=413)
                return
            if length > MAX_POST_BODY:
                # Drain (bounded, in chunks, never buffered whole) so the
                # client finishes its send cleanly, then refuse.
                left = length
                while left > 0:
                    chunk = self.rfile.read(min(left, 65536))
                    if not chunk:
                        break
                    left -= len(chunk)
                self._send("<h1>Bad request</h1><p>Request body too large.</p>", code=413)
                return
            raw = self.rfile.read(length).decode("utf-8", "replace") if length else ""
            form = parse_qs(raw, keep_blank_values=True)

            def field(name):
                return (form.get(name) or [""])[0]

            # Phase A (E3): per-SESSION CSRF token, required on every
            # state-changing POST, compared in constant time.
            if not hmac.compare_digest(field("csrf_token"), _current_csrf()):
                self._send("<h1>Forbidden</h1><p>Missing or invalid form token. "
                           "Reload the page and use the form on it.</p>", code=403)
                return
            if u.path == "/setup":
                # W5-C: setup closes permanently once credentials exist.
                st = load_state(); st["trading"] = trading_status()
                if _credentials_exist():
                    self._send(page_not_found(st), code=404)
                    return
                name = field("owner_name").strip()
                pw = field("password")
                pw2 = field("password_confirm")
                problem = None
                if not name or len(name) > 80:
                    problem = "Please enter your name (up to 80 characters)."
                elif len(pw) < 8:
                    problem = "Please choose a password of at least 8 characters."
                elif pw != pw2:
                    problem = "The two passwords did not match. Nothing was saved."
                if problem is not None:
                    self._send(page_setup(st, problem), code=400)
                    return
                ok, msg = _save_setup_credentials(name, pw)
                if not ok:
                    self._send(page_setup(st, msg), code=400)
                    return
                _login_record_success()
                self._rotate_session()
                self._redirect("/")
                return
            if u.path == "/picker/select":
                # W5-A: activate/create the offering's own $100 pot.
                pot_id = field("pot_id")
                _, offs = _picker_data()
                offering_name = None
                for info in offs.values():
                    lst = info.get("offerings") if isinstance(info, dict) else info
                    for off in lst or []:
                        if str(off.get("pot_id") or "") == pot_id:
                            offering_name = off.get("name")
                            break
                ok, msg = _activate_pot(pot_id, offering_name)
                fid = _flash_put(msg, "ok" if ok else "warn")
                self._redirect(f"/picker?flash={fid}")
                return
            if u.path == "/login":
                if _login_locked():
                    self._send("<h1>Too many attempts</h1><p>Too many failed login "
                               "attempts. Logins are refused for 5 minutes.</p>", code=429)
                    return
                cfg = _load_cfg()
                ok = False
                if _auth is not None and cfg.get("dashboard_password_hash"):
                    ok = _auth.verify_password(field("password"),
                                               cfg.get("dashboard_password_salt") or "",
                                               cfg.get("dashboard_password_hash") or "")
                if not ok:
                    _login_record_failure()
                    if _login_locked():
                        self._send("<h1>Too many attempts</h1><p>Too many failed login "
                                   "attempts. Logins are refused for 5 minutes.</p>", code=429)
                        return
                    st = load_state(); st["trading"] = trading_status()
                    self._send(page_login(st, "Incorrect password."), code=401)
                    return
                _login_record_success()
                self._rotate_session()
                self._redirect("/")
                return
            if u.path == "/logout":
                if getattr(_LOCAL, "session", None) is not None:
                    _LOCAL.session["authenticated"] = False
                self._redirect("/login" if _auth_required() else "/")
                return
            if u.path == "/panic/verify":
                st = load_state(); st["trading"] = trading_status()
                self._send(page_panic(st, _panic_verify_results()))
                return
            if _tmode is None:
                ok, msg = False, ("Trading-mode module unavailable -- nothing "
                                  "changed; the app stays in PAPER.")
            else:
                ok, msg = self._run_mode_action(u.path, field)
            target = "/mode"
            if u.path in ("/mode/stop-all", "/mode/resume"):
                ref = urlparse(self.headers.get("Referer") or "")
                # F14: redirect target whitelisted to known page paths.
                if ref.path in KNOWN_PAGE_PATHS:
                    target = ref.path
            fid = _flash_put(msg, "ok" if ok else "warn")
            self._redirect(f"{target}?flash={fid}")
        except Exception as e:
            print(f"dashboard error (POST {getattr(self, 'path', '?')}): {_scrub_exc(e)}",
                  file=sys.stderr, flush=True)
            try:
                self._send(_error_page(), code=500)
            except Exception:
                pass

def main():
    if PORT is None:
        # R2-N7: one clean line for a bad DASHBOARD_PORT, no traceback.
        print("Dashboard could not start: DASHBOARD_PORT must be a whole "
              "number between 1 and 65535.", file=sys.stderr, flush=True)
        return 2
    # Phase A (E1): bind from config; non-loopback needs the explicit
    # opt-in AND a dashboard password, else one clean refusal line.
    global EFFECTIVE_BIND
    bind, refusal = resolve_bind()
    if refusal is not None:
        print(refusal, file=sys.stderr, flush=True)
        return 2
    EFFECTIVE_BIND = bind
    try:
        srv = ThreadingHTTPServer((bind, PORT), Handler)
    except (OSError, OverflowError) as e:
        # F13: one clean line, no traceback (e.g. a double-clicked run.py).
        print(f"Dashboard could not start: port {PORT} is unavailable "
              f"({e.strerror or e}). Is another copy already running?",
              file=sys.stderr, flush=True)
        return 1
    print(f"Atlas Gate dashboard running at http://localhost:{PORT}  (Ctrl+C to stop)", flush=True)
    if not _is_loopback_bind(bind):
        print(f"WARNING: {EXPOSURE_BANNER}", file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
