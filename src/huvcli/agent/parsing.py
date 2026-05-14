"""Reply parsing: think/XML scrubbing, MiniMax-style tool call extraction,
JSON-action fallback extraction.

Pure functions, no I/O, no state — safe to import anywhere.
"""

from __future__ import annotations

import json
import re
from typing import Any


# <think>...</think>
THINK_RE = re.compile(r"<think\b[^>]*>.*?</think>", re.IGNORECASE | re.DOTALL)

# Closed envelope: <minimax:tool_call> ... </minimax:tool_call>
TOOL_BLOCK_RE = re.compile(
    r"<(?:[a-z]+:)?tool_call\b[^>]*>(.*?)</(?:[a-z]+:)?tool_call>",
    re.IGNORECASE | re.DOTALL,
)
# Unclosed envelope (truncated response): match from opening tag to EOF.
TOOL_BLOCK_OPEN_RE = re.compile(
    r"<(?:[a-z]+:)?tool_call\b[^>]*>(.*)\Z",
    re.IGNORECASE | re.DOTALL,
)
# Any sign of a tool-call envelope, so we can detect partial/garbled XML.
TOOL_MARKER_RE = re.compile(
    r"<(?:[a-z]+:)?tool_call\b",
    re.IGNORECASE,
)
# Closed invoke + EOF-bound invoke for truncated responses.
_INVOKE_RE = re.compile(
    r'<invoke\s+name="([^"]+)"\s*>(.*?)</invoke>',
    re.IGNORECASE | re.DOTALL,
)
_INVOKE_OPEN_RE = re.compile(
    r'<invoke\s+name="([^"]+)"\s*>(.*?)(?:</invoke>|\Z)',
    re.IGNORECASE | re.DOTALL,
)
_PARAM_RE = re.compile(
    r'<parameter\s+name="([^"]+)"\s*>(.*?)</parameter>',
    re.IGNORECASE | re.DOTALL,
)


def strip_think(text: str) -> str:
    return THINK_RE.sub("", text).strip()


def _coerce_param(value: str) -> Any:
    """Heuristically convert XML parameter text into a Python value."""
    v = value.strip()
    if v in {"true", "True"}:
        return True
    if v in {"false", "False"}:
        return False
    if v.lstrip("-").isdigit():
        try:
            return int(v)
        except ValueError:
            return value
    return value  # preserves whitespace inside content blocks


def parse_xml_tool_calls(text: str) -> list[dict[str, Any]]:
    """Parse MiniMax-style `<minimax:tool_call><invoke name="..."><parameter ...>` blocks.

    Tolerates truncated/unclosed envelopes (Cloudflare 524, max_tokens cuts, etc.).
    Returns the same shape as native tool_calls: [{id, name, args}].
    """
    calls: list[dict[str, Any]] = []
    counter = 0
    blocks = TOOL_BLOCK_RE.findall(text)
    if not blocks:
        m = TOOL_BLOCK_OPEN_RE.search(text)
        if m:
            blocks = [m.group(1)]
    for block in blocks:
        matches = _INVOKE_RE.findall(block) or _INVOKE_OPEN_RE.findall(block)
        for name, inner in matches:
            args: dict[str, Any] = {}
            for pname, pvalue in _PARAM_RE.findall(inner):
                args[pname] = _coerce_param(pvalue)
            counter += 1
            calls.append({"id": f"xml_{counter}", "name": name.strip(), "args": args})
    return calls


def looks_like_garbled_xml_tool(text: str) -> bool:
    """True when text smells like a botched tool-call attempt — XML markers
    present but our parser couldn't extract any valid calls."""
    return bool(TOOL_MARKER_RE.search(text)) or "<invoke" in text.lower()


def scrub_prose(text: str) -> str:
    """Strip think blocks + closed/unclosed tool_call envelopes.

    Used so the bad-final check operates on what the user would actually
    see — not on raw think/XML that scrubs to nothing.
    """
    if not text:
        return ""
    cleaned = strip_think(text)
    cleaned = TOOL_BLOCK_RE.sub("", cleaned)
    open_m = TOOL_BLOCK_OPEN_RE.search(cleaned)
    if open_m:
        cleaned = cleaned[: open_m.start()]
    return cleaned.strip()


def _extract_json_object(text: str) -> str:
    """Pull the first balanced top-level JSON object out of free-form text."""
    start = text.find("{")
    if start < 0:
        raise json.JSONDecodeError("No JSON object found", text, 0)
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise json.JSONDecodeError("Unterminated JSON object", text, start)


def parse_action(text: str) -> dict[str, Any]:
    """JSON-action fallback: extract `{"action": "tool"|"final", ...}` from prose."""
    action = json.loads(_extract_json_object(text))
    if not isinstance(action, dict):
        raise json.JSONDecodeError("JSON action must be an object", text, 0)
    return action
