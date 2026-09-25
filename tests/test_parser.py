"""AD1 parser + case/workspace tests."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

from ad1_fixture import build_sample_ad1  # noqa: E402
from tforensic.ad1.parser import AD1  # noqa: E402
from tforensic.analysis import classify_artifacts, hashes, is_executable  # noqa: E402
from tforensic.case import open_case  # noqa: E402
from tforensic.workspace import cleanup_session  # noqa: E402


class TestAD1Parser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.files = [
            ("hello.txt", b"hello world from T Forensic\n"),
            ("readme.txt", b"AD1 test payload " * 8),
            ("malware.exe", b"MZ" + b"\x00" * 64),
        ]
        cls.tmp = tempfile.NamedTemporaryFile(suffix=".ad1", delete=False)
        cls.tmp.write(build_sample_ad1(cls.files))
        cls.tmp.flush()
        cls.tmp.close()
        cls.img = AD1(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.img.close()
        os.unlink(cls.tmp.name)

    def test_root(self):
        self.assertEqual(self.img.root.name, "SAMPLE")
        self.assertTrue(self.img.root.is_dir)
        self.assertEqual(len(self.img.root.children), 3)

    def test_roundtrip(self):
        by_name = {c.name: c for c in self.img.root.children}
        for name, payload in self.files:
            data = self.img.read_file(by_name[name])
            self.assertEqual(data, payload)

    def test_hashes_and_exe(self):
        by_name = {c.name: c for c in self.img.root.children}
        data = self.img.read_file(by_name["malware.exe"])
        self.assertTrue(is_executable(data))
        h = hashes(data)
        self.assertEqual(h["size"], len(data))
        self.assertEqual(len(h["sha256"]), 64)

    def test_artifacts(self):
        hits = classify_artifacts(self.img.root.children)
        labels = {h["label"] for h in hits}
        self.assertIn("Executable", labels)


class TestWorkspace(unittest.TestCase):
    def test_session_lifecycle(self):
        raw = build_sample_ad1([("a.txt", b"abc")])
        with tempfile.NamedTemporaryFile(suffix=".ad1", delete=False) as f:
            f.write(raw)
            path = f.name
        try:
            with tempfile.TemporaryDirectory() as root:
                os.environ["TFOR_SESSION_ROOT"] = root
                case = open_case(path)
                self.assertTrue(os.path.isdir(case.meta.temp_dir))
                self.assertTrue(
                    os.path.isfile(os.path.join(case.meta.temp_dir, "session.json"))
                )
                self.assertEqual(case.img.root.name, "SAMPLE")
                exported = case.export_file("SAMPLE/a.txt")
                self.assertTrue(os.path.isfile(exported))
                self.assertEqual(Path(exported).read_bytes(), b"abc")
                sid = case.meta.id
                case.close()
                cleanup_session(sid)
                self.assertFalse(os.path.isdir(os.path.join(root, sid)))
        finally:
            os.unlink(path)
            os.environ.pop("TFOR_SESSION_ROOT", None)


if __name__ == "__main__":
    unittest.main()
