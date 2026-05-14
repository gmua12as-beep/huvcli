"""Back-compat shim — actual implementation lives in huvcli.session.compaction."""

from __future__ import annotations

from .session.compaction import (  # noqa: F401
    COMPACT_KEEP_RECENT,
    COMPACT_TARGET_CHARS,
    COMPACT_THRESHOLD_CHARS,
    SUMMARY_SYSTEM,
    compact_if_needed,
    needs_compaction,
    total_chars,
)
