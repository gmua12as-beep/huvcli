from __future__ import annotations

import difflib
import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


APPROVAL_SUGGEST = "suggest"
APPROVAL_AUTO_EDIT = "auto-edit"
APPROVAL_FULL_AUTO = "full-auto"
APPROVAL_MODES = {APPROVAL_SUGGEST, APPROVAL_AUTO_EDIT, APPROVAL_FULL_AUTO}


def _colorize_diff(text: str) -> str:
    """Standalone tiny diff colorizer for tools.py verbose previews."""
    import os, sys
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    out = []
    for line in text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            out.append(f"\x1b[1;90m{line}\x1b[0m")
        elif line.startswith("@@"):
            out.append(f"\x1b[35m{line}\x1b[0m")
        elif line.startswith("+"):
            out.append(f"\x1b[32m{line}\x1b[0m")
        elif line.startswith("-"):
            out.append(f"\x1b[31m{line}\x1b[0m")
        else:
            out.append(f"\x1b[2m{line}\x1b[0m")
    return "\n".join(out)


@dataclass
class ToolContext:
    cwd: Path
    yes: bool = False
    verbose: bool = False
    approval: str = APPROVAL_SUGGEST
    # mtime+size of files the model has read this session — guards stale edits.
    read_state: dict[str, tuple[float, int]] = field(default_factory=dict)
    # Plan store (codex `update_plan` style).
    plan: list[dict[str, str]] = field(default_factory=list)
    # File changes this session: rel_path -> {action, adds, dels}.
    # action ∈ {"added", "modified", "deleted"}.
    changes: dict[str, dict[str, Any]] = field(default_factory=dict)


def _record_change(ctx: ToolContext, target: Path, action: str, adds: int = 0, dels: int = 0) -> None:
    key = _rel(ctx, target)
    prior = ctx.changes.get(key)
    if prior:
        # Once "added", stay "added" even on subsequent edits.
        if prior["action"] == "added" and action == "modified":
            action = "added"
        # Once "deleted", that's terminal.
        if prior["action"] == "deleted":
            action = "deleted"
        adds += prior.get("adds", 0)
        dels += prior.get("dels", 0)
    ctx.changes[key] = {"action": action, "adds": adds, "dels": dels}


def _diff_counts(old: str, new: str) -> tuple[int, int]:
    """Cheap +/- line counts via difflib."""
    adds = dels = 0
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), n=0, lineterm=""):
        if line.startswith("+") and not line.startswith("+++"):
            adds += 1
        elif line.startswith("-") and not line.startswith("---"):
            dels += 1
    return adds, dels


def _project_path(ctx: ToolContext, value: str) -> Path:
    path = (ctx.cwd / value).resolve()
    root = ctx.cwd.resolve()
    if path != root and root not in path.parents:
        raise ValueError("Path outside project denied")
    return path


def _rel(ctx: ToolContext, target: Path) -> str:
    try:
        return str(target.relative_to(ctx.cwd.resolve()))
    except ValueError:
        return str(target)


def _confirm(ctx: ToolContext, prompt: str, kind: str = "edit") -> bool:
    # Approval matrix: suggest = ask everything; auto-edit = auto edits, ask commands;
    # full-auto = auto everything except dangerous.
    if ctx.yes:
        return True
    if ctx.approval == APPROVAL_FULL_AUTO and kind != "dangerous":
        return True
    if ctx.approval == APPROVAL_AUTO_EDIT and kind == "edit":
        return True
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except EOFError:
        return False
    return answer in {"y", "yes"}


def _read_text_preserving(target: Path) -> tuple[str, str, bool]:
    if not target.exists():
        return "", "\n", False
    raw = target.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    newline = "\r\n" if b"\r\n" in raw else "\n"
    had_trailing = text.endswith("\n") or text.endswith("\r")
    return text, newline, had_trailing


