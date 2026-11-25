# Package manifest: what is in here, where it came from, and what was left out

This package reproduces, file for file, the code printed in the three code appendices of *The $100 Question* (Atlas Gate Publishing, 2026), with one removal made at the publisher's direction before posting, described in the exclusions below: the chardet library is not in this repository, and one small joblib test file could not be posted byte for byte and is not in this repository either. Every other file was copied, never modified, and every copied file was checked against the hash recorded when the book was built. All checks passed.

## Contents and counts

| Part | Folder | Files | Lines | Source |
| --- | --- | --- | --- | --- |
| Appendix E, the companion application | `app/` | 62 | 12,824 | The live project folder `stock-app/app/` |
| Appendix F, the test code | `tests/` | 1,422 | 395,524 | The live project folder `stock-app/backtests/`, deduplicated as the book deduplicated it |
| Appendix G, the borrowed library code | `borrowed-libraries/site-packages/` | 1,363 | 609,501 | The Python library environment at `stock-app/backtests/v6/meta-labeling/venv/`, minus chardet as described below |
| Appendix G licence texts, as assembled for the book | `borrowed-libraries/licenses/` | 23 | 2,131 | The book build folder `appendix-g/licenses/`, minus the LGPL text that belonged to chardet |
| Licence files standing inside the borrowed packages | inside `borrowed-libraries/site-packages/` | 9 | 1,040 | The same library environment, copied in place |

Total code: 2,847 files and 1,017,849 lines, plus the licence texts above, two file index files, and the three documents at the top of the package (README, LICENSE, and this manifest).

The line counts use the book's own counting convention. The Appendix F total matches the count printed in the book exactly: 395,524 lines. The Appendix G total printed in the book is 650,783 lines across 1,411 files; this repository holds 609,501 of those lines across 1,363 files, because chardet (48 files, 41,282 lines) was removed before posting, and one further file could not be posted byte for byte, both as described below.

## How each part was verified

* Appendix E: the book's generated listing holds 62 documents and files. Each one was compared against the live file of the same name and all 62 matched, word for word.
* Appendix F: the book's inventory recorded 1,840 script files written for this program, counting identical copies each time they appear. Those reduce to 1,422 distinct files, and those are what this package holds, each once, at the first of its paths in the book's order. `tests/FILE-INDEX.csv` lists every distinct file with its hash, its line count, and every folder in the project archive that held a copy, so any copy can be traced. A fresh check of the live backtests folder against the book's inventory found no missing files, no changed files, and no extra script files.
* Appendix G: every one of the 1,411 files was checked against the SHA-256 hash in the book's own Appendix G manifest, `manifest_g.json`, during the copy. All 1,411 matched. The 48 chardet files were then removed, as described below, and `borrowed-libraries/FILE-INDEX.csv` repeats that manifest with the chardet rows removed, so the index matches what this repository holds. Two provenance documents are included in `borrowed-libraries/`: `CURE-RECORD.md`, the record of how the ten licence files that pip's packaging had stripped were recovered from the official releases at the pinned versions, and `VENV-LICENSE-AUDIT.md`, the file by file licence audit of the environment.

## Secrets scan

Before packaging, all 2,919 files in the three code sets were scanned for credential patterns: assignments to variables named for API keys, secrets, tokens, and passwords, and the known prefixes of common key formats. Three candidate lines were found and each was read and cleared:

* Two dashboard test files (`app/dashboard/test_auth.py` and `app/dashboard/test_picker_login.py`) set a dummy password constant used only by their own login tests. It is a test fixture invented for those tests, not a real credential, and the files are included as printed.
* One line in pip's own library code (`pip/_internal/utils/misc.py`) holds a masked password fragment made of asterisks, part of pip's tool for hiding passwords inside URLs. It is not a credential, and the file is included as printed.

No real API key, token, password, or other credential value was found anywhere in the package. The application's example configuration holds empty and placeholder key slots only, as printed in the book. Nothing was removed or altered because of the scan.

## What was excluded, and why

* chardet, removed before posting at the publisher's direction (25 November 2026): 48 files, 41,282 lines, the copy of the chardet library vendored inside pip at `pip/_vendor/chardet/`, together with the LGPL 2.1 licence text file that was included for it. The licence audit in `borrowed-libraries/VENV-LICENSE-AUDIT.md` classed every other borrowed package as clear to redistribute on its stated conditions, and chardet alone as the one item a publishing lawyer should confirm first, because its LGPL terms are stricter than the BSD, MIT, and Apache terms covering the rest. The publisher chose to remove it rather than carry that open item. The audit documents are kept in this repository unchanged, so the record of chardet's place in the original test environment, its version (5.1.0), and the audit's reasoning all remain on file. Anyone who needs chardet itself can install it from its own publishers in the normal way. No other borrowed file was removed.
* One joblib test file not posted (25 November 2026): `borrowed-libraries/site-packages/joblib/test/test_func_inspect_special_encoding.py`, a 145 byte test fixture written in the Big5 character encoding on purpose, because testing how the library reads unusually encoded files is its whole job. GitHub's upload path accepts standard text only, and the one attempted posting converted the file's characters into a different encoding, which changed its bytes; that converted copy was removed at once, because this repository does not carry files that differ from the record. The file itself is unharmed: it is printed in Appendix G of the full records edition, it is in the zip package of this code, its SHA-256 hash stands in `borrowed-libraries/FILE-INDEX.csv` so any copy can be checked against it, and it ships with joblib's own releases. This repository therefore holds 1,362 of the 1,363 Appendix G library files listed above.
* Duplicate copies in the test archive: 418 extra copies of the distinct test scripts (1,840 files counting copies, 1,422 distinct). The book printed each distinct file once, and so does this package. Every copy location is recorded in `tests/FILE-INDEX.csv`.
* The wider adversarial test suites for the application: 18 test files that sit in the live app folder, among them the adversarial suites for the dashboard, the data layer, the engines, the pots, the reports, and the watcher. Appendix E states in its own introduction that these suites ship with the program but are not reprinted in the book, and this package reproduces the printed record, so they are not included. They still exist in the project archive, and the book's printed application code is complete without them.
* Application data and outputs: saved pot states, generated report outputs, sample data feeds, integrity results files (data the engines check against, not code), dashboard screenshots, and the app's QA report document. Appendix E did not print them, for the reason its introduction gives: they are data and outputs, not code.
* Non-script files in the backtests archive: results documents, scoreboards, and data files in Markdown, JSON, and CSV form. Appendix F printed the scripts only, and so does this package.
* The rest of the library environment: package metadata folders, package data files, compiled Python files, and binary library files inside the venv. Appendix G printed the 1,411 Python source files, and so does this package. The borrowed packages can be installed from their publishers in the normal way; this folder is the printed record of the exact code the test ran on.
* Build and junk files throughout: `__pycache__` folders, `.pyc` files, version control folders, book documents, page renders, and build scripts from the book's own production. None of that is program code.

## One limit, stated plainly

The borrowed file set in this package is the set the book printed, verified hash by hash against the book's Appendix G manifest, with the single chardet removal described above, so no reconstruction was needed. The one thing this package does not do is make the borrowed environment runnable as a folder: it is a source record, and anyone who wants to run the meta-labeling test should install the libraries from their publishers at the versions named in `borrowed-libraries/VENV-LICENSE-AUDIT.md` and in the package metadata recorded in `borrowed-libraries/FILE-INDEX.csv`.
