from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from huvcli.agent import SessionState


class SessionStateTests(unittest.TestCase):
    def test_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            s = SessionState(cwd=Path(raw))
            self.assertEqual(s.tokens, {"prompt": 0, "completion": 0, "total": 0})
            self.assertEqual(s.changes, {})
            self.assertEqual(s.hooks, {})

    def test_close_is_safe_when_no_mcp(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            s = SessionState(cwd=Path(raw))
            s.close()  # must not raise


class StorageCapTests(unittest.TestCase):
    def test_save_caps_long_conversations(self) -> None:
        from huvcli.storage import save_conversation, load_conversation
        with tempfile.TemporaryDirectory() as raw:
            cwd = Path(raw)
            msgs = [{"role": "system", "content": "sys"}]
            for i in range(500):
                msgs.append({"role": "user", "content": f"u{i}"})
                msgs.append({"role": "assistant", "content": f"a{i}"})
            save_conversation(cwd, msgs, max_messages=50)
            loaded = load_conversation(cwd)
            self.assertEqual(len(loaded), 50)
            # Last message preserved.
            self.assertEqual(loaded[-1], msgs[-1])

    def test_save_skips_orphan_tool_message_at_cut(self) -> None:
        from huvcli.storage import save_conversation, load_conversation
        with tempfile.TemporaryDirectory() as raw:
            cwd = Path(raw)
            msgs = [{"role": "system", "content": "sys"}]
            # First a long preamble we want trimmed:
            for i in range(60):
                msgs.append({"role": "user", "content": f"u{i}"})
                msgs.append({"role": "assistant", "content": f"a{i}"})
            # Now add a `tool` boundary right at where the cut would land.
            msgs.append({"role": "tool", "tool_call_id": "t1", "content": "result"})
            msgs.append({"role": "assistant", "content": "ok"})
            save_conversation(cwd, msgs, max_messages=5)
            loaded = load_conversation(cwd)
            # First kept message must NOT be a tool result.
            self.assertNotEqual(loaded[0].get("role"), "tool")
