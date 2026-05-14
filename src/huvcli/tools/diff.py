"""Tiny ANSI diff colorizer for verbose previews in write/edit/patch tools."""

from __future__ import annotations

import os
import sys


def colorize_diff(text: str) -> str:
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
