from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from huvcli.tools import ToolContext
from huvcli.tools.webfetch import webfetch, _html_to_text


def _ctx() -> ToolContext:
    return ToolContext(cwd=Path(tempfile.gettempdir()), yes=True)


class HtmlStripTests(unittest.TestCase):
    def test_drops_script_and_style(self) -> None:
        out = _html_to_text(
            "<html><head><style>body{color:red}</style></head>"
            "<body><script>alert(1)</script><p>Hello</p></body></html>"
        )
        self.assertIn("Hello", out)
        self.assertNotIn("alert", out)
        self.assertNotIn("color:red", out)

    def test_unescapes_entities(self) -> None:
        out = _html_to_text("<p>&amp; &lt;ok&gt;</p>")
        self.assertIn("& <ok>", out)


class WebfetchTests(unittest.TestCase):
    def test_rejects_non_http_scheme(self) -> None:
        with self.assertRaises(ValueError):
            webfetch(_ctx(), "ftp://example.com/foo")

    def test_returns_body_on_success(self) -> None:
        body = b"<html><body><h1>Hi</h1></body></html>"

        class FakeResp:
            status = 200
            headers = {"Content-Type": "text/html; charset=utf-8"}
            def read(self_inner, n=-1): return body
            def geturl(self_inner): return "https://example.com/"
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *exc): return False

        with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
            out = webfetch(_ctx(), "https://example.com/")
        self.assertIn("[GET 200]", out)
        self.assertIn("https://example.com/", out)
        self.assertIn("Hi", out)
        # HTML tags stripped.
        self.assertNotIn("<h1>", out)

    def test_truncates_long_bodies(self) -> None:
        body = ("A" * 500000).encode("utf-8")

        class FakeResp:
            status = 200
            headers = {"Content-Type": "text/plain"}
            def read(self_inner, n=-1): return body[:n] if n > 0 else body
            def geturl(self_inner): return "https://example.com/big"
            def __enter__(self_inner): return self_inner
            def __exit__(self_inner, *exc): return False

        with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
            out = webfetch(_ctx(), "https://example.com/big", max_chars=1000)
        self.assertIn("...truncated", out)

    def test_http_error_returned_as_text(self) -> None:
        import urllib.error
        err = urllib.error.HTTPError(
            "https://example.com/", 404, "Not Found", hdrs=None, fp=io.BytesIO(b""),
        )
        with mock.patch("urllib.request.urlopen", side_effect=err):
            out = webfetch(_ctx(), "https://example.com/")
        self.assertIn("HTTP 404", out)
