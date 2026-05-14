"""ToolContext — per-invocation state container shared by every tool."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .permission import APPROVAL_SUGGEST


@dataclass
class ToolContext:
    cwd: Path
    yes: bool = False
    verbose: bool = False
    approval: str = APPROVAL_SUGGEST
    # mtime+size of files the model has read this session — guards stale edits.
    read_state: dict[str, tuple[float, int]] = field(default_factory=dict)
    # Plan store (codex `update_plan` style).
    plan: list[dict[str, str]] = field(default_factory=list)
    # File changes this session: rel_path -> {action, adds, dels}.
    # action ∈ {"added", "modified", "deleted"}.
    changes: dict[str, dict[str, Any]] = field(default_factory=dict)
    # Original bytes of every file we've touched, snapped on first modification.
    # Value is None when the file did not exist (so revert = delete).
    originals: dict[str, bytes | None] = field(default_factory=dict)
