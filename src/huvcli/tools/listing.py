"""list_files — enumerate project files (gitignore-aware when possible)."""

from __future__ import annotations

import os
from pathlib import Path

from .context import ToolContext
from .descriptions import load as _load_description
from .paths import SKIP_DIRS, git_tracked


SCHEMA = {
    "name": "list_files",
    "description": _load_description(__file__),
    "parameters": {
        "type": "object",
        "properties": {"max_files": {"type": "integer", "default": 500}},
    },
}

REQUIRED: list[str] = []
ARG_ALIASES: dict[str, str] = {}
EXAMPLE = '{"max_files": 500}'


def list_files(ctx: ToolContext, max_files: int = 500) -> str:
    tracked = git_tracked(ctx)
    if tracked is not None:
        items = tracked[:max_files]
        if len(tracked) > max_files:
            return "\n".join(items) + "\n...truncated"
        return "\n".join(items) or "(no files)"
    items: list[str] = []
    for root, dirs, files in os.walk(ctx.cwd):
        dirs[:] = [item for item in dirs if item not in SKIP_DIRS]
        for name in files:
            rel = str((Path(root) / name).relative_to(ctx.cwd))
            items.append(rel)
            if len(items) >= max_files:
                return "\n".join(items) + "\n...truncated"
    return "\n".join(items) or "(no files)"


def call(ctx: ToolContext, args: dict) -> str:
    return list_files(ctx, int(args.get("max_files", 500)))
