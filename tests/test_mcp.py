from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from huvcli.mcp import MCPRegistry, load_config


HERE = Path(__file__).resolve().parent
FAKE_SERVER = str(HERE / "fake_mcp_server.py")


def _write_config(root: Path, servers: dict) -> None:
    (root / ".huvcli").mkdir(parents=True, exist_ok=True)
    (root / ".huvcli" / "mcp.json").write_text(
        json.dumps({"servers": servers}), encoding="utf-8"
    )


class MCPConfigTests(unittest.TestCase):
    def test_missing_config_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            self.assertEqual(load_config(Path(raw)), {})

    def test_parses_servers(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_config(root, {"fake": {"command": "py", "args": ["x"], "env": {"K": "V"}}})
            cfg = load_config(root)
            self.assertIn("fake", cfg)
            self.assertEqual(cfg["fake"]["args"], ["x"])
            self.assertEqual(cfg["fake"]["env"], {"K": "V"})


class MCPRegistryTests(unittest.TestCase):
    def _make_registry(self, root: Path) -> MCPRegistry:
        _write_config(root, {
            "fake": {"command": sys.executable, "args": [FAKE_SERVER], "env": {}},
        })
        return MCPRegistry(root)

    def test_discover_lists_tools_with_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            registry = self._make_registry(Path(raw))
            try:
                schemas = registry.discover()
                names = [s["name"] for s in schemas]
                self.assertIn("mcp__fake__echo", names)
                echo = next(s for s in schemas if s["name"] == "mcp__fake__echo")
                self.assertIn("text", echo["parameters"]["properties"])
            finally:
                registry.close_all()

    def test_call_routes_to_server(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            registry = self._make_registry(Path(raw))
            try:
                registry.discover()
                self.assertTrue(registry.has("mcp__fake__echo"))
                out = registry.call("mcp__fake__echo", {"text": "hi"})
                self.assertEqual(out, "hi")
            finally:
                registry.close_all()

    def test_error_response_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            registry = self._make_registry(Path(raw))
            try:
                registry.discover()
                # Force-route a known-bad tool name via direct client call.
                # boom is not in tool_index, so we register it manually.
                registry._tool_index["mcp__fake__boom"] = ("fake", "boom")
                out = registry.call("mcp__fake__boom", {})
                self.assertIn("MCP error", out)
                self.assertIn("kaboom", out)
            finally:
                registry.close_all()

    def test_unknown_tool_raises(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            registry = self._make_registry(Path(raw))
            try:
                with self.assertRaises(ValueError):
                    registry.call("mcp__nope__x", {})
            finally:
                registry.close_all()

    def test_bad_server_does_not_crash_discover(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            _write_config(root, {
                "broken": {"command": "this-command-does-not-exist-xyz", "args": [], "env": {}},
            })
            registry = MCPRegistry(root)
            try:
                schemas = registry.discover()
                # One placeholder schema indicating failure.
                names = [s["name"] for s in schemas]
                self.assertTrue(any("unavailable" in n for n in names))
            finally:
                registry.close_all()
