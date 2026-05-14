"""Auto-compaction — summarize old turns when conversation grows large.

Strategy (CC-style):
- Measure total chars across messages.
- When > threshold, peel off oldest non-system messages up to a cutoff,
  ask the model to summarize them, then replace with one synthetic
  "[Prior conversation summary]" user message.
- Always preserve the last `keep_recent` messages verbatim.
- A `role=tool` message must stay paired with its assistant tool_calls —
  never split that boundary.
"""

from __future__ import annotations

import os
from typing import Any


COMPACT_THRESHOLD_CHARS = int(os.environ.get("HUV_COMPACT_CHARS", "400000"))
COMPACT_KEEP_RECENT = int(os.environ.get("HUV_COMPACT_KEEP", "24"))
COMPACT_TARGET_CHARS = int(os.environ.get("HUV_COMPACT_TARGET", "180000"))


def _msg_chars(msg: dict[str, Any]) -> int:
    total = 0
    content = msg.get("content")
    if isinstance(content, str):
        total += len(content)
    for tc in msg.get("tool_calls") or []:
        fn = tc.get("function") or {}
        total += len(fn.get("name") or "") + len(fn.get("arguments") or "")
    return total


def total_chars(messages: list[dict[str, Any]]) -> int:
    return sum(_msg_chars(m) for m in messages)


def _is_tool_pair_safe_cut(messages: list[dict[str, Any]], index: int) -> bool:
    if index >= len(messages):
        return True
    return messages[index].get("role") != "tool"


def needs_compaction(messages: list[dict[str, Any]], threshold: int = COMPACT_THRESHOLD_CHARS) -> bool:
    return total_chars(messages) > threshold


def _render_for_summary(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        tool_calls = m.get("tool_calls") or []
        if tool_calls:
            names = ", ".join((tc.get("function") or {}).get("name", "") for tc in tool_calls)
            parts.append(f"[{role}] tool_calls: {names}\n{content}".rstrip())
        elif role == "tool":
            parts.append(f"[tool_result]\n{content[:2000]}")
        else:
            parts.append(f"[{role}]\n{content[:4000]}")
    return "\n\n".join(parts)


SUMMARY_SYSTEM = (
    "You compress an agent conversation into a dense factual summary for the agent itself to reuse. "
    "Preserve: files read/edited (with paths), commands run + outcomes, decisions made, open questions, "
    "current goal. Drop: chit-chat, redundant tool output, exact stdout. Use compact bullet lists. "
    "Max ~600 words. No preamble — start with the summary."
)


def compact_if_needed(
    messages: list[dict[str, Any]],
    summarize: callable,  # type: ignore[valid-type]
    threshold: int = COMPACT_THRESHOLD_CHARS,
    keep_recent: int = COMPACT_KEEP_RECENT,
    target: int = COMPACT_TARGET_CHARS,
) -> tuple[list[dict[str, Any]], bool]:
    """Return (possibly-compacted messages, was_compacted).

    `summarize(text) -> str` is injected so this module stays test-friendly
    (real impl calls the API; tests pass a fake).
    """
    if not needs_compaction(messages, threshold):
        return messages, False

    system_msgs: list[dict[str, Any]] = []
    body: list[dict[str, Any]] = messages
    if messages and messages[0].get("role") == "system":
        system_msgs = [messages[0]]
        body = messages[1:]

    if len(body) <= keep_recent:
        return messages, False

    cut = len(body) - keep_recent
    while cut < len(body) and not _is_tool_pair_safe_cut(body, cut):
        cut += 1
    if cut < 2 or cut >= len(body):
        return messages, False
    pre_chars = sum(_msg_chars(m) for m in body[:cut])
    if pre_chars < target // 4:
        return messages, False

    to_summarize = body[:cut]
    keep = body[cut:]
    rendered = _render_for_summary(to_summarize)
    summary = summarize(rendered).strip() or "(prior turns omitted)"
    synthetic = {
        "role": "user",
        "content": f"[Prior conversation summary — {len(to_summarize)} messages compacted]\n{summary}",
    }
    return system_msgs + [synthetic] + keep, True
