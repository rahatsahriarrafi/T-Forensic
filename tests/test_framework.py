"""Framework: lab, plugins, playbooks."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tforensic.casedb import create_case
from tforensic.framework.lab import LabWorkspace
from tforensic.framework.plugin import discover_plugins, list_plugins, run_plugin
from tforensic.framework.playbook import list_playbooks, run_playbook


class FrameworkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = create_case("FW", examiner="t", cases_root=self.root)
        img = self.root / "a.bin"
        img.write_bytes(b"data")
        self.ev = self.db.add_evidence(img, kind="unknown")
        self.db.upsert_file(
            self.ev["id"],
            {"path": "/secret_password.txt", "name": "secret_password.txt", "size": 4},
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_lab_and_plugins(self):
        lab = LabWorkspace(self.db)
        st = lab.enable(virtual_write=True)
        self.assertTrue(st.enabled)
        self.assertTrue(st.virtual_write)
        self.assertTrue(st.cache_file)

        discover_plugins()
        names = {p["name"] for p in list_plugins()}
        self.assertIn("strings_hunt", names)
        self.assertIn("correlate", names)

        res = run_plugin("strings_hunt", self.db, evidence_id=self.ev["id"])
        self.assertTrue(res.ok)
        self.assertTrue(res.files_written)

        res2 = run_plugin("correlate", self.db)
        self.assertTrue(res2.ok)

    def test_playbooks_listed(self):
        pbs = {p["name"] for p in list_playbooks() if not p.get("error")}
        self.assertIn("quick_triage", pbs)
        self.assertIn("deep_lab", pbs)


if __name__ == "__main__":
    unittest.main()
