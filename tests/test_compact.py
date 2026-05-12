from __future__ import annotations

import unittest

from huvcli.compact import compact_if_needed, needs_compaction, total_chars


def _msg(role: str, content: str, tool_calls=None) -> dict:
    m: dict = {"role": role, "content": content}
    if tool_calls is not None:
        m["tool_calls"] = tool_calls
    return m


class CompactTests(unittest.TestCase):
    def test_no_compaction_under_threshold(self) -> None:
        msgs = [_msg("system", "sys"), _msg("user", "hi"), _msg("assistant", "hello")]
        out, did = compact_if_needed(msgs, summarize=lambda t: "SUMMARY", threshold=10_000)
        self.assertFalse(did)
        self.assertEqual(out, msgs)

    def test_compaction_replaces_old_turns_with_summary(self) -> None:
        big = "x" * 5000
        msgs = [_msg("system", "sys")]
        for i in range(40):
            msgs.append(_msg("user", f"u{i}-{big}"))
            msgs.append(_msg("assistant", f"a{i}-{big}"))
        before_total = total_chars(msgs)
        captured = {}

        def fake_summary(text: str) -> str:
            captured["text"] = text
            return "PRIOR_SUMMARY"

        out, did = compact_if_needed(
            msgs, summarize=fake_summary,
            threshold=100_000, keep_recent=8, target=40_000,
        )
        self.assertTrue(did)
        # System preserved.
        self.assertEqual(out[0]["role"], "system")
        # Second message is the synthetic summary.
        self.assertEqual(out[1]["role"], "user")
        self.assertIn("PRIOR_SUMMARY", out[1]["content"])
        # Last messages preserved verbatim.
        self.assertEqual(out[-1], msgs[-1])
        self.assertEqual(out[-2], msgs[-2])
        # Net size shrank.
        self.assertLess(total_chars(out), before_total)
        # Summarizer received rendered prior context.
        self.assertIn("[user]", captured["text"])

    def test_does_not_split_tool_pair(self) -> None:
        # Construct: user, assistant(tool_calls), tool, user, assistant
        # If naive cut lands on the `tool` message, it would orphan it.
        big = "x" * 8000
        msgs = [
            _msg("system", "sys"),
            _msg("user", f"u0-{big}"),
            _msg("assistant", "", tool_calls=[{"function": {"name": "read_file", "arguments": "{}"}}]),
            _msg("tool", f"result-{big}"),
            _msg("user", f"u1-{big}"),
            _msg("assistant", f"a1-{big}"),
            _msg("user", f"u2-{big}"),
            _msg("assistant", f"a2-{big}"),
        ]
        out, did = compact_if_needed(
            msgs, summarize=lambda t: "S",
            threshold=20_000, keep_recent=3, target=10_000,
        )
        if did:
            roles = [m["role"] for m in out]
            # No orphan `tool` right after the synthetic summary.
            for i, r in enumerate(roles):
                if r == "tool":
                    self.assertEqual(roles[i - 1], "assistant")

    def test_needs_compaction_threshold(self) -> None:
        msgs = [_msg("user", "x" * 100)]
        self.assertFalse(needs_compaction(msgs, threshold=200))
        self.assertTrue(needs_compaction(msgs, threshold=50))
