"""Append only audit log, and the paper trial record (design 6.9, 6.3).

The log is a JSON Lines file at state/audit_log.jsonl. One record per
event, appended, never rewritten: this module exposes no edit or
delete path, and record() opens the file in append mode only. The log
is the evidence the paper trial gate reads, and it is written so a
user can hand it to anyone and have the app's whole history read off
it: cycle runs, data failures, rankings produced, previews shown and
confirmed or expired, orders submitted with broker ids, fills read
back, reconciliation results, cap refusals, mode changes, unlock
events, kill switch engagements and cancellations, pond events.

Tamper evidence (adversarial fix step, attacks G1, G2, G3): every
entry carries a sequence number, the hash of the previous entry, and
its own hash, forming a chain over the whole file. The paper trial
gate verifies the chain before it believes a single event: a hand
written line, a deleted line, a reordered line, or a corrupted line
anywhere in the file breaks the chain, and a broken chain reads as
NO trial at all (the gate fails closed). A torn final fragment (a
crash mid append, leaving a last line with no terminating newline)
is the one tolerated defect: it was never a completed record, readers
skip it, and the next record() call repairs the tail before
appending. Entries written before the chain existed carry no chain
fields and therefore do not verify: a pre chain log is treated as a
damaged log, and the trial must be evidenced by chained entries.

Paper trial (DECISIONS.md ruling 1): live enabling is refused until
the log shows a completed paper trial of 90 days that includes at
least one completed quarterly selection cycle, with every cycle
reconciled and no unresolved reconciliation mismatch. Only cycles
executed against a real paper broker connection count (adversarial
fix step, attack Y2): a run with no broker keys is SIMULATED, its
events carry simulated=true, and the gate never counts them.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import date, datetime
from pathlib import Path

try:
    from data import mode as _mode
    _DEFAULT_STATE_DIR = _mode.STATE_DIR
except Exception:  # pragma: no cover
    _DEFAULT_STATE_DIR = Path(__file__).resolve().parent.parent / "state"

try:
    from data import redact as _redact
except Exception:  # pragma: no cover
    _redact = None

AUDIT_FILE = "audit_log.jsonl"
PAPER_TRIAL_DAYS = 90

_LOCK = threading.Lock()
_GENESIS = "0" * 64
_CHAIN_FIELDS = ("seq", "prev", "chain")


def audit_path(state_dir=None) -> Path:
    return (Path(state_dir) if state_dir else _DEFAULT_STATE_DIR) / AUDIT_FILE


def _scrub(value):
    if isinstance(value, str) and _redact is not None:
        try:
            return _redact.scrub_text(value)
        except Exception:
            return value
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


def _chain_of(entry: dict) -> str:
    """The entry's hash: sha256 over the canonical JSON of the entry
    WITHOUT its own chain field (the prev field is inside, so each
    hash commits to the whole history before it)."""
    body = {k: v for k, v in entry.items() if k != "chain"}
    canon = json.dumps(body, allow_nan=False, sort_keys=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _read_chain_tail(p: Path) -> tuple[int, str, bool]:
    """(next_seq, prev_hash, tail_ok) for appending to the log at p.

    tail_ok is False when the existing file's completed lines do not
    themselves verify: record() still appends (the log is the app's
    diary, and refusing to write would hide new events), but the new
    entry chains onto the last readable entry so verify_integrity()
    keeps reporting the earlier damage. A torn final fragment (no
    terminating newline) is truncated first: it was never a completed
    record."""
    try:
        raw = p.read_bytes()
    except (FileNotFoundError, OSError):
        return 0, _GENESIS, True
    if not raw:
        return 0, _GENESIS, True
    if not raw.endswith(b"\n"):
        cut = raw.rfind(b"\n")
        raw = raw[:cut + 1] if cut >= 0 else b""
        with open(p, "r+b") as f:
            f.truncate(len(raw))
        if not raw:
            return 0, _GENESIS, True
    seq = 0
    prev = _GENESIS
    ok = True
    for line in raw.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except Exception:
            ok = False
            continue
        if not isinstance(entry, dict) or entry.get("seq") != seq \
                or entry.get("prev") != prev \
                or entry.get("chain") != _chain_of(entry):
            ok = False
        if isinstance(entry, dict) and isinstance(entry.get("chain"), str):
            prev = entry["chain"]
        seq += 1
    return seq, prev, ok


def record(event: str, state_dir=None, **fields) -> dict:
    """Append one event. Returns the record written.

    Append only: the file is opened with mode "a" and the record is
    flushed and fsynced before returning, so a crash cannot take a
    written event with it, and no code path here ever truncates or
    rewrites earlier completed lines. The one repair record() makes
    is dropping a torn final fragment (a crash mid append) before
    appending, since that fragment was never a completed record.
    Every entry is hash chained to the one before it (see the module
    docstring)."""
    if not isinstance(event, str) or not event:
        raise ValueError(f"audit event must be a non-empty string, got {event!r}")
    entry = {"ts": datetime.now().isoformat(timespec="seconds"),
             "event": event}
    entry.update(_scrub(fields))
    p = audit_path(state_dir)
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        seq, prev, _tail_ok = _read_chain_tail(p)
        entry["seq"] = seq
        entry["prev"] = prev
        entry["chain"] = _chain_of(entry)
        line = json.dumps(entry, allow_nan=False, sort_keys=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())
    return entry


def _scan(state_dir=None) -> tuple[list[dict], str | None, bool]:
    """Read the log once. Returns (events, integrity_problem, torn):
    the completed entries in file order; a plain description of the
    first integrity failure found, or None when the chain verifies
    end to end; and whether a torn final fragment was skipped. Any
    completed line that does not parse, lacks its chain fields, is
    out of sequence, or does not hash to its recorded chain is an
    integrity failure: a damaged log is reported as damaged, never
    silently read as a shorter honest one."""
    p = audit_path(state_dir)
    try:
        raw = p.read_bytes()
    except (FileNotFoundError, OSError):
        return [], None, False
    if not raw:
        return [], None, False
    torn = False
    if not raw.endswith(b"\n"):
        cut = raw.rfind(b"\n")
        raw = raw[:cut + 1] if cut >= 0 else b""
        torn = True
    events: list[dict] = []
    prev = _GENESIS
    for i, line in enumerate(raw.decode("utf-8", "replace").splitlines()):
        if not line.strip():
            return events, (f"line {i + 1} of the audit log is blank; "
                            f"the log has been edited or damaged"), torn
        try:
            entry = json.loads(line)
        except Exception:
            return events, (f"line {i + 1} of the audit log does not "
                            f"parse; the log has been edited or "
                            f"damaged"), torn
        if not isinstance(entry, dict):
            return events, (f"line {i + 1} of the audit log is not an "
                            f"event record; the log has been edited or "
                            f"damaged"), torn
        if entry.get("seq") != i:
            return events, (f"line {i + 1} of the audit log is out of "
                            f"sequence (an entry was added, deleted, or "
                            f"reordered); the log cannot be trusted"), torn
        if entry.get("prev") != prev:
            return events, (f"line {i + 1} of the audit log does not "
                            f"chain to the entry before it (an entry "
                            f"was added, deleted, or reordered); the "
                            f"log cannot be trusted"), torn
        if entry.get("chain") != _chain_of(entry):
            return events, (f"line {i + 1} of the audit log fails its "
                            f"integrity hash (its contents were "
                            f"edited); the log cannot be trusted"), torn
        prev = entry["chain"]
        events.append(entry)
    return events, None, torn


def verify_integrity(state_dir=None) -> tuple[bool, str | None]:
    """(True, None) when the audit log's hash chain verifies end to
    end; (False, problem) otherwise. A missing or empty log verifies
    (it evidences nothing, and the gate treats it as no trial)."""
    _events, problem, _torn = _scan(state_dir)
    return problem is None, problem


def read_events(state_dir=None) -> list[dict]:
    """All completed events, in file order. A torn final fragment (a
    crash mid append) is skipped, never fatal. Callers that act on
    the log as EVIDENCE (the paper trial gate) use
    paper_trial_status(), which verifies the chain first and fails
    closed on any damage; read_events() itself stays a plain reader
    for display and diagnostics."""
    events, _problem, _torn = _scan(state_dir)
    return events


def _event_date(entry: dict) -> date | None:
    ts = entry.get("ts")
    if isinstance(ts, str):
        try:
            return date.fromisoformat(ts[:10])
        except ValueError:
            return None
    return None


def paper_trial_status(state_dir=None, today: date | None = None) -> dict:
    """Evaluate the paper trial from the audit log (ruling 1).

    The chain is verified FIRST: if the log is damaged (any entry
    added, deleted, reordered, edited, or unparseable), the trial
    reads as not started at all, however convincing the surviving
    lines look. A damaged log is no trial.

    Complete only when ALL of these hold, over verified entries:
      * a paper cycle has completed against a real paper broker
        connection (event "cycle_complete" with mode "paper",
        reconciled true, and simulated not true), starting the
        trial clock;
      * at least PAPER_TRIAL_DAYS days have passed since that first
        completed paper cycle;
      * at least one quarterly selection cycle has completed in
        paper mode against the broker inside the trial (event
        "selection_cycle_complete" with mode "paper" and simulated
        not true);
      * no reconciliation mismatch recorded during the trial is left
        unresolved (a "reconciliation_mismatch" event is resolved by
        a later "mismatch_resolved" event carrying the same
        mismatch_id).
    """
    today = today or date.today()
    events, problem, _torn = _scan(state_dir)
    if problem is not None:
        return {"complete": False, "started": None, "days": 0,
                "days_required": PAPER_TRIAL_DAYS,
                "selection_cycle_done": False, "unresolved_mismatches": 0,
                "log_integrity": "broken", "integrity_problem": problem,
                "reason": ("The audit log failed its integrity check: "
                           f"{problem}. A damaged log counts as no "
                           "paper trial at all. Restore the log from a "
                           "backup, or start the trial again with a "
                           "fresh log.")}
    started = None
    selection_done = False
    open_mismatches: dict[str, dict] = {}
    for e in events:
        d = _event_date(e)
        if e.get("event") == "cycle_complete" and e.get("mode") == "paper" \
                and e.get("reconciled") is True \
                and e.get("simulated") is not True:
            if started is None and d is not None:
                started = d
            continue
        if started is None:
            continue
        if e.get("event") == "selection_cycle_complete" \
                and e.get("mode") == "paper" \
                and e.get("simulated") is not True:
            selection_done = True
        elif e.get("event") == "reconciliation_mismatch":
            mid = str(e.get("mismatch_id") or e.get("ts") or len(open_mismatches))
            open_mismatches[mid] = e
        elif e.get("event") == "mismatch_resolved":
            open_mismatches.pop(str(e.get("mismatch_id") or ""), None)
    days = (today - started).days if started is not None else 0
    unresolved = len(open_mismatches)
    complete = bool(started is not None and days >= PAPER_TRIAL_DAYS
                    and selection_done and unresolved == 0)
    if started is None:
        reason = ("No completed paper cycle is on record yet. Run the "
                  "daily cycle in PAPER mode; the trial clock starts at "
                  "the first completed, reconciled paper cycle.")
    elif days < PAPER_TRIAL_DAYS:
        reason = (f"Paper trial in progress: day {days} of "
                  f"{PAPER_TRIAL_DAYS} (started {started.isoformat()}).")
    elif not selection_done:
        reason = ("The 90 days have passed, but no quarterly selection "
                  "cycle has completed in paper mode yet. The trial "
                  "requires one: the champion decides quarterly, so a "
                  "trial without a selection round has not tested the "
                  "app end to end.")
    elif unresolved:
        reason = (f"The paper trial has {unresolved} unresolved "
                  f"reconciliation mismatch(es) on record. Resolve them "
                  f"(record the cause in the audit log) before live can "
                  f"be enabled.")
    else:
        reason = ("Paper trial complete: 90 days, including a completed "
                  "quarterly selection cycle, with no unresolved "
                  "mismatch.")
    return {"complete": complete, "started": started.isoformat() if started else None,
            "days": days, "days_required": PAPER_TRIAL_DAYS,
            "selection_cycle_done": selection_done,
            "unresolved_mismatches": unresolved,
            "log_integrity": "ok", "integrity_problem": None,
            "reason": reason}


def live_unlock_blocker(state_dir=None, today: date | None = None) -> str | None:
    """None when live may be enabled; otherwise the plain-language
    reason it is refused (design gate 6.3). The enable path (dashboard
    Trading Mode page, run.py) consults this BEFORE data.mode's own
    checks, so a refused unlock leaves the config untouched."""
    st = paper_trial_status(state_dir, today=today)
    if st["complete"]:
        return None
    return ("Live mode was NOT enabled: the paper trial is not "
            f"complete. {st['reason']} The app stays in PAPER mode.")
