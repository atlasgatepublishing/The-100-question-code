"""Smart Money Watcher — RADAR / DISPLAY ONLY.

Design authority: ~/workspace/stock-app/DESIGN.md, "Smart money watcher"
and "Watcher scope: everyone who files".

STRUCTURAL SAFETY CONTRACT
--------------------------
This module CANNOT originate a trade:
  * It exposes only read / flag / display functions.
  * It imports NOTHING from any trading, pot, broker, or execution code.
    (Only the Python standard library, plus ``requests`` for EDGAR reads.)
  * Its return values are plain display dicts with a ``display_only: True``
    marker and a human-readable ``flag`` / ``reason``. There is no order,
    buy, sell, execute, or submit function in this module — by design.
A strategy may *look* at these records (radar), per DESIGN.md, but any
decision to trade lives in tested strategy code elsewhere, never here.

Feeds (all free)
----------------
* Form 4 insider transactions — EDGAR full-text / submissions (2 business
  days; fastest disclosure). Open-market purchases weighted highest,
  cluster buying and CEO/CFO buys boosted, 10b5-1 plan sales discounted.
* Schedule 13D (activist, 5 business days — an event signal) / 13G (passive).
* Form 13F — quarterly, due 45 days after quarter end, so 45–135 days
  stale when seen. CONTEXT ONLY, always labelled with its staleness.
* Congressional STOCK Act trades — free public datasets (House/Senate
  Stock Watcher style). SLOW CONFIRMATION ONLY: 30–45 day lag, amounts
  are ranges only, never exact dollars.

Offline / replay mode: ``load_sample_feed()`` reads the bundled
``sample_feed.json``; every record from it is labelled ``SAMPLE``.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable


class WatcherFeedError(ValueError):
    """A watcher feed is present but the wrong shape / unparseable.

    QA M-8: a corrupt feed must be distinguishable from an empty feed —
    callers get this typed error, never an AttributeError and never a
    silent ``[]`` for a present-but-wrong ``records`` key.
    """

# NOTE: deliberately no imports from pots / broker / strategies / execution.

PRIORITY_SYMBOLS: dict[str, str] = {
    "NVDA": "Nvidia", "MSFT": "Microsoft", "AAPL": "Apple", "META": "Meta",
    "AMZN": "Amazon", "GOOGL": "Alphabet", "TSLA": "Tesla",
}
PRIORITY_ROLES = ("CEO", "CFO", "Founder", "Director", "Chief Executive", "Chief Financial")

EDGAR_HEADERS = {"User-Agent": "TerryStockApp/1.0 (personal research; watcher display only)"}


@dataclass
class WatcherRecord:
    """One display record. ``display_only`` is always True."""
    feed: str                      # form4 | schedule13d | schedule13g | form13f | congress
    symbol: str
    filer_name: str
    filer_role: str
    transaction_date: str
    filed_date: str
    transaction_type: str          # open_market_purchase | sale | stake_disclosed | ...
    shares: float | None = None
    price: float | None = None
    value: float | None = None
    amount_range: str | None = None        # congress only, e.g. "$15,001-$50,000"
    is_10b5_1: bool = False
    priority: bool = False
    score: float = 0.0                     # radar weight, NOT a trade signal
    flag: str = "info"                     # info | notable | priority | context | slow_confirmation
    reason: str = ""
    staleness_note: str = ""
    source: str = "SEC EDGAR"
    sample: bool = False
    display_only: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------- scoring
def score_form4(rec: WatcherRecord, cluster_size: int = 1) -> WatcherRecord:
    """Weight a Form 4 record the way DESIGN.md prescribes."""
    score, reasons = 0.0, []
    t = rec.transaction_type.lower()
    if "purchase" in t or t in ("buy", "open_market_purchase"):
        score += 3.0; reasons.append("open-market purchase (insider's own money)")
        if any(k in rec.filer_role.upper() for k in ("CEO", "CFO", "CHIEF EXECUTIVE", "CHIEF FINANCIAL")):
            score += 2.0; reasons.append("CEO/CFO buyer")
        if cluster_size >= 3:
            score += 3.0; reasons.append(f"cluster buying: {cluster_size} insiders")
        elif cluster_size == 2:
            score += 1.5; reasons.append("cluster buying: 2 insiders")
    elif "sale" in t or t == "sell":
        score += 0.5; reasons.append("insider sale (low weight — many innocent reasons)")
        if rec.is_10b5_1:
            score -= 0.5; reasons.append("10b5-1 pre-arranged plan sale — discounted")
    else:
        reasons.append("non-open-market transaction (grant/exercise/other) — low weight")
    if rec.is_10b5_1 and "purchase" not in t:
        rec.reason = "; ".join(reasons)
    rec.score = round(max(score, 0.0), 2)
    rec.reason = "; ".join(reasons) or rec.reason
    rec.staleness_note = "Form 4: filed within 2 business days — fastest public disclosure."
    return rec


def _norm_text(s: str) -> str:
    """Whitespace-collapsed, case-folded text for identity comparisons."""
    return " ".join(str(s or "").split()).casefold()


def _canon_date(s: str) -> str:
    """Canonical YYYY-MM-DD for a date string ('2026-11-18T00:00:00' and
    '2026-11-18' are the same filing date); unparseable values pass
    through normalised so they still key consistently."""
    t = str(s or "").strip()
    try:
        return date.fromisoformat(t[:10]).isoformat()
    except ValueError:
        return _norm_text(t)


def _dedupe_key(r: WatcherRecord) -> tuple:
    """Identity of a filing for de-duplication (QA H-2, R2-H1/R2-M7):
    same feed, filer, form/transaction type, security, date and
    share/amount identity = the same filing re-delivered, not a second
    filing. R2: the key is NORMALISED — EDGAR re-deliveries with
    'Insider A ' / 'insider a' formatting, or an ISO-timestamp date,
    are the same filing, not new insiders."""
    return (r.feed.strip().lower(), r.symbol.upper(), _norm_text(r.filer_name),
            _norm_text(r.transaction_type), _canon_date(r.transaction_date),
            r.shares, r.price, r.amount_range)


def dedupe(records: list[WatcherRecord]) -> list[WatcherRecord]:
    """Drop exact re-deliveries, keeping the first copy. QA H-2: without
    this, one Form 4 delivered 3x fabricated a 3-insider cluster."""
    seen: set = set()
    out: list[WatcherRecord] = []
    for r in records:
        k = _dedupe_key(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


_SAMPLE_PREFIX = "[SAMPLE DATA — not a real filing] "
_PRIORITY_PREFIX_RE = None  # compiled lazily below (re imported here)
import re as _re
_PRIORITY_PREFIX_RE = _re.compile(
    r"^PRIORITY filer/symbol \([^)]*\): .*?major signal\. ")


def _future_dated(r: WatcherRecord) -> bool:
    """R2-L8: a transaction dated well in the future is not current
    radar (the loader tolerates +30 days for clock skew; scoring does
    not treat a filing dated weeks ahead as today's signal)."""
    try:
        d = date.fromisoformat(_canon_date(r.transaction_date))
    except ValueError:
        return False
    return d > date.today() + timedelta(days=7)


def annotate(records: list[WatcherRecord]) -> list[WatcherRecord]:
    """Apply priority flags, cluster detection, and per-feed labelling."""
    records = dedupe(records)
    # R2-H1/R2-M7: a cluster counts DISTINCT insiders (normalised filer
    # names), never raw records — re-deliveries and amended copies of
    # one filing cannot inflate it.
    cluster_filers: dict[tuple[str, str], set] = defaultdict(set)
    for r in records:
        if r.feed == "form4" and "purchase" in r.transaction_type.lower():
            cluster_filers[(r.symbol.upper(), _canon_date(r.transaction_date)[:7])].add(
                _norm_text(r.filer_name))
    clusters = {k: len(v) for k, v in cluster_filers.items()}
    for r in records:
        r.symbol = r.symbol.upper()
        # R2-L10: strip prefixes from a previous annotate() pass so
        # re-running annotate never stacks them.
        if r.reason.startswith(_SAMPLE_PREFIX):
            r.reason = r.reason[len(_SAMPLE_PREFIX):]
        r.reason = _PRIORITY_PREFIX_RE.sub("", r.reason)
        r.priority = r.symbol in PRIORITY_SYMBOLS and r.feed == "form4"
        if r.feed == "form4":
            score_form4(r, clusters.get((r.symbol, _canon_date(r.transaction_date)[:7]), 1))
            if _future_dated(r):
                r.score = 0.0
                r.reason = ("future-dated filing — not scored as current radar; " + r.reason)
        elif r.feed == "schedule13d":
            r.score, r.flag = 2.5, "notable"
            r.reason = "13D: 5%+ stake with activist intent — event signal (display only)"
            r.staleness_note = "13D due within 5 business days of crossing 5%."
        elif r.feed == "schedule13g":
            r.score, r.flag = 1.0, "info"
            r.reason = "13G: 5%+ passive stake — context only"
        elif r.feed == "form13f":
            r.score, r.flag = 0.5, "context"
            r.reason = "13F: long-term institutional context only — never a timing signal"
            r.staleness_note = ("13F is 45–135 days stale: quarterly, due 45 days after "
                                "quarter end; long-only snapshot, holder may already have sold.")
        elif r.feed == "congress":
            r.score, r.flag = 0.5, "slow_confirmation"
            r.reason = "STOCK Act trade: slow confirmation/context only — never a fast trigger"
            r.staleness_note = ("Congress: reported 30–45 days after the trade; "
                                "amounts are ranges only, not exact dollars.")
        if r.priority:
            r.flag = "priority"
            r.reason = (f"PRIORITY filer/symbol ({PRIORITY_SYMBOLS[r.symbol]}): Form 4 jumps the "
                        f"queue. Note: priority-list selling is usually 10b5-1 and means little; "
                        f"an open-market buy would be a major signal. " + r.reason)
        if r.sample:
            r.source = "SAMPLE"
            r.reason = "[SAMPLE DATA — not a real filing] " + r.reason
    return sorted(records, key=lambda x: (x.priority, x.score), reverse=True)


# ---------------------------------------------------------------- loading
def _s(v: Any, default: str = "") -> str:
    """String coercion that never turns None into the literal 'None' (QA M-9)."""
    return default if v is None else str(v)


def _num(v: Any, field_name: str) -> float | None:
    """Coerce a numeric field; raise ValueError on garbage/non-finite (QA M-9)."""
    if v is None:
        return None
    if isinstance(v, bool):
        raise ValueError(f"{field_name}={v!r} is not a number")
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name}={v!r} is not a number") from None
    if not math.isfinite(f):
        raise ValueError(f"{field_name}={v!r} is not finite")
    return f


