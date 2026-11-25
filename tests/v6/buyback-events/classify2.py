#!/usr/bin/env python3
"""Phase 2 v2 (support script): classify scanned 8-K texts into buyback
AUTHORIZATION announcement events. Supersedes classify.py.

v2 changes, each forced by a named calibration failure in v1:
 - T5 split: v1 matched the adjective in 'the approved share repurchase
   programs' (Mastercard's quarterly activity line, 20 false events).
   v2 requires 'new/additional' (T5a) or a verb + article structure (T5b).
 - T7 now allows 'repurchase up to $X' and 'repurchase of up to N shares'
   (v1 missed JNJ 2022-09-14 'repurchase up to $5 billion').
 - Per-match guards, applied to every trigger:
   RETURNED-GUARD (loosened): the amount is the object of 'returned ...
   through/in the form of ... dividends/repurchases' = activity report.
   ACTIVITY-GUARD (T3 only): the matched repurchase token is the past
   tense 'repurchased $...' = activity, not authorization (BAC earnings
   bullets paired unrelated 'increased' verbs with deposit balances).
   REMAINING-GUARD: 'remaining under' immediately before the match =
   a standing program being referenced (Mastercard).
   REFERENCE-GUARD: the match sits inside a citation of a prior
   'Form 8-K dated ...' (BAC debt prospectus boilerplate).
Every surviving event emits its snippet for manual audit; every
'authoriz'-near-'repurchas' window that fires nothing is a near-miss
for the recall audit."""
import json, os, re
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "buyback-events-data")
TEXTS = os.path.join(CACHE, "texts")

AMT = r"\$\s?[\d,.]+\s*(?:billion|million|bn|mm)"
TRIGGERS = [
    ("T1_new_amt_auth", re.compile(
        r"new\s+(?:additional\s+)?" + AMT + r"\s+(?:share|stock|common\s+stock)\s+"
        r"(?:repurchase|buyback)\s+(?:authorization|program|plan)")),
    ("T2_board_auth", re.compile(
        r"(?:board|directors)[^.]{0,140}?(?:authoriz\w+|approv\w+|increas\w+)"
        r"[^.]{0,140}?repurchas")),
    ("T3_auth_amt", re.compile(
        r"(?:authoriz\w+|announc\w+|approv\w+|increas\w+)[^.]{0,80}?" + AMT +
        r"[^.]{0,60}?(?:repurchas|buyback)")),
    ("T4_increase_to", re.compile(
        r"increas\w+[^.]{0,90}?repurchase\s+(?:authorization|program)[^.]{0,60}?"
        r"(?:to|by)\s+" + AMT)),
    ("T5a_new_program", re.compile(
        r"(?:announc\w+|authoriz\w+|approv\w+)[^.]{0,80}?"
        r"(?:new\s+|additional\s+)(?:share|stock)\s+(?:repurchase|buyback)\s+"
        r"(?:program|authorization|plan)")),
    ("T5b_a_program", re.compile(
        r"(?:announc\w+|authoriz\w+)\s+a\s+(?:new\s+)?(?:share|stock)\s+"
        r"(?:repurchase|buyback)\s+(?:program|authorization|plan)")),
    ("T6_program_of_amt", re.compile(
        r"(?:repurchase|buyback)\s+(?:program|authorization|plan)\s+of\s+"
        r"(?:up\s+to\s+)?" + AMT)),
    ("T7_auth_rep_of", re.compile(
        r"authoriz\w+[^.]{0,110}?repurchas\w+\s+(?:of\s+)?(?:up\s+to\s+)?(?:"
        + AMT + r"|[\d,.]+\s*(?:million|billion)\s+(?:additional\s+)?shares)")),
    ("T8_additional_amt", re.compile(
        r"additional\s+" + AMT + r"\s+(?:share|stock)?\s*(?:repurchase|buyback)")),
    ("T9_new_program_noamt", re.compile(
        r"new\s+(?:share|stock)\s+(?:repurchase|buyback)\s+"
        r"(?:program|authorization|plan)")),
    # 'authorized the repurchase of up to 10 million additional shares'
    ("T10_share_count", re.compile(
        r"authoriz\w+[^.]{0,110}?repurchas\w+\s+(?:of\s+)?(?:up\s+to\s+)?"
        r"[\d,.]+\s*(?:million|billion)\s+(?:additional\s+)?(?:shares|common)")),
]
AMT_RE = re.compile(AMT)
ASR_RE = re.compile(r"accelerated\s+share\s+repurchase")
DEBT_RE = re.compile(
    r"repurchas\w*\s+of\s+(?:its\s+|the\s+)?(?:outstanding\s+)?"
    r"(?:[\d.]+%\s+)?(?:senior\s+|subordinated\s+)?"
    r"(?:notes|debt|debentures|bonds|term\s+loan)")
