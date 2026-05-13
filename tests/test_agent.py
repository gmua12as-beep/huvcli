from __future__ import annotations

import json
import unittest

from huvcli.agent import _is_bad_final, _parse_action, _parse_xml_tool_calls, _strip_think


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
