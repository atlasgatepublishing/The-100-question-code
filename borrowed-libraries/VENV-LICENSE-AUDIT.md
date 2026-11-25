# License Audit: the borrowed library code in the meta-labeling venv

Ordered by Terry, 2026-11-23. Question: can the library code that Appendix F of the book left out be printed in the book legally, and on what terms?

Scope audited: every Python file under `~/workspace/stock-app/backtests/v6/meta-labeling/venv`, which is 1,411 .py files and 650,782 lines. Method: every license in this audit was read from a file on disk inside that venv, and the evidence path is cited for each package. Nothing was classified from memory. Where the venv holds no license evidence for a package, this audit says so and does not certify it.

One correction to what was assumed going in: this venv does not contain NumPy or SciPy. It holds six installed distributions. They are scikit-learn, joblib, narwhals, cloudpickle, threadpoolctl, and pip. pip in turn carries 24 vendored components inside its own folder, and scikit-learn carries two bundled external projects. Counting every separate rights holder whose code sits in the tree, the table below has 33 entries.

Classes used: (A) clear to print, with stated conditions. (B) printable with care, copyleft or unusual terms. (C) not printable as it stands, because the venv holds no license for it that this audit could read.

## The full package table

| Package | Version | Files | Lines | License found on disk | Evidence (file read) | Class |
|---|---|---|---|---|---|---|
| scikit-learn (sklearn) | 1.9.1 | 671 | 381,344 | BSD 3-Clause | scikit_learn-1.9.1.dist-info/licenses/COPYING; METADATA License-Expression: BSD-3-Clause | A |
| array_api_compat (bundled inside sklearn/externals) | bundled | in sklearn count | in sklearn count | MIT | sklearn/externals/array_api_compat/LICENSE | A |
| array_api_extra (bundled inside sklearn/externals) | bundled | in sklearn count | in sklearn count | MIT | sklearn/externals/array_api_extra/LICENSE | A |
| joblib | 1.6.0 | 71 | 24,310 | BSD 3-Clause | joblib-1.6.0.dist-info/licenses/LICENSE.txt; METADATA License-Expression: BSD-3-Clause | A |
| narwhals | 2.29.0 | 170 | 56,337 | MIT | narwhals-2.29.0.dist-info/licenses/LICENSE.md; METADATA License-Expression: MIT | A |
| cloudpickle | 3.1.3 | 3 | 1,598 | BSD 3-Clause | cloudpickle-3.1.3.dist-info/licenses/LICENSE; METADATA License-Expression: BSD-3-Clause | A |
| threadpoolctl | 3.8.0 | 1 | 2,092 | BSD 3-Clause | threadpoolctl-3.8.0.dist-info/licenses/LICENSE; METADATA License-Expression: BSD-3-Clause | A |
| pip (its own code, including _vendor/__init__.py) | 24.0 | 151 | 30,881 | MIT | pip-24.0.dist-info/LICENSE.txt; METADATA License: MIT | A |
| CacheControl (vendored in pip) | 0.13.1 | 12 | 1,586 | Apache License 2.0 | pip/_vendor/cachecontrol/__init__.py, SPDX-License-Identifier: Apache-2.0 | A |
| colorama (vendored in pip) | 0.4.6 | 13 | 1,679 | BSD 3-Clause | pip/_vendor/colorama/__init__.py header: "BSD 3-Clause license, see LICENSE file" (the LICENSE file itself is not shipped in the vendored copy) | A, note 1 |
| distlib (vendored in pip) | 0.3.8 | 13 | 10,645 | PSF (Python Software Foundation) | pip/_vendor/distlib/__init__.py header: "Licensed to the Python Software Foundation under a contributor agreement. See LICENSE.txt" (LICENSE.txt not shipped in the vendored copy) | A, note 1 |
| distro (vendored in pip) | 1.8.0 | 3 | 1,457 | Apache License 2.0 | pip/_vendor/distro/distro.py header | A |
| packaging (vendored in pip) | 21.3 | 11 | 2,928 | Dual: Apache License 2.0 or BSD, at the user's choice | pip/_vendor/packaging/__init__.py header | A |
| Pygments (vendored in pip) | 2.15.1 | 35 | 10,384 | BSD | pip/_vendor/pygments/__init__.py header: ":license: BSD, see LICENSE for details" (LICENSE not shipped) | A, note 1 |
| pyparsing (vendored in pip) | 3.1.0 | 11 | 10,913 | MIT (full permission text embedded in the file header) | pip/_vendor/pyparsing/__init__.py | A |
| requests (vendored in pip) | 2.31.0 | 18 | 5,411 | Apache License 2.0 | pip/_vendor/requests/__init__.py header: ":license: Apache 2.0" | A |
| six (vendored in pip) | 1.16.0 | 1 | 998 | MIT (full permission text in the file) | pip/_vendor/six.py | A |
| tenacity (vendored in pip) | 8.2.2 | 11 | 1,651 | Apache License 2.0 | pip/_vendor/tenacity/__init__.py header | A |
| tomli (vendored in pip) | 2.0.1 | 4 | 819 | MIT | pip/_vendor/tomli/__init__.py, SPDX-License-Identifier: MIT | A |
| urllib3 (vendored in pip) | 1.26.17 | 39 | 11,698 | MIT | pip/_vendor/urllib3/__init__.py: __license__ = "MIT" | A |
| webencodings (vendored in pip) | 0.5.1 | 5 | 1,110 | BSD | pip/_vendor/webencodings/__init__.py header: ":license: BSD, see LICENSE for details" (LICENSE not shipped) | A, note 1 |
| chardet (vendored in pip) | 5.1.0 | 48 | 41,282 | GNU Lesser General Public License, version 2.1 or any later version | License block printed in the header of pip/_vendor/chardet/__init__.py and repeated across its files | B |
| certifi (vendored in pip) | 2023.7.22 | 3 | 135 | No license found anywhere in the venv | Searched: all files under pip/_vendor/certifi; no LICENSE file, no license header | C |
| idna (vendored in pip) | 3.4 | 8 | 13,471 | No license found anywhere in the venv | Searched: all files under pip/_vendor/idna | C |
| msgpack (vendored in pip) | 1.0.5 | 4 | 1,308 | No license found anywhere in the venv | Searched: all files under pip/_vendor/msgpack | C |
| pkg_resources (the vendored piece of setuptools in pip) | 68.0.0 | 1 | 3,361 | No license found anywhere in the venv | Searched: pip/_vendor/pkg_resources/__init__.py in full | C |
| platformdirs (vendored in pip) | 3.8.1 | 8 | 1,625 | No license found anywhere in the venv | Searched: all files under pip/_vendor/platformdirs | C |
| pyproject_hooks (vendored in pip) | 1.0.0 | 5 | 732 | No license found anywhere in the venv | Searched: all files under pip/_vendor/pyproject_hooks | C |
| resolvelib (vendored in pip) | 1.0.1 | 7 | 925 | No license found anywhere in the venv | Searched: all files under pip/_vendor/resolvelib | C |
| rich (vendored in pip) | 13.4.2 | 77 | 25,563 | No license found for rich itself. Its file _spinners.py embeds the MIT license of a third party data set it uses (cli-spinners, copyright Sindre Sorhus), printed in full inside that file | pip/_vendor/rich/_spinners.py, lines 1 to 20 | C |
| truststore (vendored in pip) | 0.8.0 | 6 | 1,467 | No license found anywhere in the venv | Searched: all files under pip/_vendor/truststore | C |
| typing_extensions (vendored in pip) | 4.7.1 | 1 | 3,072 | No license found anywhere in the venv | Searched: pip/_vendor/typing_extensions.py in full | C |