RETURNED_RE = re.compile(
    r"returned\s+(?:a\s+total\s+of\s+|approximately\s+|about\s+|over\s+|more\s+than\s+)?"
    r"\$\s?[\d,.]+\s*(?:billion|million)[^.]{0,70}?"
    r"(?:in\s+the\s+form\s+of|through)[^.]{0,45}?(?:repurchas|dividends)")
REFERENCE_RE = re.compile(r"(?:form\s+)?8-k\s+dated")
REMAINING_RE = re.compile(r"remaining\s+under")


def windows(text, needle=r"repurchas\w*|buyback|buy-back", half=400):
    low = text.lower()
    spans = []
    for m in re.finditer(needle, low):
        s, e = max(0, m.start() - half), min(len(low), m.end() + half)
        if spans and s <= spans[-1][1]:
            spans[-1] = (spans[-1][0], max(spans[-1][1], e))
        else:
            spans.append((s, e))
    return [(s, low[s:e]) for s, e in spans]


def _guarded(w, base, name, m):
    """Return a guard tag if this match is void, else None."""
    span = w[max(0, m.start() - 170):m.end() + 90]
    if REFERENCE_RE.search(w[max(0, m.start() - 170):m.start() + 10]):
        return "reference-guard"
    if REMAINING_RE.search(w[max(0, m.start() - 45):m.start() + 5]):
        return "remaining-guard"
    if RETURNED_RE.search(span):
        return "returned-guard"
    if DEBT_RE.search(w) and "share" not in w and "stock" not in w:
        return "debt-guard"
    if ASR_RE.search(w):
        strong = name in ("T1_new_amt_auth", "T4_increase_to",
                          "T8_additional_amt") or \
            re.search(r"new|additional|increas", m.group(0))
        if not strong:
            return "asr-guard"
    if name == "T3_auth_amt":
        tail = w[m.start():m.end() + 45]
        rp = re.search(r"repurchased\s+(?:approximately\s+|about\s+)?\$", tail)
        if rp:
            return "activity-guard"
    return None


def classify_text(text):
    hits, near = [], []
    for base, w in windows(text):
        fired = []
        for name, rx in TRIGGERS:
            m = rx.search(w)
            if m:
                g = _guarded(w, base, name, m)
                if g:
                    near.append(f"[{g}] " + w)
                else:
                    fired.append((name, m))
        if not fired:
            if "authoriz" in w and "repurchas" in w:
                near.append(w)
            continue
        name, m = fired[0]
        amt = None
        am = AMT_RE.search(w[max(0, m.start() - 50):m.end() + 200])
        if am:
            amt = am.group(0)
        hits.append((name, amt,
                     w[max(0, m.start() - 120):m.end() + 160]))
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
                          "file": path, "window": w[:700]})
        if is_ev:
            events.append({"ticker": ticker, "date": fdate, "accession": acc,
                           "file": path,
                           "triggers": [h[0] for h in hits],
                           "amount": hits[0][1],
                           "snippet": hits[0][2]})
    events.sort(key=lambda e: (e["date"] or "", e["ticker"]))
    json.dump(events, open(os.path.join(CACHE, "events_raw2.json"), "w"), indent=1)
    json.dump(nears, open(os.path.join(CACHE, "near_misses2.json"), "w"), indent=1)
    print(f"candidate events: {len(events)}  near-miss windows: {len(nears)}")
    print(Counter(e["ticker"] for e in events))


if __name__ == "__main__":
    main()
