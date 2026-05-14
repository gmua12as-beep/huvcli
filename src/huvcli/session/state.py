"""SessionState — carries resources + accumulators across run_agent calls.

Owned by the CLI's chat loop so MCP subprocesses, hooks, and per-session
totals (tokens, file changes, originals) survive between prompts instead
of being reconstructed every turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..mcp import MCPRegistry


@dataclass
class SessionState:
    cwd: Path
    mcp: "MCPRegistry | None" = None
    hooks: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    # Accumulated session totals.
    changes: dict[str, dict[str, Any]] = field(default_factory=dict)
    # rel_path -> original bytes (None = file didn't exist before).
    originals: dict[str, "bytes | None"] = field(default_factory=dict)
    tokens: dict[str, int] = field(default_factory=lambda: {"prompt": 0, "completion": 0, "total": 0})
    # Last-known size of the message history sent to the model (chars).
    last_history_chars: int = 0
    compactions: int = 0

    def close(self) -> None:
        if self.mcp is not None:
            self.mcp.close_all()
