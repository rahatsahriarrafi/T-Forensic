"""Tests for persistent case DB + ingest modules (no real evidence required)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tforensic.casedb import CaseDB, create_case, list_cases
from tforensic.ingest.modules import artifacts, keyword
from tforensic.report import generate_html_report
from tforensic.case_ops import export_case_zip


class CaseDBTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_add_tag_report(self):
        db = create_case("Unit Case", examiner="tester", cases_root=self.root)
        info = db.info()
        self.assertEqual(info.name, "Unit Case")
        self.assertTrue((self.root / info.id / "case.db").is_file())

        # fake evidence file
        img = self.root / "sample.bin"
        img.write_bytes(b"MZ" + b"\x00" * 100)
        ev = db.add_evidence(img, kind="raw")
        self.assertEqual(ev["kind"], "raw")
        self.assertTrue(ev["sha256"])

        fid = db.upsert_file(
            ev["id"],
            {"path": "/Windows/System32/notepad.exe", "name": "notepad.exe", "size": 1024},
        )
        db.add_tag(fid, "notable")
        db.add_note("test note", file_id=fid)
        db.add_bookmark(fid, "notepad")
        db.add_timeline_event(
            {
                "evidence_id": ev["id"],
                "file_id": fid,
                "ts": 1_700_000_000,
                "event_type": "mtime",
                "source": "test",
                "description": "test event",
                "path": "/Windows/System32/notepad.exe",
            }
        )
        db.import_hash_set("unit", ["d41d8cd98f00b204e9800998ecf8427e"], kind="known", algo="md5")
        self.assertEqual(db.stats()["files"], 1)
        self.assertTrue(list_cases(self.root))

        charts = db.chart_data()
        self.assertEqual(charts["metrics"]["files"], 1)
        self.assertTrue(any(x["label"] == "exe" for x in charts["extensions"]))
        self.assertTrue(charts["timeline"])

        report = generate_html_report(db)
        self.assertTrue(Path(report).is_file())
        self.assertIn("Unit Case", Path(report).read_text(encoding="utf-8"))

        z = export_case_zip(db)
        self.assertTrue(Path(z).is_file())

    def test_artifact_module(self):
        db = create_case("Mod Case", cases_root=self.root)
        img = self.root / "x.dd"
        img.write_bytes(b"raw")
        ev = db.add_evidence(img, kind="raw")
        db.upsert_file(ev["id"], {"path": "/Users/a/NTUSER.DAT", "name": "NTUSER.DAT", "size": 10})
        db.upsert_file(ev["id"], {"path": "/Users/a/History", "name": "History", "size": 10})
        db.upsert_file(ev["id"], {"path": "/secret_password.txt", "name": "secret_password.txt", "size": 5})

        def cb(p, m, e=None):
            pass

        r = artifacts.run(db, ev["id"], cb)
        self.assertGreaterEqual(r["hits"], 1)
        r2 = keyword.run(db, ev["id"], cb)
        self.assertGreaterEqual(r2["hits"], 1)
        arts = db.list_artifacts()
        self.assertTrue(arts)


if __name__ == "__main__":
    unittest.main()
