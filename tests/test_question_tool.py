from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from huvcli.tools import ToolContext, call_tool
from huvcli.tools.question import ask


def _ctx(**kwargs) -> ToolContext:
    return ToolContext(cwd=Path(tempfile.gettempdir()), **kwargs)


class QuestionToolTests(unittest.TestCase):
    def test_returns_user_text(self) -> None:
        ctx = _ctx(yes=False)
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", return_value="green"):
            out = ask(ctx, "Pick a color")
        self.assertEqual(out, "green")

    def test_numbered_option_resolves(self) -> None:
        ctx = _ctx(yes=False)
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", return_value="2"):
            out = ask(ctx, "Pick one", ["red", "blue", "green"])
        self.assertEqual(out, "blue")

    def test_defers_in_yes_mode(self) -> None:
        ctx = _ctx(yes=True)
        out = ask(ctx, "anything?")
        self.assertIn("deferred", out.lower())

    def test_eof_returns_cancelled(self) -> None:
        ctx = _ctx(yes=False)
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", side_effect=EOFError):
            out = ask(ctx, "anything?")
        self.assertIn("cancelled", out.lower())

    def test_dispatch_via_call_tool(self) -> None:
        ctx = _ctx(yes=False)
        with mock.patch("sys.stdin.isatty", return_value=True), \
             mock.patch("builtins.input", return_value="yes"):
            out = call_tool(ctx, "question", {"question": "Continue?"})
        self.assertEqual(out, "yes")

    def test_alias_prompt_maps_to_question(self) -> None:
        ctx = _ctx(yes=True)
        # `prompt` is the alias; should still dispatch.
        out = call_tool(ctx, "question", {"prompt": "huh?"})
        self.assertIn("deferred", out.lower())
