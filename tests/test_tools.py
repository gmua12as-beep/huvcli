from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from huvcli.tools import (
    ToolContext,
    apply_patch,
    call_tool,
    edit_file,
    glob_files,
    grep,
    list_files,
    read_file,
    read_files,
    run_command,
    update_plan,
)


def _ctx(root: Path, **kwargs) -> ToolContext:
    return ToolContext(cwd=root, yes=True, **kwargs)


class ApplyPatchTests(unittest.TestCase):
    def test_apply_patch_updates_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "hello.txt").write_text("one\ntwo\n", encoding="utf-8")
            ctx = _ctx(root)
            result = apply_patch(
                ctx,
                "--- hello.txt\n+++ hello.txt\n@@ -1,2 +1,2 @@\n one\n-two\n+three\n",
            )
            self.assertIn("Patched hello.txt", result)
            self.assertEqual((root / "hello.txt").read_text(encoding="utf-8"), "one\nthree\n")

    def test_apply_patch_creates_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ctx = _ctx(root)
            apply_patch(
                ctx,
                "--- /dev/null\n+++ new.txt\n@@ -0,0 +1,2 @@\n+alpha\n+beta\n",
            )
            self.assertEqual((root / "new.txt").read_text(encoding="utf-8"), "alpha\nbeta\n")

    def test_apply_patch_blocks_outside_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ctx = _ctx(root)
            with self.assertRaises(ValueError):
                apply_patch(ctx, "--- ../x\n+++ ../x\n@@ -0,0 +1 @@\n+bad\n")

    def test_fuzzy_locator_handles_shifted_line_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.txt").write_text("A\nB\nC\nD\nE\n", encoding="utf-8")
            ctx = _ctx(root)
            # Hunk header says lines 1-3 but content lives at lines 3-5.
            apply_patch(
                ctx,
                "--- a.txt\n+++ a.txt\n@@ -1,3 +1,3 @@\n C\n-D\n+DD\n E\n",
            )
            self.assertEqual((root / "a.txt").read_text(encoding="utf-8"), "A\nB\nC\nDD\nE\n")

    def test_blank_line_treated_as_context(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.txt").write_text("A\n\nB\n", encoding="utf-8")
            ctx = _ctx(root)
            apply_patch(
                ctx,
                "--- a.txt\n+++ a.txt\n@@ -1,3 +1,3 @@\n A\n\n-B\n+BB\n",
            )
            self.assertEqual((root / "a.txt").read_text(encoding="utf-8"), "A\n\nBB\n")

    def test_crlf_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "w.txt").write_bytes(b"one\r\ntwo\r\nthree\r\n")
            ctx = _ctx(root)
            apply_patch(
                ctx,
                "--- w.txt\n+++ w.txt\n@@ -1,3 +1,3 @@\n one\n-two\n+TWO\n three\n",
            )
            self.assertEqual((root / "w.txt").read_bytes(), b"one\r\nTWO\r\nthree\r\n")

    def test_begin_patch_envelope_update(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "c.txt").write_text("alpha\nbeta\n", encoding="utf-8")
            ctx = _ctx(root)
            apply_patch(
                ctx,
                "*** Begin Patch\n*** Update File: c.txt\n@@ -1,2 +1,2 @@\n alpha\n-beta\n+BETA\n*** End Patch",
            )
            self.assertEqual((root / "c.txt").read_text(encoding="utf-8"), "alpha\nBETA\n")

    def test_begin_patch_envelope_add(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ctx = _ctx(root)
            apply_patch(
                ctx,
                "*** Begin Patch\n*** Add File: new.txt\n+line1\n+line2\n*** End Patch",
            )
            self.assertTrue((root / "new.txt").exists())


class EditFileTests(unittest.TestCase):
    def test_requires_prior_read(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.py").write_text("hello\n", encoding="utf-8")
            ctx = _ctx(root)
            with self.assertRaises(ValueError) as cm:
                edit_file(ctx, "a.py", "hello", "HI")
            self.assertIn("read_file", str(cm.exception))

    def test_detects_external_change(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "a.py"
            target.write_text("hello\n", encoding="utf-8")
            ctx = _ctx(root)
            read_file(ctx, "a.py")
            time.sleep(0.02)
            target.write_text("changed\n", encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                edit_file(ctx, "a.py", "changed", "X")
            self.assertIn("changed on disk", str(cm.exception))

    def test_rejects_ambiguous_match(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.py").write_text("foo\nfoo\n", encoding="utf-8")
            ctx = _ctx(root)
            read_file(ctx, "a.py")
            with self.assertRaises(ValueError) as cm:
                edit_file(ctx, "a.py", "foo", "X")
            self.assertIn("matches", str(cm.exception))

    def test_replace_all(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.py").write_text("foo\nfoo\nbar\n", encoding="utf-8")
            ctx = _ctx(root)
            read_file(ctx, "a.py")
            edit_file(ctx, "a.py", "foo", "X", replace_all=True)
            self.assertEqual((root / "a.py").read_text(encoding="utf-8"), "X\nX\nbar\n")

    def test_rejects_oversized_edit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "a.tsx"
            # Build a real 600-line file so freshness + locate succeed.
            lines = ["// line " + str(i) for i in range(1, 601)]
            target.write_text("\n".join(lines) + "\n", encoding="utf-8")
            ctx = _ctx(root)
            read_file(ctx, "a.tsx")
            big_old = "\n".join(lines[:300])
            big_new = "\n".join(["// NEW " + str(i) for i in range(1, 301)])
            with self.assertRaises(ValueError) as cm:
                edit_file(ctx, "a.tsx", big_old, big_new)
            msg = str(cm.exception)
            self.assertIn("too much scope", msg)
            self.assertIn("smaller targeted edits", msg)

    def test_oversized_edit_allowed_with_replace_all(self) -> None:
        # replace_all is the explicit "I know what I'm doing" override.
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "a.tsx"
            target.write_text("foo\n" * 500, encoding="utf-8")
            ctx = _ctx(root)
            read_file(ctx, "a.tsx")
            # 500 occurrences of foo → still over limit lines-wise but
            # replace_all signals intentional sweep.
            edit_file(ctx, "a.tsx", "foo", "bar", replace_all=True)
            self.assertEqual((root / "a.tsx").read_text(encoding="utf-8"), "bar\n" * 500)

    def test_preserves_crlf_and_no_trailing_newline(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.txt").write_bytes(b"one\r\ntwo\r\nthree")
            ctx = _ctx(root)
            read_file(ctx, "a.txt")
            edit_file(ctx, "a.txt", "two", "TWO")
            self.assertEqual((root / "a.txt").read_bytes(), b"one\r\nTWO\r\nthree")


class ReadFileTests(unittest.TestCase):
    def test_returns_line_numbers_and_header(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
            ctx = _ctx(root)
            out = read_file(ctx, "a.txt")
            self.assertIn("lines 1-3 of 3", out)
            self.assertIn("\talpha", out)
            self.assertIn("3\tgamma", out)

    def test_offset_and_limit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.txt").write_text("\n".join(f"L{i}" for i in range(1, 11)) + "\n", encoding="utf-8")
            ctx = _ctx(root)
            out = read_file(ctx, "a.txt", offset=3, limit=2)
            self.assertIn("lines 4-5 of 10", out)
            self.assertIn("L4", out)
            self.assertIn("L5", out)
            self.assertNotIn("L6", out)


class GlobGrepTests(unittest.TestCase):
    def test_glob_recursive(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "sub").mkdir()
            (root / "a.py").write_text("x", encoding="utf-8")
            (root / "sub" / "b.py").write_text("x", encoding="utf-8")
            (root / "ignore.md").write_text("x", encoding="utf-8")
            ctx = _ctx(root)
            out = glob_files(ctx, "**/*.py")
            self.assertIn("a.py", out)
            self.assertIn("b.py", out)
            self.assertNotIn("ignore.md", out)

    def test_grep_python_fallback_finds_match(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.py").write_text("first\nNEEDLE here\nthird\n", encoding="utf-8")
            ctx = _ctx(root)
            out = grep(ctx, "NEEDLE")
            self.assertIn("a.py", out)
            self.assertIn("NEEDLE", out)
            self.assertIn(":2:", out)

    def test_grep_no_match(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.py").write_text("nothing here\n", encoding="utf-8")
            ctx = _ctx(root)
            self.assertEqual(grep(ctx, "ZZZ"), "(no matches)")


class RunCommandTests(unittest.TestCase):
    def test_blocks_destructive_without_flag(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw))
            result = run_command(ctx, "git reset --hard")
            self.assertIn("Command blocked", result)


class UpdatePlanTests(unittest.TestCase):
    def test_records_steps_and_renders(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw))
            out = update_plan(ctx, [
                {"step": "explore", "status": "completed"},
                {"step": "implement", "status": "in_progress"},
                {"step": "test"},
            ])
            self.assertIn("[x] explore", out)
            self.assertIn("[>] implement", out)
            self.assertIn("[ ] test", out)
            self.assertEqual(len(ctx.plan), 3)

    def test_normalizes_bad_status(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw))
            update_plan(ctx, [{"step": "x", "status": "bogus"}])
            self.assertEqual(ctx.plan[0]["status"], "pending")


class ReadFilesTests(unittest.TestCase):
    def test_batch_read_returns_one_block_per_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.txt").write_text("hello\n", encoding="utf-8")
            (root / "b.txt").write_text("world\n", encoding="utf-8")
            ctx = _ctx(root)
            out = read_files(ctx, ["a.txt", "b.txt"])
            self.assertIn("[a.txt] lines 1-1 of 1", out)
            self.assertIn("[b.txt] lines 1-1 of 1", out)
            self.assertIn("hello", out)
            self.assertIn("world", out)

    def test_batch_read_records_each_file_for_freshness(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.txt").write_text("aa\n", encoding="utf-8")
            (root / "b.txt").write_text("bb\n", encoding="utf-8")
            ctx = _ctx(root)
            read_files(ctx, ["a.txt", "b.txt"])
            # Editing either is allowed now.
            edit_file(ctx, "a.txt", "aa", "AA")
            edit_file(ctx, "b.txt", "bb", "BB")

    def test_batch_read_inlines_per_file_errors(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "ok.txt").write_text("good\n", encoding="utf-8")
            ctx = _ctx(root)
            out = read_files(ctx, ["ok.txt", "missing.txt"])
            self.assertIn("good", out)
            self.assertIn("missing.txt", out)
            self.assertIn("ERROR", out)


class ArgNormalizationTests(unittest.TestCase):
    def test_path_alias_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.txt").write_text("hi\n", encoding="utf-8")
            ctx = _ctx(root)
            # Model sends `file_path` instead of `path`.
            out = call_tool(ctx, "read_file", {"file_path": "a.txt"})
            self.assertIn("hi", out)

    def test_write_content_alias(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ctx = _ctx(root)
            # `text` alias for content, `filename` for path.
            call_tool(ctx, "write_file", {"filename": "out.txt", "text": "hello"})
            self.assertEqual((root / "out.txt").read_text(encoding="utf-8"), "hello")

    def test_missing_required_arg_has_helpful_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw))
            with self.assertRaises(ValueError) as cm:
                call_tool(ctx, "write_file", {"path": "x.txt"})  # missing content
            msg = str(cm.exception)
            self.assertIn("missing required arg", msg)
            self.assertIn("content", msg)

    def test_read_files_accepts_single_string(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.txt").write_text("hi\n", encoding="utf-8")
            ctx = _ctx(root)
            # Model sent `paths` as a string, not list.
            out = call_tool(ctx, "read_files", {"paths": "a.txt"})
            self.assertIn("hi", out)

    def test_empty_args_error_includes_example(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw))
            with self.assertRaises(ValueError) as cm:
                call_tool(ctx, "write_file", {})
            msg = str(cm.exception)
            self.assertIn("NO arguments", msg)
            self.assertIn("Example", msg)
            self.assertIn("path", msg)
            self.assertIn("content", msg)

    def test_partial_args_error_includes_example(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw))
            with self.assertRaises(ValueError) as cm:
                call_tool(ctx, "edit_file", {"path": "x"})  # missing old/new
            msg = str(cm.exception)
            self.assertIn("Example", msg)
            self.assertIn("old_string", msg)

    def test_apply_patch_error_message_is_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw))
            with self.assertRaises(ValueError) as cm:
                apply_patch(ctx, "this is not a diff")
            self.assertIn("unified-diff form", str(cm.exception))
            self.assertIn("edit_file", str(cm.exception))


class HardeningTests(unittest.TestCase):
    def test_read_file_rejects_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "sub").mkdir()
            ctx = _ctx(root)
            with self.assertRaises(ValueError) as cm:
                read_file(ctx, "sub")
            self.assertIn("directory", str(cm.exception))

    def test_read_file_rejects_huge_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            target = root / "big.bin"
            # Create sparse-ish 11 MB file.
            with target.open("wb") as f:
                f.seek(11 * 1024 * 1024)
                f.write(b"x")
            ctx = _ctx(root)
            with self.assertRaises(ValueError) as cm:
                read_file(ctx, "big.bin")
            self.assertIn("too large", str(cm.exception))

    def test_grep_skips_binary_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.py").write_text("NEEDLE in text\n", encoding="utf-8")
            (root / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"NEEDLE" * 100)
            (root / "blob.bin").write_bytes(b"NEEDLE\x00more")
            ctx = _ctx(root)
            out = grep(ctx, "NEEDLE")
            self.assertIn("a.py", out)
            self.assertNotIn("img.png", out)
            self.assertNotIn("blob.bin", out)

    def test_grep_bad_regex_raises(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            ctx = _ctx(Path(raw))
            with self.assertRaises(ValueError):
                grep(ctx, "[unterminated")


class ChangeTrackingTests(unittest.TestCase):
    def test_write_file_records_added(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ctx = _ctx(root)
            from huvcli.tools import write_file
            write_file(ctx, "new.txt", "alpha\nbeta\n")
            self.assertIn("new.txt", ctx.changes)
            self.assertEqual(ctx.changes["new.txt"]["action"], "added")
            self.assertEqual(ctx.changes["new.txt"]["adds"], 2)

    def test_edit_file_records_modified_with_counts(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.py").write_text("one\ntwo\nthree\n", encoding="utf-8")
            ctx = _ctx(root)
            read_file(ctx, "a.py")
            edit_file(ctx, "a.py", "two", "TWO")
            entry = ctx.changes["a.py"]
            self.assertEqual(entry["action"], "modified")
            self.assertEqual(entry["adds"], 1)
            self.assertEqual(entry["dels"], 1)

    def test_apply_patch_records_added_and_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ctx = _ctx(root)
            apply_patch(
                ctx,
                "--- /dev/null\n+++ new.txt\n@@ -0,0 +1,2 @@\n+alpha\n+beta\n",
            )
            self.assertEqual(ctx.changes["new.txt"]["action"], "added")
            # Now delete it via patch.
            apply_patch(
                ctx,
                "--- new.txt\n+++ /dev/null\n",
            )
            self.assertEqual(ctx.changes["new.txt"]["action"], "deleted")

    def test_added_stays_added_on_subsequent_edit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            ctx = _ctx(root)
            from huvcli.tools import write_file
            write_file(ctx, "n.txt", "x\n")
            read_file(ctx, "n.txt")
            edit_file(ctx, "n.txt", "x", "y")
            self.assertEqual(ctx.changes["n.txt"]["action"], "added")


class ListFilesTests(unittest.TestCase):
    def test_skips_known_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("x", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "huge.js").write_text("x", encoding="utf-8")
            ctx = _ctx(root)
            out = list_files(ctx)
            self.assertIn("a.py", out)
            # node_modules excluded by walk; git ls-files returns nothing in non-repo,
            # so we go through walk path here.
            self.assertNotIn("huge.js", out)
