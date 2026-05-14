"""Stateful helpers operating on ToolContext: read-tracking, change recording, snapshots.

Kept separate from `paths.py` (stateless filesystem helpers) and `context.py`
(the dataclass) to avoid import cycles and keep responsibilities clear.
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import TYPE_CHECKING

from .paths import rel

if TYPE_CHECKING:
    from .context import ToolContext


def record_read(ctx: "ToolContext", target: Path) -> None:
    """Capture mtime+size so we can refuse stale edits later."""
    if target.exists():
        st = target.stat()
        ctx.read_state[str(target.resolve())] = (st.st_mtime, st.st_size)


def check_read_freshness(ctx: "ToolContext", target: Path) -> None:
    """Raise if the file was not read this session, or if it changed on disk."""
    key = str(target.resolve())
    if key not in ctx.read_state:
        raise ValueError(
            f"Refusing to edit {rel(ctx, target)}: read_file it first so edits "
            f"reflect current contents."
        )
    if not target.exists():
        return
    st = target.stat()
    recorded = ctx.read_state[key]
    if (st.st_mtime, st.st_size) != recorded:
        raise ValueError(
            f"{rel(ctx, target)} changed on disk since last read. Re-read before editing."
        )


def snapshot_original(ctx: "ToolContext", target: Path) -> None:
    """Capture original file bytes (or None marker) on first touch this session."""
    key = rel(ctx, target)
    if key in ctx.originals:
        return
    if target.exists():
        try:
            ctx.originals[key] = target.read_bytes()
        except OSError:
            ctx.originals[key] = None
    else:
        ctx.originals[key] = None


def record_change(ctx: "ToolContext", target: Path, action: str, adds: int = 0, dels: int = 0) -> None:
    """Roll up a per-file change. Sticky-add and sticky-deleted semantics."""
    key = rel(ctx, target)
    prior = ctx.changes.get(key)
    if prior:
        if prior["action"] == "added" and action == "modified":
            action = "added"
        if prior["action"] == "deleted":
            action = "deleted"
        adds += prior.get("adds", 0)
        dels += prior.get("dels", 0)
    ctx.changes[key] = {"action": action, "adds": adds, "dels": dels}


def diff_counts(old: str, new: str) -> tuple[int, int]:
    """Cheap +/- line counts via difflib (n=0 keeps the diff tight)."""
    adds = dels = 0
    for line in difflib.unified_diff(old.splitlines(), new.splitlines(), n=0, lineterm=""):
        if line.startswith("+") and not line.startswith("+++"):
            adds += 1
        elif line.startswith("-") and not line.startswith("---"):
            dels += 1
    return adds, dels
