from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from huvcli.hooks import load_hooks, run_hooks


def _write_config(root: Path, payload: dict) -> None:
    (root / ".huvcli").mkdir(parents=True, exist_ok=True)
    (root / ".huvcli" / "hooks.json").write_text(json.dumps(payload), encoding="utf-8")


class HooksTests(unittest.TestCase):
    def test_load_missing_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            self.assertEqual(load_hooks(Path(raw)), {})

    def test_load_filters_invalid_events_and_blank_commands(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_config(root, {
                "pre_tool": [{"command": "echo ok"}, {"command": ""}],
                "garbage_event": [{"command": "echo no"}],
            })
            loaded = load_hooks(root)
            self.assertIn("pre_tool", loaded)
            self.assertEqual(len(loaded["pre_tool"]), 1)
            self.assertNotIn("garbage_event", loaded)

    def test_pre_tool_allows_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            # cross-platform allow: `python -c "import sys; sys.exit(0)"`
            cmd = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
            hooks = {"pre_tool": [{"matcher": "", "command": cmd}]}
            allowed, out = run_hooks(root, hooks, "pre_tool", {"tool": "edit_file", "args": {}})
            self.assertTrue(allowed)

    def test_pre_tool_blocks_on_nonzero_exit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cmd = f'"{sys.executable}" -c "import sys; sys.stderr.write(\'NO\'); sys.exit(2)"'
            hooks = {"pre_tool": [{"matcher": "edit_file", "command": cmd}]}
            allowed, out = run_hooks(root, hooks, "pre_tool", {"tool": "edit_file", "args": {}})
            self.assertFalse(allowed)
            self.assertIn("hook blocked", out)

    def test_matcher_filters_tools(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cmd = f'"{sys.executable}" -c "import sys; sys.exit(2)"'
            hooks = {"pre_tool": [{"matcher": "^edit_file$", "command": cmd}]}
            # Non-matching tool → hook skipped, allowed.
            allowed, _ = run_hooks(root, hooks, "pre_tool", {"tool": "read_file", "args": {}})
            self.assertTrue(allowed)
            # Matching tool → blocked.
            allowed, _ = run_hooks(root, hooks, "pre_tool", {"tool": "edit_file", "args": {}})
            self.assertFalse(allowed)

    def test_skips_mcp_tools(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cmd = f'"{sys.executable}" -c "import sys; sys.exit(2)"'
            hooks = {"pre_tool": [{"matcher": "", "command": cmd}]}
            allowed, _ = run_hooks(root, hooks, "pre_tool", {"tool": "mcp__fs__read", "args": {}})
            self.assertTrue(allowed)

    def test_json_decision_block(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            script = root / "hook.py"
            script.write_text(
                'import sys\nsys.stdout.write(\'{"decision":"block","reason":"policy"}\\n\')\nsys.exit(0)\n',
                encoding="utf-8",
            )
            cmd = f'"{sys.executable}" "{script}"'
            hooks = {"pre_tool": [{"matcher": "", "command": cmd}]}
            allowed, out = run_hooks(root, hooks, "pre_tool", {"tool": "edit_file", "args": {}})
            self.assertFalse(allowed)
            self.assertIn("policy", out)

    def test_post_tool_output_appended(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            cmd = f'"{sys.executable}" -c "print(\'lint clean\')"'
            hooks = {"post_tool": [{"matcher": "", "command": cmd}]}
            allowed, out = run_hooks(root, hooks, "post_tool", {"tool": "edit_file", "args": {}, "result": "x"})
            self.assertTrue(allowed)
            self.assertIn("lint clean", out)
