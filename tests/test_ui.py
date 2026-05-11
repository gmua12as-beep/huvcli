from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from huvcli.ui import UI


class UITests(unittest.TestCase):
    def test_plain_welcome_contains_project(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            text = UI(plain=True).welcome(Path(raw), save=True)
            self.assertIn("Huv CLI", text)
            self.assertIn("Project:", text)

    def test_plain_answer_wraps_result(self) -> None:
        text = UI(plain=True).answer("hello")
        self.assertIn("Result", text)
        self.assertIn("hello", text)
