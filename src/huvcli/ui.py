"""Visual layer for the CLI.

Stdlib-only ANSI. Supports a `plain` mode (no colors, no box drawing) for
non-tty / NO_COLOR / pipe scenarios. Truecolor is used when the terminal
advertises it (env `COLORTERM in {truecolor, 24bit}`), otherwise we fall
back to the 8/16-color palette.

Design language:
  - Quiet chrome, bright accents — content is the focus.
  - One accent color (cyan) for chrome, one for success (green), one for
    warn (yellow), one for danger (red). Dim grey for secondary.
  - Boxed sections only at meaningful boundaries (welcome, answer, plan,
    diff). Tool calls are inline w/ a left bullet, not boxed — too noisy
    otherwise.
  - Diffs colorized like git: green +, red -, dim @@.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from . import __version__


_ROUNDED = ("╭", "╮", "╰", "╯", "─", "│")
_HEAVY = ("┌", "┐", "└", "┘", "─", "│")
_ASCII = ("+", "+", "+", "+", "-", "|")


def _truecolor() -> bool:
    return os.environ.get("COLORTERM", "").lower() in {"truecolor", "24bit"}


def _term_width(default: int = 80) -> int:
    try:
        return shutil.get_terminal_size((default, 20)).columns
    except OSError:
        return default


def _visible_len(text: str) -> int:
    """Length ignoring ANSI escapes."""
    out = 0
    i = 0
    while i < len(text):
        if text[i] == "\x1b":
            end = text.find("m", i)
            if end == -1:
                break
            i = end + 1
            continue
        out += 1
        i += 1
    return out


class UI:
    def __init__(self, plain: bool = False) -> None:
        self.plain = plain or not sys.stdout.isatty() or bool(os.environ.get("NO_COLOR"))
        self.truecolor = (not self.plain) and _truecolor()
        self.width = _term_width()
        # ASCII fallback for Windows consoles that can't render box chars.
        enc = (getattr(sys.stdout, "encoding", None) or "").lower()
        self.unicode_ok = "utf" in enc or os.name != "nt"

    # ---- color primitives -----------------------------------------------

    def _esc(self, code: str, text: str) -> str:
        if self.plain:
            return text
        return f"\x1b[{code}m{text}\x1b[0m"

    def _rgb_or(self, r: int, g: int, b: int, fallback_code: str, text: str) -> str:
        if self.plain:
            return text
        if self.truecolor:
            return f"\x1b[38;2;{r};{g};{b}m{text}\x1b[0m"
        return self._esc(fallback_code, text)

    def dim(self, t: str) -> str:    return self._esc("2", t)
    def bold(self, t: str) -> str:   return self._esc("1", t)
    def italic(self, t: str) -> str: return self._esc("3", t)
    def green(self, t: str) -> str:  return self._esc("32", t)
    def cyan(self, t: str) -> str:   return self._esc("36", t)
    def yellow(self, t: str) -> str: return self._esc("33", t)
    def red(self, t: str) -> str:    return self._esc("31", t)
    def magenta(self, t: str) -> str:return self._esc("35", t)
    def blue(self, t: str) -> str:   return self._esc("34", t)
    def grey(self, t: str) -> str:   return self._rgb_or(140, 140, 150, "2", t)
    def accent(self, t: str) -> str: return self._rgb_or(120, 200, 255, "36", t)
    def good(self, t: str) -> str:   return self._rgb_or(120, 220, 160, "32", t)
    def warn(self, t: str) -> str:   return self._rgb_or(240, 200, 100, "33", t)
    def bad(self, t: str) -> str:    return self._rgb_or(240, 120, 120, "31", t)

    # ---- glyphs ---------------------------------------------------------

    _GLYPHS = {
        "think":  "◇",
        "files":  "▤",
        "read":   "◉",
        "edit":   "✎",
        "write":  "✎",
        "run":    "▶",
        "done":   "✓",
        "warn":   "⚠",
        "error":  "✗",
        "plan":   "☰",
        "mcp":    "⊕",
        "hook":   "⌁",
        "bullet": "•",
    }

    _ASCII_GLYPHS = {
        "think": "*", "files": "#", "read": "o", "edit": "/", "write": "/",
        "run": ">", "done": "v", "warn": "!", "error": "x", "plan": "=",
        "mcp": "+", "hook": "~", "bullet": "*",
    }

    def glyph(self, kind: str) -> str:
        if self.plain:
            return {"done": "[ok]", "warn": "[!]", "error": "[x]"}.get(kind, "*")
        if not self.unicode_ok:
            return self._ASCII_GLYPHS.get(kind, "*")
        return self._GLYPHS.get(kind, "•")

    # ---- frames / sections ---------------------------------------------

    def _box(self, lines: list[str], title: str | None, color, char_set) -> str:
        if self.plain:
            header = f"--- {title} ---" if title else "---"
            footer = "-" * len(header)
            return "\n".join([header, *lines, footer])
        if not self.unicode_ok:
            char_set = _ASCII
        tl, tr, bl, br, h, v = char_set
        inner = max(self.width - 2, 30)
        # Render title on top border: ╭─ Title ───────╮
        if title:
            label = f" {title} "
            top = tl + h + color(label) + h * max(1, inner - 1 - _visible_len(label)) + tr
        else:
            top = tl + h * inner + tr
        bot = bl + h * inner + br
        body = []
        cap = inner - 1
        for raw in lines:
            for sub in (raw.splitlines() or [""]):
                # Soft-wrap any line longer than the box interior.
                pieces = self._wrap_visible(sub, cap) if cap > 10 else [sub]
                for piece in pieces:
                    pad = max(0, cap - _visible_len(piece))
                    body.append(f"{color(v)} {piece}{' ' * pad}{color(v)}")
        return "\n".join([color(top), *body, color(bot)])

    def _wrap_visible(self, text: str, width: int) -> list[str]:
        """Wrap by visible width while keeping ANSI escapes intact."""
        if _visible_len(text) <= width:
            return [text]
        out: list[str] = []
        cur = ""
        cur_vis = 0
        i = 0
        active: list[str] = []  # active SGR sequences so we can replay across wraps
        while i < len(text):
            if text[i] == "\x1b":
                end = text.find("m", i)
                if end == -1:
                    cur += text[i:]
                    break
                seq = text[i : end + 1]
                cur += seq
                if seq == "\x1b[0m":
                    active.clear()
                else:
                    active.append(seq)
                i = end + 1
                continue
            cur += text[i]
            cur_vis += 1
            i += 1
            if cur_vis >= width:
                out.append(cur + ("\x1b[0m" if active else ""))
                cur = "".join(active)
                cur_vis = 0
        if cur:
            out.append(cur)
        return out

    # ---- top-level renders ---------------------------------------------

    def welcome(self, cwd: Path, save: bool, approval: str = "suggest", model: str | None = None) -> str:
        if self.plain:
            return "\n".join([
                f"Huv CLI v{__version__}",
                f"Project: {cwd}",
                f"Memory:  {'on' if save else 'off'}",
                f"Mode:    {approval}",
                f"Model:   {model or '(default)'}",
                "Type /help for commands.",
            ])
        diamond = "◆" if self.unicode_ok else "*"
        logo = self.accent(self.bold(f" {diamond} Huv  v{__version__}"))
        rows = [
            logo,
            "",
            f"{self.grey('project')}  {cwd}",
            f"{self.grey('memory ')}  {self.good('on') if save else self.warn('off')}",
            f"{self.grey('mode   ')}  {self._pill_for_mode(approval)}",
            f"{self.grey('model  ')}  {model or self.dim('(default)')}",
            "",
            self.dim("type /help for commands · !cmd to run shell · /quit to exit"),
        ]
        return self._box(rows, title=None, color=self.accent, char_set=_ROUNDED)

    def _pill_for_mode(self, approval: str) -> str:
        text = f" {approval} "
        if approval == "suggest":
            return self.cyan(text)
        if approval == "auto-edit":
            return self.yellow(text)
        if approval == "full-auto":
            return self.red(text)
        return text

    def status(self, label: str, kind: str = "think") -> str:
        if self.plain:
            return f"  .. {label}"
        icon = self.glyph(kind)
        paint = {
            "done": self.good, "warn": self.warn, "error": self.bad,
            "edit": self.accent, "write": self.accent, "read": self.accent,
            "files": self.accent, "run": self.warn, "plan": self.magenta,
            "mcp": self.magenta, "hook": self.magenta,
        }.get(kind, self.cyan)
        return f"  {paint(icon)} {self.grey(label)}"

    def result(self, label: str, ok: bool = True) -> str:
        if self.plain:
            return f"  {'[ok]' if ok else '[!]'} {label}"
        icon = self.good(self.glyph("done")) if ok else self.bad(self.glyph("error"))
        return f"  {icon} {label}"

    def tool_call(self, name: str, summary: str, ok: bool = True) -> str:
        if self.plain:
            return f"  > {name}  {summary}"
        marker = self.accent("▸" if self.unicode_ok else ">")
        sep = self.grey("·" if self.unicode_ok else "-")
        tag = self.bold(self.accent(name))
        body = summary if ok else self.bad(summary)
        return f"  {marker} {tag} {sep} {self.grey(body)}"

    def answer(self, text: str) -> str:
        clean = text.strip()
        if not clean:
            return ""
        return self._box(clean.splitlines() or [""], title="Result", color=self.good, char_set=_ROUNDED)

    def section(self, title: str) -> str:
        if self.plain:
            return f"\n== {title} =="
        ch = "─" if self.unicode_ok else "-"
        bar = ch * max(2, self.width - 4 - len(title))
        return f"\n{self.dim(ch)} {self.bold(self.accent(title))} {self.dim(bar)}"

    def divider(self) -> str:
        if self.plain:
            return "-" * 60
        ch = "─" if self.unicode_ok else "-"
        return self.dim(ch * min(self.width, 80))

    # ---- specialty renders ---------------------------------------------

    def diff(self, text: str, max_lines: int = 60) -> str:
        """Colorize a unified diff. Plain mode passes through verbatim."""
        if not text:
            return ""
        lines = text.splitlines()
        truncated = False
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            truncated = True
        if self.plain:
            out = "\n".join(lines)
            return out + ("\n... (diff truncated)" if truncated else "")
        out_lines: list[str] = []
        for line in lines:
            if line.startswith("+++") or line.startswith("---"):
                out_lines.append(self.bold(self.grey(line)))
            elif line.startswith("@@"):
                out_lines.append(self.magenta(line))
            elif line.startswith("+"):
                out_lines.append(self.good(line))
            elif line.startswith("-"):
                out_lines.append(self.bad(line))
            else:
                out_lines.append(self.grey(line))
        if truncated:
            out_lines.append(self.dim("... (diff truncated)"))
        return "\n".join(out_lines)

    def plan(self, steps: list[dict[str, str]]) -> str:
        """Render an update_plan list with status icons."""
        if not steps:
            return self.dim("(empty plan)")
        rows: list[str] = []
        for s in steps:
            status = s.get("status", "pending")
            label = s.get("step", "")
            if self.plain:
                icon = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}.get(status, "[ ]")
                rows.append(f"{icon} {label}")
                continue
            if status == "completed":
                rows.append(f"  {self.good(self.glyph('done'))} {self.grey(label)}")
            elif status == "in_progress":
                arrow = "▸" if self.unicode_ok else ">"
                rows.append(f"  {self.accent(arrow)} {self.bold(label)}")
            else:
                circle = "○" if self.unicode_ok else "o"
                rows.append(f"  {self.dim(circle)} {label}")
        return "\n".join(rows)

    def error(self, message: str) -> str:
        if self.plain:
            return f"[!] {message}"
        return f"  {self.bad(self.glyph('error'))} {self.bad(message)}"

    def info(self, message: str) -> str:
        if self.plain:
            return f"[i] {message}"
        icon = "ⓘ" if self.unicode_ok else "i"
        return f"  {self.accent(icon)} {self.grey(message)}"

    def prompt_label(self) -> str:
        if self.plain:
            return "huv> "
        arrow = "▸" if self.unicode_ok else ">"
        return f"{self.accent(arrow)} "

    def changed_files(self, changes: dict[str, dict]) -> str:
        """Render a per-session change summary.

        changes: {rel_path: {action: added|modified|deleted, adds: int, dels: int}}
        """
        if not changes:
            return ""
        action_glyph = {
            "added":    ("A", self.good),
            "modified": ("M", self.warn),
            "deleted":  ("D", self.bad),
        }
        action_glyph_ascii = {"added": "A", "modified": "M", "deleted": "D"}
        rows: list[str] = []
        totals_adds = sum(int(c.get("adds", 0)) for c in changes.values())
        totals_dels = sum(int(c.get("dels", 0)) for c in changes.values())
        for path in sorted(changes):
            entry = changes[path]
            action = entry.get("action", "modified")
            adds = int(entry.get("adds", 0))
            dels = int(entry.get("dels", 0))
            stats = ""
            if action != "deleted" and (adds or dels):
                if self.plain:
                    stats = f"  +{adds}/-{dels}"
                else:
                    stats = "  " + self.good(f"+{adds}") + self.grey("/") + self.bad(f"-{dels}")
            if self.plain:
                tag = action_glyph_ascii.get(action, "M")
                rows.append(f"  [{tag}] {path}{stats}")
            else:
                tag, paint = action_glyph.get(action, ("M", self.warn))
                rows.append(f"  {paint(tag)} {path}{stats}")
        if self.plain:
            footer = f"  {len(changes)} file(s), +{totals_adds}/-{totals_dels}"
        else:
            footer = (
                "  " + self.dim(f"{len(changes)} file(s)") + self.grey(" · ")
                + self.good(f"+{totals_adds}") + self.grey("/") + self.bad(f"-{totals_dels}")
            )
        return "\n".join([self.section("Files changed"), *rows, footer])

    def hint_bar(self, approval: str, model: str | None, mcp_count: int = 0) -> str:
        """Single-line status row above the prompt."""
        if self.plain:
            return f"[{approval}] {model or 'default'} mcp:{mcp_count}"
        bits = [
            f"{self.grey('mode')} {self._pill_for_mode(approval)}",
            f"{self.grey('model')} {self.dim(model or 'default')}",
        ]
        if mcp_count:
            bits.append(f"{self.grey('mcp')} {self.magenta(str(mcp_count))}")
        return "  ".join(bits)
