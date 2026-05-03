from __future__ import annotations

import json
from typing import Any

from .config import Settings
from .db import MemoryStore
from .router_client import RouterClient
from .tools import ToolRegistry


class AgentOrchestrator:
    def __init__(
        self,
        settings: Settings,
        store: MemoryStore,
        router_client: RouterClient,
        tool_registry: ToolRegistry,
        base_system_prompt: str,
    ) -> None:
        self.settings = settings
        self.store = store
        self.router_client = router_client
        self.tool_registry = tool_registry
        self.base_system_prompt = base_system_prompt

    def handle_user_message(self, chat_id: str, text: str) -> str:
        self.store.add_message(chat_id, "user", text)
        return self._generate_reply(chat_id)

    def handle_proactive_event(self, chat_id: str, event_text: str) -> str:
        self.store.add_message(chat_id, "user", f"[PROACTIVE_EVENT]\n{event_text}")
        return self._generate_reply(chat_id)

    def _generate_reply(self, chat_id: str) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._build_system_prompt()},
            *self.store.get_recent_messages(chat_id, self.settings.context_messages),
        ]

        for _ in range(self.settings.max_tool_loops):
            model_reply = self.router_client.chat(messages, tools=self.tool_registry.openai_tools)

            if model_reply.tool_calls:
                assistant_message: dict[str, Any] = {"role": "assistant", "content": model_reply.content, "tool_calls": []}
                tool_results: list[tuple[str, str, dict[str, Any]]] = []

                for tool_call in model_reply.tool_calls:
                    assistant_message["tool_calls"].append(
                        {
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": tool_call.name,
                                "arguments": json.dumps(tool_call.arguments),
                            },
                        }
                    )
                    args_with_ctx = {**tool_call.arguments, "_chat_id": chat_id}
                    result = self.tool_registry.execute(tool_call.name, args_with_ctx)
                    tool_results.append((tool_call.id, tool_call.name, result))

                messages.append(assistant_message)
                for tool_call_id, tool_name, result in tool_results:
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": json.dumps(result),
                        }
                    )
                continue

            if model_reply.text_tool_call:
                result = self.tool_registry.execute(
                    model_reply.text_tool_call.name,
                    {**model_reply.text_tool_call.arguments, "_chat_id": chat_id},
                )
                messages.append({"role": "assistant", "content": model_reply.content})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"Tool `{model_reply.text_tool_call.name}` returned:\n"
                            f"{json.dumps(result)}\n"
                            "Use this result to answer the user now."
                        ),
                    }
                )
                continue

            final_text = (model_reply.content or "").strip()
            if not final_text:
                final_text = "I could not produce a response yet. Ask again with a narrower request."
            self.store.add_message(chat_id, "assistant", final_text)
            return final_text

        fallback = "I hit the tool-call loop limit. Ask again and I’ll continue from here."
        self.store.add_message(chat_id, "assistant", fallback)
        return fallback

    def _build_system_prompt(self) -> str:
        base = self.base_system_prompt.replace("{{AGENT_NAME}}", self.settings.agent_name)
        return (
            f"{base}\n\n"
            "Available tools:\n"
            f"{self.tool_registry.describe_tools()}\n\n"
            "Keep messages concise for WhatsApp unless the user asks for detail."
        )
