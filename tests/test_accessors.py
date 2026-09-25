"""Extension accessor tests."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "engine"))

from tforensic.accessors import accessor_for, open_with_accessor  # noqa: E402


class TestAccessors(unittest.TestCase):
    def test_ext_map(self):
        self.assertEqual(accessor_for("a/b/note.txt"), "text")
        self.assertEqual(accessor_for("pic.PNG"), "image")
        self.assertEqual(accessor_for("data.json"), "json")
        self.assertEqual(accessor_for("app.exe"), "pe")
        self.assertEqual(accessor_for("hist.sqlite"), "sqlite")

    def test_json_pretty(self):
        raw = json.dumps({"a": 1, "b": [2, 3]}).encode()
        r = open_with_accessor("x.json", raw)
        self.assertEqual(r.accessor, "json")
        self.assertEqual(r.mode, "json")
        self.assertIn("\n", r.text)

    def test_image_data_url(self):
        # minimal 1x1 PNG
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
            b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        r = open_with_accessor("dot.png", png)
        self.assertEqual(r.mode, "image")
        self.assertTrue(r.data_url.startswith("data:image/png;base64,"))

    def test_zip_list(self):
        buf = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
        buf.close()
        try:
            with zipfile.ZipFile(buf.name, "w") as zf:
                zf.writestr("hello.txt", "hi")
                zf.writestr("dir/a.bin", b"\x00\x01")
            data = open(buf.name, "rb").read()
            r = open_with_accessor("sample.zip", data)
            self.assertEqual(r.mode, "list")
            names = [i["name"] for i in r.items]
            self.assertIn("hello.txt", names)
        finally:
            os.unlink(buf.name)

    def test_sqlite_tables(self):
        path = tempfile.mktemp(suffix=".db")
        try:
            con = sqlite3.connect(path)
            con.execute("CREATE TABLE users (id INT, name TEXT)")
            con.execute("INSERT INTO users VALUES (1, 'alice')")
            con.commit()
            con.close()
            data = open(path, "rb").read()
            r = open_with_accessor("users.db", data)
            self.assertEqual(r.accessor, "sqlite")
            self.assertEqual(r.mode, "table")
            self.assertTrue(any(t["name"] == "users" for t in r.items))
            self.assertEqual(r.columns, ["id", "name"])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