def _write_text_preserving(target: Path, lines: list[str], newline: str, trailing: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    body = newline.join(lines)
    if trailing and lines:
        body += newline
    target.write_bytes(body.encode("utf-8"))


def _record_read(ctx: ToolContext, target: Path) -> None:
    if target.exists():
        st = target.stat()
        ctx.read_state[str(target.resolve())] = (st.st_mtime, st.st_size)


def _check_read_freshness(ctx: ToolContext, target: Path) -> None:
    key = str(target.resolve())
    if key not in ctx.read_state:
        raise ValueError(
            f"Refusing to edit {_rel(ctx, target)}: read_file it first so edits reflect current contents."
        )
    if not target.exists():
        return
    st = target.stat()
    recorded = ctx.read_state[key]
    if (st.st_mtime, st.st_size) != recorded:
        raise ValueError(
            f"{_rel(ctx, target)} changed on disk since last read. Re-read before editing."
        )


_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build", ".huvcli", ".idea", ".vscode"}


def _git_tracked(ctx: ToolContext) -> list[str] | None:
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


def list_files(ctx: ToolContext, max_files: int = 200) -> str:
    tracked = _git_tracked(ctx)
    if tracked is not None:
        items = tracked[:max_files]
        if len(tracked) > max_files:
            return "\n".join(items) + "\n...truncated"
        return "\n".join(items) or "(no files)"
    items: list[str] = []
    for root, dirs, files in os.walk(ctx.cwd):
        dirs[:] = [item for item in dirs if item not in _SKIP_DIRS]
        for name in files:
            rel = str((Path(root) / name).relative_to(ctx.cwd))
            items.append(rel)
            if len(items) >= max_files:
                return "\n".join(items) + "\n...truncated"
    return "\n".join(items) or "(no files)"


def glob_files(ctx: ToolContext, pattern: str, max_files: int = 200) -> str:
    """Glob match relative to cwd. Supports ** recursion."""
    matches = sorted(str(p.relative_to(ctx.cwd)) for p in ctx.cwd.glob(pattern) if p.is_file())
    # Filter skip dirs.
    matches = [m for m in matches if not any(part in _SKIP_DIRS for part in Path(m).parts)]
    if not matches:
        return "(no matches)"
    if len(matches) > max_files:
        return "\n".join(matches[:max_files]) + "\n...truncated"
    return "\n".join(matches)


def grep(ctx: ToolContext, pattern: str, path: str | None = None, glob: str | None = None, max_matches: int = 200) -> str:
    """Search file contents. Uses ripgrep if available, else Python fallback."""
    target_dir = _project_path(ctx, path) if path else ctx.cwd
    rg = _which("rg")
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
            # Rewrite absolute paths to relative.
            rel_lines = [_rewrite_path_prefix(line, ctx.cwd) for line in lines]
            return "\n".join(rel_lines) + suffix
        except subprocess.SubprocessError:
            pass
    # Fallback: python walk.
    regex = re.compile(pattern)
    results: list[str] = []
    for root, dirs, files in os.walk(target_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if glob and not fnmatch.fnmatch(name, glob):
                continue
            fp = Path(root) / name
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


def _which(name: str) -> str | None:
    from shutil import which
    return which(name)


def _rewrite_path_prefix(line: str, cwd: Path) -> str:
    prefix = str(cwd.resolve())
    if line.startswith(prefix):
        rest = line[len(prefix):].lstrip("\\/")
        return rest
    return line


def read_file(ctx: ToolContext, path: str, offset: int = 0, limit: int = 2000, max_chars: int = 200000) -> str:
    """Read file with cat -n style line numbers + offset/limit. Records read for staleness guard."""
    target = _project_path(ctx, path)
    if not target.exists():
        raise ValueError(f"File not found: {path}")
    raw = target.read_text(encoding="utf-8", errors="replace")
    _record_read(ctx, target)
    lines = raw.splitlines()
    total = len(lines)
    start = max(0, offset)
    end = min(total, start + max(1, limit))
    window = lines[start:end]
    out_lines = []
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


def write_file(ctx: ToolContext, path: str, content: str) -> str:
    target = _project_path(ctx, path)
    existed = target.exists()
    old = target.read_text(encoding="utf-8", errors="replace") if existed else ""
    diff = "\n".join(
        difflib.unified_diff(
            old.splitlines(), content.splitlines(),
            fromfile=f"{path} (old)", tofile=f"{path} (new)", lineterm="",
        )
    )
    if diff and ctx.verbose:
        print(_colorize_diff(diff[:12000]))
    if not _confirm(ctx, f"Write {path}?", kind="edit"):
        return "Write cancelled"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _record_read(ctx, target)
    adds, dels = _diff_counts(old, content)
    _record_change(ctx, target, "added" if not existed else "modified", adds, dels)
    return f"Wrote {path}"


def edit_file(ctx: ToolContext, path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    target = _project_path(ctx, path)
    if not target.exists():
        raise ValueError(f"File not found: {path}")
    _check_read_freshness(ctx, target)
    if old_string == new_string:
        raise ValueError("old_string and new_string are identical")
    if not old_string:
        raise ValueError("old_string must not be empty")

    text, newline, trailing = _read_text_preserving(target)
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
            print(_colorize_diff(diff[:12000]))
    if not _confirm(ctx, f"Edit {path} ({n_changed} replacement{'s' if n_changed != 1 else ''})?", kind="edit"):
        return "Edit cancelled"

    out = new_norm.replace("\n", newline) if newline == "\r\n" else new_norm
    if trailing and not out.endswith(newline):
        out += newline
    elif not trailing and out.endswith(newline):
        out = out[: -len(newline)]
    target.write_bytes(out.encode("utf-8"))
    _record_read(ctx, target)
    adds, dels = _diff_counts(norm, new_norm)
    _record_change(ctx, target, "modified", adds, dels)
    return f"Edited {path} ({n_changed} replacement{'s' if n_changed != 1 else ''})"


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
    return any(re.search(p, command, re.IGNORECASE) for p in _DANGEROUS_PATTERNS)


def run_command(ctx: ToolContext, command: str, timeout: int = 120, dangerous: bool = False) -> str:
    is_dangerous = _looks_dangerous(command) or dangerous
    if _looks_dangerous(command) and not dangerous:
        return "Command blocked: looks destructive. Re-run with dangerous=true if intentional."
    prompt = f"Run command in {ctx.cwd}: {command}?"
    if is_dangerous:
        prompt = f"DANGEROUS command in {ctx.cwd}: {command}?"
    if not _confirm(ctx, prompt, kind="dangerous" if is_dangerous else "command"):
        return "Command cancelled"
    result = subprocess.run(
        command, cwd=ctx.cwd, shell=True, text=True, capture_output=True,
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
    """codex `*** Begin Patch ... *** End Patch` envelope → unified diff.

    Recognized forms inside envelope:
      *** Add File: path
      *** Update File: path
      *** Delete File: path
      *** End Patch
    Lines inside Add/Update use '+', '-', ' ' prefixes (no @@ headers required for Add).
    """
    if "*** Begin Patch" not in patch:
        return patch
    lines = patch.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines) and not lines[i].startswith("*** Begin Patch"):
        i += 1
    i += 1  # skip Begin Patch
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
            out.append(f"--- /dev/null")
            out.append(f"+++ {path}")
            out.append(f"@@ -0,0 +1,{len(added)} @@")
            for a in added:
                out.append("+" + a)
            continue
        if line.startswith("*** Delete File:"):
            path = line[len("*** Delete File:"):].strip()
            out.append(f"--- {path}")
            out.append(f"+++ /dev/null")
            i += 1
            continue
        if line.startswith("*** Update File:"):
            path = line[len("*** Update File:"):].strip()
            i += 1
            out.append(f"--- {path}")
            out.append(f"+++ {path}")
            # Body until next *** marker. Insert synthetic @@ if missing.
            body_start = i
            while i < len(lines) and not lines[i].startswith("*** "):
                i += 1
            body = lines[body_start:i]
            if body and not body[0].startswith("@@"):
                # Best-effort header — fuzzy locator will fix line numbers.
                out.append("@@ -1 +1 @@")
            out.extend(body)
            continue
        i += 1
    return "\n".join(out)


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
        target = _project_path(ctx, path)
        if new_path is None:
            changes.append((target, None, "\n", False))
            while index < len(patch_lines) and not patch_lines[index].startswith("--- "):
                index += 1
            continue
        old_text, newline, trailing = _read_text_preserving(target)
        old_lines = old_text.splitlines()
        try:
            new_lines, index = _apply_hunks(old_lines, patch_lines, index)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from None
        changes.append((target, new_lines, newline, trailing if old_text else True))
    if not changes:
        raise ValueError("No unified diff found")
    if ctx.verbose:
        print(patch[:12000])
    if not _confirm(ctx, f"Apply patch to {len(changes)} file(s)?", kind="edit"):
        return "Patch cancelled"
    results: list[str] = []
    for target, lines, newline, trailing in changes:
        if lines is None:
            existed = target.exists()
            if existed:
                target.unlink()
            _record_change(ctx, target, "deleted")
            results.append(f"Deleted {_rel(ctx, target)}")
            continue
        existed = target.exists()
        old_text = target.read_text(encoding="utf-8", errors="replace") if existed else ""
        _write_text_preserving(target, lines, newline, trailing)
        _record_read(ctx, target)
        new_text = "\n".join(lines)
        adds, dels = _diff_counts(old_text, new_text)
        _record_change(ctx, target, "added" if not existed else "modified", adds, dels)
        results.append(f"Patched {_rel(ctx, target)}")
    return "\n".join(results)


def update_plan(ctx: ToolContext, steps: list[dict[str, str]]) -> str:
    """Codex-style plan tool. Each step: {step: str, status: pending|in_progress|completed}."""
    cleaned: list[dict[str, str]] = []
    for item in steps:
        if not isinstance(item, dict):
            raise ValueError("Each plan step must be an object")
        step = str(item.get("step") or item.get("content") or "").strip()
        status = str(item.get("status", "pending")).strip().lower()
        if status not in {"pending", "in_progress", "completed"}:
            status = "pending"
        if step:
            cleaned.append({"step": step, "status": status})
    ctx.plan = cleaned
    icon = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}
    return "\n".join(f"{icon.get(s['status'], '[ ]')} {s['step']}" for s in cleaned) or "(empty plan)"


# Tool schemas for native function-calling APIs.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "list_files",
        "description": "List project files (respects .gitignore via git ls-files when available).",
        "parameters": {
            "type": "object",
            "properties": {"max_files": {"type": "integer", "default": 200}},
        },
    },
    {
        "name": "glob",
        "description": "Glob match files with ** recursion (e.g. 'src/**/*.py').",
        "parameters": {
            "type": "object",
            "properties": {"pattern": {"type": "string"}, "max_files": {"type": "integer", "default": 200}},
            "required": ["pattern"],
        },
    },
    {
        "name": "grep",
        "description": "Search file contents by regex. Uses ripgrep when available.",
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
    },
    {
        "name": "read_file",
        "description": "Read file with cat -n line numbers. Use offset/limit for large files. Required before edit_file.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "default": 0, "description": "0-based start line"},
                "limit": {"type": "integer", "default": 2000},
            },
            "required": ["path"],
        },
    },
    {
        "name": "edit_file",
        "description": "Exact-string replacement. old_string must be unique (or replace_all=true). Requires prior read_file.",
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
    },
    {
        "name": "write_file",
        "description": "Create new file or full rewrite. Prefer edit_file for changes to existing files.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
    },
    {
        "name": "apply_patch",
        "description": "Apply unified diff or codex '*** Begin Patch / *** End Patch' envelope. Multi-file capable.",
        "parameters": {
            "type": "object",
            "properties": {"patch": {"type": "string"}},
            "required": ["patch"],
        },
    },
    {
        "name": "run_command",
        "description": "Run shell command in project. Set dangerous=true for destructive ops.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "default": 120},
                "dangerous": {"type": "boolean", "default": False},
            },
            "required": ["command"],
        },
    },
    {
        "name": "update_plan",
        "description": "Replace current task plan. Use for multi-step work. Steps: [{step, status: pending|in_progress|completed}].",
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "step": {"type": "string"},
                            "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                        },
                        "required": ["step"],
                    },
                },
            },
            "required": ["steps"],
        },
    },
]


