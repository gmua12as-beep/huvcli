from __future__ import annotations

import difflib
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ToolContext:
    cwd: Path
    yes: bool = False


def _project_path(ctx: ToolContext, value: str) -> Path:
    path = (ctx.cwd / value).resolve()
    root = ctx.cwd.resolve()
    if path != root and root not in path.parents:
        raise ValueError("Path outside project denied")
    return path


def _confirm(ctx: ToolContext, prompt: str) -> bool:
    if ctx.yes:
        return True
    answer = input(f"{prompt} [y/N] ").strip().lower()
    return answer in {"y", "yes"}


def list_files(ctx: ToolContext, max_files: int = 200) -> str:
    items: list[str] = []
    skip_dirs = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
    for root, dirs, files in os.walk(ctx.cwd):
        dirs[:] = [item for item in dirs if item not in skip_dirs]
        for name in files:
            rel = str((Path(root) / name).relative_to(ctx.cwd))
            items.append(rel)
            if len(items) >= max_files:
                return "\n".join(items) + "\n...truncated"
    return "\n".join(items) or "(no files)"


def read_file(ctx: ToolContext, path: str, max_chars: int = 20000) -> str:
    target = _project_path(ctx, path)
    data = target.read_text(encoding="utf-8", errors="replace")
    if len(data) > max_chars:
        return data[:max_chars] + "\n...truncated"
    return data


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    target = _project_path(ctx, path)
    old = ""
    if target.exists():
        old = target.read_text(encoding="utf-8", errors="replace")
    diff = "\n".join(
        difflib.unified_diff(
            old.splitlines(),
            content.splitlines(),
            fromfile=f"{path} (old)",
            tofile=f"{path} (new)",
            lineterm="",
        )
    )
    if diff:
        print(diff[:12000])
    if not _confirm(ctx, f"Write {path}?"):
        return "Write cancelled"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {path}"


_DANGEROUS_PATTERNS = [
    r"\bRemove-Item\b.*\s-(?:Recurse|Force)\b",
    r"\brm\b.*\s-rf\b",
    r"\brmdir\b.*\s/(?:s|q)\b",
    r"\bdel\b.*\s/(?:s|q)\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\s+-[^\s]*f",
    r"\bformat\b",
    r"\bshutdown\b",
    r"\bInvoke-Expression\b|\biex\b",
]


def _looks_dangerous(command: str) -> bool:
    return any(re.search(pattern, command, re.IGNORECASE) for pattern in _DANGEROUS_PATTERNS)


def run_command(ctx: ToolContext, command: str, timeout: int = 120, dangerous: bool = False) -> str:
    if _looks_dangerous(command) and not dangerous:
        return "Command blocked: looks destructive. Re-run with dangerous=true if intentional."
    prompt = f"Run command in {ctx.cwd}: {command}?"
    if dangerous:
        prompt = f"DANGEROUS command in {ctx.cwd}: {command}?"
    if not _confirm(ctx, prompt):
        return "Command cancelled"
    result = subprocess.run(
        command,
        cwd=ctx.cwd,
        shell=True,
        text=True,
        capture_output=True,
        timeout=max(1, min(timeout, 3600)),
    )
    out = result.stdout.strip()
    err = result.stderr.strip()
    parts = [f"exit_code={result.returncode}"]
    if out:
        parts.append("stdout:\n" + out[-12000:])
    if err:
        parts.append("stderr:\n" + err[-12000:])
    return "\n".join(parts)


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


def _apply_unified_to_lines(old_lines: list[str], patch_lines: list[str], start: int) -> tuple[list[str], int]:
    output: list[str] = []
    cursor = 0
    index = start
    while index < len(patch_lines) and patch_lines[index].startswith("@@"):
        old_start, _new_start = _parse_hunk_header(patch_lines[index])
        target = max(old_start - 1, 0)
        if target < cursor:
            raise ValueError("Overlapping hunks")
        output.extend(old_lines[cursor:target])
        cursor = target
        index += 1
        while index < len(patch_lines) and not patch_lines[index].startswith("@@") and not patch_lines[index].startswith("--- "):
            line = patch_lines[index]
            if line.startswith("\\ No newline"):
                index += 1
                continue
            marker = line[:1]
            value = line[1:]
            if marker == " ":
                if cursor >= len(old_lines) or old_lines[cursor] != value:
                    raise ValueError(f"Patch context mismatch near: {value}")
                output.append(value)
                cursor += 1
            elif marker == "-":
                if cursor >= len(old_lines) or old_lines[cursor] != value:
                    raise ValueError(f"Patch removal mismatch near: {value}")
                cursor += 1
            elif marker == "+":
                output.append(value)
            else:
                raise ValueError(f"Bad patch line: {line}")
            index += 1
    output.extend(old_lines[cursor:])
    return output, index


def apply_patch(ctx: ToolContext, patch: str) -> str:
    patch_lines = patch.splitlines()
    index = 0
    changes: list[tuple[Path, list[str] | None]] = []
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
        target = _project_path(ctx, path)
        if new_path is None:
            changes.append((target, None))
            while index < len(patch_lines) and not patch_lines[index].startswith("--- "):
                index += 1
            continue
        old_text = "" if old_path is None or not target.exists() else target.read_text(encoding="utf-8", errors="replace")
        old_lines = old_text.splitlines()
        new_lines, index = _apply_unified_to_lines(old_lines, patch_lines, index)
        changes.append((target, new_lines))
    if not changes:
        raise ValueError("No unified diff found")
    print(patch[:12000])
    if not _confirm(ctx, f"Apply patch to {len(changes)} file(s)?"):
        return "Patch cancelled"
    results: list[str] = []
    for target, lines in changes:
        if lines is None:
            if target.exists():
                target.unlink()
            results.append(f"Deleted {target.relative_to(ctx.cwd)}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        results.append(f"Patched {target.relative_to(ctx.cwd)}")
    return "\n".join(results)


def call_tool(ctx: ToolContext, tool: str, args: dict[str, Any]) -> str:
    if tool == "list_files":
        return list_files(ctx, int(args.get("max_files", 200)))
    if tool == "read_file":
        return read_file(ctx, str(args["path"]), int(args.get("max_chars", 20000)))
    if tool == "write_file":
        return write_file(ctx, str(args["path"]), str(args["content"]))
    if tool == "apply_patch":
        return apply_patch(ctx, str(args["patch"]))
    if tool == "run_command":
        return run_command(
            ctx,
            str(args["command"]),
            int(args.get("timeout", 120)),
            bool(args.get("dangerous", False)),
        )
    raise ValueError(f"Unknown tool: {tool}")
