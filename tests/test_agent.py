from __future__ import annotations

import json
import unittest

from huvcli.agent import _is_bad_final, _parse_action, _parse_xml_tool_calls, _strip_think
from huvcli.provider import ApiClient, ApiConfig


class ParseActionTests(unittest.TestCase):
    def test_extracts_json_from_prose(self) -> None:
        action = _parse_action('Here:\n{"action":"final","text":"done"}\nThanks')
        self.assertEqual(action["action"], "final")
        self.assertEqual(action["text"], "done")

    def test_handles_braces_inside_strings(self) -> None:
        action = _parse_action('{"action":"final","text":"value { still text }"}')
        self.assertEqual(action["text"], "value { still text }")

    def test_rejects_missing_json(self) -> None:
        with self.assertRaises(json.JSONDecodeError):
            _parse_action("no object")

    def test_rejects_placeholder_final(self) -> None:
        self.assertTrue(_is_bad_final("short summary"))
        self.assertTrue(_is_bad_final("done"))
        self.assertFalse(_is_bad_final("I checked the files and recommend tightening the hero spacing next."))


class MaxStepsConfigTests(unittest.TestCase):
    def test_default_max_steps_from_env(self) -> None:
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"HUV_MAX_STEPS": "123"}):
            # Reimport module to pick up the env change.
            import importlib
            import huvcli.agent
            importlib.reload(huvcli.agent)
            self.assertEqual(huvcli.agent.DEFAULT_MAX_STEPS, 123)
            # Reset back to module default for downstream tests.
            os.environ.pop("HUV_MAX_STEPS", None)
            importlib.reload(huvcli.agent)


class XmlToolCallTests(unittest.TestCase):
    def test_parses_minimax_tool_call(self) -> None:
        text = (
            '<think>plan it</think>\n'
            '<minimax:tool_call>\n'
            '<invoke name="write_file">\n'
            '<parameter name="path">src/App.tsx</parameter>\n'
            '<parameter name="content">hello world</parameter>\n'
            '</invoke>\n'
            '</minimax:tool_call>'
        )
        calls = _parse_xml_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "write_file")
        self.assertEqual(calls[0]["args"]["path"], "src/App.tsx")
        self.assertEqual(calls[0]["args"]["content"], "hello world")

    def test_multiple_invokes_in_block(self) -> None:
        text = (
            '<tool_call>'
            '<invoke name="read_file"><parameter name="path">a.py</parameter></invoke>'
            '<invoke name="read_file"><parameter name="path">b.py</parameter></invoke>'
            '</tool_call>'
        )
        calls = _parse_xml_tool_calls(text)
        self.assertEqual([c["args"]["path"] for c in calls], ["a.py", "b.py"])

    def test_no_xml_returns_empty(self) -> None:
        self.assertEqual(_parse_xml_tool_calls("just prose, no tags"), [])

    def test_coerces_bool_and_int(self) -> None:
        text = (
            '<tool_call><invoke name="edit_file">'
            '<parameter name="replace_all">true</parameter>'
            '<parameter name="limit">42</parameter>'
            '</invoke></tool_call>'
        )
        args = _parse_xml_tool_calls(text)[0]["args"]
        self.assertIs(args["replace_all"], True)
        self.assertEqual(args["limit"], 42)

    def test_strip_think_removes_blocks(self) -> None:
        self.assertEqual(_strip_think("hi <think>secret</think> bye"), "hi  bye")
        self.assertEqual(_strip_think("<think>only</think>"), "")

    def test_parses_truncated_tool_call(self) -> None:
        # Cloudflare cut the response mid-XML — no closing </minimax:tool_call>.
        text = (
            '<minimax:tool_call>\n'
            '<invoke name="write_file">\n'
            '<parameter name="path">src/App.tsx</parameter>\n'
            '<parameter name="content">truncated content here'
        )
        calls = _parse_xml_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "write_file")
        self.assertEqual(calls[0]["args"]["path"], "src/App.tsx")

    def test_garbled_xml_detected(self) -> None:
        from huvcli.agent import _looks_like_garbled_xml_tool
        self.assertTrue(_looks_like_garbled_xml_tool("<minimax:tool_call>oops"))
        self.assertTrue(_looks_like_garbled_xml_tool("here is <invoke name=\"x\""))
        self.assertFalse(_looks_like_garbled_xml_tool("totally normal answer"))


class ScrubProseTests(unittest.TestCase):
    def test_strips_think_and_returns_text(self) -> None:
        from huvcli.agent import _scrub_prose
        self.assertEqual(_scrub_prose("<think>plan</think>real answer"), "real answer")

    def test_strips_unclosed_tool_call_to_empty(self) -> None:
        from huvcli.agent import _scrub_prose
        # Truncated tool-call envelope with no usable prose around it.
        self.assertEqual(
            _scrub_prose("<minimax:tool_call><invoke name=\"x\"><parameter"),
            "",
        )

    def test_strips_closed_tool_call_keeps_surrounding_prose(self) -> None:
        from huvcli.agent import _scrub_prose
        text = "Doing the work.<minimax:tool_call>...</minimax:tool_call>"
        self.assertEqual(_scrub_prose(text), "Doing the work.")

    def test_long_think_only_response_collapses(self) -> None:
        # This was the actual bug — long think block, _is_bad_final on raw
        # text said "fine" but after scrub there was nothing left.
        from huvcli.agent import _scrub_prose, _is_bad_final
        text = "<think>" + ("a long internal monologue " * 10) + "</think>"
        self.assertGreater(len(text), 30)
        self.assertFalse(_is_bad_final(text))           # raw passes the gate
        self.assertEqual(_scrub_prose(text), "")        # scrub kills it
        self.assertTrue(_is_bad_final(_scrub_prose(text)))  # post-scrub fails — good


class ProviderRetryTests(unittest.TestCase):
    def test_request_retries_on_timeout(self) -> None:
        from unittest import mock

        calls = {"n": 0}

        def fake_urlopen(*args, **kwargs):  # noqa: ANN002, ANN003
            calls["n"] += 1
            if calls["n"] < 3:
                raise TimeoutError("simulated read timeout")
            class _Resp:
                def __enter__(self_inner):
                    return self_inner
                def __exit__(self_inner, *exc):
                    return False
                def read(self_inner):
                    return b'{"choices":[{"message":{"content":"ok"}}]}'
            return _Resp()

        client = ApiClient(ApiConfig(api_key="x", max_retries=3, timeout=1))
        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen), \
             mock.patch("huvcli.provider.time.sleep"):
            reply = client.complete([{"role": "user", "content": "hi"}], tools=None)
        self.assertEqual(reply["text"], "ok")
        self.assertEqual(calls["n"], 3)

    def test_request_gives_up_after_max_retries(self) -> None:
        from unittest import mock

        def always_timeout(*args, **kwargs):  # noqa: ANN002, ANN003
            raise TimeoutError("nope")

        client = ApiClient(ApiConfig(api_key="x", max_retries=1, timeout=1))
        with mock.patch("urllib.request.urlopen", side_effect=always_timeout), \
             mock.patch("huvcli.provider.time.sleep"):
            with self.assertRaises(RuntimeError) as cm:
                client.complete([{"role": "user", "content": "hi"}], tools=None)
        self.assertIn("timed out", str(cm.exception).lower())
