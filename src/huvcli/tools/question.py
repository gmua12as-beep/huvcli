"""question — ask the user a clarifying question mid-task.

When the model would otherwise have to guess (ambiguous request, missing
detail), it calls this tool. We print the question, capture stdin, return
the user's answer as the tool result. Less ambiguous than emitting prose.
"""

from __future__ import annotations

import sys

from .context import ToolContext
from .descriptions import load as _load_description


SCHEMA = {
    "name": "question",
    "description": _load_description(__file__),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The question text shown to the user."},
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional preset choices the user can pick by number.",
            },
        },
        "required": ["question"],
    },
}
REQUIRED = ["question"]
ARG_ALIASES = {"prompt": "question", "ask": "question", "text": "question",
                "choices": "options", "answers": "options"}
EXAMPLE = '{"question": "Should I add tests for this change?", "options": ["yes", "no"]}'


def ask(ctx: ToolContext, question: str, options: list[str] | None = None) -> str:
    # Render: the question + numbered options if any.
    print()
    print(f"  ? {question}")
    if options:
        for i, opt in enumerate(options, 1):
            print(f"    {i}) {opt}")
        prompt = "Your answer (number or text): "
    else:
        prompt = "Your answer: "

    # In non-tty or yes-mode contexts we can't actually ask.
    if not sys.stdin.isatty() or ctx.yes:
        return (
            "Question deferred: no interactive stdin available "
            f"(yes-mode={ctx.yes}, tty={sys.stdin.isatty()}). "
            "Proceed with your best judgement and explain the assumption in the final answer."
        )

    try:
        raw = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return "Question cancelled by user. Proceed with reasonable default."

    if options and raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx]
    return raw or "(empty)"


def call(ctx: ToolContext, args: dict) -> str:
    options = args.get("options") or None
    if options is not None and not isinstance(options, list):
        options = [str(options)]
    return ask(
        ctx,
        str(args["question"]),
        [str(o) for o in options] if options else None,
    )
