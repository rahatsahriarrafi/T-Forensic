"""Dependency probe tests."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from tforensic.deps import (  # noqa: E402
    check_dependencies,
    check_requirements_txt,
    ensure_requirements,
    format_deps_text,
)


class TestDeps(unittest.TestCase):
    def test_report_shape(self):
        r = check_dependencies()
        self.assertIn("deps", r)
        self.assertIn("missing", r)
        self.assertIn("install", r)
        self.assertIn("counts", r)
        self.assertIn("requirements_ok", r)
        self.assertTrue(r["counts"]["total"] >= 10)
        text = format_deps_text(r)
        self.assertIn("TFF dependencies", text)

    def test_python_core_ok(self):
        r = check_dependencies()
        py = next(d for d in r["deps"] if d["id"] == "python3")
        self.assertTrue(py["ok"])

    def test_requirements_txt_gate(self):
        req = check_requirements_txt()
        self.assertIn("ok", req)
        self.assertTrue(req["path"].endswith("requirements.txt"))
        ok, msg = ensure_requirements()
        self.assertTrue(ok, msg)

    def test_requirements_block_message(self):
        with mock.patch("tforensic.deps._has_mod", return_value=False):
            req = check_requirements_txt()
            self.assertFalse(req["ok"])
            self.assertTrue(req["missing"])


if __name__ == "__main__":
    unittest.main()
