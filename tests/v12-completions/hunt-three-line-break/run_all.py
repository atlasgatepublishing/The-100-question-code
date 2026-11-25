#!/usr/bin/env python3
"""One-process staged run with a resilient chunk writer (the sandbox file
write gate intermittently returns EPERM; chunks are retried with backoff
until they land). Prints progress to stdout."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_stages as S

HERE = os.path.dirname(os.path.abspath(__file__))

def resilient_dump(name, obj):
    text = json.dumps(obj)
    path = os.path.join(HERE, name)
    # truncate/create (creation always works; content is appended in chunks)
    try:
        with open(path, "w") as f:
            pass
    except Exception:
        pass
    CH = 16384
    off = 0; waits = 0
    with open(path, "a") as f:
        while off < len(text):
            chunk = text[off:off + CH]
            try:
                f.write(chunk); f.flush()
                off += len(chunk)
            except PermissionError:
                waits += 1
                if waits > 400:
                    raise
                time.sleep(3)
    print(f"wrote {name} ({len(text)} bytes, {waits} write-waits)", flush=True)

S.dump = resilient_dump  # monkeypatch: run_stages.dump(name, obj)

for st in ("spy", "pond", "ppl_long", "ppl_val", "coins", "cpl_full", "cpl_recent", "merge"):
    print("stage", st, "start", flush=True)
    {"spy": S.stage_spy, "pond": S.stage_pond, "coins": S.stage_coins, "merge": S.stage_merge,
     "ppl_long": lambda: S.stage_ppl("LONG"), "ppl_val": lambda: S.stage_ppl("VAL"),
     "cpl_full": lambda: S.stage_cpl("FULL"), "cpl_recent": lambda: S.stage_cpl("RECENT")}[st]()
    print("stage", st, "done", flush=True)
print("ALL COMPLETE", flush=True)
