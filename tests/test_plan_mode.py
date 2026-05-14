from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from huvcli.tools import ToolContext, call_tool
from huvcli.tools.permission import APPROVAL_PLAN, MUTATING_TOOLS
from huvcli.tools.registry import TOOL_SCHEMAS, schemas_for


def _ctx(approval: str = "plan") -> ToolContext:
    return ToolContext(cwd=Path(tempfile.gettempdir()), yes=True, approval=approval)


class PlanModeSchemaTests(unittest.TestCase):
    def test_plan_mode_filters_mutating_tools_from_schemas(self) -> None:
        schemas = schemas_for(APPROVAL_PLAN)
        names = {s["name"] for s in schemas}
        for muting in MUTATING_TOOLS:
            self.assertNotIn(muting, names, f"{muting} should be hidden in plan mode")
        # Read-only tools survive.
        self.assertIn("read_file", names)
        self.assertIn("grep", names)
        self.assertIn("webfetch", names)
        self.assertIn("question", names)

    def test_non_plan_modes_keep_all_schemas(self) -> None:
        full = {s["name"] for s in TOOL_SCHEMAS}
        for mode in ("suggest", "auto-edit", "full-auto"):
            names = {s["name"] for s in schemas_for(mode)}
            self.assertEqual(names, full)


class PlanModeDispatchTests(unittest.TestCase):
    def test_dispatch_refuses_mutating_tool_in_plan_mode(self) -> None:
        ctx = _ctx(approval="plan")
        out = call_tool(ctx, "write_file", {"path": "x.txt", "content": "hi"})
        self.assertIn("plan mode", out.lower())
        self.assertIn("write_file", out)

    def test_dispatch_allows_read_in_plan_mode(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "x.txt").write_text("hello\n", encoding="utf-8")
            ctx = ToolContext(cwd=root, yes=True, approval="plan")
            out = call_tool(ctx, "read_file", {"path": "x.txt"})
            self.assertIn("hello", out)

    def test_apply_patch_refused_in_plan_mode(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.txt").write_text("one\n", encoding="utf-8")
            ctx = ToolContext(cwd=root, yes=True, approval="plan")
            out = call_tool(ctx, "apply_patch", {
                "patch": "--- a.txt\n+++ a.txt\n@@ -1 +1 @@\n-one\n+ONE\n",
            })
            self.assertIn("plan mode", out.lower())
            # File was NOT changed.
            self.assertEqual((root / "a.txt").read_text(encoding="utf-8"), "one\n")
