"""edit_file — targeted exact-string replacement with safety guards.

This is the workhorse for code changes. Refuses ambiguous matches and
oversized edits to keep the agent honest about scope.
"""

from __future__ import annotations

import difflib
import os
import re

from .context import ToolContext
from .descriptions import load as _load_description
from .diff import colorize_diff
from .paths import project_path, read_text_preserving
from .permission import confirm
from .state import (
    check_read_freshness,
    diff_counts,
    record_change,
    record_read,
    snapshot_original,
)


SCHEMA = {
    "name": "edit_file",
    "description": _load_description(__file__),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean", "default": False},
        },
        "required": ["path", "old_string", "new_string"],
    },
}
REQUIRED = ["path", "old_string", "new_string"]
ARG_ALIASES = {
    "file_path": "path", "filename": "path", "file": "path",
    "find": "old_string", "search": "old_string", "old": "old_string",
    "replace": "new_string", "new": "new_string",
    "all": "replace_all", "global": "replace_all",
}
EXAMPLE = '{"path": "src/App.tsx", "old_string": "const x = 1", "new_string": "const x = 2"}'

# Soft limit on a single edit's "change size" — total lines added + removed.
# When exceeded, edit_file returns a nudge. Tunable via HUV_MAX_EDIT_LINES.
# replace_all=True is the explicit "I know what I'm doing" override.
MAX_EDIT_LINES = int(os.environ.get("HUV_MAX_EDIT_LINES", "120"))


def edit_file(
    ctx: ToolContext,
    path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> str:
    target = project_path(ctx, path)
    if not target.exists():
        raise ValueError(f"File not found: {path}")
    check_read_freshness(ctx, target)
    if old_string == new_string:
        raise ValueError("old_string and new_string are identical")
    if not old_string:
        raise ValueError("old_string must not be empty")

    # Scope guard.
    old_lines = old_string.count("\n") + 1
    new_lines = new_string.count("\n") + 1
    change_size = old_lines + new_lines
    if change_size > MAX_EDIT_LINES * 2 and not replace_all:
        raise ValueError(
            f"edit_file: this edit would change ~{change_size} lines in one call "
            f"(limit ~{MAX_EDIT_LINES * 2}). That's almost always too much scope. "
            f"Break it into smaller targeted edits — one element, one block, or one "
            f"function per call. If the user explicitly asked for a full rewrite, "
            f"use write_file instead."
        )

    text, newline, trailing = read_text_preserving(target)
    norm = text.replace("\r\n", "\n")
    needle = old_string.replace("\r\n", "\n")
    replacement = new_string.replace("\r\n", "\n")

    count = norm.count(needle)
    if count == 0:
        loose_norm = re.sub(r"[ \t]+\n", "\n", norm)
        loose_needle = re.sub(r"[ \t]+\n", "\n", needle)
        loose_count = loose_norm.count(loose_needle)
        if loose_count == 0:
            raise ValueError(
                f"old_string not found in {path}. Re-read file — content differs from your expectation."
            )
        if loose_count > 1 and not replace_all:
            raise ValueError(
                f"old_string matches {loose_count} locations (whitespace-loose). Add context or replace_all=true."
            )
        new_norm = loose_norm.replace(loose_needle, replacement, -1 if replace_all else 1)
        n_changed = loose_count if replace_all else 1
    elif count > 1 and not replace_all:
        raise ValueError(
            f"old_string matches {count} locations in {path}. Add surrounding context or replace_all=true."
        )
    else:
        new_norm = norm.replace(needle, replacement, -1 if replace_all else 1)
        n_changed = count if replace_all else 1

    if ctx.verbose:
        diff = "\n".join(
            difflib.unified_diff(
                norm.splitlines(), new_norm.splitlines(),
                fromfile=f"{path} (old)", tofile=f"{path} (new)", lineterm="",
            )
        )
        if diff:
            print(colorize_diff(diff[:12000]))
    label = f"Edit {path} ({n_changed} replacement{'s' if n_changed != 1 else ''})?"
    if not confirm(ctx, label, kind="edit"):
        return "Edit cancelled"

    snapshot_original(ctx, target)
    out = new_norm.replace("\n", newline) if newline == "\r\n" else new_norm
    if trailing and not out.endswith(newline):
        out += newline
    elif not trailing and out.endswith(newline):
        out = out[: -len(newline)]
    target.write_bytes(out.encode("utf-8"))
    record_read(ctx, target)
    adds, dels = diff_counts(norm, new_norm)
    record_change(ctx, target, "modified", adds, dels)
    return f"Edited {path} ({n_changed} replacement{'s' if n_changed != 1 else ''})"


def call(ctx: ToolContext, args: dict) -> str:
    return edit_file(
        ctx, str(args["path"]),
        str(args["old_string"]), str(args["new_string"]),
        bool(args.get("replace_all", False)),
    )
