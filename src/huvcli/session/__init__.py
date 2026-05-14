"""huvcli.session — session-scoped state, storage, and compaction.

Mirrors opencode's `session/` package: gather everything that lives across
multiple turns of a single conversation into one focused area.
"""

from __future__ import annotations

from .compaction import (
    COMPACT_KEEP_RECENT,
    COMPACT_TARGET_CHARS,
    COMPACT_THRESHOLD_CHARS,
    SUMMARY_SYSTEM,
    compact_if_needed,
    needs_compaction,
    total_chars,
)
from .state import SessionState
from .storage import (
    DEFAULT_PREFS,
    append_history,
    conversation_path,
    ensure_workspace,
    history_path,
    load_conversation,
    load_prefs,
    prefs_path,
    recent_history,
    save_conversation,
    save_prefs,
    set_pref,
    workspace_dir,
)


__all__ = [
    # state
    "SessionState",
    # storage
    "DEFAULT_PREFS", "workspace_dir", "prefs_path", "history_path", "conversation_path",
    "save_conversation", "load_conversation", "load_prefs", "save_prefs",
    "ensure_workspace", "append_history", "recent_history", "set_pref",
    # compaction
    "COMPACT_THRESHOLD_CHARS", "COMPACT_KEEP_RECENT", "COMPACT_TARGET_CHARS",
    "SUMMARY_SYSTEM",
    "total_chars", "needs_compaction", "compact_if_needed",
]