def _valid_record_date(s: str) -> bool:
    """A filing date must be a real calendar date, not absurdly future (QA M-9)."""
    if not s:
        return True  # missing date: tolerated (sample/default records)
    try:
        d = date.fromisoformat(s[:10])
    except ValueError:
        return False
    return d <= date.today() + timedelta(days=30)


def _record_from_dict(d: dict[str, Any]) -> WatcherRecord:
    if not isinstance(d, dict):
        raise ValueError(f"record is not an object: {str(d)[:60]!r}")
    # Congress amount range (QA M-9): a missing upper bound renders as
    # "$15,001+" — never the impossible "$15,001-$0". Bounds are rounded,
    # not silently truncated.
    amt = None
    low = _num(d.get("amount_range_low"), "amount_range_low")
    if low is not None:
        high = _num(d.get("amount_range_high"), "amount_range_high")
        amt = (f"${int(round(low)):,}-${int(round(high)):,}" if high is not None
               else f"${int(round(low)):,}+")
    known = {f for f in WatcherRecord.__dataclass_fields__}  # type: ignore[attr-defined]
    extra = {k: v for k, v in d.items() if k not in known and k not in
             ("amount_range_low", "amount_range_high", "percent_of_class", "quarter_end", "intent")}
    rec = WatcherRecord(
        # R2-L4: feed strings are case-normalised at the boundary --
        # "FORM4"/"Form4" are Form 4, not an unknown feed scoring 0.
        feed=_s(d.get("feed"), "form4").strip().lower() or "form4",
        symbol=_s(d.get("symbol")).upper(),
        filer_name=_s(d.get("filer_name")), filer_role=_s(d.get("filer_role")),
        transaction_date=_s(d.get("transaction_date")), filed_date=_s(d.get("filed_date")),
        transaction_type=_s(d.get("transaction_type")),
        shares=_num(d.get("shares"), "shares"),
        price=_num(d.get("price"), "price"), value=_num(d.get("value"), "value"),
        amount_range=amt,
        is_10b5_1=bool(d.get("is_10b5_1", False)), sample=bool(d.get("sample", False))
        or _s(d.get("source")).upper() == "SAMPLE",
        source=_s(d.get("source"), "SEC EDGAR") or "SEC EDGAR", extra=extra)
    for field_name in ("transaction_date", "filed_date"):
        if not _valid_record_date(getattr(rec, field_name)):
            raise ValueError(f"{field_name}={getattr(rec, field_name)!r} is not a valid, sane date")
    return rec


