#!/usr/bin/env python3
"""Build per-selection-date ranked books for all 10 managers (read-only inputs).
Uses the v10 cloning engine's own effective_book / rank_positions verbatim."""
import importlib.util, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    "clone_engine", os.path.expanduser("~/workspace/stock-app/backtests/v10-retest/cloning-13f/engine.py"))
ENG = importlib.util.module_from_spec(spec); spec.loader.exec_module(ENG)
E = ENG.E

spy = E.get_prices("SPY")
pb = E.PriceBook({"SPY": spy})
Q = E.quarter_selection_dates(pb, "2019-01-02", "2026-11-20")
print("selection dates", len(Q), Q[0], Q[-1], flush=True)

books = {}   # date -> cik -> [{cusip,name,title,value,pct}]
names = {}   # cusip -> (name,title)
for D in Q:
    books[D] = {}
    for cik in ENG.PANEL:
        book, period, _f = ENG.effective_book(cik, D)
        if book is None:
            books[D][str(cik)] = None; continue
        ranked = ENG.rank_positions(book)
        rows = []
        for r in ranked:
            rows.append({"cusip": r["cusip"], "name": r["name"], "title": r["title"],
                         "value": r["value"], "pct": r["pct_of_table"]})
            names.setdefault(r["cusip"], (r["name"], r["title"]))
        books[D][str(cik)] = {"period": period, "rows": rows}
    print(D, {c: (len(v["rows"]) if v else None) for c, v in books[D].items()}, flush=True)

json.dump({"dates": Q, "books": books,
           "cusip_names": {c: list(v) for c, v in names.items()}},
          open(os.path.join(HERE, "books.json"), "w"))
print("distinct cusips:", len(names))
