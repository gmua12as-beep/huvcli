from __future__ import annotations

import sys
import unittest
from unittest import mock


class _FakeReadline:
    """Module-level fake so importing `readline` later in the completer
    callback still finds it."""
    __doc__ = "GNU readline"
    _captured: dict = {}

    @classmethod
    def set_completer(cls, fn):
        cls._captured["fn"] = fn

    @classmethod
    def set_completer_delims(cls, _):
        pass

    @classmethod
    def parse_and_bind(cls, _):
        pass

    @classmethod
    def get_line_buffer(cls):
        return cls._captured.get("buffer", "")


class CompleterTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeReadline._captured = {}
        self._patcher = mock.patch.dict(sys.modules, {"readline": _FakeReadline})
        self._patcher.start()
        from huvcli.cli import _install_completer
        self._install = _install_completer

    def tearDown(self) -> None:
        self._patcher.stop()

    def _install_with(self, paths: list[str]):
        result = self._install(lambda: paths)
        # New tuple return shape: (active, backend_name).
        if isinstance(result, tuple):
            active, _backend = result
        else:
            active = result
        self.assertTrue(active)
        return _FakeReadline._captured["fn"]

    def _set_buffer(self, buf: str) -> None:
        _FakeReadline._captured["buffer"] = buf

    def _all_matches(self, fn, prefix: str) -> list[str]:
        out: list[str] = []
        i = 0
        while True:
            m = fn(prefix, i)
            if m is None:
                break
            out.append(m)
            i += 1
        return out

    def test_completes_slash_command_names(self) -> None:
        fn = self._install_with([])
        self._set_buffer("/he")
        out = self._all_matches(fn, "/he")
        self.assertIn("/help", out)

    def test_completes_approval_modes(self) -> None:
        fn = self._install_with([])
        self._set_buffer("/approval ")
        out = self._all_matches(fn, "")
        self.assertIn("suggest", out)
        self.assertIn("auto-edit", out)
        self.assertIn("full-auto", out)

    def test_completes_revert_paths(self) -> None:
        fn = self._install_with(["src/a.py", "src/b.py"])
        self._set_buffer("/revert src/")
        out = self._all_matches(fn, "src/")
        self.assertEqual(sorted(out), ["src/a.py", "src/b.py"])
        self._set_buffer("/revert ")
        out_all = self._all_matches(fn, "")
        self.assertIn("all", out_all)
        self.assertIn("src/a.py", out_all)


class CompleterMissingReadlineTests(unittest.TestCase):
    def test_install_completer_returns_false_when_readline_missing(self) -> None:
        with mock.patch.dict(sys.modules, {"readline": None}):
            from huvcli.cli import _install_completer
            result = _install_completer(lambda: [])
            if isinstance(result, tuple):
                active, _backend = result
            else:
                active = result
            self.assertFalse(active)


class ReadlineBackendDetectionTests(unittest.TestCase):
    def test_pyreadline3_detected_by_file_path(self) -> None:
        from huvcli.cli import _readline_backend_name

        class Stub:
            __doc__ = None
            __name__ = "readline"
            __file__ = "C:\\Python\\site-packages\\pyreadline3\\rlmain.py"
        self.assertEqual(_readline_backend_name(Stub), "pyreadline3")

    def test_libedit_detected_by_docstring(self) -> None:
        from huvcli.cli import _readline_backend_name

        class Stub:
            __doc__ = "Importing this module enables command line editing using libedit."
            __name__ = "readline"
            __file__ = "/usr/lib/readline.so"
        self.assertEqual(_readline_backend_name(Stub), "libedit")

    def test_none_docstring_does_not_crash(self) -> None:
        from huvcli.cli import _readline_backend_name

        class Stub:
            __doc__ = None
            __name__ = "readline"
            __file__ = "/usr/lib/readline.so"
        self.assertIn("readline", _readline_backend_name(Stub).lower())
