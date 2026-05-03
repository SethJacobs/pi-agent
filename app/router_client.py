from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from .config import Settings


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ModelReply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    text_tool_call: Optional[ToolCall] = None


class RouterClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelReply:
        payload: dict[str, Any] = {
            "model": self.settings.router_model,
            "messages": messages,
            "temperature": 0.2,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {"Content-Type": "application/json"}
        if self.settings.router_api_key:
            headers["Authorization"] = f"Bearer {self.settings.router_api_key}"

        response = requests.post(
            self.settings.router_chat_url,
            headers=headers,
            json=payload,
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()

        choice = data["choices"][0]["message"]
        content = (choice.get("content") or "").strip()

        native_tool_calls: list[ToolCall] = []
        for raw in choice.get("tool_calls", []) or []:
            fn = raw.get("function", {})
            native_tool_calls.append(
                ToolCall(
                    id=raw.get("id", f"call_{len(native_tool_calls)+1}"),
                    name=fn.get("name", ""),
                    arguments=self._safe_json_loads(fn.get("arguments", "{}")),
                )
            )

        text_tool_call = None
        if not native_tool_calls and content:
            text_tool_call = self._extract_text_tool_call(content)

        return ModelReply(content=content, tool_calls=native_tool_calls, text_tool_call=text_tool_call)

    def _safe_json_loads(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if not isinstance(value, str):
            return {}
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _extract_text_tool_call(self, content: str) -> Optional[ToolCall]:
        # Protocol A: strict JSON object
        # {"type":"tool_call","tool":"tool_name","arguments":{...}}
        try:
            payload = json.loads(content)
            if (
                isinstance(payload, dict)
                and payload.get("type") == "tool_call"
                and isinstance(payload.get("tool"), str)
                and isinstance(payload.get("arguments"), dict)
            ):
                return ToolCall(
                    id="text_tool_json",
                    name=payload["tool"],
                    arguments=payload["arguments"],
                )
        except json.JSONDecodeError:
            pass

        # Protocol B: CALL_TOOL: name {"arg":"value"}
        match = re.search(r"CALL_TOOL:\s*([a-zA-Z0-9_]+)\s*(\{.*\})?$", content, flags=re.DOTALL)
        if not match:
            return None

        name = match.group(1)
        args = self._safe_json_loads(match.group(2) or "{}")
        return ToolCall(id="text_tool_call", name=name, arguments=args)
