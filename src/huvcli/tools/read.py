"""read_file + read_files — view file contents with cat -n line numbers."""

from __future__ import annotations

from .context import ToolContext
from .descriptions import load as _load_description
from .paths import project_path
from .state import record_read


READ_FILE_SCHEMA = {
    "name": "read_file",
    "description": _load_description(__file__, "read"),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "default": 0, "description": "0-based start line"},
            "limit": {"type": "integer", "default": 2000},
        },
        "required": ["path"],
    },
}
READ_FILE_REQUIRED = ["path"]
READ_FILE_ALIASES = {"file_path": "path", "filename": "path", "file": "path"}
READ_FILE_EXAMPLE = '{"path": "src/App.tsx"}'

READ_FILES_SCHEMA = {
    "name": "read_files",
    "description": _load_description(__file__, "read_files"),
    "parameters": {
        "type": "object",
        "properties": {
            "paths": {"type": "array", "items": {"type": "string"}},
            "offset": {"type": "integer", "default": 0},
            "limit": {"type": "integer", "default": 2000},
        },
        "required": ["paths"],
    },
}
READ_FILES_REQUIRED = ["paths"]
READ_FILES_ALIASES = {
    "file_paths": "paths", "files": "paths",
    "filenames": "paths", "path": "paths",
}
READ_FILES_EXAMPLE = '{"paths": ["src/App.tsx", "src/index.css"]}'

_MAX_FILE_BYTES = 10 * 1024 * 1024


def read_file(
    ctx: ToolContext,
    path: str,
    offset: int = 0,
    limit: int = 2000,
    max_chars: int = 200000,
) -> str:
    target = project_path(ctx, path)
    if not target.exists():
        raise ValueError(f"File not found: {path}")
    if target.is_dir():
        raise ValueError(
            f"Path is a directory, not a file: {path}. Use list_files or glob instead."
        )
    try:
        size = target.stat().st_size
    except OSError:
        size = 0
    if size > _MAX_FILE_BYTES:
        raise ValueError(
            f"File too large ({size // 1024} KB) to read in full. "
            f"Use grep or read_file with offset/limit to target a section."
        )
    raw = target.read_text(encoding="utf-8", errors="replace")
    record_read(ctx, target)
    lines = raw.splitlines()
    total = len(lines)
    start = max(0, offset)
    end = min(total, start + max(1, limit))
    window = lines[start:end]
    out_lines: list[str] = []
    width = len(str(end)) if end else 1
    chars = 0
    for i, line in enumerate(window, start + 1):
        rendered = f"{str(i).rjust(width)}\t{line}"
        chars += len(rendered) + 1
        if chars > max_chars:
            out_lines.append("...truncated (raise max_chars or shrink limit)")
            break
        out_lines.append(rendered)
    header = f"[{path}] lines {start + 1}-{end} of {total}"
    return header + "\n" + "\n".join(out_lines)


def read_files(
    ctx: ToolContext,
    paths: list[str],
    offset: int = 0,
    limit: int = 2000,
) -> str:
    if not paths:
        raise ValueError("read_files requires at least one path in `paths`")
    if isinstance(paths, str):
        paths = [paths]
    chunks: list[str] = []
    for raw in paths:
        p = str(raw)
        try:
            chunks.append(read_file(ctx, p, offset=offset, limit=limit))
        except (ValueError, OSError) as exc:
            chunks.append(f"[{p}] ERROR: {exc}")
    return "\n\n".join(chunks)


def call_read_file(ctx: ToolContext, args: dict) -> str:
    return read_file(
        ctx, str(args["path"]),
        int(args.get("offset", 0)),
        int(args.get("limit", 2000)),
    )


def call_read_files(ctx: ToolContext, args: dict) -> str:
    paths = args["paths"]
    if isinstance(paths, str):
        paths = [paths]
    return read_files(
        ctx, [str(p) for p in paths],
        int(args.get("offset", 0)),
        int(args.get("limit", 2000)),
    )