def load_sample_feed(path: str | Path | None = None) -> list[WatcherRecord]:
    """Replay/no-network mode: bundled sample records, labelled SAMPLE.

    QA M-8/M-9: wrong-shape feeds raise :class:`WatcherFeedError`;
    individually invalid records are dropped and counted on
    ``load_sample_feed.last_dropped`` (surfaced by ``get_watcher_feed``).
    """
    p = Path(path) if path else Path(__file__).with_name("sample_feed.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise WatcherFeedError(f"{p}: invalid JSON ({e})") from e
    if not isinstance(data, dict):
        raise WatcherFeedError(f"{p}: feed must be a JSON object with a 'records' list, "
                               f"got {type(data).__name__}")
    if "records" not in data:
        raise WatcherFeedError(f"{p}: feed has no 'records' key — corrupt/wrong feed, "
                               "not an empty feed")
    raw_records = data["records"]
    if not isinstance(raw_records, list):
        raise WatcherFeedError(f"{p}: 'records' must be a list, got {type(raw_records).__name__}")
    records, dropped = [], 0
    for d in raw_records:
        try:
            records.append(_record_from_dict(d))
        except ValueError:
            dropped += 1
    load_sample_feed.last_dropped = dropped  # type: ignore[attr-defined]
    return annotate(records)


load_sample_feed.last_dropped = 0  # type: ignore[attr-defined]


def fetch_edgar_recent_form4(symbols: Iterable[str] | None = None, limit: int = 50) -> list[WatcherRecord]:
    """Best-effort live read of recent EDGAR filings (display only).

    Uses EDGAR's free browse JSON. Network/parse failures return [] so the
    caller can fall back to ``load_sample_feed()`` — never raises into the UI.
    Full Form 4 XML parsing (ownershipDocument) is the production path; this
    lightweight reader lists recent 4/13D/13G/13F filings per symbol.
    """
    try:
        import requests  # local import: module stays importable offline
    except ImportError:
        return []
    out: list[WatcherRecord] = []
    form_feed = {"4": "form4", "SC 13D": "schedule13d", "SC 13G": "schedule13g", "13F-HR": "form13f"}
    for sym in (list(symbols) if symbols else list(PRIORITY_SYMBOLS)):
        try:
            tickers = requests.get("https://www.sec.gov/files/company_tickers.json",
                                   headers=EDGAR_HEADERS, timeout=15).json()
            cik = next((v["cik_str"] for v in tickers.values() if v["ticker"] == sym.upper()), None)
            if cik is None:
                continue
            sub = requests.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json",
                               headers=EDGAR_HEADERS, timeout=15).json()
            recent = sub.get("filings", {}).get("recent", {})
            for i, form in enumerate(recent.get("form", [])[:200]):
                if form in form_feed and len(out) < limit:
                    out.append(WatcherRecord(
                        feed=form_feed[form], symbol=sym.upper(), filer_name=sub.get("name", sym),
                        filer_role="Filer (see filing)", transaction_date=recent["filingDate"][i],
                        filed_date=recent["filingDate"][i], transaction_type="filing_listed",
                        source="SEC EDGAR"))
        except Exception:
            continue
    return annotate(out)


