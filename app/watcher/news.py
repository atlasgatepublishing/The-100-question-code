"""News Brain — risk-gate DISPLAY only.

Design authority: DESIGN.md, "News brain (veto/risk gate and slow signal,
NOT a race trigger)".

This module classifies headlines / 8-K item codes into severity flags
attached to holdings and returns display records plus *suggested* gate
annotations (e.g. "pause new buys suggested"). It executes NOTHING: no
imports from trading/pot/broker code, no order functions. A human or a
tested strategy module decides what, if anything, to do with a flag.

8-K item codes used (deterministic rules first, per DESIGN.md):
  5.02 officer/director departure  -> high
  1.03 bankruptcy                  -> critical
  4.02 restatement (non-reliance)  -> critical
  4.01 auditor change              -> high
  2.02 earnings results            -> info / earnings-window note
Keyword rules cover RSS headlines for the same event families.
Offline fallback: bundled ``sample_news.json``, labelled SAMPLE.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Iterable

ITEM_RULES: dict[str, tuple[str, str, str]] = {
    # code: (event, severity, suggested gate annotation)
    "5.02": ("Officer/director departure", "high", "pause new buys suggested"),
    "1.03": ("Bankruptcy", "critical", "pause new buys suggested; review holding urgently"),
    "4.02": ("Financial restatement / non-reliance", "critical", "pause new buys suggested; review holding urgently"),
    "4.01": ("Auditor change", "high", "pause new buys suggested"),
    "2.02": ("Earnings results", "info", "earnings window — no tight stops; blackout rules apply"),
}
KEYWORD_RULES: list[tuple[tuple[str, ...], str, str, str]] = [
    (("bankrupt", "chapter 11"), "Bankruptcy", "critical", "pause new buys suggested; review holding urgently"),
    (("restat", "non-reliance", "cannot be relied"), "Restatement", "critical", "pause new buys suggested; review holding urgently"),
    (("auditor resign", "auditor change", "dismissed its auditor"), "Auditor change", "high", "pause new buys suggested"),
    (("ceo resign", "cfo resign", "chief executive depart", "steps down"), "Executive departure", "high", "pause new buys suggested"),
    (("sec investigation", "fraud", "delist"), "Regulatory/legal risk", "high", "pause new buys suggested"),
    (("earnings", "quarterly results", "revenue"), "Earnings", "info", "earnings window — blackout rules apply"),
]
SEVERITY_ORDER = {"info": 0, "medium": 1, "high": 2, "critical": 3}


class NewsFeedError(ValueError):
    """A news feed is present but the wrong shape / unparseable (QA M-8)."""


@dataclass
class NewsFlag:
    symbol: str
    date: str
    headline: str
    event: str
    severity: str                    # info | medium | high | critical
    gate_annotation: str             # suggestion for display, never an action
    item_codes: list[str] = field(default_factory=list)
    source: str = "EDGAR 8-K / RSS"
    sample: bool = False
    display_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify(symbol: str, headline: str, item_codes: Iterable[str] | str | None = (),
             on_date: str = "", source: str = "EDGAR 8-K / RSS",
             sample: bool = False) -> NewsFlag:
    # QA M-10: a bare string is ONE code, not an iterable of characters;
    # None means "no codes"; a None headline/symbol degrades to "".
    if item_codes is None:
        codes: list[str] = []
    elif isinstance(item_codes, str):
        codes = [item_codes.strip()] if item_codes.strip() else []
    else:
        codes = [str(c).strip() for c in item_codes if c is not None]
    headline = "" if headline is None else str(headline)
    symbol = "" if symbol is None else str(symbol)
    best: tuple[str, str, str] | None = None
    for code in codes:
        if code in ITEM_RULES and (best is None or SEVERITY_ORDER[ITEM_RULES[code][1]] > SEVERITY_ORDER[best[1]]):
            best = ITEM_RULES[code]
    low = headline.lower()
    for words, event, sev, gate in KEYWORD_RULES:
        if any(w in low for w in words) and (best is None or SEVERITY_ORDER[sev] > SEVERITY_ORDER[best[1]]):
            best = (event, sev, gate)
    if best is None:
        best = ("General news", "info", "no gate suggested — display only")
    event, severity, gate = best
    if sample:
        headline = headline if "SAMPLE" in headline else headline + " [SAMPLE]"
    return NewsFlag(symbol=symbol.upper(), date=on_date or date.today().isoformat(),
                    headline=headline, event=event, severity=severity,
                    gate_annotation=gate, item_codes=codes, source="SAMPLE" if sample else source,
                    sample=sample)


def load_sample_news(path: str | Path | None = None) -> list[NewsFlag]:
    p = Path(path) if path else Path(__file__).with_name("sample_news.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise NewsFeedError(f"{p}: invalid JSON ({e})") from e
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise NewsFeedError(f"{p}: news feed must be an object with a 'records' list")
    # R2-L5: non-object rows are dropped AND counted (the watcher feed
    # already accounted for its drops; the news feed silently ate them).
    kept, dropped = [], 0
    for d in data["records"]:
        if isinstance(d, dict):
            kept.append(d)
        else:
            dropped += 1
    load_sample_news.last_dropped = dropped  # type: ignore[attr-defined]
    return [classify(d.get("symbol", ""), d.get("headline", ""), d.get("item_codes", []),
                     d.get("date", ""), sample=True)
            for d in kept]


load_sample_news.last_dropped = 0  # type: ignore[attr-defined]


def fetch_rss_headlines(feed_urls: Iterable[str], timeout: int = 15) -> list[dict[str, str]]:
    """Minimal free-RSS reader (stdlib XML). Returns [] on any failure."""
    import urllib.request
    import xml.etree.ElementTree as ET
    out: list[dict[str, str]] = []
    for url in feed_urls:
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "TerryStockApp/1.0"}), timeout=timeout).read()
            for item in ET.fromstring(raw).iter("item"):
                out.append({"headline": (item.findtext("title") or "").strip(),
                            "date": (item.findtext("pubDate") or "")[:10], "source": url})
        except Exception:
            continue
    return out


def flags_for_holdings(flags: list[NewsFlag], symbols: Iterable[str]) -> list[NewsFlag]:
    wanted = {s.upper() for s in symbols}
    return sorted([f for f in flags if f.symbol in wanted],
                  key=lambda f: SEVERITY_ORDER[f.severity], reverse=True)


def get_news_flags(online_feeds: Iterable[str] | None = None) -> dict[str, Any]:
    """Dashboard entry point. Sample fallback keeps the UI honest offline."""
    flags: list[NewsFlag] = []
    if online_feeds:
        for h in fetch_rss_headlines(online_feeds):
            flags.append(classify("", h["headline"], (), h["date"], h["source"]))
    mode = "live-rss" if flags else "sample"
    if not flags:
        flags = load_sample_news()
    return {"mode": mode, "label": "SAMPLE" if mode == "sample" else "LIVE",
            "generated": date.today().isoformat(), "display_only": True,
            "disclaimer": ("News flags are a risk gate / display only — they never execute anything. "
                           "Free feeds arrive after the first price jump; no non-public information, ever."),
            "flags": [f.to_dict() for f in flags]}


if __name__ == "__main__":
    feed = get_news_flags()
    print(f"mode={feed['mode']} label={feed['label']} flags={len(feed['flags'])}")
    for f in feed["flags"]:
        print(f"- [{f['severity']}] {f['symbol']} {f['event']} :: {f['gate_annotation']}")
