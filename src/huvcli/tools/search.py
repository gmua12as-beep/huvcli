"""grep — regex search across project files. Uses ripgrep if installed."""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from pathlib import Path

from .context import ToolContext
from .descriptions import load as _load_description
from .paths import (
    SKIP_DIRS,
    looks_binary,
    project_path,
    rewrite_path_prefix,
    which_bin,
)


SCHEMA = {
    "name": "grep",
    "description": _load_description(__file__),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string", "description": "Optional subdir"},
            "glob": {"type": "string", "description": "Optional filename glob filter"},
            "max_matches": {"type": "integer", "default": 200},
        },
        "required": ["pattern"],
    },
}

REQUIRED = ["pattern"]
ARG_ALIASES = {
    "query": "pattern", "regex": "pattern", "search": "pattern",
    "directory": "path", "dir": "path", "include": "glob",
}
EXAMPLE = '{"pattern": "useState", "glob": "*.tsx"}'

_MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB per-file cap on Python fallback


def grep(
    ctx: ToolContext,
    pattern: str,
    path: str | None = None,
    glob: str | None = None,
    max_matches: int = 200,
) -> str:
    target_dir = project_path(ctx, path) if path else ctx.cwd
    rg = which_bin("rg")
    if rg:
        cmd = [rg, "--line-number", "--no-heading", "--color=never", "-S", pattern]
        if glob:
            cmd += ["--glob", glob]
        cmd.append(str(target_dir))
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            out = result.stdout.strip()
            lines = out.splitlines()[:max_matches]
            if not lines:
                return "(no matches)"
            suffix = "\n...truncated" if len(out.splitlines()) > max_matches else ""
            rel_lines = [rewrite_path_prefix(line, ctx.cwd) for line in lines]
            return "\n".join(rel_lines) + suffix
        except subprocess.SubprocessError:
            pass
    # Python fallback: walk, skip binaries + huge files.
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"Bad regex: {exc}") from None
    results: list[str] = []
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if glob and not fnmatch.fnmatch(name, glob):
                continue
            fp = Path(root) / name
            try:
                if fp.stat().st_size > _MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            if looks_binary(fp):
                continue
            try:
                with fp.open(encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if regex.search(line):
                            rel = str(fp.relative_to(ctx.cwd))
                            results.append(f"{rel}:{i}:{line.rstrip()}")
                            if len(results) >= max_matches:
                                return "\n".join(results) + "\n...truncated"
            except OSError:
                continue
    return "\n".join(results) if results else "(no matches)"


def call(ctx: ToolContext, args: dict) -> str:
    return grep(
        ctx, str(args["pattern"]),
        args.get("path"), args.get("glob"),
        int(args.get("max_matches", 200)),
    )
