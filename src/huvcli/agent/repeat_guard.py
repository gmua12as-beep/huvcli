"""RepeatGuard — short-circuit detector for the agent loop.

When the model calls the same tool with the same arguments 3+ times in a row
(e.g. fruitless greps), we return a nudge instead of running the tool again.
This stops the model from burning step budget on a known-failing pattern.
"""

from __future__ import annotations

import json
from typing import Any


class RepeatGuard:
    def __init__(self, history_size: int = 8) -> None:
        self.history_size = history_size
        self._recent: list[tuple[str, str, str]] = []

    def _key(self, args: dict[str, Any]) -> str:
        try:
            return json.dumps(args, sort_keys=True, default=str)[:500]
        except (TypeError, ValueError):
            return repr(args)[:500]

    def maybe_short_circuit(self, name: str, args: dict[str, Any]) -> str | None:
        key_args = self._key(args)
        key = (name, key_args)
        matching = [(n, a, r) for n, a, r in self._recent[-4:] if (n, a) == key]
        if len(matching) >= 3:
            last_result = matching[-1][2]
            return (
                f"You've called {name} with these same args {len(matching) + 1} times "
                f"and keep getting the same result:\n{last_result[:300]}\n"
                f"Try a different approach — different search terms, different files, "
                f"or use a different tool. Don't repeat this exact call."
            )
        return None

    def record(self, name: str, args: dict[str, Any], result: str) -> None:
        key_args = self._key(args)
        snippet = result.strip().splitlines()[0][:200] if result.strip() else ""
        self._recent.append((name, key_args, snippet))
        if len(self._recent) > self.history_size:
            del self._recent[0]
