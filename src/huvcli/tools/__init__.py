"""huvcli.tools — tool implementations split per-file, opencode-style.

Each tool has its own module under this package. This `__init__` re-exports
the names that the rest of the codebase (and tests) consume, so the public
import surface stays stable:

    from huvcli.tools import ToolContext, call_tool, edit_file, ...

If you add a new tool, drop a `tools/<name>.py` declaring SCHEMA, REQUIRED,
ARG_ALIASES, EXAMPLE, and a `call(ctx, args)` function, then register it in
`tools/registry.py`.
"""

from __future__ import annotations

# Approval primitives.
from .permission import (
    APPROVAL_AUTO_EDIT,
    APPROVAL_FULL_AUTO,
    APPROVAL_MODES,
    APPROVAL_SUGGEST,
)

# Context dataclass.
from .context import ToolContext

# Stateful helpers — exported because tests reach for `_snapshot_original`.
from .state import snapshot_original as _snapshot_original  # noqa: F401

# Public tool functions.
from .edit import edit_file
from .glob import glob_files
from .listing import list_files
from .patch import apply_patch
from .plan import update_plan
from .read import read_file, read_files
from .revert import revert_files
from .search import grep
from .shell import run_command
from .write import write_file

# Registry — schemas + dispatcher.
from .registry import TOOL_SCHEMAS, call_tool


__all__ = [
    # Approval
    "APPROVAL_SUGGEST", "APPROVAL_AUTO_EDIT", "APPROVAL_FULL_AUTO", "APPROVAL_MODES",
    # Context
    "ToolContext",
    # Tools
    "list_files", "glob_files", "grep",
    "read_file", "read_files",
    "write_file", "edit_file", "apply_patch", "run_command",
    "update_plan", "revert_files",
    # Registry
    "TOOL_SCHEMAS", "call_tool",
]
