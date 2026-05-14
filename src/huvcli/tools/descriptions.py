"""Helper that loads a tool's description from a co-located `.md` file.

Pattern (mirrors opencode's `tool/<name>.ts` + `tool/<name>.txt`):
    tools/edit.py       # implementation
    tools/edit.md       # description shown to the model

If the `.md` is missing (dev import quirk, stripped package), we fall back to
a generic stub so SCHEMA stays well-formed.
"""

from __future__ import annotations

from pathlib import Path


def load(module_file: str, basename: str | None = None) -> str:
    """Return the description text for the tool whose module is at `module_file`.

    Call from a tool module as: `description = load(__file__)`.
    Optionally override `basename` when the .md doesn't match the .py stem
    (e.g. read.py owns both read.md and read_files.md).
    """
    py = Path(module_file)
    stem = basename or py.stem
    md = py.with_name(f"{stem}.md")
    if md.exists():
        return md.read_text(encoding="utf-8").strip()
    return f"(description for {stem} not found)"
