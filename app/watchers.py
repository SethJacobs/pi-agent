from __future__ import annotations

import logging
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Settings
from .db import MemoryStore
from .orchestrator import AgentOrchestrator
from .tools import ToolRegistry
from .whatsapp import WhatsAppBridgeClient

logger = logging.getLogger(__name__)

HEARTBEAT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "HEARTBEAT.md"


class ProactiveWatchers:
    def __init__(
        self,
        settings: Settings,
        store: MemoryStore,
        tool_registry: ToolRegistry,
        orchestrator: AgentOrchestrator,
        whatsapp_client: WhatsAppBridgeClient,
    ) -> None:
        self.settings = settings
        self.store = store
        self.tool_registry = tool_registry
        self.orchestrator = orchestrator
        self.whatsapp_client = whatsapp_client
        self.scheduler = BackgroundScheduler(timezone="UTC")
        self.started = False

        # Wire scheduling callbacks into the tool registry
        self.tool_registry._scheduler_add_fn = self._add_agent_job
        self.tool_registry._scheduler_remove_fn = self._remove_agent_job

    def start(self) -> None:
        if self.started:
            return

        # Heartbeat — runs every N minutes, agent decides if anything needs saying
        heartbeat_interval = self.settings.heartbeat_interval_seconds
        if heartbeat_interval > 0:
            self.scheduler.add_job(
                self._run_heartbeat,
                trigger="interval",
                seconds=heartbeat_interval,
                id="heartbeat",
                max_instances=1,
                coalesce=True,
            )

        # Home Assistant entity watcher
        if self.settings.watch_entity_ids:
            self.scheduler.add_job(
                self.poll_home_assistant,
                trigger="interval",
                seconds=self.settings.watcher_interval_seconds,
                id="ha_watcher",
                max_instances=1,
                coalesce=True,
            )

        # Paperless new-document watcher
        if self.settings.paperless_poll_seconds > 0:
            self.scheduler.add_job(
                self.poll_paperless,
                trigger="interval",
                seconds=self.settings.paperless_poll_seconds,
                id="paperless_watcher",
                max_instances=1,
                coalesce=True,
            )

        self.scheduler.start()
        self.started = True

        # Restore any agent-scheduled jobs that survived a restart
        self._restore_agent_jobs()
        logger.info("Proactive watchers started.")

    def shutdown(self) -> None:
        if self.started:
            self.scheduler.shutdown(wait=False)
            self.started = False

    # --- Heartbeat ---

    def _run_heartbeat(self) -> None:
        chat_id = self.settings.whatsapp_default_chat_id
        if not chat_id:
            return

        if HEARTBEAT_PATH.exists():
            heartbeat_content = HEARTBEAT_PATH.read_text(encoding="utf-8").strip()
        else:
            heartbeat_content = "No HEARTBEAT.md found. Do a quick status check and report anything worth noting."

        event_text = (
            "[HEARTBEAT]\n"
            f"{heartbeat_content}\n\n"
            "Check if any conditions above are met right now. "
            "If yes, send a concise message. "
            "If nothing needs attention, reply exactly: HEARTBEAT_OK"
        )

        reply = self.orchestrator.handle_proactive_event(chat_id, event_text)
        if reply.strip().upper() == "HEARTBEAT_OK":
            logger.debug("Heartbeat: nothing to report.")
            return

        self.whatsapp_client.send_message(chat_id, reply)

    # --- Agent self-scheduling ---

    def _add_agent_job(self, job_id: str, label: str, cron: str, prompt: str, chat_id: str) -> None:
        self.store.add_scheduled_job(job_id, label, cron, prompt, chat_id)

        def run_job() -> None:
            reply = self.orchestrator.handle_proactive_event(chat_id, f"[SCHEDULED: {label}]\n{prompt}")
            self.whatsapp_client.send_message(chat_id, reply)

        self.scheduler.add_job(
            run_job,
            trigger=CronTrigger.from_crontab(cron, timezone="UTC"),
            id=f"agent_{job_id}",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        logger.info("Scheduled agent job '%s' (%s) with cron '%s'", label, job_id, cron)

    def _remove_agent_job(self, job_id: str) -> None:
        self.store.remove_scheduled_job(job_id)
        aps_id = f"agent_{job_id}"
        if self.scheduler.get_job(aps_id):
            self.scheduler.remove_job(aps_id)
        logger.info("Removed agent job %s", job_id)

    def _restore_agent_jobs(self) -> None:
        for job in self.store.list_scheduled_jobs():
            try:
                self._add_agent_job(
                    job["id"], job["label"], job["cron"], job["prompt"], job["chat_id"]
                )
                logger.info("Restored scheduled job '%s'", job["label"])
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not restore job %s: %s", job["id"], exc)

    # --- Home Assistant watcher ---

    def poll_home_assistant(self) -> None:
        chat_id = self.settings.whatsapp_default_chat_id
        if not chat_id or not self.settings.watch_entity_ids:
            return

        for entity_id in self.settings.watch_entity_ids:
            result = self.tool_registry.home_assistant_get_state(entity_id)
            if not result.get("ok"):
                continue

            current_state = str(result.get("state"))
            state_key = f"ha.entity.{entity_id}"
            previous_state = self.store.get_state(state_key)
            self.store.set_state(state_key, current_state)

            if previous_state is None or previous_state == current_state:
                continue

            event_text = (
                f"Home Assistant update: `{entity_id}` changed from `{previous_state}` to `{current_state}`. "
                "Send a short proactive message and suggest one next action."
            )
            reply = self.orchestrator.handle_proactive_event(chat_id, event_text)
            self.whatsapp_client.send_message(chat_id, reply)

    # --- Paperless watcher ---

    def poll_paperless(self) -> None:
        chat_id = self.settings.whatsapp_default_chat_id
        if not chat_id:
            return

        result = self.tool_registry.paperless_recent_documents(limit=10)
        if not result.get("ok"):
            return

        docs = result.get("documents", [])
        docs = [doc for doc in docs if isinstance(doc.get("id"), int)]
        if not docs:
            return

        docs.sort(key=lambda item: item["id"])
        state_key = "paperless.last_seen_id"
        previous = self.store.get_state(state_key)
        last_seen_id = int(previous) if previous and previous.isdigit() else None
        newest_id = docs[-1]["id"]

        if last_seen_id is None:
            self.store.set_state(state_key, str(newest_id))
            return

        new_docs = [doc for doc in docs if doc["id"] > last_seen_id]
        if not new_docs:
            return

        self.store.set_state(state_key, str(newest_id))
        for doc in new_docs[:3]:
            event_text = (
                "New Paperless document detected. "
                f"Title: `{doc.get('title')}`. "
                f"Created: `{doc.get('created')}`. "
                f"Tags: `{doc.get('tags')}`. "
                "Send a concise proactive nudge asking if I should summarize or categorize it."
            )
            reply = self.orchestrator.handle_proactive_event(chat_id, event_text)
            self.whatsapp_client.send_message(chat_id, reply)
