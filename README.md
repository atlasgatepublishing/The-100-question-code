# The $100 Question: the complete code

Published by Atlas Gate Publishing, Springfield, Illinois, as the companion code to the book *The $100 Question: We Tested Every Trading Strategy We Could Find*.

This repository holds all of the code printed in the three code appendices of the full records edition of the book, in the same three parts:

* `app/` is Appendix E: the complete source code of the companion application, exactly as it stood at the close of the App v2 build on 23 November 2026. Its own README and build report are included at `app/README.md` and `app/BUILD-REPORT.md`.
* `tests/` is Appendix F: every test script that produced a number in the book, organised by phase and family, in the same folders the project archive uses. Where the archive held identical copies of one script in several folders, this repository holds the script once, at the first of those paths. `tests/FILE-INDEX.csv` records the hash of every distinct script and every folder that held a copy.
* `borrowed-libraries/` is Appendix G: the published library code that one test, the meta-labeling test in Version 6, ran on. It is other people's code, it stays under its own licences, and those licence texts are included in `borrowed-libraries/licenses/` and in the library folders themselves. `borrowed-libraries/FILE-INDEX.csv` lists every borrowed file with its package and hash. One package, chardet, was removed from this folder before posting, at the publisher's direction; the manifest explains why, and the licence audit kept in this folder records its place in the original test environment.

## Running the application

The program runs entirely on your own machine, with your own keys. Nothing is sent back to the publisher. See `app/README.md` for setup instructions and `app/config.example.json` for the shape of the configuration file. Your keys are stored on your own machine only, in the local key store the code describes.

The program starts in paper mode, where orders are simulated and no real money moves. Live mode, where orders go to a real broker account, is a separate step that you switch on yourself, with your own broker keys and a typed sentence of consent, as Chapter 33 of the book describes. Read that chapter, and Chapter 34 on how the machine was tested, before you consider switching anything on.

## A warning, stated plainly

Every result in the book comes from historical replays: past markets played back on a computer, with rules frozen in advance and costs charged. Nothing in the book was traded live before publication, backtested performance does not predict future results, and neither the book nor this code is investment advice. The strategies are proven only in replay, the protective floor has the limits the book states, and using this program can lose money. The publisher is not your financial adviser.

## Licences

The program's own code, in `app/` and `tests/`, is Copyright 2026 Atlas Gate Publishing and is released under the non-commercial licence in the `LICENSE` file at the top of this repository: free for personal use, and nobody may sell it or anything built from it.

The borrowed code in `borrowed-libraries/` is not covered by that licence. Each borrowed package keeps the licence its own authors issued, printed in full in `borrowed-libraries/licenses/`, and any right those licences grant you is yours on their terms.
