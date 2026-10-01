"""ShellBags / EXIF smoke tests for Q9-style questions."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from tforensic.shellbags_view import parse_shellbags  # noqa: E402
from tforensic.accessors import open_with_accessor  # noqa: E402

UC = Path(
    "/home/nullx-a/CyberDefenders/AfricanFalls Lab/root/Users/John Doe/"
    "AppData/Local/Microsoft/Windows/UsrClass.dat"
)
JPG = Path(
    "/home/nullx-a/CyberDefenders/AfricanFalls Lab/root/Users/John Doe/"
    "Pictures/Contact/20210429_151535.jpg"
)


class ShellbagsTests(unittest.TestCase):
    @unittest.skipUnless(UC.is_file(), "UsrClass.dat missing")
    def test_dcim_camera_chain(self):
        info = parse_shellbags(UC.read_bytes(), name="UsrClass.dat")
        names = {e.get("name") for e in info.get("entries") or []}
        self.assertIn("LG Q7", names)
        self.assertIn("DCIM", names)
        self.assertIn("Camera", names)
        r = open_with_accessor(str(UC), UC.read_bytes())
        self.assertEqual(r.accessor, "shellbags")
        joined = " ".join(str(x) for row in (r.rows or []) for x in row)
        self.assertIn("Camera", joined)

    @unittest.skipUnless(JPG.is_file(), "sample jpg missing")
    def test_exif_lg_phone(self):
        r = open_with_accessor(str(JPG), JPG.read_bytes())
        self.assertIn(r.accessor, {"exif", "image"})
        if r.accessor == "exif":
            blob = " ".join(str(x) for row in (r.rows or []) for x in row).upper()
            self.assertTrue("LG" in blob or "LM-Q725" in blob or "MAKE" in blob)


if __name__ == "__main__":
    unittest.main()