def get_watcher_feed(online: bool = False, symbols: Iterable[str] | None = None) -> dict[str, Any]:
    """Single entry point for the dashboard. Display records only."""
    records = fetch_edgar_recent_form4(symbols) if online else []
    mode = "live-edgar"
    dropped = 0
    if not records:
        records, mode = load_sample_feed(), "sample"
        dropped = getattr(load_sample_feed, "last_dropped", 0)
    return {"mode": mode, "label": "SAMPLE" if mode == "sample" else "LIVE",
            "dropped_records": dropped,
            "generated": date.today().isoformat(), "display_only": True,
            "disclaimer": ("Radar only — the watcher never originates a trade. 13F is 45–135 days "
                           "stale; congressional data lags 30–45 days and shows amount ranges only. "
                           "Firms' live orders, shorts and strategies are NOT public."),
            "records": [r.to_dict() for r in records]}


def flags_for_holdings(records: list[WatcherRecord], symbols: Iterable[str]) -> list[WatcherRecord]:
    """Read-only filter: watcher records touching current holdings."""
    wanted = {s.upper() for s in symbols}
    return [r for r in records if r.symbol in wanted]


if __name__ == "__main__":
    feed = get_watcher_feed(online=False)
    print(f"mode={feed['mode']} label={feed['label']} records={len(feed['records'])}")
    for r in feed["records"]:
        print(f"- [{r['flag']}] {r['symbol']} {r['feed']} score={r['score']} :: {r['reason']}")
