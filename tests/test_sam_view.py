"""SAM NTLM dump + AD1 $DSC hive file reclassification tests."""
from __future__ import annotations

import hashlib
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from tforensic.accessors import accessor_for, open_with_accessor  # noqa: E402
from tforensic.sam_view import dump_sam_hashes  # noqa: E402

LAB = "/home/nullx-a/CyberDefenders/AfricanFalls Lab/DiskDrigger.ad1"
SAM_PATH = (
    "Custom Content Image([Multi])/001Win10.e01:Partition 2 [50647MB]:NONAME [NTFS]/"
    "[root]/Windows/System32/config/SAM"
)
SYS_PATH = (
    "Custom Content Image([Multi])/001Win10.e01:Partition 2 [50647MB]:NONAME [NTFS]/"
    "[root]/Windows/System32/config/SYSTEM"
)
JOHN_NT = "ecf53750b76cc9a62057ca85ff4c850e"


@unittest.skipUnless(os.path.isfile(LAB), "AfricanFalls DiskDrigger.ad1 missing")
class TestSamHiveLab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tforensic.case import open_case

        cls.case = open_case(LAB)

    @classmethod
    def tearDownClass(cls):
        cls.case.close()

    def test_sam_is_file_not_dir(self):
        sam = self.case.get(SAM_PATH)
        self.assertIsNotNone(sam)
        self.assertFalse(sam.is_dir)
        self.assertEqual(sam.size, 65536)
        data = self.case.read(SAM_PATH)
        self.assertEqual(data[:4], b"regf")
        self.assertEqual(len(data), 65536)

    def test_john_doe_ntlm_and_password(self):
        sam = self.case.read(SAM_PATH)
        system = self.case.read(SYS_PATH)
        info = dump_sam_hashes(sam, system, crack=True)
        self.assertIsNone(info.get("error"), info.get("error"))
        by_name = {u["username"]: u for u in info["users"]}
        self.assertIn("John Doe", by_name)
        self.assertEqual(by_name["John Doe"]["nt_hash"], JOHN_NT)
        self.assertEqual(
            hashlib.new("md4", "ctf2021".encode("utf-16le")).hexdigest(),
            JOHN_NT,
        )
        self.assertEqual(by_name["John Doe"].get("password"), "ctf2021")
        self.assertIn((info.get("crack") or {}).get("tool"), {"john", "hashcat"})

    def test_accessor_sam(self):
        self.assertEqual(accessor_for("Windows/System32/config/SAM"), "sam")
        sam = self.case.read(SAM_PATH)
        system = self.case.read(SYS_PATH)
        r = open_with_accessor(SAM_PATH, sam, system_data=system)
        self.assertEqual(r.accessor, "sam")
        self.assertEqual(r.mode, "table")
        blob = "\n".join(f"{a} {b}" for a, b in (r.rows or []))
        self.assertIn("John Doe", blob)
        self.assertIn("ctf2021", blob)


class TestSamAccessorUnit(unittest.TestCase):
    def test_sam_without_system(self):
        r = open_with_accessor("SAM", b"regf" + b"\x00" * 32)
        self.assertEqual(r.accessor, "sam")
        self.assertTrue(any("SYSTEM" in (row[1] or "") for row in (r.rows or [])))


if __name__ == "__main__":
    unittest.main()
