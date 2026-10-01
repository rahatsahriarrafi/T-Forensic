"""Prefetch viewer tests."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from tforensic.prefetch_view import parse_prefetch  # noqa: E402
from tforensic.accessors import open_with_accessor  # noqa: E402


PF = Path(
    "/home/nullx-a/CyberDefenders/AfricanFalls Lab/root/Windows/Prefetch/"
    "TORBROWSER-INSTALL-WIN64-10.0-F3C4DF19.pf"
)


class PrefetchViewTests(unittest.TestCase):
    @unittest.skipUnless(PF.is_file(), "lab Prefetch sample missing")
    def test_tor_installer_pf(self):
        data = PF.read_bytes()
        info = parse_prefetch(data, name=PF.name)
        self.assertIsNotNone(info)
        self.assertNotIn("error", info) or self.assertTrue(info.get("executable"))
        self.assertIn("TORBROWSER-INSTALL", (info.get("executable") or "").upper())
        self.assertTrue(info.get("is_installer"))
        self.assertGreaterEqual(int(info.get("run_count") or 0), 1)
        r = open_with_accessor(str(PF), data)
        self.assertEqual(r.accessor, "prefetch")
        self.assertEqual(r.mode, "table")


if __name__ == "__main__":
    unittest.main()
