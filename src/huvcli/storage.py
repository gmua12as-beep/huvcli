"""Back-compat shim — actual implementation lives in huvcli.session.storage."""

from __future__ import annotations

from .session.storage import (  # noqa: F401
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
