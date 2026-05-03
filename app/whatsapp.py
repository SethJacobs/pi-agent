from __future__ import annotations

from typing import Any, Optional, Tuple

import requests

from .config import Settings


class WhatsAppBridgeClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def parse_incoming_message(self, payload: dict[str, Any]) -> Optional[Tuple[str, str]]:
        webhook_type = payload.get("typeWebhook")
        if isinstance(webhook_type, str) and webhook_type and "incoming" not in webhook_type.lower():
            return None

        chat_id = self._first_nonempty_str(
            payload.get("chatId"),
            payload.get("chat_id"),
            payload.get("sender"),
            payload.get("from"),
            payload.get("senderData", {}).get("chatId") if isinstance(payload.get("senderData"), dict) else None,
            payload.get("message", {}).get("chatId") if isinstance(payload.get("message"), dict) else None,
        )

        text = self._first_nonempty_str(
            payload.get("text"),
            payload.get("body"),
            payload.get("message"),
            payload.get("textMessage"),
            payload.get("messageData", {}).get("textMessageData", {}).get("textMessage")
            if isinstance(payload.get("messageData"), dict)
            else None,
            payload.get("message", {}).get("text") if isinstance(payload.get("message"), dict) else None,
            payload.get("data", {}).get("text") if isinstance(payload.get("data"), dict) else None,
        )

        if not chat_id or not text:
            return None
        return chat_id, text

    def send_message(self, chat_id: Optional[str], text: str) -> None:
        destination = chat_id or self.settings.whatsapp_default_chat_id
        if not destination:
            raise ValueError("No destination chat_id provided and WHATSAPP_DEFAULT_CHAT_ID is empty.")

        headers = {"Content-Type": "application/json"}
        if self.settings.whatsapp_token:
            headers["Authorization"] = f"Bearer {self.settings.whatsapp_token}"

        payload = {"chatId": destination, "text": text, "message": text}
        response = requests.post(
            self.settings.whatsapp_send_url,
            headers=headers,
            json=payload,
            timeout=self.settings.request_timeout_seconds,
        )
        response.raise_for_status()

    def _first_nonempty_str(self, *values: Any) -> Optional[str]:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
