"""Status labels, result summaries, and bad-final detection."""

from __future__ import annotations


STATUS = {
    "list_files": ("Checking files...", "files"),
    "glob": ("Globbing...", "files"),
    "grep": ("Searching...", "files"),
    "read_file": ("Reading...", "read"),
    "read_files": ("Reading files...", "read"),
    "apply_patch": ("Patching...", "edit"),
    "edit_file": ("Editing...", "edit"),
    "write_file": ("Writing...", "write"),
    "run_command": ("Running...", "run"),
    "update_plan": ("Planning...", "think"),
    "webfetch": ("Fetching...", "files"),
    "question": ("Asking you...", "think"),
    "repo_overview": ("Mapping repo...", "files"),
}

# Tools fast/quiet enough that the pre-status line is pure noise — just
# show the result. Slow/blocking tools (writes, patches, commands) still
# get their pre-status so the user knows what's happening.
QUIET_PRE_STATUS = {"read_file", "read_files", "list_files", "glob", "grep", "update_plan", "repo_overview"}


def result_summary(tool: str, result: str) -> str:
    first = result.strip().splitlines()[0] if result.strip() else "done"
    if tool == "list_files":
        count = len([line for line in result.splitlines() if line and line != "...truncated"])
        return f"Found {count} files."
    if tool == "glob":
        return f"Glob: {first}"
    if tool == "grep":
        count = len(result.splitlines())
        return f"{count} match(es)" if result != "(no matches)" else "No matches"
    if tool == "read_file":
        return first
    if tool == "read_files":
        headers = [
            line for line in result.splitlines()
            if line.startswith("[") and "] lines " in line
        ]
        return f"Read {len(headers)} file(s)."
    if tool in {"apply_patch", "write_file", "edit_file"}:
        return first
    if tool == "run_command":
        return first
    if tool == "update_plan":
        return "Plan updated."
    if tool == "webfetch":
        return first  # already a "[GET 200] url" header
    if tool == "question":
        return f"User: {result[:80]}"
    if tool == "repo_overview":
        # Files = top-level lines that don't start with two spaces (symbols are indented).
        files = sum(1 for line in result.splitlines() if line and not line.startswith("  "))
        return f"Mapped {files} file(s)."
    return "Done."


def is_bad_final(answer: str) -> bool:
    normalized = " ".join(answer.strip().lower().split())
    if not normalized:
        return True
    placeholders = {"short summary", "summary", "done", "complete", "finished", "ok"}
    if normalized in placeholders:
        return True
    return len(answer.strip()) < 30
