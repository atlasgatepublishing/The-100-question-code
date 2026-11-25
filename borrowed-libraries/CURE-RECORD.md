# Appendix G cure record and license sources

Compiled 2026-11-24 (UTC) by the Appendix G build agent. Every license identity and
copyright notice below rests on the named evidence, gathered from the package's
official release records or from distribution records of the exact pinned version.
Pinned versions are pip 24.0's own vendor list (pip/_vendor/vendor.txt in the venv).

## Class C (pip vendored components): all ten cured

1. certifi 2023.7.22: Mozilla Public License 2.0. Evidence: Debian machine readable
   copyright file for python3-certifi (Files: *, Copyright: Kenneth Reitz, License:
   MPL-2), the Oracle OCI open source notices (certifi MPL-2.0), and the Fedora
   python-pip spec vendored list (certifi: MPL-2.0). MPL-2.0 text: system copy at
   /usr/share/common-licenses/MPL-2.0, saved as licenses/mpl-2.0.txt.
   Notice printed: Copyright: Kenneth Reitz.
2. idna 3.4: BSD 3-Clause. Evidence: the project's official LICENSE.md at tag v3.4
   (github.com/kjd/idna, read through the chromium.googlesource.com mirror):
   "Copyright (c) 2013-2021, Kim Davies" over the BSD 3-Clause text.
   Saved as licenses/bsd3-idna-LICENSE.md.
3. msgpack 1.0.5: Apache License 2.0. Evidence: package metadata at 1.0.3 and 1.0.6
   (License: Apache 2.0, License-File: COPYING, OSI Apache classifier), the Cisco
   open source notice printing msgpack's COPYING ("Copyright (C) 2008-2011 INADA
   Naoki"), and the Apache header in msgpack's own source files.
   Saved as licenses/apache-msgpack-COPYING.txt; full Apache text printed once.
