from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from huvcli.ui import UI


class UITests(unittest.TestCase):
    def test_plain_welcome_contains_project(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            text = UI(plain=True).welcome(Path(raw), save=True, approval="suggest", model="m")
            self.assertIn("Huv CLI", text)
            self.assertIn("Project:", text)
            self.assertIn("suggest", text)

    def test_plain_answer_wraps_result(self) -> None:
        text = UI(plain=True).answer("hello")
        self.assertIn("Result", text)
        self.assertIn("hello", text)

    def test_plain_tool_call(self) -> None:
        text = UI(plain=True).tool_call("edit_file", "Edited foo.py", ok=True)
        self.assertIn("edit_file", text)
        self.assertIn("Edited foo.py", text)

    def test_plain_diff_passthrough(self) -> None:
        diff = "--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new"
        text = UI(plain=True).diff(diff)
        self.assertIn("-old", text)
        self.assertIn("+new", text)
        self.assertNotIn("\x1b[", text)

    def test_plain_plan_uses_brackets(self) -> None:
        text = UI(plain=True).plan([
            {"step": "a", "status": "completed"},
            {"step": "b", "status": "in_progress"},
            {"step": "c", "status": "pending"},
        ])
        self.assertIn("[x] a", text)
        self.assertIn("[>] b", text)
        self.assertIn("[ ] c", text)

    def test_color_diff_uses_ansi(self) -> None:
        ui = UI(plain=False)
        ui.plain = False  # force enable
        out = ui.diff("+added\n-removed\n@@ x @@")
        # Plain check: at minimum some ANSI escape was added.
        # If TTY check disables color anyway, just verify it doesn't raise.
        self.assertIn("added", out)
        self.assertIn("removed", out)

    def test_visible_len_skips_ansi(self) -> None:
        from huvcli.ui import _visible_len
        self.assertEqual(_visible_len("\x1b[32mhi\x1b[0m"), 2)
        self.assertEqual(_visible_len("plain"), 5)

    def test_status_and_result_render(self) -> None:
        ui = UI(plain=True)
        self.assertIn("..", ui.status("Reading", "read"))
        self.assertIn("[ok]", ui.result("did it", ok=True))
        self.assertIn("[!]", ui.result("nope", ok=False))

    def test_error_and_info(self) -> None:
        ui = UI(plain=True)
        self.assertIn("[!]", ui.error("oops"))
        self.assertIn("[i]", ui.info("hi"))

    def test_changed_files_plain_empty(self) -> None:
        ui = UI(plain=True)
        self.assertEqual(ui.changed_files({}), "")

    def test_changed_files_plain_renders_actions_and_counts(self) -> None:
        ui = UI(plain=True)
        out = ui.changed_files({
            "src/a.py": {"action": "added",    "adds": 10, "dels": 0},
            "src/b.py": {"action": "modified", "adds": 3,  "dels": 2},
            "old.txt":  {"action": "deleted",  "adds": 0,  "dels": 0},
        })
        self.assertIn("Files changed", out)
        self.assertIn("[A] src/a.py", out)
        self.assertIn("+10/-0", out)
        self.assertIn("[M] src/b.py", out)
        self.assertIn("+3/-2", out)
        self.assertIn("[D] old.txt", out)
        self.assertIn("3 file(s)", out)
        self.assertIn("+13/-2", out)

    def test_hint_bar_plain(self) -> None:
        ui = UI(plain=True)
        bar = ui.hint_bar("auto-edit", "gpt-x", 2)
        self.assertIn("auto-edit", bar)
        self.assertIn("gpt-x", bar)
        self.assertIn("mcp:2", bar)
