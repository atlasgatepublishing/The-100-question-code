#!/usr/bin/env python3
"""Integrity runner: runs the ORIGINAL v3 script (byte-identical copy,
original_aggressive_v3.py) end-to-end with its data directory pointed at
the read-only v3 cache (all 15 symbols already cached there, so fetch()
never writes and never hits the network). Output lands in this folder as
aggressive-v3-results.json, exactly as the original main() writes it."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import original_aggressive_v3 as m
m.DATA = os.path.expanduser("~/workspace/stock-app/backtests/v3/data")
if __name__ == "__main__":
    m.main()
