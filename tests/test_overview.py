from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from huvcli.tools import ToolContext, call_tool
from huvcli.tools.overview import repo_overview


def _ctx(root: Path) -> ToolContext:
    return ToolContext(cwd=root, yes=True)


class RepoOverviewTests(unittest.TestCase):
    def test_extracts_python_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "a.py").write_text(
                "def hello():\n    pass\n\nclass Foo:\n    pass\n\nCONST = 1\n",
                encoding="utf-8",
            )
            ctx = _ctx(root)
            out = repo_overview(ctx)
            self.assertIn("a.py", out)
            self.assertIn("def hello", out)
            self.assertIn("class Foo", out)
            self.assertIn("CONST", out)

    def test_extracts_typescript_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "Foo.tsx").write_text(
                "export function App() {}\n"
                "export const useThing = () => {};\n"
                "export interface Props {}\n"
                "export type Id = string;\n"
                "export default class Bar {}\n",
                encoding="utf-8",
            )
            ctx = _ctx(root)
            out = repo_overview(ctx)
            self.assertIn("Foo.tsx", out)
            self.assertIn("App", out)
            self.assertIn("useThing", out)
            self.assertIn("Props", out)
            self.assertIn("Id", out)
            self.assertIn("Bar", out)

    def test_extracts_go_and_rust_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "main.go").write_text(
                "package main\n\n"
                "func Doit() {}\n"
                "type Thing struct{}\n",
                encoding="utf-8",
            )
            (root / "lib.rs").write_text(
                "pub fn run() {}\n"
                "pub struct Widget;\n"
                "pub trait Doable {}\n",
                encoding="utf-8",
            )
            ctx = _ctx(root)
            out = repo_overview(ctx)
            self.assertIn("Doit", out)
            self.assertIn("Thing", out)
            self.assertIn("run", out)
            self.assertIn("Widget", out)
            self.assertIn("Doable", out)

    def test_unknown_extension_shown_without_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "notes.md").write_text("# Hello\n", encoding="utf-8")
            ctx = _ctx(root)
            out = repo_overview(ctx)
            self.assertIn("notes.md", out)
            # No symbol indentation line for unknown ext.
            self.assertNotIn("  Hello", out)

    def test_caps_max_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            for i in range(50):
                (root / f"f{i}.py").write_text(f"def f{i}(): pass\n", encoding="utf-8")
            ctx = _ctx(root)
            out = repo_overview(ctx, max_files=5)
            self.assertIn("truncated", out)
            files = [line for line in out.splitlines() if line and not line.startswith("  ") and "truncated" not in line]
            self.assertLessEqual(len(files), 5)

    def test_skips_skip_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("def keep(): pass\n", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "junk.py").write_text("def skip_me(): pass\n", encoding="utf-8")
            ctx = _ctx(root)
            out = repo_overview(ctx)
            self.assertIn("a.py", out)
            self.assertNotIn("junk.py", out)

    def test_path_filter_to_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "lib.py").write_text("def in_src(): pass\n", encoding="utf-8")
            (root / "tests" / "t.py").write_text("def in_tests(): pass\n", encoding="utf-8")
            ctx = _ctx(root)
            out = repo_overview(ctx, path="src")
            self.assertIn("lib.py", out)
            self.assertNotIn("t.py", out)

    def test_dispatch_through_call_tool(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "x.py").write_text("def hi(): pass\n", encoding="utf-8")
            ctx = _ctx(root)
            out = call_tool(ctx, "repo_overview", {})
            self.assertIn("x.py", out)
            self.assertIn("hi", out)

    def test_alias_directory_maps_to_path(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("def yes(): pass\n", encoding="utf-8")
            (root / "other.py").write_text("def no(): pass\n", encoding="utf-8")
            ctx = _ctx(root)
            out = call_tool(ctx, "repo_overview", {"directory": "src"})
            self.assertIn("a.py", out)
            self.assertNotIn("other.py", out)


class DescriptionLoaderTests(unittest.TestCase):
    def test_descriptions_loaded_from_md(self) -> None:
        from huvcli.tools.registry import TOOL_SCHEMAS
        by_name = {s["name"]: s for s in TOOL_SCHEMAS}
        # Spot-check a few tools: their descriptions should be longer/richer
        # than the old single-sentence placeholders.
        self.assertGreater(len(by_name["edit_file"]["description"]), 200)
        self.assertIn("workhorse", by_name["edit_file"]["description"].lower())
        self.assertIn("structural outline", by_name["repo_overview"]["description"].lower())

    def test_missing_md_falls_back_gracefully(self) -> None:
        from huvcli.tools.descriptions import load
        # Point at a path whose .md sibling does not exist.
        with tempfile.TemporaryDirectory() as raw:
            fake = Path(raw) / "nonexistent.py"
            fake.write_text("# placeholder", encoding="utf-8")
            desc = load(str(fake))
            self.assertIn("not found", desc)
