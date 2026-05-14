"""run_command — execute a shell command in the project directory."""

from __future__ import annotations

import re
import subprocess

from .context import ToolContext
from .descriptions import load as _load_description
from .permission import confirm


SCHEMA = {
    "name": "run_command",
    "description": _load_description(__file__),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "default": 120},
            "dangerous": {"type": "boolean", "default": False},
        },
        "required": ["command"],
    },
}
REQUIRED = ["command"]
ARG_ALIASES = {"cmd": "command", "shell": "command", "exec": "command"}
EXAMPLE = '{"command": "npm test"}'

DANGEROUS_PATTERNS = [
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


def looks_dangerous(command: str) -> bool:
    return any(re.search(p, command, re.IGNORECASE) for p in DANGEROUS_PATTERNS)


def run_command(
    ctx: ToolContext,
    command: str,
    timeout: int = 120,
    dangerous: bool = False,
) -> str:
    is_dangerous = looks_dangerous(command) or dangerous
    if looks_dangerous(command) and not dangerous:
        return "Command blocked: looks destructive. Re-run with dangerous=true if intentional."
    prompt = f"Run command in {ctx.cwd}: {command}?"
    if is_dangerous:
        prompt = f"DANGEROUS command in {ctx.cwd}: {command}?"
    if not confirm(ctx, prompt, kind="dangerous" if is_dangerous else "command"):
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


def call(ctx: ToolContext, args: dict) -> str:
    return run_command(
        ctx, str(args["command"]),
        int(args.get("timeout", 120)),
        bool(args.get("dangerous", False)),
    )
