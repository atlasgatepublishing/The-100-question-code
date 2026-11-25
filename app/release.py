"""Release integrity manifest for the Atlas Gate stock app.

Stdlib only. Builds and verifies a SHA-256 manifest of every shipped
file so a user can check that the copy they downloaded is the copy that
was published (see README.md, "For the publisher").

Usage:
    python release.py build    -> write CHECKSUMS.sha256 + release_manifest.json
    python release.py verify   -> recompute and compare; exit 0 if clean, 1 if not

File set: every file under the app directory EXCEPT
  * config.local.json and config.local.json.*   (the user's own keys/config)
  * state/** except state/README.txt            (live pot state)
  * __pycache__/** and *.pyc                    (bytecode caches)
  * CHECKSUMS.sha256 and release_manifest.json  (this tool's own outputs)
  * reports/output/** except a README if present (generated reports)
  * *.tmp                                       (temp files)
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

VERSION = "1.2.0"

CHECKSUMS_NAME = "CHECKSUMS.sha256"
MANIFEST_NAME = "release_manifest.json"


def _is_included(rel: Path) -> bool:
    """True when the app-relative path `rel` belongs in the release file set."""
    parts = rel.parts
    name = rel.name
    if name == "config.local.json" or name.startswith("config.local.json."):
        return False
    if name in (CHECKSUMS_NAME, MANIFEST_NAME):
        return False
    if "__pycache__" in parts:
        return False
    if name.endswith(".pyc"):
        return False
    if name.endswith(".tmp"):
        return False
    # state/** except state/README.txt
    if parts[0] == "state":
        return rel.as_posix() == "state/README.txt"
    # reports/output/** except a README if present
    if len(parts) >= 2 and parts[0] == "reports" and parts[1] == "output":
        return name.startswith("README")
    return True


def _iter_files(app_dir: Path):
    app_dir = Path(app_dir)
    for p in sorted(app_dir.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(app_dir)
        if _is_included(rel):
            yield rel, p


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical_files_hash(files: dict) -> str:
    canonical = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_manifest(app_dir) -> dict:
    """Return {"version", "files", "manifest_sha256"} for `app_dir`."""
    app_dir = Path(app_dir)
    files = {}
    for rel, p in _iter_files(app_dir):
        files[rel.as_posix()] = _sha256_file(p)
    files = dict(sorted(files.items()))
    return {
        "version": VERSION,
        "files": files,
        "manifest_sha256": _canonical_files_hash(files),
    }


def write_outputs(app_dir) -> dict:
    """Build the manifest and write CHECKSUMS.sha256 + release_manifest.json."""
    app_dir = Path(app_dir)
    manifest = build_manifest(app_dir)
    lines = [f"{digest}  {relpath}"
             for relpath, digest in sorted(manifest["files"].items())]
    (app_dir / CHECKSUMS_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    (app_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def verify(app_dir) -> tuple[bool, list[str]]:
    """Recompute the file set and compare it with the stored manifest.

    Returns (ok, problems). Each problem is a plain-language string naming
    the file: missing, changed, or an unlisted extra file in the file set.
    """
    app_dir = Path(app_dir)
    problems: list[str] = []
    manifest_path = app_dir / MANIFEST_NAME
    checksums_path = app_dir / CHECKSUMS_NAME
    if not manifest_path.is_file():
        return False, [f"{MANIFEST_NAME} is missing -- run: python release.py build"]
    if not checksums_path.is_file():
        problems.append(f"{CHECKSUMS_NAME} is missing -- run: python release.py build")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        return False, problems + [f"{MANIFEST_NAME} could not be read ({type(e).__name__}: {e})"]
    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        return False, problems + [f"{MANIFEST_NAME} has an unexpected shape"]
    listed: dict = manifest["files"]

    # The manifest's own self-hash must match its file list.
    if manifest.get("manifest_sha256") != _canonical_files_hash(listed):
        problems.append(f"{MANIFEST_NAME}: manifest_sha256 does not match its file list")

    # CHECKSUMS.sha256, when present, must agree with the manifest.
    if checksums_path.is_file():
        try:
            seen = {}
            for line in checksums_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                digest, _, relpath = line.partition("  ")
                seen[relpath.strip()] = digest.strip()
            if seen != listed:
                problems.append(f"{CHECKSUMS_NAME} does not match {MANIFEST_NAME}")
        except Exception as e:
            problems.append(f"{CHECKSUMS_NAME} could not be read ({type(e).__name__}: {e})")

    current = build_manifest(app_dir)["files"]
    for relpath in sorted(listed):
        if relpath not in current:
            problems.append(f"missing file: {relpath}")
        elif current[relpath] != listed[relpath]:
            problems.append(f"changed file: {relpath}")
    for relpath in sorted(current):
        if relpath not in listed:
            problems.append(f"unlisted extra file: {relpath}")
    return (not problems), problems


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    app_dir = Path(__file__).resolve().parent
    if len(argv) != 1 or argv[0] not in ("build", "verify"):
        print("usage: python release.py build|verify", file=sys.stderr)
        return 2
    if argv[0] == "build":
        manifest = write_outputs(app_dir)
        print(f"release {manifest['version']}: wrote {CHECKSUMS_NAME} and "
              f"{MANIFEST_NAME} for {len(manifest['files'])} files")
        print(f"manifest_sha256: {manifest['manifest_sha256']}")
        return 0
    ok, problems = verify(app_dir)
    if ok:
        manifest = json.loads((app_dir / MANIFEST_NAME).read_text(encoding="utf-8"))
        print(f"release verify OK: {len(manifest.get('files', {}))} files match "
              f"{MANIFEST_NAME} (version {manifest.get('version', '?')})")
        return 0
    print("release verify FAILED:")
    for problem in problems:
        print(f"  - {problem}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
