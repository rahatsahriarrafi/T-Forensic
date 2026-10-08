"""Folder evidence (phone file-system extraction) opens like an AD1 image."""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from tforensic.accessors import open_with_accessor  # noqa: E402
from tforensic.case import load_case, tree_dict  # noqa: E402
from tforensic.evidence import classify_evidence, open_evidence  # noqa: E402
from tforensic.folder_image import folder_manifest  # noqa: E402


class TestFolderEvidence(unittest.TestCase):
    def setUp(self):
        self._sessions = tempfile.TemporaryDirectory()
        os.environ["TFOR_SESSION_ROOT"] = self._sessions.name
        self._tmp = tempfile.TemporaryDirectory()
        phone = Path(self._tmp.name) / "android_dump"
        db_dir = phone / "data/data/com.android.providers.telephony/databases"
        db_dir.mkdir(parents=True)
        con = sqlite3.connect(db_dir / "mmssms.db")
        con.execute("CREATE TABLE sms (address TEXT, body TEXT)")
        con.execute("INSERT INTO sms VALUES ('+8801700000000', 'meet at 5')")
        con.commit()
        con.close()
        dcim = phone / "sdcard/DCIM/Camera"
        dcim.mkdir(parents=True)
        (dcim / "IMG_0001.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9")
        (phone / "sdcard/notes.txt").write_text("evidence line\n" * 10000)
        (phone / "sdcard/link_to_notes").symlink_to("notes.txt")
        self.phone = phone

    def tearDown(self):
        os.environ.pop("TFOR_SESSION_ROOT", None)
        self._tmp.cleanup()
        self._sessions.cleanup()

    def test_open_folder_like_image(self):
        self.assertEqual(classify_evidence(self.phone), "folder")
        case = open_evidence(str(self.phone))
        info = case.info()
        self.assertEqual(info["kind"], "folder")
        self.assertEqual(info["files"], 4)
        self.assertEqual(len(info["image_sha256"]), 64)

        root = case.img.root.path
        tree = tree_dict(case.img.root)
        self.assertEqual(tree["name"], "android_dump")

        notes = case.read(f"{root}/sdcard/notes.txt")
        self.assertEqual(notes, ("evidence line\n" * 10000).encode())

        # Symlinks are recorded, never followed
        self.assertEqual(case.read(f"{root}/sdcard/link_to_notes"), b"symlink -> notes.txt")

        db_path = f"{root}/data/data/com.android.providers.telephony/databases/mmssms.db"
        r = open_with_accessor(db_path, case.read(db_path))
        self.assertEqual(r.accessor, "sqlite")
        self.assertTrue(any(t["name"] == "sms" for t in r.items))

        meta = case.img.metadata(case.get(f"{root}/sdcard/DCIM/Camera/IMG_0001.jpg"))
        self.assertEqual(meta[3], "70")
        self.assertIn("Mode", meta)

        # Reload by session id (CLI / desktop restart path)
        again = load_case(info["session_id"])
        self.assertEqual(again.info()["kind"], "folder")

    def test_sqlite_wal_rows_visible(self):
        """Discord kv-storage: main DB file is empty, every row lives in the -wal."""
        import shutil

        work = Path(self._tmp.name) / "live"
        work.mkdir()
        con = sqlite3.connect(work / "a")
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA wal_autocheckpoint=0")
        con.execute("CREATE TABLE messages0 (a, data)")
        con.execute(
            "INSERT INTO messages0 VALUES (?, ?)",
            (b"\x07messages", b'{"content":"We\'ll meet at **The Mob Museum**"}'),
        )
        con.commit()
        kv = self.phone / "data/data/com.discord/files/kv-storage/@account.1"
        kv.mkdir(parents=True)
        # Copy while the writer is still open, so the WAL is not checkpointed
        shutil.copy(work / "a", kv / "a")
        shutil.copy(work / "a-wal", kv / "a-wal")
        con.close()

        case = open_evidence(str(self.phone))
        p = f"{case.img.root.path}/data/data/com.discord/files/kv-storage/@account.1/a"
        bare = open_with_accessor(p, case.read(p))
        self.assertFalse(any("Mob Museum" in str(r) for r in (bare.rows or [])))

        r = open_with_accessor(p, case.read(p), wal_data=case.read(p + "-wal"))
        self.assertEqual(r.accessor, "sqlite")
        self.assertIn("-wal merged", r.note)
        cells = [c for row in (r.rows or []) for c in row]
        self.assertTrue(any("The Mob Museum" in str(c) for c in cells), cells)
        # BLOB text shows as text, not hex
        self.assertIn("·messages", cells)

    def test_manifest_detects_change(self):
        before, _, _ = folder_manifest(self.phone)
        (self.phone / "sdcard/notes.txt").write_text("tampered")
        after, _, _ = folder_manifest(self.phone)
        self.assertNotEqual(before, after)


if __name__ == "__main__":
    unittest.main()
