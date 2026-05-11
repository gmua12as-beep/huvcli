from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


def _unmask(values: list[int], key: int) -> str:
    return "".join(chr(item ^ key) for item in values)


_K = 41
_BASE = [
    65,
    93,
    93,
    89,
    90,
    19,
    6,
    6,
    69,
    69,
    68,
    7,
    74,
    65,
    64,
    72,
    90,
    76,
    78,
    89,
    92,
    7,
    95,
    71,
    6,
    95,
    24,
]
_CHAT = [
    6,
    74,
    65,
    72,
    93,
    6,
    74,
    70,
    68,
    89,
    69,
    76,
    93,
    64,
    70,
    71,
    90,
]
_RESPONSES = [6, 91, 76, 90, 89, 70, 71, 90, 76, 90]
_MODELS = [6, 68, 70, 77, 76, 69, 90]


@dataclass(frozen=True)
class ApiConfig:
    model: str = os.environ.get("HUV_MODEL", "MiniMax-M2.7")
    api_key: str | None = os.environ.get("HUV_API_KEY") or None
    timeout: int = int(os.environ.get("HUV_TIMEOUT", "120"))
    api_style: str = os.environ.get("HUV_API_STYLE", "chat")

    @property
    def base_url(self) -> str:
        return _unmask(_BASE, _K)


class ApiClient:
    def __init__(self, config: ApiConfig | None = None) -> None:
        self.config = config or ApiConfig()

    def list_models(self) -> Any:
        return self._request("GET", self.config.base_url + _unmask(_MODELS, _K))

    def complete(self, messages: list[dict[str, str]]) -> str:
        if self.config.api_style == "responses":
            return self._complete_responses(messages)
        return self._complete_chat(messages)

    def _complete_chat(self, messages: list[dict[str, str]]) -> str:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": 0.2,
        }
        data = self._request("POST", self.config.base_url + _unmask(_CHAT, _K), payload)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected chat response: {data!r}") from exc

    def _complete_responses(self, messages: list[dict[str, str]]) -> str:
        prompt = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        payload = {
            "model": self.config.model,
            "input": prompt,
            "temperature": 0.2,
        }
        data = self._request("POST", self.config.base_url + _unmask(_RESPONSES, _K), payload)
        if isinstance(data.get("output_text"), str):
            return data["output_text"]
        try:
            parts = data["output"][0]["content"]
            return "".join(part.get("text", "") for part in parts)
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected responses response: {data!r}") from exc

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
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"API connection failed: {exc.reason}") from exc
        return json.loads(raw) if raw else None
