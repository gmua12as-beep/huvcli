"""Minimal stdio MCP server used by tests. Implements just enough JSON-RPC
to satisfy huvcli.mcp.MCPClient: `initialize`, `tools/list`, `tools/call`.

Exposes one tool `echo` that returns whatever text it gets.
"""

from __future__ import annotations

import json
import sys


def _send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = req.get("method")
        rid = req.get("id")
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake", "version": "0"},
            }})
        elif method == "notifications/initialized":
            # Notification — no response.
            continue
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": rid, "result": {
                "tools": [{
                    "name": "echo",
                    "description": "Echo the input text",
                    "inputSchema": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                }],
            }})
        elif method == "tools/call":
            params = req.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            if name == "echo":
                _send({"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": str(args.get("text", ""))}],
                }})
            elif name == "boom":
                _send({"jsonrpc": "2.0", "id": rid, "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": "kaboom"}],
                }})
            else:
                _send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown tool"}})
        else:
            _send({"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "unknown method"}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
