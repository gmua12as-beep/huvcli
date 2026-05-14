"""huvcli.agent — the model loop, split into focused submodules.

Mirrors opencode's `agent/` package layout: `prompt.py` owns the system prompt,
`parsing.py` owns reply parsing, `render.py` owns inline status/summary text,
`repeat_guard.py` is the same-call-three-times short-circuit, and `loop.py`
holds `run_agent` — the orchestrator that ties them together.

Public surface kept identical to the old monolithic agent.py so callers and
tests don't need to change anything.
"""

from __future__ import annotations

import os

from ..session import SessionState
from .loop import run_agent


# Env-driven, read fresh on every package reload. The loop reaches back
# into this module at call time so tests that `importlib.reload(huvcli.agent)`
# after setting HUV_MAX_STEPS see the new value.
DEFAULT_MAX_STEPS = int(os.environ.get("HUV_MAX_STEPS", "60"))

# Test-touched internals — re-exported under their historical underscore names
# so test files keep working without modification.
from .parsing import (
    looks_like_garbled_xml_tool as _looks_like_garbled_xml_tool,
    parse_action as _parse_action,
    parse_xml_tool_calls as _parse_xml_tool_calls,
    scrub_prose as _scrub_prose,
    strip_think as _strip_think,
)
from .render import is_bad_final as _is_bad_final


__all__ = [
    "DEFAULT_MAX_STEPS",
    "run_agent",
    "SessionState",
    # Test-touched internals (back-compat).
    "_is_bad_final",
    "_looks_like_garbled_xml_tool",
    "_parse_action",
    "_parse_xml_tool_calls",
    "_scrub_prose",
    "_strip_think",
]
