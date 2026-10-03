"""Extension accessor tests."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
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
        self.assertEqual(accessor_for("data.json"), "json")
        self.assertEqual(accessor_for("app.exe"), "pe")
        self.assertEqual(accessor_for("hist.sqlite"), "sqlite")
        self.assertEqual(accessor_for("Windows/System32/config/SAM"), "sam")
        self.assertEqual(accessor_for("clip.MOD"), "media")
        self.assertEqual(accessor_for("tape.tod"), "media")

    def test_mod_mpeg_ps(self):
        # Minimal MPEG-2 Program Stream pack header (camcorder .MOD)
        data = b"\x00\x00\x01\xba" + b"\x00" * 32
        self.assertEqual(accessor_for("MOV001.MOD", data), "media")
        r = open_with_accessor("MOV001.MOD", data)
        self.assertEqual(r.accessor, "media")
        self.assertIn("MPEG", r.note)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_mod_still_frame(self):
        # Tiny MPEG-PS clip shaped like camcorder .MOD
        fd, path = tempfile.mkstemp(suffix=".mod")
        os.close(fd)
        try:
            raw = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=duration=0.5:size=160x120:rate=5",
                    "-c:v", "mpeg2video", "-q:v", "5", "-f", "vob",
                    "-y", path,
                ],
                capture_output=True,
                timeout=20,
                check=False,
            )
            self.assertEqual(raw.returncode, 0, raw.stderr.decode("utf-8", "replace"))
            with open(path, "rb") as fh:
                data = fh.read()
            self.assertGreater(len(data), 100)
            r = open_with_accessor("MOV001.MOD", data)
            self.assertEqual(r.accessor, "media")
            self.assertTrue(r.data_url.startswith("data:image/jpeg;base64,"), r.note)
            self.assertIn("Still frame", r.note)
        finally:
            os.unlink(path)

    def test_mod_tracker_music(self):
        data = bytearray(1084)
        data[1080:1084] = b"M.K."
        self.assertEqual(accessor_for("song.mod", bytes(data)), "hex")
        r = open_with_accessor("song.mod", bytes(data))
        self.assertEqual(r.mode, "hex")
        self.assertIn("Tracker", r.note)

    def test_png_exif_accessor(self):
        self.assertEqual(accessor_for("pic.PNG"), "exif")

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
    def test_jpeg_truncated_still_visible(self):
        """Phone JPEGs often exceed the old 2-4 MiB cap; cut-off bytes must not be embedded."""
        fd, path = tempfile.mkstemp(suffix=".jpg")
        os.close(fd)
        try:
            raw = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=size=3200x2400:duration=1",
                    "-frames:v", "1", "-q:v", "1", "-y", path,
                ],
                capture_output=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(raw.returncode, 0, raw.stderr.decode("utf-8", "replace"))
            with open(path, "rb") as fh:
                data = fh.read()
            # Mid-file cut (no EOI) — old code embedded this and <img> stayed blank
            trunc = data[: max(80_000, len(data) // 3)]
            if trunc.endswith(b"\xff\xd9"):
                trunc = trunc[:-2]
            r = open_with_accessor("IMG_0001.JPG", trunc)
            self.assertEqual(r.accessor, "exif")
            self.assertTrue(r.data_url.startswith("data:image/jpeg;base64,"), r.note)
            import base64
            jpg = base64.b64decode(r.data_url.split(",", 1)[1])
            self.assertEqual(jpg[:2], b"\xff\xd8")
            self.assertEqual(jpg[-2:], b"\xff\xd9")
        finally:
            os.unlink(path)

    def test_json_pretty(self):
        raw = json.dumps({"a": 1, "b": [2, 3]}).encode()
        r = open_with_accessor("x.json", raw)
        self.assertEqual(r.accessor, "json")
        self.assertEqual(r.mode, "json")
        self.assertIn("\n", r.text)

    def test_image_data_url(self):
        # minimal 1x1 PNG — routed via EXIF accessor (still embeds preview)
        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
            b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        r = open_with_accessor("dot.png", png)
        self.assertEqual(r.accessor, "exif")
        self.assertEqual(r.mode, "table")
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
            self.assertIn(r.mode, ("table", "sqlite-browser"))
            self.assertTrue(any(t["name"] == "users" for t in r.items))
            self.assertEqual(r.columns, ["id", "name"])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
