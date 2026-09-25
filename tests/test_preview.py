"""Smart preview encoding detection tests."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from tforensic.preview import detect_and_decode  # noqa: E402


class TestPreview(unittest.TestCase):
    def test_utf8(self):
        r = detect_and_decode("hello café\n".encode("utf-8"))
        self.assertEqual(r.mode, "text")
        self.assertEqual(r.encoding, "utf-8")
        self.assertIn("café", r.text)

    def test_utf16_le_with_bom(self):
        raw = "Secret note\r\nline2".encode("utf-16-le")
        bom = b"\xff\xfe" + raw
        r = detect_and_decode(bom)
        self.assertEqual(r.mode, "text")
        self.assertEqual(r.encoding, "utf-16-le")
        self.assertIn("Secret note", r.text)

    def test_utf16_le_no_bom(self):
        # Classic AD1 Viewer failure: UTF-16LE without BOM looks like garbage as UTF-8.
        text = "Password=hunter2\nAdmin=true\n"
        raw = text.encode("utf-16-le")
        # Naive UTF-8 would produce mojibake / NULs embedded.
        naive = raw.decode("utf-8", "replace")
        self.assertTrue("\x00" in naive or "�" in naive or "Password" not in naive)

        r = detect_and_decode(raw)
        self.assertEqual(r.mode, "text")
        self.assertEqual(r.encoding, "utf-16-le")
        self.assertIn("Password=hunter2", r.text)

    def test_pe_goes_to_hex(self):
        data = b"MZ" + b"\x90" * 128
        r = detect_and_decode(data)
        self.assertEqual(r.mode, "hex")
        self.assertTrue(r.executable)
        self.assertIn("4d 5a", r.text)

    def test_binary_random(self):
        data = bytes(range(256)) * 4
        r = detect_and_decode(data)
        self.assertEqual(r.mode, "hex")
        self.assertEqual(r.kind, "binary")

    def test_empty(self):
        r = detect_and_decode(b"")
        self.assertEqual(r.kind, "empty")


if __name__ == "__main__":
    unittest.main()