4. pkg_resources (setuptools 68.0.0): MIT. Evidence: SUSE and OpenEmbedded package
   records (License: MIT), the pypa packaging guide (setuptools LICENSE file, MIT),
   and attribution records for the 68.x line (Maple, setuptools 68.2.2: "Copyright
   Jason R. Coombs and contributors", MIT License).
   Saved as licenses/mit-setuptools-LICENSE.txt with notice "Copyright Jason R. Coombs".
5. platformdirs 3.8.1: MIT. Evidence: Fedora python-pip spec vendored list
   (platformdirs: MIT), package metadata (License-Expression: MIT, License-File:
   LICENSE), and the Debian python3-pip copyright file, which records pip's vendored
   platformdirs as "Copyright: 2010 ActiveState Software Inc., License: MIT".
   Saved as licenses/mit-platformdirs-LICENSE.txt.
6. pyproject_hooks 1.0.0: MIT. Evidence: SUSE spec for exactly version 1.0.0
   (License: MIT, source files.pythonhosted.org pyproject_hooks-1.0.0.tar.gz),
   Fedora python-pip spec (pyproject-hooks: MIT), and third party notice files
   recording "Copyright (c) 2017 Thomas Kluyver".
   Saved as licenses/mit-pyproject_hooks-LICENSE.txt.
7. resolvelib 1.0.1: ISC. Evidence: third party license listings for resolvelib
   ("ISC License, Copyright Tzu-ping Chung"), ISC classifiers in notice reports,
   and the Fedora python-pip spec license roll up, which includes ISC for the
   vendored set. ISC text: canonical text as published by SPDX and the Internet
   Systems Consortium. Saved as licenses/isc-resolvelib-LICENSE.txt.
8. rich 13.4.2: MIT. Evidence: Oracle's rich attribution page printing rich's
   LICENSE ("Copyright (c) 2020 Will McGugan" over the MIT text), GitHub SBOM
   records (rich, MIT, "Copyright (c) 2020 Will McGugan" plus "Copyright (c)
   Sindre Sorhus" for the embedded cli-spinners data in rich/_spinners.py, which
   prints verbatim with the file), and the Debian copyright file for rich.
   Saved as licenses/mit-rich-LICENSE.txt.
9. truststore 0.8.0: MIT. Evidence: the truststore LICENSE file itself, recovered
   verbatim from a later pip's vendored copy ("The MIT License (MIT), Copyright
   (c) 2022 Seth Michael Larson"), Ren'Py's license page ("truststore: Copyright
   (c) 2022 Seth Michael Larson"), and Gentoo's truststore record (LICENSE="MIT").
   Saved as licenses/mit-truststore-LICENSE.txt.
10. typing_extensions 4.7.1: Python Software Foundation License. Evidence:
    NetApp notice reports ("py3-typing-extensions, Python Software Foundation
    License 2.0") and Oracle Solaris' pip license file, which prints
    typing_extensions under "PYTHON SOFTWARE FOUNDATION LICENSE VERSION 2".
    The PSF text printed in this appendix is the distlib LICENSE.txt document
    below, which is the Python license file carrying that grant.

Result: ten of ten cured, none left out.

## Class A fetched texts (license file not present in the venv)

- distlib 0.3.8 (PSF): LICENSE.txt is the Python license document. Recovered in
  full from a mirror of the official pypa/distlib GitHub file (LICENSE.txt at
  0.3.0; the file is unchanged in kind through 0.3.8 per the distlib deepwiki
  record of distlib-0.3.8.dist-info/LICENSE.txt, 285 lines), cross-checked
  against this machine's Python 3.12 LICENSE.txt for the shared sections.
  Saved as licenses/psf-distlib-LICENSE.txt. Vendored header on disk in the
  venv: "Copyright (C) 2012-2023 Vinay Sajip. Licensed to the Python Software
  Foundation under a contributor agreement."
- colorama 0.4.6 (BSD 3-Clause): LICENSE.txt identified by the OpenEmbedded
  recipe checksum record for the 0.4.6 release (LICENSE = BSD-3-Clause,
  LIC_FILES_CHKSUM md5 b4936429a56a652b84c5c01280dcaa26), the package metadata
  (License-Expression: BSD-3-Clause, License-File: LICENSE.txt), and the header
  grant inside the vendored files ("Copyright Jonathan Hartley 2013. BSD
  3-Clause license"). The direct GitHub fetch of the file failed with an HTTP
  503 on 2026-11-24 and was not retried; the printed text is the BSD 3-Clause
  text under colorama's notice, "Copyright (c) 2013, Jonathan Hartley".
  Saved as licenses/bsd3-colorama-LICENSE.txt.
- Pygments 2.15.1 (BSD 2-Clause): license identity and file checksum from the
  OpenEmbedded recipe for exactly 2.15.1 (LICENSE = BSD-2-Clause,
  LIC_FILES_CHKSUM md5 36a13c90514e2899f1eba7f41c3ee592). Notice wording follows
  the project's LICENSE file as recorded by the Debian copyright file and by
  license scanners of later releases: "Copyright (c) 2006-2023 by the
  respective authors (see AUTHORS file)." (The audit's shorthand said "by the
  Pygments team"; the file's own wording is the respective authors line.)
  Saved as licenses/bsd2-pygments-LICENSE.txt.
- webencodings 0.5.1 (BSD 3-Clause): OpenEmbedded recipe for 0.5.1 records
  LICENSE = BSD-3-Clause (PKG-INFO license line checksum e910b35b0ef4e1f665b9a75d6afb7709);
  SUSE likewise records BSD-3-Clause for 0.5.1. Notice from the package's own
  file headers in the venv: "Copyright 2012 by Simon Sapin".
  Saved as licenses/bsd3-webencodings-LICENSE.txt.
- Apache License 2.0 text: system copy /usr/share/common-licenses/Apache-2.0,
  cross-checked against apache.org (http://www.apache.org/licenses/LICENSE-2.0.html).
  Saved as licenses/apache-2.0.txt.
- LGPL 2.1 text (chardet, Class B): system copy /usr/share/common-licenses/LGPL-2.1.
  Saved as licenses/lgpl-2.1.txt.

## On-disk license files copied from the venv itself

bsd3-scikit-learn-COPYING.txt, bsd3-joblib-LICENSE.txt, bsd3-cloudpickle-LICENSE.txt,
bsd3-threadpoolctl-LICENSE.txt, mit-narwhals-LICENSE.md, mit-pip-LICENSE.txt,
pip-AUTHORS.txt, mit-array_api_compat-LICENSE.txt, mit-array_api_extra-LICENSE.txt.
