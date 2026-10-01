"""Readable AD1 metadata + Recycle $I parsing."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from tforensic.meta_format import (  # noqa: E402
    format_ad1_timestamp,
    format_attrs,
    parse_recycle_i,
)


class MetaFormatTests(unittest.TestCase):
    def test_ad1_timestamp(self):
        self.assertEqual(
            format_ad1_timestamp("20210429T182217.599865"),
            "2021-04-29 18:22:17 UTC",
        )

    def test_format_attrs_labels(self):
        rows = format_attrs({"8": "20210429T182217.599865", "40968": "John Doe"})
        labels = {r["label"] for r in rows}
        self.assertIn("Modified", labels)
        self.assertIn("Owner name", labels)
        time_row = next(r for r in rows if r["label"] == "Modified")
        self.assertIn("2021-04-29 18:22:17 UTC", time_row["display"])

    def test_recycle_i(self):
        # Built from AfricanFalls $IW9BJ2Z.txt header shape (version 2)
        path = (
            Path("/home/nullx-a/CyberDefenders/AfricanFalls Lab/root/$Recycle.Bin/"
                 "S-1-5-21-3061953532-2461696977-1363062292-1001/$IW9BJ2Z.txt")
        )
        if not path.is_file():
            self.skipTest("lab extract not present")
        parsed = parse_recycle_i(path.read_bytes())
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["deleted_utc"], "2021-04-29 18:22:17 UTC")
        self.assertIn("10-million-password-list-top-100.txt", parsed["original_path"])


if __name__ == "__main__":
    unittest.main()
