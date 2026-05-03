from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .config import get_settings
from .db import MemoryStore
from .orchestrator import AgentOrchestrator
from .router_client import RouterClient
from .tools import ToolRegistry
from .watchers import ProactiveWatchers
from .whatsapp import WhatsAppBridgeClient

settings = get_settings()
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger(__name__)

prompt_path = Path(__file__).resolve().parents[1] / "prompts" / "system_prompt.txt"
base_prompt = prompt_path.read_text(encoding="utf-8")

store = MemoryStore(settings.sqlite_path)
router_client = RouterClient(settings)
tool_registry = ToolRegistry(settings, store)
orchestrator = AgentOrchestrator(settings, store, router_client, tool_registry, base_prompt)
whatsapp_client = WhatsAppBridgeClient(settings)
watchers = ProactiveWatchers(settings, store, tool_registry, orchestrator, whatsapp_client)

app = FastAPI(title="Pi Agent Harness", version="0.1.0")


class LocalMessageRequest(BaseModel):
    chat_id: str
    text: str
    send_whatsapp: bool = False


@app.on_event("startup")
def startup_event() -> None:
    watchers.start()


@app.on_event("shutdown")
def shutdown_event() -> None:
    watchers.shutdown()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/message")
def message(request: LocalMessageRequest) -> dict[str, str]:
    reply = orchestrator.handle_user_message(request.chat_id, request.text)
    if request.send_whatsapp:
        whatsapp_client.send_message(request.chat_id, reply)
    return {"reply": reply}


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request) -> dict[str, Any]:
    if settings.webhook_secret:
        received_secret = request.headers.get("x-webhook-token")
        if received_secret != settings.webhook_secret:
            raise HTTPException(status_code=401, detail="Invalid webhook secret.")

    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc

    parsed = whatsapp_client.parse_incoming_message(payload)
    if not parsed:
        return {"status": "ignored"}

    chat_id, text = parsed
    reply = orchestrator.handle_user_message(chat_id, text)
    whatsapp_client.send_message(chat_id, reply)
    return {"status": "ok", "chat_id": chat_id}


@app.post("/watchers/run-once")
def run_watchers_once() -> dict[str, str]:
    watchers.poll_home_assistant()
    watchers.poll_paperless()
    return {"status": "watchers_ran"}
