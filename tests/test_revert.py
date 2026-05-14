from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from huvcli.tools import (
    ToolContext,
    apply_patch,
    edit_file,
    read_file,
    revert_files,
    write_file,
)


def _ctx(root: Path) -> ToolContext:
    return ToolContext(cwd=root, yes=True)


class RevertTests(unittest.TestCase):
    def test_revert_restores_modified_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "a.py"
            target.write_text("hello\nworld\n", encoding="utf-8")
            ctx = _ctx(root)
            read_file(ctx, "a.py")
            edit_file(ctx, "a.py", "hello", "GOODBYE")
            self.assertEqual(target.read_text(encoding="utf-8"), "GOODBYE\nworld\n")

            results = revert_files(ctx, ctx.originals)
            self.assertEqual(target.read_text(encoding="utf-8"), "hello\nworld\n")
            self.assertTrue(any("restored" in line and "a.py" in line for line in results))
            # Tracking cleared.
            self.assertNotIn("a.py", ctx.originals)
            self.assertNotIn("a.py", ctx.changes)

    def test_revert_removes_added_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ctx = _ctx(root)
            write_file(ctx, "new.txt", "fresh\n")
            self.assertTrue((root / "new.txt").exists())
            revert_files(ctx, ctx.originals)
            self.assertFalse((root / "new.txt").exists())

    def test_revert_restores_deleted_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "x.txt").write_text("keep me\n", encoding="utf-8")
            ctx = _ctx(root)
            apply_patch(ctx, "--- x.txt\n+++ /dev/null\n")
            self.assertFalse((root / "x.txt").exists())
            revert_files(ctx, ctx.originals)
            self.assertEqual((root / "x.txt").read_text(encoding="utf-8"), "keep me\n")

    def test_revert_specific_path_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.py").write_text("aa\n", encoding="utf-8")
            (root / "b.py").write_text("bb\n", encoding="utf-8")
            ctx = _ctx(root)
            read_file(ctx, "a.py")
            read_file(ctx, "b.py")
            edit_file(ctx, "a.py", "aa", "AA")
            edit_file(ctx, "b.py", "bb", "BB")
            revert_files(ctx, ctx.originals, paths=["a.py"])
            self.assertEqual((root / "a.py").read_text(encoding="utf-8"), "aa\n")
            self.assertEqual((root / "b.py").read_text(encoding="utf-8"), "BB\n")
            # b.py still tracked, a.py cleared.
            self.assertIn("b.py", ctx.originals)
            self.assertNotIn("a.py", ctx.originals)

    def test_multiple_edits_revert_to_pristine(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "a.py"
            target.write_text("v1\n", encoding="utf-8")
            ctx = _ctx(root)
            read_file(ctx, "a.py")
            edit_file(ctx, "a.py", "v1", "v2")
            read_file(ctx, "a.py")  # refresh read state
            edit_file(ctx, "a.py", "v2", "v3")
            self.assertEqual(target.read_text(encoding="utf-8"), "v3\n")
            revert_files(ctx, ctx.originals)
            # Restored to v1 (first pristine), not v2.
            self.assertEqual(target.read_text(encoding="utf-8"), "v1\n")

    def test_revert_empty_originals(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw))
            out = revert_files(ctx, {})
            self.assertTrue(any("No tracked" in line for line in out))

    def test_revert_preserves_binary_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "data.bin"
            target.write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff\xfe")
            ctx = _ctx(root)
            # Simulate touching it via write_file (which goes through utf-8) —
            # we'll bypass and use the lower-level snapshot to ensure raw bytes
            # round-trip.
            from huvcli.tools import _snapshot_original
            _snapshot_original(ctx, target)
            target.write_bytes(b"corrupt")
            revert_files(ctx, ctx.originals)
            self.assertEqual(target.read_bytes(), b"\x89PNG\r\n\x1a\n\x00\xff\xfe")
