"""apply_patch — apply a unified diff or codex `*** Begin Patch` envelope.

The fuzzy hunk locator is what makes this resilient: model-generated diffs
often have off-by-N line numbers. We search a window around the hint and
fall back to whitespace-insensitive matching before giving up.
"""

from __future__ import annotations

import re
from pathlib import Path

from .context import ToolContext
from .paths import (
    project_path,
    read_text_preserving,
    rel,
    write_text_preserving,
)
from .descriptions import load as _load_description
from .permission import confirm
from .state import (
    diff_counts,
    record_change,
    record_read,
    snapshot_original,
)


SCHEMA = {
    "name": "apply_patch",
    "description": _load_description(__file__),
    "parameters": {
        "type": "object",
        "properties": {"patch": {"type": "string"}},
        "required": ["patch"],
    },
}
REQUIRED = ["patch"]
ARG_ALIASES = {"diff": "patch", "unified_diff": "patch", "patch_text": "patch"}
EXAMPLE = '{"patch": "--- a.txt\\n+++ a.txt\\n@@ -1 +1 @@\\n-old\\n+new\\n"}'


# ---- diff parsing helpers ------------------------------------------------

def _patch_path(raw: str) -> str | None:
    path = raw.strip().split("\t", 1)[0]
    if path == "/dev/null":
        return None
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


def _parse_hunk_header(header: str) -> tuple[int, int]:
    match = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", header)
    if not match:
        raise ValueError(f"Bad hunk header: {header}")
    return int(match.group(1)), int(match.group(2))


def _classify(line: str) -> tuple[str, str]:
    if line == "":
        return " ", ""
    return line[:1], line[1:]


def _collect_hunk(patch_lines: list[str], index: int) -> tuple[list[tuple[str, str]], int]:
    body: list[tuple[str, str]] = []
    while index < len(patch_lines):
        line = patch_lines[index]
        if line.startswith("@@") or line.startswith("--- ") or line.startswith("*** "):
            break
        if line.startswith("\\ No newline"):
            index += 1
            continue
        marker, value = _classify(line)
        if marker not in (" ", "-", "+"):
            raise ValueError(f"Bad patch line at {index}: {line!r}")
        body.append((marker, value))
        index += 1
    return body, index


def _hunk_matches_at(old_lines: list[str], pos: int, body: list[tuple[str, str]], loose: bool = False) -> bool:
    cursor = pos
    for marker, value in body:
        if marker == "+":
            continue
        if cursor >= len(old_lines):
            return False
        actual = old_lines[cursor]
        if loose:
            if actual.rstrip() != value.rstrip():
                return False
        else:
            if actual != value:
                return False
        cursor += 1
    return True


def _locate_hunk(old_lines: list[str], hint: int, body: list[tuple[str, str]]) -> int:
    hint = max(0, min(hint, len(old_lines)))
    max_offset = max(hint, len(old_lines) - hint, 200)
    for loose in (False, True):
        for offset in range(0, max_offset + 1):
            for candidate in (hint + offset, hint - offset) if offset else (hint,):
                if candidate < 0 or candidate > len(old_lines):
                    continue
                if _hunk_matches_at(old_lines, candidate, body, loose=loose):
                    return candidate
    expected = [v for m, v in body if m in (" ", "-")][:3]
    raise ValueError(
        f"Could not locate hunk near line {hint + 1}. Expected: {expected!r}. "
        f"Re-read file and regenerate diff, or use edit_file."
    )


def _apply_hunks(old_lines: list[str], patch_lines: list[str], start: int) -> tuple[list[str], int]:
    output: list[str] = []
    cursor = 0
    index = start
    while index < len(patch_lines) and patch_lines[index].startswith("@@"):
        old_start, _ = _parse_hunk_header(patch_lines[index])
        index += 1
        body, index = _collect_hunk(patch_lines, index)
        target = _locate_hunk(old_lines, old_start - 1, body)
        if target < cursor:
            raise ValueError(f"Overlapping hunks at line {target + 1}")
        output.extend(old_lines[cursor:target])
        cursor = target
        for marker, value in body:
            if marker == " ":
                if cursor >= len(old_lines):
                    raise ValueError(f"Patch context past EOF at line {cursor + 1}")
                output.append(old_lines[cursor])
                cursor += 1
            elif marker == "-":
                if cursor >= len(old_lines):
                    raise ValueError(f"Patch removal past EOF at line {cursor + 1}")
                cursor += 1
            elif marker == "+":
                output.append(value)
    output.extend(old_lines[cursor:])
    return output, index


