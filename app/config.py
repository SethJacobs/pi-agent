from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    agent_name: str = "HomeOps"
    sqlite_path: str = "./agent.db"

    router_base_url: str = "http://127.0.0.1:8001"
    router_chat_path: str = "/v1/chat/completions"
    router_api_key: Optional[str] = None
    router_model: str = "openai/gpt-4.1-mini"
    request_timeout_seconds: int = 60

    context_messages: int = 12
    max_tool_loops: int = 4

    whatsapp_send_url: str = "http://127.0.0.1:3000/sendMessage"
    whatsapp_token: Optional[str] = None
    whatsapp_default_chat_id: Optional[str] = None
    webhook_secret: Optional[str] = None

    home_assistant_base_url: Optional[str] = None
    home_assistant_token: Optional[str] = None

    paperless_base_url: Optional[str] = None
    paperless_token: Optional[str] = None

    watch_entity_ids: List[str] = Field(default_factory=list)
    watcher_interval_seconds: int = 300
    paperless_poll_seconds: int = 600
    heartbeat_interval_seconds: int = 1800  # 30 min; set 0 to disable

    log_level: str = "INFO"

    @property
    def router_chat_url(self) -> str:
        return f"{self.router_base_url.rstrip('/')}/{self.router_chat_path.lstrip('/')}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
