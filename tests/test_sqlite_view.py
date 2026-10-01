"""SQLite evidence browser (Autopsy-style)."""
import os
import sqlite3
import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))

from tforensic.sqlite_view import (  # noqa: E402
    browse_summary,
    list_tables,
    materialize_sqlite,
    table_rows,
    table_schema,
)


class SqliteViewTests(unittest.TestCase):
    def setUp(self):
        self.path = tempfile.mktemp(suffix=".db")
        con = sqlite3.connect(self.path)
        con.executescript(
            """
            CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);
            INSERT INTO users VALUES (1, 'alice'), (2, 'bob');
            CREATE TABLE notes (id INTEGER, body BLOB);
            INSERT INTO notes VALUES (1, X'DEADBEEF');
            """
        )
        con.close()
        self.data = open(self.path, "rb").read()

    def tearDown(self):
        try:
            os.unlink(self.path)
        except OSError:
            pass

    def test_browse(self):
        mat = materialize_sqlite("evidence/users.db", self.data)
        tables = list_tables(mat["path"])
        names = {t["name"] for t in tables}
        self.assertEqual(names, {"users", "notes"})
        rows = table_rows(mat["path"], "users", 0, 10)
        self.assertEqual(rows["columns"], ["id", "name"])
        self.assertEqual(rows["total"], 2)
        self.assertEqual(rows["rows"][0], ["1", "alice"])
        sch = table_schema(mat["path"], "users")
        self.assertTrue(any(c["name"] == "name" for c in sch["columns"]))
        summary = browse_summary(mat["path"], size=len(self.data))
        self.assertEqual(summary["mode"], "sqlite-browser")
        self.assertTrue(summary["browser"])


if __name__ == "__main__":
    unittest.main()