Note 1: for these four packages the license is named in a header on disk, but pip's vendoring stripped the license text file itself out of the copy. The grant is on record; the full license text has to be taken from the package's official release and printed with the code. That is a production step, not a legal blocker.

Not counted above, because they are not Python code and cannot be printed as code listings: the compiled binary libraries under scikit_learn.libs, and certifi's cacert.pem data file. Neither sits inside the 1,411 .py files.

## Class totals

| Class | Packages | Files | Lines |
|---|---|---|---|
| A, clear to print with conditions | 21 of the 33 entries (5 of 6 distributions, pip's own code, 2 sklearn externals, 13 vendored components) | 1,243 | 557,841 |
| B, printable with care | 1 (chardet) | 48 | 41,282 |
| C, not printable as it stands | 10 vendored components | 120 | 51,659 |
| Total | 33 entries (6 distributions, 24 vendored components, 2 bundled externals, 1 embedded data set counted inside rich) | 1,411 | 650,782 |

## What class A would add to the book

Appendix F printed 395,524 lines of the program's own code. The book grew from 577 pages to 5,542 pages when Appendix F went in, so Appendix F runs about 4,965 pages, which is about 79.7 lines of code per page at the book's code appendix density. At that same density:

- Class A, 557,841 lines, adds about 7,000 pages.
- Class B, 41,282 lines, would add about 518 pages on top of that.
- Class C, 51,659 lines, would add about 648 pages if it is cured first.

## The exact conditions for the class A set

### BSD 3-Clause packages: scikit-learn, joblib, cloudpickle, threadpoolctl, and by header grant colorama, Pygments, webencodings, and packaging if the BSD side of its dual license is elected

The license text read on disk (scikit_learn-1.9.1.dist-info/licenses/COPYING, and the same words in the joblib and threadpoolctl files) requires all of the following:

1. Source redistributions keep the copyright notice, the list of conditions, and the disclaimer. A printed book is a source redistribution, so the book must print the full BSD 3-Clause text together with each package's copyright notice.
2. Neither the name of the copyright holder nor the names of its contributors may be used to endorse or promote products derived from the software without specific prior written permission. For this book the practical meaning is narrow and important: the code may be printed and the book may be sold, but the book's cover, advertising, and sales copy must not use names like scikit-learn or joblib as if those teams endorsed the book. Factual description inside the text (this test used scikit-learn) is not endorsement.
3. The code must be printed as it stands, with the notices that are already inside the files kept in place. Appendix F already prints code verbatim, so this is satisfied by the same method.

### MIT packages: narwhals, pip and the MIT parts of its vendored tree (pyparsing, six, tomli, urllib3), and scikit-learn's two bundled externals (array_api_compat, array_api_extra)

The license text read on disk (narwhals-2.29.0.dist-info/licenses/LICENSE.md, and the same words in pip-24.0.dist-info/LICENSE.txt) requires one thing: the copyright notice and the permission notice must be included in all copies. Printing each package's MIT text with its copyright line next to its code satisfies it in full. MIT places no restriction on selling the book and no restriction on endorsement beyond what ordinary trademark and false claim law already says.

### Apache License 2.0 packages: CacheControl, distro, requests, tenacity, and packaging if the Apache side of its dual license is elected

Evidence on disk for each of these is a header or SPDX line naming the Apache License, Version 2.0. The Apache terms require:

1. A copy of the Apache License 2.0 text must go to every recipient. The book must print the full Apache license text once, in the license pages for this appendix.
2. Copyright, patent, trademark, and attribution notices present in the source must be kept. The vendored files carry their headers, and verbatim printing keeps them.
3. Modified files must carry notices saying they were changed. The book prints this code unmodified, so no change notices are owed, as long as the listings truly are verbatim.
4. If a work ships a NOTICE text file, its attribution notices must be reproduced. This audit searched the vendored tree and found no NOTICE file in any Apache licensed vendored package on disk, so there is no NOTICE content to reproduce from what the venv holds.
5. The license grants no right to use the licensors' trade names or trademarks except to describe the origin of the work. Same practical rule as BSD clause 3: describe factually, never imply endorsement.

### PSF package: distlib

The header on disk says the code is licensed to the Python Software Foundation under a contributor agreement and points to a LICENSE.txt that the vendored copy does not include. The PSF license is a permissive license of the same family as BSD and MIT. Its conditions are to keep the copyright notice (Copyright (C) 2012-2023 Vinay Sajip) and to print the PSF license agreement text with the code. That text must be taken from the official distlib release, since it is not on disk here.

## The exact license and notice pages class A needs printed with it

Four license texts, printed once each in a licenses section at the front of the new appendix, plus one copyright notice block per package. Nothing else.

1. BSD 3-Clause License, full text, followed by these copyright notices, one per package, copied from the files read:
   - Copyright (c) 2007-2026 The scikit-learn developers. (from scikit_learn-1.9.1.dist-info/licenses/COPYING)
   - Copyright (c) 2008-2021, The joblib developers. (from joblib-1.6.0.dist-info/licenses/LICENSE.txt)
   - Copyright (c) 2015, Cloudpickle contributors; Copyright (c) 2012, Regents of the University of California; Copyright (c) 2009 PiCloud, Inc. (from cloudpickle-3.1.3.dist-info/licenses/LICENSE)
   - Copyright (c) 2019, threadpoolctl contributors. (from threadpoolctl-3.8.0.dist-info/licenses/LICENSE)
   - Copyright Jonathan Hartley 2013 (colorama, from its header)
   - Copyright 2006-2023 by the Pygments team (from its header)
   - Copyright 2012 by Simon Sapin (webencodings, from its header)
   - The packaging copyright notice, if the BSD side of its dual license is elected (header in pip/_vendor/packaging/__init__.py)
2. MIT License, full text, followed by these copyright notices:
   - Copyright (c) 2024 to present, Marco Gorelli (narwhals)
   - Copyright (c) 2008-present The pip developers (pip, from pip-24.0.dist-info/LICENSE.txt; pip's AUTHORS.txt, also on disk in the same folder, should be printed with it)
   - Copyright (c) 2003-2022 Paul T. McGuire (pyparsing)
   - Copyright (c) 2010-2020 Benjamin Peterson (six)
   - Copyright Taneli Hukkinen, 2021 (tomli, from its SPDX header)
   - The MIT grant as it appears in urllib3 itself: __license__ = "MIT" (pip/_vendor/urllib3/__init__.py)
   - Copyright (c) 2022 Consortium for Python Data API Standards (array_api_compat)
   - Copyright (c) 2024 Consortium for Python Data API Standards (array_api_extra)
3. Apache License, Version 2.0, full text, applying to:
   - CacheControl, copyright Eric Larson, 2015 (SPDX header)
   - distro, Copyright 2015, 2016, 2017 Nir Cohen
   - requests, Copyright Kenneth Reitz
   - tenacity, Copyright 2016-2018 Julien Danjou, Copyright 2017 Elisey Zanko, Copyright 2016 Étienne Bersac, Copyright 2016 Joshua Harlow (all from its header)
   - packaging, if the Apache side of its dual license is elected instead of BSD
4. The Python Software Foundation license agreement text, for distlib, Copyright (C) 2012-2023 Vinay Sajip, licensed to the Python Software Foundation under a contributor agreement. This text is not on disk in the venv and must be taken from the official distlib release.

For colorama, Pygments, webencodings, and distlib, the license texts named in their headers must likewise be taken from the packages' official releases, because pip's vendoring removed the license files from the copies on disk. The grants themselves are evidenced on disk by the headers cited in the table.

## Class B: chardet, and what its terms would demand

chardet 5.1.0 (48 files, 41,282 lines) carries the GNU Lesser General Public License, version 2.1 or any later version, stated in a license block at the top of its files. The LGPL was written for software distribution, not for print, and its terms applied to a printed book would require at least this: the full LGPL text printed with the code, every copyright and license notice kept intact, and no terms imposed on the reader that restrict the rights the LGPL gives them in that code. A verbatim appendix of the library's own source, standing on its own and not merged into any other work, is the strongest position under the LGPL, and nothing in the LGPL reaches across mere aggregation to put the rest of the book under copyleft. The residual risk is real, though: the LGPL's rules about works that use the library and about providing the source in usable form were drafted with programs in mind, and how a court would map them onto a printed and sold book has no settled answer this audit can point to. Verdict: printable with care, and this is the one package where the publishing lawyer's pass should be a condition, not a courtesy. It is also worth saying plainly that chardet sits three layers down inside pip, a tool the tests used to install packages. Its 41,282 lines say nothing about any test in the book.

## Class C: the ten packages with no license on disk, and the cure

certifi, idna, msgpack, pkg_resources, platformdirs, pyproject_hooks, resolvelib, rich, truststore, and typing_extensions ship inside pip's vendored tree with no license file and no license statement in their code that this audit could find, after searching every file in each package. That does not mean they are unlicensed in the world. It means the evidence is not in this venv, and this audit does not certify what it did not read. As the book stands, printing them would be printing code with no license in hand, which is exactly the trouble Terry asked to avoid. The cure is mechanical: for each of the ten, take the license text from the package's own official release for the exact version listed in the table (pip's vendor.txt, read on disk, pins every version), print that license and its copyright notice with the code, and reclassify. Until that step is done and checked, they stay out. One special case: rich's own file _spinners.py already contains, in full, the MIT license of the cli-spinners data it embeds, copyright Sindre Sorhus. That embedded license is printable as it stands, but it covers the spinner data, not rich itself.

## Bottom line

Of the 1,411 borrowed files, 1,243 files and 557,841 lines are clear to print today, on four license texts and the notice blocks listed above, adding about 7,000 pages. One package (chardet, 48 files) is printable with care and a lawyer's confirmation. Ten packages (120 files, 51,659 lines) cannot be certified from what is on disk and stay out until their license texts are pulled from their official releases and printed alongside. No package in the venv carries terms that forbid printing outright. The barrier is evidence and conditions, not prohibition.
