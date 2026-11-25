#!/usr/bin/env python3
"""Chunked stdin->file writer with resume-from-disk retry.
Workaround for an environment write throttle (EPERM on ordinary writes,
first hit 2026-11-22 ~14:55 amid many parallel workers). The throttle
can refuse a write AFTER persisting part of it, so naive retries
duplicate bytes. Protocol: after every write attempt (success or
PermissionError), take the confirmed position from the file's actual
size and continue from there — a chunk is never blindly rewritten.
Usage: producer | python3 chunkwriter.py TARGET
"""
import sys, time, os

def main():
    target = sys.argv[1]
    data = sys.stdin.buffer.read()
    if os.path.exists(target):
        os.remove(target)
    chunk, t0 = 512, time.time()
    with open(target, "wb") as f:
        while True:
            pos = os.fstat(f.fileno()).st_size
            if pos >= len(data):
                break
            try:
                f.write(data[pos:pos + chunk]); f.flush()
            except PermissionError:
                time.sleep(3)
                if time.time() - t0 > 2400:
                    print(f"chunkwriter: gave up at {pos}/{len(data)}", flush=True)
                    sys.exit(1)
    got = os.path.getsize(target)
    ok = got == len(data)
    print(f"chunkwriter: wrote {got} bytes to {target} in {round(time.time()-t0,1)}s "
          f"({'SIZE-OK' if ok else 'SIZE-MISMATCH'})", flush=True)
    sys.exit(0 if ok else 2)

if __name__ == "__main__":
    main()
