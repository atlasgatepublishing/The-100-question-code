#!/usr/bin/env python3
"""Phase 2 (support script): classify scanned 8-K texts into buyback
AUTHORIZATION announcement events.

Rules frozen after calibration on Apple's filings (the pond's most
formulaic announcer). A filing is an EVENT if any window of +/-400 chars
around a 'repurchas*' mention matches a trigger pattern, subject to the
ASR-only and debt-tender guards. Every trigger emits its snippet for
manual audit; every 'authoriz*'-near-'repurchas*' window that does NOT
trigger is emitted as a near-miss for a recall audit."""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "buyback-events-data")
TEXTS = os.path.join(CACHE, "texts")

AMT = r"\$\s?[\d,.]+\s*(?:billion|million|bn|mm)"
TRIGGERS = [
    # "new $100 billion share repurchase authorization (announced)"
    ("T1_new_amt_auth", re.compile(
        r"new\s+(?:additional\s+)?" + AMT + r"\s+(?:share|stock|common\s+stock)\s+"
        r"(?:repurchase|buyback)\s+(?:authorization|program|plan)")),
    # "board has authorized an additional $75 billion for share repurchases"
    ("T2_board_auth", re.compile(
        r"(?:board|directors)[^.]{0,140}?(?:authoriz\w+|approv\w+|increas\w+)"
        r"[^.]{0,140}?repurchas")),
    # "authorized/announced ... $X ... repurchase" (tightened after the
    # MSFT calibration: bullet-form earnings text has no periods, so the
    # verb window is short and the RETURNED-GUARD below voids the match
    # when the amount is an activity report, not an authorization)
    ("T3_auth_amt", re.compile(
        r"(?:authoriz\w+|announc\w+|approv\w+|increas\w+)[^.]{0,80}?" + AMT +
        r"[^.]{0,60}?(?:repurchas|buyback)")),
    # "increased its share repurchase authorization to $210 billion"
    ("T4_increase_to", re.compile(
        r"increas\w+[^.]{0,90}?repurchase\s+(?:authorization|program)[^.]{0,60}?"
        r"(?:to|by)\s+" + AMT)),
    # "announced a new share repurchase program" / "authorized ... buyback program"
    ("T5_new_program", re.compile(
        r"(?:announc\w+|authoriz\w+|approv\w+)[^.]{0,80}?"
        r"(?:new\s+|additional\s+)?(?:share|stock)\s+(?:repurchase|buyback)\s+"
        r"(?:program|authorization|plan)")),
    # "repurchase program of up to $X billion"
    ("T6_program_of_amt", re.compile(
        r"(?:repurchase|buyback)\s+(?:program|authorization|plan)\s+of\s+"
        r"(?:up\s+to\s+)?" + AMT)),
    # "authorized the repurchase of up to $X / N million shares"
    ("T7_auth_rep_of", re.compile(
        r"authoriz\w+[^.]{0,110}?repurchas\w+\s+of\s+(?:up\s+to\s+)?(?:"
        + AMT + r"|[\d,.]+\s*(?:million|billion)\s+(?:shares|of\s+(?:its\s+)?"
        r"(?:common\s+)?(?:stock|shares)))")),
    # "additional $X billion share repurchase authorization"
    ("T8_additional_amt", re.compile(
        r"additional\s+" + AMT + r"\s+(?:share|stock)?\s*(?:repurchase|buyback)")),
    # "new share repurchase program/authorization" (no amount in window)
    ("T9_new_program_noamt", re.compile(
        r"new\s+(?:share|stock)\s+(?:repurchase|buyback)\s+"
        r"(?:program|authorization|plan)")),
]
AMT_RE = re.compile(AMT)
ASR_RE = re.compile(r"accelerated\s+share\s+repurchase")
# Activity-report guard: "returned $9.7 billion to shareholders in the form
# of share repurchases and dividends" reports PAST buyback activity; it is
# not an authorization. A T3 hit whose amount is the object of "returned"
# is void (other triggers in the same window are unaffected).
RETURNED_RE = re.compile(
    r"returned\s+(?:a\s+total\s+of\s+|approximately\s+|about\s+|over\s+)?"
    r"\$\s?[\d,.]+\s*(?:billion|million)[^.]{0,60}?"
    r"(?:in\s+the\s+form\s+of|through)\s+(?:share\s+repurchases|dividends)")
