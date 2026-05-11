from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from huvcli.tools import ToolContext, apply_patch, run_command


class ToolTests(unittest.TestCase):
    def test_apply_patch_updates_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "hello.txt").write_text("one\ntwo\n", encoding="utf-8")
            ctx = ToolContext(cwd=root, yes=True)
            result = apply_patch(
                ctx,
                "--- hello.txt\n"
                "+++ hello.txt\n"
                "@@ -1,2 +1,2 @@\n"
                " one\n"
                "-two\n"
                "+three\n",
            )
            self.assertIn("Patched hello.txt", result)
            self.assertEqual((root / "hello.txt").read_text(encoding="utf-8"), "one\nthree\n")

    def test_apply_patch_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ctx = ToolContext(cwd=root, yes=True)
            apply_patch(
                ctx,
                "--- /dev/null\n"
                "+++ new.txt\n"
                "@@ -0,0 +1,2 @@\n"
                "+alpha\n"
                "+beta\n",
            )
            self.assertEqual((root / "new.txt").read_text(encoding="utf-8"), "alpha\nbeta\n")

    def test_apply_patch_blocks_outside_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ctx = ToolContext(cwd=root, yes=True)
            with self.assertRaises(ValueError):
                apply_patch(ctx, "--- ../x\n+++ ../x\n@@ -0,0 +1 @@\n+bad\n")

    def test_run_command_blocks_destructive_without_flag(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = ToolContext(cwd=Path(raw), yes=True)
            result = run_command(ctx, "git reset --hard")
            self.assertIn("Command blocked", result)
