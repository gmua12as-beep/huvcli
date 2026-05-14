"""webfetch — pull a URL into context.

Practical use: the model can look up docs/RFCs/READMEs instead of guessing.
Skill-locked to GET, size-capped, sniffs HTML and strips it to a plain-text
approximation (no full DOM — stdlib only).
"""

from __future__ import annotations

import html
import os
import re
import urllib.error
import urllib.request

from .context import ToolContext
from .descriptions import load as _load_description


SCHEMA = {
    "name": "webfetch",
    "description": _load_description(__file__),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full http(s) URL."},
            "max_chars": {"type": "integer", "default": 100000},
        },
        "required": ["url"],
    },
}
REQUIRED = ["url"]
ARG_ALIASES = {"link": "url", "href": "url", "uri": "url"}
EXAMPLE = '{"url": "https://docs.python.org/3/library/json.html"}'

_DEFAULT_TIMEOUT = int(os.environ.get("HUV_WEBFETCH_TIMEOUT", "20"))
_USER_AGENT = "HuvCLI/0.1 (+webfetch)"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _html_to_text(body: str) -> str:
    # Drop <script>/<style> blocks first so their bodies don't leak through.
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.IGNORECASE | re.DOTALL)
    # Convert common block tags into newlines.
    body = re.sub(r"<(br|/p|/div|/li|/h[1-6]|/tr)[^>]*>", "\n", body, flags=re.IGNORECASE)
    # Strip remaining tags.
    body = _TAG_RE.sub("", body)
    body = html.unescape(body)
    # Tidy whitespace.
    body = _WS_RE.sub(" ", body)
    body = _BLANK_LINES_RE.sub("\n\n", body)
    return body.strip()


def webfetch(ctx: ToolContext, url: str, max_chars: int = 100000) -> str:
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("URL must start with http:// or https://")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "text/*, */*;q=0.1"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=_DEFAULT_TIMEOUT) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            raw = resp.read(max_chars * 4 + 1024)  # over-read; we'll trim
            status = resp.status
            final_url = resp.geturl()
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code} {exc.reason} for {url}"
    except urllib.error.URLError as exc:
        return f"URL error: {exc.reason} for {url}"
    except (TimeoutError, OSError) as exc:
        return f"Fetch failed: {exc} (url={url})"

    # Best-effort decode.
    encoding = "utf-8"
    if "charset=" in ctype:
        encoding = ctype.split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
    try:
        body = raw.decode(encoding, errors="replace")
    except LookupError:
        body = raw.decode("utf-8", errors="replace")

    if "html" in ctype or body.lstrip().lower().startswith(("<!doctype", "<html")):
        body = _html_to_text(body)

    truncated = len(body) > max_chars
    if truncated:
        body = body[:max_chars] + "\n...truncated"

    header = f"[GET {status}] {final_url}"
    if "content-type" not in header.lower() and ctype:
        header += f"  ({ctype})"
    return header + "\n\n" + body


def call(ctx: ToolContext, args: dict) -> str:
    return webfetch(ctx, str(args["url"]), int(args.get("max_chars", 100000)))
