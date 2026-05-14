"""glob — match files by pattern with ** recursion."""

from __future__ import annotations

from pathlib import Path

from .context import ToolContext
from .descriptions import load as _load_description
from .paths import SKIP_DIRS


SCHEMA = {
    "name": "glob",
    "description": _load_description(__file__),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "max_files": {"type": "integer", "default": 500},
        },
        "required": ["pattern"],
    },
}

REQUIRED = ["pattern"]
ARG_ALIASES = {"glob": "pattern", "match": "pattern"}
EXAMPLE = '{"pattern": "src/**/*.tsx"}'


def glob_files(ctx: ToolContext, pattern: str, max_files: int = 200) -> str:
    matches = sorted(
        str(p.relative_to(ctx.cwd))
        for p in ctx.cwd.glob(pattern)
        if p.is_file()
    )
    matches = [m for m in matches if not any(part in SKIP_DIRS for part in Path(m).parts)]
    if not matches:
        return "(no matches)"
    if len(matches) > max_files:
        return "\n".join(matches[:max_files]) + "\n...truncated"
    return "\n".join(matches)


def call(ctx: ToolContext, args: dict) -> str:
    return glob_files(ctx, str(args["pattern"]), int(args.get("max_files", 200)))
