"""OVA extract + prepare tests."""
from __future__ import annotations

import os
import sys
import tarfile
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from tforensic.evidence import classify_evidence  # noqa: E402
from tforensic.ova import extract_ova, is_ova_file, prepare_disk_for_xmount  # noqa: E402


class TestOVA(unittest.TestCase):
    def test_extract_picks_raw_disk(self):
        with tempfile.TemporaryDirectory() as td:
            disk = os.path.join(td, "disk.raw")
            with open(disk, "wb") as f:
                f.write(b"\x00" * 4096)
            ova = os.path.join(td, "box.ova")
            with tarfile.open(ova, "w") as tar:
                tar.add(disk, arcname="disk.raw")
                # tiny companion
                side = os.path.join(td, "notes.txt")
                open(side, "w").write("hi")
                tar.add(side, arcname="notes.txt")

            self.assertTrue(is_ova_file(ova))
            self.assertEqual(classify_evidence(ova), "ova")

            out = os.path.join(td, "extract")
            meta = extract_ova(ova, out)
            self.assertTrue(meta["primary_disk"].endswith("disk.raw"))
            path, itype = prepare_disk_for_xmount(meta["primary_disk"], os.path.join(td, "conv"))
            self.assertEqual(itype, "raw")
            self.assertTrue(os.path.isfile(path))


if __name__ == "__main__":
    unittest.main()