DEBT_RE = re.compile(
    r"repurchas\w*\s+of\s+(?:its\s+|the\s+)?(?:outstanding\s+)?"
    r"(?:[\d.]+%\s+)?(?:senior\s+|subordinated\s+)?"
    r"(?:notes|debt|debentures|bonds|term\s+loan)")
AUTH_NEAR = re.compile(r"authoriz")


def windows(text, needle=r"repurchas\w*|buyback|buy-back", half=400):
    low = text.lower()
    spans = []
    for m in re.finditer(needle, low):
        s, e = max(0, m.start() - half), min(len(low), m.end() + half)
        if spans and s <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], e))
        else:
            spans.append((s, e))
    return [low[s:e] for s, e in spans]


def classify_text(text):
    """Return (is_event, hits, near_misses).
    hits: list of (trigger_name, amount_str_or_None, snippet)
    near_misses: windows containing 'authoriz' near a repurchase mention
    that fired no trigger (recall-audit material)."""
    hits, near = [], []
    for w in windows(text):
        fired = []
        for name, rx in TRIGGERS:
            m = rx.search(w)
            if m:
                fired.append((name, m))
        if fired and all(n == "T3_auth_amt" for n, _ in fired) \
                and RETURNED_RE.search(w):
            near.append("[returned-guard] " + w)
            continue
        if not fired:
            if "authoriz" in w and "repurchas" in w:
                near.append(w)
            continue
        # guards apply per window
        snippet_src = fired[0][1]
        if DEBT_RE.search(w) and "share" not in w and "stock" not in w:
            near.append("[debt-guard] " + w)
            continue
        if ASR_RE.search(w):
            # an ASR mention kills the window unless the trigger is an
            # explicit new/additional/increased authorization (T1/T4/T8 or
            # T2/T3 with new/additional/increas language in the match)
            strong = any(
                n in ("T1_new_amt_auth", "T4_increase_to", "T8_additional_amt")
                or re.search(r"new|additional|increas", m.group(0))
                for n, m in fired)
            if not strong:
                near.append("[asr-guard] " + w)
                continue
        amt = None
        am = AMT_RE.search(w[max(0, snippet_src.start() - 50):
                              snippet_src.end() + 200])
        if am:
            amt = am.group(0)
        else:
            am = AMT_RE.search(w)
            amt = am.group(0) if am else None
        hits.append((fired[0][0], amt,
                     w[max(0, snippet_src.start() - 120):
                       snippet_src.end() + 160]))
    return bool(hits), hits, near


def main():
    log = json.load(open(os.path.join(CACHE, "scan_log.json")))
    meta = {v["ticker"] + "_" + k.replace("-", ""): (v["ticker"], v["date"], k)
            for k, v in log.items() if v.get("mention")}
    events, nears = [], []
    for path in sorted(os.listdir(TEXTS)):
        if not path.endswith(".txt"):
            continue
        key = path[:-4]
        ticker, fdate, acc = meta.get(key, (key.split("_")[0], None, None))
        text = open(os.path.join(TEXTS, path), errors="ignore").read()
        is_ev, hits, near = classify_text(text)
        for w in near:
            nears.append({"ticker": ticker, "date": fdate, "accession": acc,
                          "file": path, "window": w[:600]})
        if is_ev:
            events.append({"ticker": ticker, "date": fdate, "accession": acc,
                           "file": path,
                           "triggers": [h[0] for h in hits],
                           "amount": hits[0][1],
                           "snippet": hits[0][2]})
    events.sort(key=lambda e: (e["date"] or "", e["ticker"]))
    json.dump(events, open(os.path.join(CACHE, "events_raw.json"), "w"), indent=1)
    json.dump(nears, open(os.path.join(CACHE, "near_misses.json"), "w"), indent=1)
    print(f"candidate events: {len(events)}  near-miss windows: {len(nears)}")
    from collections import Counter
    print(Counter(e["ticker"] for e in events))


if __name__ == "__main__":
    main()
