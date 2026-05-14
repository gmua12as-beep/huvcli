"""Stateless path + file-system helpers shared by every tool."""

from __future__ import annotations

import subprocess
from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import ToolContext


SKIP_DIRS = {
    ".git", ".venv", "venv", "node_modules", "__pycache__",
    "dist", "build", ".huvcli", ".idea", ".vscode",
}

BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff",
    ".pdf", ".zip", ".gz", ".tar", ".7z", ".rar", ".bz2", ".xz",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".pyc", ".class",
    ".mp3", ".mp4", ".mov", ".avi", ".wav", ".flac",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".db", ".sqlite", ".sqlite3",
}


def project_path(ctx: "ToolContext", value: str) -> Path:
    """Resolve `value` against `ctx.cwd`. Raises if it escapes the project."""
    path = (ctx.cwd / value).resolve()
    root = ctx.cwd.resolve()
    if path != root and root not in path.parents:
        raise ValueError("Path outside project denied")
    return path


def rel(ctx: "ToolContext", target: Path) -> str:
    try:
        return str(target.relative_to(ctx.cwd.resolve()))
    except ValueError:
        return str(target)


def which_bin(name: str) -> str | None:
    return which(name)


def rewrite_path_prefix(line: str, cwd: Path) -> str:
    """Strip absolute cwd prefix so output is repo-relative."""
    prefix = str(cwd.resolve())
    if line.startswith(prefix):
        return line[len(prefix):].lstrip("\\/")
    return line


def read_text_preserving(target: Path) -> tuple[str, str, bool]:
    """Return (text, newline, had_trailing_newline). Detects CRLF on disk."""
    if not target.exists():
        return "", "\n", False
    raw = target.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    had_trailing = text.endswith("\n") or text.endswith("\r")
    return text, newline, had_trailing


def write_text_preserving(target: Path, lines: list[str], newline: str, trailing: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    body = newline.join(lines)
    if trailing and lines:
        body += newline
    target.write_bytes(body.encode("utf-8"))


def git_tracked(ctx: "ToolContext") -> list[str] | None:
    """`git ls-files` if a repo, else None."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ctx.cwd, capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


def looks_binary(path: Path) -> bool:
    if path.suffix.lower() in BINARY_EXTS:
        return True
    try:
        with path.open("rb") as f:
            chunk = f.read(4096)
    except OSError:
        return True
    if b"\x00" in chunk:
        return True
    # Heuristic: >30% non-text bytes.
    text_chars = bytes(range(32, 127)) + b"\n\r\t\b"
    non_text = sum(1 for b in chunk if b not in text_chars)
    return bool(chunk) and (non_text / len(chunk)) > 0.30
