"""Dependency probe tests."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from tforensic.deps import check_dependencies, format_deps_text  # noqa: E402


class TestDeps(unittest.TestCase):
    def test_report_shape(self):
        r = check_dependencies()
        self.assertIn("deps", r)
        self.assertIn("missing", r)
        self.assertIn("install", r)
        self.assertIn("counts", r)
        self.assertTrue(r["counts"]["total"] >= 10)
        text = format_deps_text(r)
        self.assertIn("TFF dependencies", text)

    def test_python_core_ok(self):
        r = check_dependencies()
        py = next(d for d in r["deps"] if d["id"] == "python3")
        self.assertTrue(py["ok"])


if __name__ == "__main__":
    unittest.main()
