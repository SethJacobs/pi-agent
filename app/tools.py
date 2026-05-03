from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import quote

import requests

from .config import Settings
from .db import MemoryStore


class ToolRegistry:
    def __init__(self, settings: Settings, store: Optional[MemoryStore] = None) -> None:
        self.settings = settings
        self.store = store
        # Injected by watchers after init to avoid circular deps
        self._scheduler_add_fn: Any = None
        self._scheduler_remove_fn: Any = None

    @property
    def openai_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "home_assistant_get_state",
                    "description": "Get current Home Assistant entity state and attributes.",
                    "parameters": {
                        "type": "object",
                        "properties": {"entity_id": {"type": "string"}},
                        "required": ["entity_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "home_assistant_call_service",
                    "description": "Call a Home Assistant service by domain and service name.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "domain": {"type": "string"},
                            "service": {"type": "string"},
                            "service_data": {"type": "object"},
                        },
                        "required": ["domain", "service"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "paperless_search_documents",
                    "description": "Search Paperless-ngx documents by query text.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "paperless_get_document",
                    "description": "Fetch details for a Paperless document by ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {"document_id": {"type": "integer"}},
                        "required": ["document_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "host_status_snapshot",
                    "description": "Get quick local host status like load average and disk usage.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_set",
                    "description": "Store a named memory. Use this to remember facts, preferences, or context about the user.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "Short identifier, e.g. 'user_timezone'"},
                            "value": {"type": "string", "description": "The value to remember"},
                        },
                        "required": ["key", "value"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_get",
                    "description": "Retrieve a named memory by key.",
                    "parameters": {
                        "type": "object",
                        "properties": {"key": {"type": "string"}},
                        "required": ["key"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_list",
                    "description": "List all stored memories.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "memory_delete",
                    "description": "Delete a named memory by key.",
                    "parameters": {
                        "type": "object",
                        "properties": {"key": {"type": "string"}},
                        "required": ["key"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "schedule_job",
                    "description": (
                        "Schedule a recurring or one-off task using cron syntax. "
                        "The agent will run the given prompt at the scheduled time and send the result to the chat. "
                        "Use standard 5-field cron: minute hour day month weekday. "
                        "Example: '0 8 * * *' = every day at 8am UTC."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string", "description": "Human-readable name for this job"},
                            "cron": {"type": "string", "description": "5-field cron expression"},
                            "prompt": {"type": "string", "description": "The task prompt to run at schedule time"},
                        },
                        "required": ["label", "cron", "prompt"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "unschedule_job",
                    "description": "Remove a previously scheduled job by its ID.",
                    "parameters": {
                        "type": "object",
                        "properties": {"job_id": {"type": "string"}},
                        "required": ["job_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_scheduled_jobs",
                    "description": "List all currently scheduled agent jobs.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    def describe_tools(self) -> str:
        return "\n".join(
            [
                "- home_assistant_get_state(entity_id): Read sensor/entity state.",
                "- home_assistant_call_service(domain, service, service_data={}): Trigger HA actions.",
                "- paperless_search_documents(query, limit=5): Search docs by title/content metadata.",
                "- paperless_get_document(document_id): Fetch one document details.",
                "- host_status_snapshot(): Return basic Pi host health status.",
                "- memory_set(key, value): Persist a named memory.",
                "- memory_get(key): Retrieve a named memory.",
                "- memory_list(): List all memories.",
                "- memory_delete(key): Delete a memory.",
                "- schedule_job(label, cron, prompt): Schedule a recurring task.",
                "- unschedule_job(job_id): Remove a scheduled job.",
                "- list_scheduled_jobs(): List all scheduled jobs.",
            ]
        )

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "home_assistant_get_state":
            return self.home_assistant_get_state(str(arguments.get("entity_id", "")))
        if name == "home_assistant_call_service":
            return self.home_assistant_call_service(
                domain=str(arguments.get("domain", "")),
                service=str(arguments.get("service", "")),
                service_data=arguments.get("service_data", {}) if isinstance(arguments.get("service_data"), dict) else {},
            )
        if name == "paperless_search_documents":
            return self.paperless_search_documents(
                query=str(arguments.get("query", "")),
                limit=int(arguments.get("limit", 5)),
            )
        if name == "paperless_get_document":
            return self.paperless_get_document(int(arguments.get("document_id", 0)))
        if name == "host_status_snapshot":
            return self.host_status_snapshot()
        if name == "memory_set":
            return self.memory_set(str(arguments.get("key", "")), str(arguments.get("value", "")))
        if name == "memory_get":
            return self.memory_get(str(arguments.get("key", "")))
        if name == "memory_list":
            return self.memory_list()
        if name == "memory_delete":
            return self.memory_delete(str(arguments.get("key", "")))
        if name == "schedule_job":
            return self.schedule_job(
                label=str(arguments.get("label", "")),
                cron=str(arguments.get("cron", "")),
                prompt=str(arguments.get("prompt", "")),
                chat_id=arguments.get("_chat_id", self.settings.whatsapp_default_chat_id or ""),
            )
        if name == "unschedule_job":
            return self.unschedule_job(str(arguments.get("job_id", "")))
        if name == "list_scheduled_jobs":
            return self.list_scheduled_jobs()
        return {"ok": False, "error": f"Unknown tool: {name}"}

    def home_assistant_get_state(self, entity_id: str) -> dict[str, Any]:
        if not self.settings.home_assistant_base_url or not self.settings.home_assistant_token:
            return {"ok": False, "error": "Home Assistant is not configured."}
        if not entity_id:
            return {"ok": False, "error": "entity_id is required."}

        try:
            url = f"{self.settings.home_assistant_base_url.rstrip('/')}/api/states/{quote(entity_id, safe='')}"
            response = requests.get(url, headers=self._ha_headers(), timeout=self.settings.request_timeout_seconds)
            response.raise_for_status()
            data = response.json()
            return {
                "ok": True,
                "entity_id": data.get("entity_id", entity_id),
                "state": data.get("state"),
                "attributes": data.get("attributes", {}),
                "last_changed": data.get("last_changed"),
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"home_assistant_get_state failed: {exc}"}

    def home_assistant_call_service(
        self,
        domain: str,
        service: str,
        service_data: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if not self.settings.home_assistant_base_url or not self.settings.home_assistant_token:
            return {"ok": False, "error": "Home Assistant is not configured."}
        if not domain or not service:
            return {"ok": False, "error": "domain and service are required."}

        try:
            url = f"{self.settings.home_assistant_base_url.rstrip('/')}/api/services/{quote(domain, safe='')}/{quote(service, safe='')}"
            response = requests.post(
                url,
                headers=self._ha_headers(),
                json=service_data or {},
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            return {"ok": True, "result": response.json()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"home_assistant_call_service failed: {exc}"}

    def paperless_search_documents(self, query: str, limit: int = 5) -> dict[str, Any]:
        if not self.settings.paperless_base_url or not self.settings.paperless_token:
            return {"ok": False, "error": "Paperless is not configured."}

        page_size = max(1, min(limit, 20))
        try:
            url = f"{self.settings.paperless_base_url.rstrip('/')}/api/documents/"
            response = requests.get(
                url,
                headers=self._paperless_headers(),
                params={"query": query, "page_size": page_size},
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results", [])
            documents = []
            for doc in results:
                documents.append(
                    {
                        "id": doc.get("id"),
                        "title": doc.get("title"),
                        "created": doc.get("created"),
                        "modified": doc.get("modified"),
                        "tags": doc.get("tags", []),
                        "document_type": doc.get("document_type"),
                        "correspondent": doc.get("correspondent"),
                    }
                )
            return {"ok": True, "query": query, "documents": documents}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"paperless_search_documents failed: {exc}"}

    def paperless_get_document(self, document_id: int) -> dict[str, Any]:
        if not self.settings.paperless_base_url or not self.settings.paperless_token:
            return {"ok": False, "error": "Paperless is not configured."}
        if document_id <= 0:
            return {"ok": False, "error": "document_id must be a positive integer."}

        try:
            url = f"{self.settings.paperless_base_url.rstrip('/')}/api/documents/{document_id}/"
            response = requests.get(
                url,
                headers=self._paperless_headers(),
                timeout=self.settings.request_timeout_seconds,
            )
            response.raise_for_status()
            doc = response.json()
            content = doc.get("content")
            if isinstance(content, str) and len(content) > 4000:
                content = f"{content[:4000]}...[truncated]"
            return {
                "ok": True,
                "document": {
                    "id": doc.get("id"),
                    "title": doc.get("title"),
                    "created": doc.get("created"),
                    "tags": doc.get("tags", []),
                    "document_type": doc.get("document_type"),
                    "correspondent": doc.get("correspondent"),
                    "content": content,
                },
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"paperless_get_document failed: {exc}"}

    def paperless_recent_documents(self, limit: int = 10) -> dict[str, Any]:
        return self.paperless_search_documents(query="", limit=limit)

    def host_status_snapshot(self) -> dict[str, Any]:
        load_1, load_5, load_15 = os.getloadavg()
        disk = shutil.disk_usage("/")
        return {
            "ok": True,
            "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
            "load_average": {"1m": load_1, "5m": load_5, "15m": load_15},
            "disk": {
                "total_bytes": disk.total,
                "used_bytes": disk.used,
                "free_bytes": disk.free,
            },
        }

    def _ha_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.settings.home_assistant_token}",
            "Content-Type": "application/json",
        }

    def _paperless_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Token {self.settings.paperless_token}",
            "Content-Type": "application/json",
        }

    # --- Memory tools ---

    def memory_set(self, key: str, value: str) -> dict[str, Any]:
        if not self.store:
            return {"ok": False, "error": "Memory store not available."}
        if not key:
            return {"ok": False, "error": "key is required."}
        self.store.set_memory(key, value)
        return {"ok": True, "key": key, "value": value}

    def memory_get(self, key: str) -> dict[str, Any]:
        if not self.store:
            return {"ok": False, "error": "Memory store not available."}
        value = self.store.get_memory(key)
        if value is None:
            return {"ok": False, "error": f"No memory found for key '{key}'."}
        return {"ok": True, "key": key, "value": value}

    def memory_list(self) -> dict[str, Any]:
        if not self.store:
            return {"ok": False, "error": "Memory store not available."}
        return {"ok": True, "memories": self.store.list_memories()}

    def memory_delete(self, key: str) -> dict[str, Any]:
        if not self.store:
            return {"ok": False, "error": "Memory store not available."}
        self.store.delete_memory(key)
        return {"ok": True, "deleted": key}

    # --- Self-scheduling tools ---

    def schedule_job(self, label: str, cron: str, prompt: str, chat_id: str) -> dict[str, Any]:
        if not self.store or not self._scheduler_add_fn:
            return {"ok": False, "error": "Scheduler not available."}
        if not label or not cron or not prompt:
            return {"ok": False, "error": "label, cron, and prompt are required."}
        job_id = str(uuid.uuid4())[:8]
        try:
            self._scheduler_add_fn(job_id, label, cron, prompt, chat_id)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Failed to schedule job: {exc}"}
        return {"ok": True, "job_id": job_id, "label": label, "cron": cron}

    def unschedule_job(self, job_id: str) -> dict[str, Any]:
        if not self.store or not self._scheduler_remove_fn:
            return {"ok": False, "error": "Scheduler not available."}
        try:
            self._scheduler_remove_fn(job_id)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"Failed to remove job: {exc}"}
        return {"ok": True, "removed": job_id}

    def list_scheduled_jobs(self) -> dict[str, Any]:
        if not self.store:
            return {"ok": False, "error": "Memory store not available."}
        return {"ok": True, "jobs": self.store.list_scheduled_jobs()}
