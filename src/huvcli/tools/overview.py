"""repo_overview — project skeleton via regex (no tree-sitter dependency).

For each tracked source file, extract top-level declarations: functions,
classes, types, exported names. Output is a tree of paths with their
symbols — gives the model project shape in one tool call instead of N
read_file dumps.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .context import ToolContext
from .descriptions import load as _load_description
from .paths import SKIP_DIRS, git_tracked


SCHEMA = {
    "name": "repo_overview",
    "description": _load_description(__file__),
    "parameters": {
        "type": "object",
        "properties": {
            "max_files": {"type": "integer", "default": 200},
            "max_symbols_per_file": {"type": "integer", "default": 20},
            "path": {
                "type": "string",
                "description": "Optional subdir to limit the overview to.",
            },
        },
    },
}
REQUIRED: list[str] = []
ARG_ALIASES = {"directory": "path", "dir": "path", "root": "path"}
EXAMPLE = '{"max_files": 200}'


# Per-language extractors. Each entry: (set_of_extensions, list_of_regexes).
# Regexes are line-anchored at column 0 so we only catch top-level decls.
_LANGS: list[tuple[set[str], list[re.Pattern[str]]]] = [
    # Python
    (
        {".py"},
        [
            re.compile(r"^(?:async\s+)?def\s+(\w+)\s*\("),
            re.compile(r"^class\s+(\w+)"),
            re.compile(r"^([A-Z_][A-Z0-9_]+)\s*[:=]"),  # module-level CONST
        ],
    ),
    # JS / TS / JSX / TSX
    (
        {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"},
        [
            re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+(\w+)"),
            re.compile(r"^(?:export\s+)?(?:default\s+)?class\s+(\w+)"),
            re.compile(r"^(?:export\s+)?interface\s+(\w+)"),
            re.compile(r"^(?:export\s+)?type\s+(\w+)"),
            re.compile(r"^(?:export\s+)?(?:const|let|var)\s+(\w+)"),
            re.compile(r"^(?:export\s+)?enum\s+(\w+)"),
        ],
    ),
    # Go
    (
        {".go"},
        [
            re.compile(r"^func\s+(?:\([^)]*\)\s+)?(\w+)\s*\("),
            re.compile(r"^type\s+(\w+)\b"),
            re.compile(r"^var\s+(\w+)\b"),
            re.compile(r"^const\s+(\w+)\b"),
        ],
    ),
    # Rust
    (
        {".rs"},
        [
            re.compile(r"^(?:pub\s+)?(?:async\s+)?fn\s+(\w+)"),
            re.compile(r"^(?:pub\s+)?struct\s+(\w+)"),
            re.compile(r"^(?:pub\s+)?enum\s+(\w+)"),
            re.compile(r"^(?:pub\s+)?trait\s+(\w+)"),
            re.compile(r"^impl(?:<[^>]*>)?\s+(\w+)"),
            re.compile(r"^(?:pub\s+)?type\s+(\w+)"),
        ],
    ),
    # Java
    (
        {".java"},
        [
            re.compile(r"^\s*public\s+(?:static\s+|final\s+|abstract\s+)*(?:class|interface|enum)\s+(\w+)"),
            re.compile(r"^\s*(?:public|protected|private)\s+(?:static\s+)?(?:[\w<>\[\]]+\s+)?(\w+)\s*\("),
        ],
    ),
    # Ruby
    (
        {".rb"},
        [
            re.compile(r"^class\s+(\w+)"),
            re.compile(r"^module\s+(\w+)"),
            re.compile(r"^def\s+(\w+)"),
        ],
    ),
    # PHP
    (
        {".php"},
        [
            re.compile(r"^(?:abstract\s+|final\s+)?class\s+(\w+)"),
            re.compile(r"^interface\s+(\w+)"),
            re.compile(r"^trait\s+(\w+)"),
            re.compile(r"^function\s+(\w+)"),
        ],
    ),
    # Swift
    (
        {".swift"},
        [
            re.compile(r"^(?:public\s+|open\s+|private\s+|internal\s+)?(?:final\s+)?class\s+(\w+)"),
            re.compile(r"^(?:public\s+|open\s+|private\s+|internal\s+)?struct\s+(\w+)"),
            re.compile(r"^(?:public\s+|open\s+|private\s+|internal\s+)?protocol\s+(\w+)"),
            re.compile(r"^(?:public\s+|open\s+|private\s+|internal\s+)?func\s+(\w+)"),
            re.compile(r"^(?:public\s+|open\s+|private\s+|internal\s+)?enum\s+(\w+)"),
        ],
    ),
]

_MAX_FILE_BYTES = 1 * 1024 * 1024  # don't try to parse huge files


def _patterns_for(path: Path) -> list[re.Pattern[str]] | None:
    ext = path.suffix.lower()
    for exts, patterns in _LANGS:
        if ext in exts:
            return patterns
    return None


def _label_for(line: str, name: str) -> str:
    """Return a short label like 'class', 'fn', 'export const' for display."""
    stripped = line.lstrip()
    head = stripped.split(name, 1)[0].strip()
    # Trim trailing keywords like 'async ' etc. for readability.
    return head if head else "symbol"


def _extract_symbols(path: Path, patterns: list[re.Pattern[str]], cap: int) -> list[str]:
    syms: list[str] = []
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("#") or line.startswith("//"):
                    continue
                # Strip trailing whitespace and limit length to keep regex fast.
                trimmed = line.rstrip()[:300]
                for pat in patterns:
                    m = pat.match(trimmed)
                    if m:
                        name = m.group(1)
                        label = _label_for(trimmed, name)
                        syms.append(f"{label} {name}".strip())
                        if len(syms) >= cap:
                            return syms
                        break
    except OSError:
        return syms
    return syms


def repo_overview(
    ctx: ToolContext,
    max_files: int = 200,
    max_symbols_per_file: int = 20,
    path: str | None = None,
) -> str:
    # Determine the file set.
    base = ctx.cwd
    if path:
        sub = (base / path).resolve()
        if base.resolve() not in (sub, *sub.parents):
            raise ValueError(f"Path {path!r} is outside the project root")
        base = sub

    tracked = git_tracked(ctx) if base == ctx.cwd else None
    files: list[Path] = []
    if tracked is not None:
        for rel in tracked:
            p = (ctx.cwd / rel).resolve()
            if p.is_file():
                files.append(p)
    else:
        for root, dirs, names in os.walk(base):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in names:
                files.append(Path(root) / name)
    files.sort()

    if not files:
        return "(no files)"

    lines: list[str] = []
    counted = 0
    for fp in files:
        if counted >= max_files:
            lines.append(f"... ({len(files) - counted} more files truncated)")
            break
        try:
            if fp.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        patterns = _patterns_for(fp)
        try:
            rel = str(fp.relative_to(ctx.cwd))
        except ValueError:
            rel = str(fp)
        if patterns is None:
            # Still show the file so the model knows it exists.
            lines.append(rel)
            counted += 1
            continue
        syms = _extract_symbols(fp, patterns, max_symbols_per_file)
        lines.append(rel)
        for s in syms:
            lines.append(f"  {s}")
        counted += 1
    return "\n".join(lines)


def call(ctx: ToolContext, args: dict) -> str:
    return repo_overview(
        ctx,
        int(args.get("max_files", 200)),
        int(args.get("max_symbols_per_file", 20)),
        args.get("path"),
    )
