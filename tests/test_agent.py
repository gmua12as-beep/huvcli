from __future__ import annotations

import json
import unittest

from huvcli.agent import _is_bad_final, _parse_action


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
