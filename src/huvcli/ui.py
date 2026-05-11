from __future__ import annotations

import os
import sys
from pathlib import Path

from . import __version__


class UI:
    def __init__(self, plain: bool = False) -> None:
        self.plain = plain or not sys.stdout.isatty() or bool(os.environ.get("NO_COLOR"))

    def color(self, text: str, code: str) -> str:
        if self.plain:
            return text
        return f"\033[{code}m{text}\033[0m"

    def dim(self, text: str) -> str:
        return self.color(text, "2")

    def green(self, text: str) -> str:
        return self.color(text, "32")

    def cyan(self, text: str) -> str:
        return self.color(text, "36")

    def yellow(self, text: str) -> str:
        return self.color(text, "33")

    def status(self, label: str, kind: str = "work") -> str:
        if self.plain:
            return f"[..] {label}"
        icon = {
            "think": "◇",
            "files": "□",
            "read": "◌",
            "edit": "✎",
            "write": "✎",
            "run": "▷",
            "done": "✓",
            "warn": "!",
        }.get(kind, "◇")
        paint = self.yellow if kind == "warn" else self.green if kind == "done" else self.cyan
        return f"{paint(icon)} {self.dim(label)}"

    def result(self, label: str, ok: bool = True) -> str:
        if self.plain:
            return f"[OK] {label}" if ok else f"[!!] {label}"
        icon = self.green("✓") if ok else self.yellow("!")
        return f"{icon} {label}"

    def welcome(self, cwd: Path, save: bool) -> str:
        if self.plain:
            return "\n".join(
                [
                    f"Huv CLI v{__version__}",
                    f"Project: {cwd}",
                    f"Memory: {'.huvcli on' if save else 'off for this session'}",
                    "Commands: chat | assets | history | prefs | exit",
                ]
            )
        width = max(54, min(86, len(str(cwd)) + 13))
        top = "╭" + "─" * (width - 2) + "╮"
        bottom = "╰" + "─" * (width - 2) + "╯"
        title = f" Huv CLI v{__version__} "
        lines = [
            top,
            "│" + self.cyan(title) + " " * (width - 2 - len(title)) + "│",
            "│" + f" Project  {cwd}".ljust(width - 2) + "│",
            "│" + f" Memory   {'.huvcli on' if save else 'off for this session'}".ljust(width - 2) + "│",
            "│" + " Tools    chat | assets | history | prefs | exit".ljust(width - 2) + "│",
            bottom,
        ]
        return "\n".join(lines)

    def answer(self, text: str) -> str:
        clean = text.strip()
        if not clean:
            return ""
        if self.plain:
            return f"\nResult\n------\n{clean}"
        return f"\n{self.green('╭─ Result')}\n{clean}\n{self.green('╰────────')}"
