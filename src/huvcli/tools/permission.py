"""Approval modes + user confirmation prompt."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .context import ToolContext


APPROVAL_SUGGEST = "suggest"
APPROVAL_AUTO_EDIT = "auto-edit"
APPROVAL_FULL_AUTO = "full-auto"
APPROVAL_PLAN = "plan"
APPROVAL_MODES = {APPROVAL_SUGGEST, APPROVAL_AUTO_EDIT, APPROVAL_FULL_AUTO, APPROVAL_PLAN}

# Tools that mutate the workspace or the outside world. In `plan` mode the
# registry refuses to dispatch them — model must plan, not act.
MUTATING_TOOLS = frozenset({
    "write_file", "edit_file", "apply_patch", "run_command",
})


def confirm(ctx: "ToolContext", prompt: str, kind: str = "edit") -> bool:
    """Ask the user (or auto-approve based on `ctx.approval` and `ctx.yes`).

    `kind` ∈ {"edit", "command", "dangerous"}.
    """
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
