"""Minimal MCP (Model Context Protocol) stdio client.

Config: `.huvcli/mcp.json` shape:

    {
      "servers": {
        "fs":      {"command": "npx",    "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]},
        "linear":  {"command": "linear-mcp", "args": [], "env": {"TOKEN": "..."}}
      }
    }

We spawn each server on demand, perform `initialize` + `tools/list`, and
expose their tools to the agent as `mcp__<server>__<tool>`. Calls route
through `MCPRegistry.call_tool`.

This is intentionally minimal: synchronous, no notifications, no sampling,
no roots. Sufficient for tool-use scenarios.
"""

from __future__ import annotations

import atexit
import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any


CONFIG_FILENAME = "mcp.json"
JSONRPC = "2.0"


def config_path(cwd: Path) -> Path:
    return cwd / ".huvcli" / CONFIG_FILENAME


def load_config(cwd: Path) -> dict[str, dict[str, Any]]:
    path = config_path(cwd)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    servers = data.get("servers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, entry in servers.items():
        if not isinstance(entry, dict) or "command" not in entry:
            continue
        out[str(name)] = {
            "command": str(entry["command"]),
            "args": list(entry.get("args") or []),
            "env": dict(entry.get("env") or {}),
        }
    return out


class MCPClient:
    """Synchronous JSON-RPC 2.0 client over a subprocess's stdio."""

    def __init__(self, name: str, command: str, args: list[str], env: dict[str, str]) -> None:
        self.name = name
        merged_env = os.environ.copy()
        merged_env.update(env)
        self.proc = subprocess.Popen(
            [command, *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=merged_env, bufsize=0,
        )
        self._lock = threading.Lock()
        self._next_id = 1
        self._initialized = False
        self.tools: list[dict[str, Any]] = []

    def _send(self, method: str, params: dict[str, Any] | None = None, notify: bool = False) -> Any:
        with self._lock:
            msg: dict[str, Any] = {"jsonrpc": JSONRPC, "method": method}
            if params is not None:
                msg["params"] = params
            if not notify:
                msg["id"] = self._next_id
                self._next_id += 1
            data = (json.dumps(msg) + "\n").encode("utf-8")
            assert self.proc.stdin is not None and self.proc.stdout is not None
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except BrokenPipeError as exc:
                raise RuntimeError(f"MCP server {self.name} stdin closed") from exc
            if notify:
                return None
            # Read responses until we find a matching id (skip notifications).
            target_id = msg["id"]
            while True:
                line = self.proc.stdout.readline()
                if not line:
                    raise RuntimeError(f"MCP server {self.name} closed before responding")
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if parsed.get("id") != target_id:
                    continue
                if "error" in parsed:
                    err = parsed["error"]
                    raise RuntimeError(f"MCP {self.name}.{method} error: {err}")
                return parsed.get("result")

    def initialize(self) -> None:
        if self._initialized:
            return
        self._send("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "huvcli", "version": "0.1"},
        })
        try:
            self._send("notifications/initialized", {}, notify=True)
        except RuntimeError:
            pass
        self._initialized = True

    def list_tools(self) -> list[dict[str, Any]]:
        self.initialize()
        result = self._send("tools/list") or {}
        tools = result.get("tools") or []
        self.tools = list(tools)
        return self.tools

    def call_tool(self, name: str, args: dict[str, Any]) -> str:
        self.initialize()
        result = self._send("tools/call", {"name": name, "arguments": args}) or {}
        # Standard MCP returns {content: [{type:"text", text:"..."}], isError?}
        content = result.get("content") or []
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
        if result.get("isError"):
            return "MCP error: " + ("\n".join(parts) if parts else "(no detail)")
        return "\n".join(parts) if parts else "(no content)"

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                self.proc.terminate()
                try:
                    self.proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.proc.kill()
        except OSError:
            pass


class MCPRegistry:
    """Lazy registry of named MCP servers. Tools surface as `mcp__<server>__<tool>`."""

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd
        self.config = load_config(cwd)
        self.clients: dict[str, MCPClient] = {}
        self._tool_index: dict[str, tuple[str, str]] = {}  # prefixed_name -> (server, raw_name)
        self._loaded = False
        atexit.register(self.close_all)

    def _get_client(self, server: str) -> MCPClient:
        if server in self.clients:
            return self.clients[server]
        entry = self.config.get(server)
        if not entry:
            raise ValueError(f"Unknown MCP server: {server}")
        client = MCPClient(server, entry["command"], entry["args"], entry["env"])
        self.clients[server] = client
        return client

    def discover(self) -> list[dict[str, Any]]:
        """Connect to each configured server, return tool schemas suitable for our API.

        Failures on individual servers are logged into the schema description
        rather than raising — keeps the agent usable when one server is down.
        """
        schemas: list[dict[str, Any]] = []
        for server in self.config:
            try:
                client = self._get_client(server)
                tools = client.list_tools()
            except Exception as exc:  # noqa: BLE001
                schemas.append({
                    "name": f"mcp__{server}__unavailable",
                    "description": f"MCP server {server} failed: {exc}",
                    "parameters": {"type": "object", "properties": {}},
                })
                continue
            for tool in tools:
                raw_name = str(tool.get("name") or "")
                if not raw_name:
                    continue
                prefixed = f"mcp__{server}__{raw_name}"
                self._tool_index[prefixed] = (server, raw_name)
                schemas.append({
                    "name": prefixed,
                    "description": str(tool.get("description") or "")[:1000],
                    "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
                })
        self._loaded = True
        return schemas

    def has(self, tool_name: str) -> bool:
        return tool_name in self._tool_index

    def call(self, tool_name: str, args: dict[str, Any]) -> str:
        if tool_name not in self._tool_index:
            raise ValueError(f"Unknown MCP tool: {tool_name}")
        server, raw_name = self._tool_index[tool_name]
        return self._get_client(server).call_tool(raw_name, args)

    def close_all(self) -> None:
        for client in self.clients.values():
            client.close()
        self.clients.clear()
