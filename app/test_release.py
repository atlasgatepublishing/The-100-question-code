"""Tests for release.py -- the release integrity manifest.

Runs against a throwaway copy of the app in a temp directory; the real
install is never touched. Stdlib only.

    python test_release.py        (or: python -m unittest test_release)
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

import release  # noqa: E402


def _copy_app(dst: Path) -> Path:
    def _ignore(_dir, names):
        return [n for n in names
                if n == "__pycache__" or n.endswith(".pyc")
                or n == "config.local.json" or n.startswith("config.local.json.")
                or n in (release.CHECKSUMS_NAME, release.MANIFEST_NAME)
                or n.endswith(".tmp")]
    shutil.copytree(APP_DIR, dst, ignore=_ignore)
    return dst


class ReleaseManifestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.app = _copy_app(Path(self._tmp.name) / "app")

    def tearDown(self):
        self._tmp.cleanup()

    def test_build_then_verify_ok(self):
        manifest = release.write_outputs(self.app)
        self.assertEqual(manifest["version"], release.VERSION)
        self.assertTrue(manifest["files"], "file set must not be empty")
        self.assertIn("release.py", manifest["files"])
        self.assertIn("run.py", manifest["files"])
        self.assertIn("state/README.txt", manifest["files"])
        self.assertNotIn("config.local.json", manifest["files"])
        self.assertTrue((self.app / release.CHECKSUMS_NAME).is_file())
        self.assertTrue((self.app / release.MANIFEST_NAME).is_file())
        ok, problems = release.verify(self.app)
        self.assertTrue(ok, f"verify should pass on a fresh build: {problems}")
        self.assertEqual(problems, [])

    def test_flipped_byte_fails_and_names_file(self):
        release.write_outputs(self.app)
        target = self.app / "run.py"
        data = bytearray(target.read_bytes())
        data[0] ^= 0xFF
        target.write_bytes(bytes(data))
        ok, problems = release.verify(self.app)
        self.assertFalse(ok)
        self.assertTrue(any("run.py" in p for p in problems), problems)

    def test_deleted_file_fails(self):
        release.write_outputs(self.app)
        (self.app / "run.py").unlink()
        ok, problems = release.verify(self.app)
        self.assertFalse(ok)
        self.assertTrue(any("run.py" in p for p in problems), problems)

    def test_unlisted_extra_file_fails(self):
        release.write_outputs(self.app)
        (self.app / "sneaky_extra.py").write_text("# not in the manifest\n")
        ok, problems = release.verify(self.app)
        self.assertFalse(ok)
        self.assertTrue(any("sneaky_extra.py" in p for p in problems), problems)

    def test_excluded_files_are_not_flagged(self):
        release.write_outputs(self.app)
        # User-local / generated files are outside the file set by design.
        (self.app / "config.local.json").write_text("{}")
        (self.app / "state" / "app_state.json").write_text("{}")
        (self.app / "reports" / "output" / "2099-01-01.md").write_text("x")
        (self.app / "scratch.tmp").write_text("x")
        ok, problems = release.verify(self.app)
        self.assertTrue(ok, problems)


if __name__ == "__main__":
    unittest.main(verbosity=2)
