"""The daily cycle layer (new code, Champion app design Section 4).

audit.py      append only broker and control audit log; the paper
              trial record that gate 6.3 reads.
caps.py       hard dollar and position caps, checked twice.
ranking.py    the champion's single date ranking, produced by the
              vendored original's own helpers.
preview.py    order preview with explicit confirmation.
daily_cycle.py  one full daily run: fetch, rank, floor check,
              targets, preview, submit (paper), reconcile.
"""
