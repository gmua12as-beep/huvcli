"""update_plan — set the agent's task plan (codex-style)."""

from __future__ import annotations

from .context import ToolContext
from .descriptions import load as _load_description


SCHEMA = {
    "name": "update_plan",
    "description": _load_description(__file__),
    "parameters": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                        },
                    },
                    "required": ["step"],
                },
            },
        },
        "required": ["steps"],
    },
}
REQUIRED = ["steps"]
ARG_ALIASES = {"plan": "steps", "todos": "steps", "items": "steps"}
EXAMPLE = '{"steps": [{"step": "do x", "status": "in_progress"}]}'

_ICON = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}


def update_plan(ctx: ToolContext, steps: list[dict[str, str]]) -> str:
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
    return "\n".join(f"{_ICON.get(s['status'], '[ ]')} {s['step']}" for s in cleaned) or "(empty plan)"


def call(ctx: ToolContext, args: dict) -> str:
    return update_plan(ctx, list(args.get("steps") or []))
