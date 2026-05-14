"""Tool registry — single source of truth for schemas, aliases, dispatch.

Each tool module declares its own `SCHEMA`, `REQUIRED`, `ARG_ALIASES`, `EXAMPLE`,
and `call(ctx, args)` function. The registry stitches them together so adding a
new tool is one module + one entry here.
"""

from __future__ import annotations

from typing import Any, Callable

from .context import ToolContext
from .permission import APPROVAL_PLAN, MUTATING_TOOLS
from . import (
    edit, glob, listing, overview, patch, plan, question,
    read, search, shell, webfetch, write,
)


# Each registry entry: (call_fn, required_args, alias_map, example_str).
_Caller = Callable[[ToolContext, dict[str, Any]], str]
_TOOLS: dict[str, tuple[_Caller, list[str], dict[str, str], str]] = {
    "list_files": (listing.call, listing.REQUIRED, listing.ARG_ALIASES, listing.EXAMPLE),
    "glob":       (glob.call,    glob.REQUIRED,    glob.ARG_ALIASES,    glob.EXAMPLE),
    "grep":       (search.call,  search.REQUIRED,  search.ARG_ALIASES,  search.EXAMPLE),
    "read_file":  (read.call_read_file,  read.READ_FILE_REQUIRED,  read.READ_FILE_ALIASES,  read.READ_FILE_EXAMPLE),
    "read_files": (read.call_read_files, read.READ_FILES_REQUIRED, read.READ_FILES_ALIASES, read.READ_FILES_EXAMPLE),
    "write_file": (write.call,   write.REQUIRED,   write.ARG_ALIASES,   write.EXAMPLE),
    "edit_file":  (edit.call,    edit.REQUIRED,    edit.ARG_ALIASES,    edit.EXAMPLE),
    "apply_patch":(patch.call,   patch.REQUIRED,   patch.ARG_ALIASES,   patch.EXAMPLE),
    "run_command":(shell.call,   shell.REQUIRED,   shell.ARG_ALIASES,   shell.EXAMPLE),
    "update_plan":(plan.call,    plan.REQUIRED,    plan.ARG_ALIASES,    plan.EXAMPLE),
    "webfetch":   (webfetch.call, webfetch.REQUIRED, webfetch.ARG_ALIASES, webfetch.EXAMPLE),
    "question":   (question.call, question.REQUIRED, question.ARG_ALIASES, question.EXAMPLE),
    "repo_overview": (overview.call, overview.REQUIRED, overview.ARG_ALIASES, overview.EXAMPLE),
}


# Schemas — exported in a stable order matching _TOOLS.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    listing.SCHEMA,
    glob.SCHEMA,
    search.SCHEMA,
    read.READ_FILE_SCHEMA,
    read.READ_FILES_SCHEMA,
    edit.SCHEMA,
    write.SCHEMA,
    patch.SCHEMA,
    shell.SCHEMA,
    plan.SCHEMA,
    webfetch.SCHEMA,
    question.SCHEMA,
    overview.SCHEMA,
]


def schemas_for(approval: str) -> list[dict[str, Any]]:
    """Schemas filtered for the given approval mode.

    In `plan` mode the model never sees mutating tools — it can't even try
    to call them. Keeps plan mode honest as a pure-read planning pass.
    """
    if approval == APPROVAL_PLAN:
        return [s for s in TOOL_SCHEMAS if s["name"] not in MUTATING_TOOLS]
    return TOOL_SCHEMAS


def _normalize_args(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Apply aliases and verify required keys, raising a useful error.

    Empty-args is a distinct failure mode — gives the model a concrete
    example to copy rather than a generic "missing X" message.
    """
    entry = _TOOLS.get(tool)
    if entry is None:
        return dict(args)
    _, required, aliases, example = entry

    if required and not args:
        raise ValueError(
            f"called {tool} with NO arguments. This tool requires {required}. "
            f"Pass them in the function `arguments` field as JSON. "
            f"Example: {tool}({example}). "
            f"Do NOT pass an empty object — fill in every required field with real values."
        )
    out: dict[str, Any] = {}
    for k, v in args.items():
        target = aliases.get(k, k)
        if target not in out:
            out[target] = v
    missing = [r for r in required if r not in out or out[r] in (None, "")]
    if missing:
        provided = sorted(args.keys())
        raise ValueError(
            f"missing required arg(s) {missing} for {tool}. "
            f"You sent keys: {provided}. Required: {required}. "
            f"Example of a correct call: {tool}({example})"
        )
    return out


def call_tool(ctx: ToolContext, tool: str, args: dict[str, Any]) -> str:
    """Dispatch a model-issued tool call. Normalises args first.

    In `plan` mode, refuses mutating tools at the dispatch boundary so even
    if the model somehow received their schemas, the call still fails safely.
    """
    if ctx.approval == APPROVAL_PLAN and tool in MUTATING_TOOLS:
        return (
            f"Refused: {tool} is not available in plan mode. "
            "Plan mode is read-only — outline the change and end with a final "
            "answer summarizing what you would do. The user will re-run in "
            "auto-edit mode to execute."
        )
    args = _normalize_args(tool, args)
    entry = _TOOLS.get(tool)
    if entry is None:
        raise ValueError(f"Unknown tool: {tool}")
    return entry[0](ctx, args)
