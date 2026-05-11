from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from huvcli.storage import append_history, ensure_workspace, recent_history, set_pref


class StorageTests(unittest.TestCase):
    def test_ensure_workspace_creates_prefs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            prefs = ensure_workspace(root)
            self.assertTrue((root / ".huvcli" / "prefs.json").exists())
            self.assertTrue(prefs["save_history"])

    def test_append_history_saves_compact_record(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            append_history(root, "hello", "done", [{"tool": "list_files", "summary": "Found 2 files."}])
            rows = recent_history(root)
            self.assertEqual(rows[0]["prompt"], "hello")
            self.assertEqual(rows[0]["answer"], "done")
            self.assertEqual(rows[0]["tools"][0]["summary"], "Found 2 files.")

    def test_save_history_pref_disables_history(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            set_pref(root, "save_history", "false")
            append_history(root, "secret", "answer", [])
            self.assertEqual(recent_history(root), [])
