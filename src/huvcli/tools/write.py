"""write_file — create a new file or perform an explicit full rewrite."""

from __future__ import annotations

import difflib

from .context import ToolContext
from .descriptions import load as _load_description
from .diff import colorize_diff
from .paths import project_path
from .permission import confirm
from .state import diff_counts, record_change, record_read, snapshot_original


SCHEMA = {
    "name": "write_file",
    "description": _load_description(__file__),
    "parameters": {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["path", "content"],
    },
}
REQUIRED = ["path", "content"]
ARG_ALIASES = {
    "file_path": "path", "filename": "path", "file": "path",
    "text": "content", "data": "content", "body": "content", "source": "content",
}
EXAMPLE = '{"path": "src/Foo.tsx", "content": "import React...\\n"}'


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    target = project_path(ctx, path)
    existed = target.exists()
    old = target.read_text(encoding="utf-8", errors="replace") if existed else ""
    diff = "\n".join(
        difflib.unified_diff(
            old.splitlines(), content.splitlines(),
            fromfile=f"{path} (old)", tofile=f"{path} (new)", lineterm="",
        )
    )
    if diff and ctx.verbose:
        print(colorize_diff(diff[:12000]))
    if not confirm(ctx, f"Write {path}?", kind="edit"):
        return "Write cancelled"
    snapshot_original(ctx, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    record_read(ctx, target)
    adds, dels = diff_counts(old, content)
    record_change(ctx, target, "added" if not existed else "modified", adds, dels)
    return f"Wrote {path}"


def call(ctx: ToolContext, args: dict) -> str:
    return write_file(ctx, str(args["path"]), str(args["content"]))
