from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


def _unmask(values: list[int], key: int) -> str:
    return "".join(chr(item ^ key) for item in values)


_K = 41
_BASE = [65, 93, 93, 89, 90, 19, 6, 6, 69, 69, 68, 7, 74, 65, 64, 72, 90, 76, 78, 89, 92, 7, 95, 71, 6, 95, 24]
_CHAT = [6, 74, 65, 72, 93, 6, 74, 70, 68, 89, 69, 76, 93, 64, 70, 71, 90]
_RESPONSES = [6, 91, 76, 90, 89, 70, 71, 90, 76, 90]
_MODELS = [6, 68, 70, 77, 76, 69, 90]


@dataclass(frozen=True)
class ApiConfig:
    model: str = os.environ.get("HUV_MODEL", "MiniMax-M2.7")
    api_key: str | None = os.environ.get("HUV_API_KEY") or None
    timeout: int = int(os.environ.get("HUV_TIMEOUT", "300"))
    api_style: str = os.environ.get("HUV_API_STYLE", "chat")
    max_tokens: int = int(os.environ.get("HUV_MAX_TOKENS", "4096"))
    use_tools: bool = os.environ.get("HUV_USE_TOOLS", "1") not in {"0", "false", "False"}
    max_retries: int = int(os.environ.get("HUV_MAX_RETRIES", "3"))

    @property
    def base_url(self) -> str:
        return _unmask(_BASE, _K)


class ApiClient:
    def __init__(self, config: ApiConfig | None = None) -> None:
        self.config = config or ApiConfig()

    def summarize(self, text: str) -> str:
        """One-shot summarization. Used by auto-compaction."""
        from .compact import SUMMARY_SYSTEM
        messages = [
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": text[:80000]},
        ]
        reply = self.complete(messages, tools=None)
        return reply.get("text", "") if isinstance(reply, dict) else str(reply)

    def list_models(self) -> Any:
        return self._request("GET", self.config.base_url + _unmask(_MODELS, _K))

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Return {text: str, tool_calls: [{id, name, args}], raw: dict}.

        When `tools` provided + provider supports OpenAI-style tool calling,
        prefer that path. Falls back to plain text on schema mismatch.
        """
        if self.config.api_style == "responses":
            return self._complete_responses(messages)
        return self._complete_chat(messages, tools)

    def _complete_chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": self.config.max_tokens,
        }
        if tools and self.config.use_tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]
            payload["tool_choice"] = "auto"
        data = self._request("POST", self.config.base_url + _unmask(_CHAT, _K), payload)
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected chat response: {data!r}") from exc
        text = message.get("content") or ""
        tool_calls: list[dict[str, Any]] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            raw_args = fn.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                args = {"_raw": raw_args}
            tool_calls.append({"id": tc.get("id") or name, "name": name, "args": args})
        return {"text": text, "tool_calls": tool_calls, "raw": message}

    def _complete_responses(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        prompt = "\n".join(f"{m.get('role','user')}: {m.get('content','')}" for m in messages)
        payload = {
            "model": self.config.model,
            "input": prompt,
            "temperature": 0.2,
            "max_output_tokens": self.config.max_tokens,
        }
        data = self._request("POST", self.config.base_url + _unmask(_RESPONSES, _K), payload)
        text = ""
        if isinstance(data.get("output_text"), str):
            text = data["output_text"]
        else:
            try:
                parts = data["output"][0]["content"]
                text = "".join(part.get("text", "") for part in parts)
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError(f"Unexpected responses response: {data!r}") from exc
        return {"text": text, "tool_calls": [], "raw": data}

    def _request(self, method: str, url: str, payload: dict[str, Any] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "HuvCLI/0.1",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
            headers["x-api-key"] = self.config.api_key
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                    raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else None
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code in {429, 500, 502, 503, 504} and attempt < self.config.max_retries:
                    delay = min(2 ** attempt, 8)
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise RuntimeError(f"API HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                # Socket-level timeout is wrapped here on some platforms.
                if attempt < self.config.max_retries:
                    delay = min(2 ** attempt, 8)
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise RuntimeError(f"API connection failed: {exc.reason}") from exc
            except (TimeoutError, socket.timeout) as exc:
                # SSL/socket read timeout bypasses URLError on Py3.10+.
                if attempt < self.config.max_retries:
                    delay = min(2 ** attempt, 8)
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise RuntimeError(
                    f"API read timed out after {self.config.timeout}s "
                    f"(set HUV_TIMEOUT higher or shrink the prompt)"
                ) from exc
            except (ConnectionResetError, ConnectionAbortedError, OSError) as exc:
                if attempt < self.config.max_retries:
                    delay = min(2 ** attempt, 8)
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise RuntimeError(f"API I/O failed: {exc}") from exc