def call_tool(ctx: ToolContext, tool: str, args: dict[str, Any]) -> str:
    if tool == "list_files":
        return list_files(ctx, int(args.get("max_files", 200)))
    if tool == "glob":
        return glob_files(ctx, str(args["pattern"]), int(args.get("max_files", 200)))
    if tool == "grep":
        return grep(
            ctx, str(args["pattern"]),
            args.get("path"), args.get("glob"), int(args.get("max_matches", 200)),
        )
    if tool == "read_file":
        return read_file(
            ctx, str(args["path"]),
            int(args.get("offset", 0)), int(args.get("limit", 2000)),
        )
    if tool == "write_file":
        return write_file(ctx, str(args["path"]), str(args["content"]))
    if tool == "edit_file":
        return edit_file(
            ctx, str(args["path"]),
            str(args["old_string"]), str(args["new_string"]),
            bool(args.get("replace_all", False)),
        )
    if tool == "apply_patch":
        return apply_patch(ctx, str(args["patch"]))
    if tool == "run_command":
        return run_command(
            ctx, str(args["command"]),
            int(args.get("timeout", 120)), bool(args.get("dangerous", False)),
        )
    if tool == "update_plan":
        return update_plan(ctx, list(args.get("steps") or []))
    raise ValueError(f"Unknown tool: {tool}")