def _strip_begin_patch_envelope(patch: str) -> str:
    """codex `*** Begin Patch ... *** End Patch` envelope → unified diff."""
    if "*** Begin Patch" not in patch:
        return patch
    lines = patch.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines) and not lines[i].startswith("*** Begin Patch"):
        i += 1
    i += 1
    while i < len(lines):
        line = lines[i]
        if line.startswith("*** End Patch"):
            break
        if line.startswith("*** Add File:"):
            path = line[len("*** Add File:"):].strip()
            i += 1
            body: list[str] = []
            while i < len(lines) and not lines[i].startswith("*** "):
                body.append(lines[i])
                i += 1
            added = [b[1:] if b.startswith("+") else b for b in body]
            out.append("--- /dev/null")
            out.append(f"+++ {path}")
            out.append(f"@@ -0,0 +1,{len(added)} @@")
            for a in added:
                out.append("+" + a)
            continue
        if line.startswith("*** Delete File:"):
            path = line[len("*** Delete File:"):].strip()
            out.append(f"--- {path}")
            out.append("+++ /dev/null")
            i += 1
            continue
        if line.startswith("*** Update File:"):
            path = line[len("*** Update File:"):].strip()
            i += 1
            out.append(f"--- {path}")
            out.append(f"+++ {path}")
            body_start = i
            while i < len(lines) and not lines[i].startswith("*** "):
                i += 1
            body = lines[body_start:i]
            if body and not body[0].startswith("@@"):
                out.append("@@ -1 +1 @@")
            out.extend(body)
            continue
        i += 1
    return "\n".join(out)


# ---- public entry point --------------------------------------------------

def apply_patch(ctx: ToolContext, patch: str) -> str:
    patch = _strip_begin_patch_envelope(patch)
    patch_lines = patch.splitlines()
    index = 0
    changes: list[tuple[Path, list[str] | None, str, bool]] = []
    while index < len(patch_lines):
        if not patch_lines[index].startswith("--- "):
            index += 1
            continue
        old_path = _patch_path(patch_lines[index][4:])
        index += 1
        if index >= len(patch_lines) or not patch_lines[index].startswith("+++ "):
            raise ValueError("Patch missing +++ header")
        new_path = _patch_path(patch_lines[index][4:])
        index += 1
        path = new_path or old_path
        if not path:
            raise ValueError("Patch missing file path")
        target = project_path(ctx, path)
        if new_path is None:
            changes.append((target, None, "\n", False))
            while index < len(patch_lines) and not patch_lines[index].startswith("--- "):
                index += 1
            continue
        old_text, newline, trailing = read_text_preserving(target)
        old_lines = old_text.splitlines()
        try:
            new_lines, index = _apply_hunks(old_lines, patch_lines, index)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from None
        changes.append((target, new_lines, newline, trailing if old_text else True))
    if not changes:
        raise ValueError(
            "No unified diff found in `patch`. Expected either:\n"
            "  unified-diff form: lines starting with `--- path` then `+++ path` then `@@ ... @@` hunks, or\n"
            "  envelope form:    `*** Begin Patch` ... `*** Update File: path` ... `*** End Patch`.\n"
            "If you just want to change a few lines, use `edit_file` instead — it's exact-string replace and far less error-prone."
        )
    if ctx.verbose:
        print(patch[:12000])
    if not confirm(ctx, f"Apply patch to {len(changes)} file(s)?", kind="edit"):
        return "Patch cancelled"
    results: list[str] = []
    for target, lines, newline, trailing in changes:
        if lines is None:
            existed = target.exists()
            snapshot_original(ctx, target)
            if existed:
                target.unlink()
            record_change(ctx, target, "deleted")
            results.append(f"Deleted {rel(ctx, target)}")
            continue
        existed = target.exists()
        old_text = target.read_text(encoding="utf-8", errors="replace") if existed else ""
        snapshot_original(ctx, target)
        write_text_preserving(target, lines, newline, trailing)
        record_read(ctx, target)
        new_text = "\n".join(lines)
        adds, dels = diff_counts(old_text, new_text)
        record_change(ctx, target, "added" if not existed else "modified", adds, dels)
        results.append(f"Patched {rel(ctx, target)}")
    return "\n".join(results)


def call(ctx: ToolContext, args: dict) -> str:
    return apply_patch(ctx, str(args["patch"]))
