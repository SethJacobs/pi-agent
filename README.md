# Pi Agent Harness

Always-on proactive AI agent for your home server. Connects to your OpenAI-compatible gateway, monitors Home Assistant and Paperless, and reaches out to you on WhatsApp when something needs attention.

## What this does

- Maintains per-chat conversation history in SQLite
- Routes all reasoning through your `pi-ai-gateway`
- Executes tools: Home Assistant, Paperless, host status, persistent memory
- Receives inbound WhatsApp messages and replies
- Runs proactive watchers: HA entity changes, new Paperless documents
- Heartbeat loop — wakes up every 30 min, checks conditions, stays silent unless something needs saying
- Agent can schedule its own recurring tasks via `schedule_job` tool

## Deployment (Docker — recommended)

This runs as a container on the same `vpn_net` as your other home-server services.

1. Copy the service block from `deploy/docker-compose.service.yml` into your `~/home-server/docker-compose.yml` under `services:`
2. Add `pi_agent_data:` to the `volumes:` section at the bottom
3. Fill in `PAPERLESS_TOKEN`, `WHATSAPP_TOKEN`, and `WHATSAPP_DEFAULT_CHAT_ID` (see sections below)
4. Build and start:

```bash
docker compose build pi-agent-harness
docker compose up -d pi-agent-harness
```

## WhatsApp bridge setup

This harness uses [wwebjs-api](https://github.com/avoylenko/wwebjs-api) — a self-hosted REST wrapper around WhatsApp Web. It runs as a sidecar container and gives you a simple HTTP API to send and receive messages.

> **Note:** This uses the unofficial WhatsApp Web protocol. It works reliably for personal use but is not officially supported by WhatsApp.

### 1. Add the bridge to your docker-compose

Add this service to `~/home-server/docker-compose.yml`:

```yaml
  whatsapp-bridge:
    image: avoylenko/wwebjs-api:latest
    container_name: whatsapp-bridge
    restart: unless-stopped
    ports:
      - "3000:3000"
    volumes:
      - whatsapp_sessions:/app/sessions
    environment:
      - API_KEY=your_secret_token_here        # set this, then use it as WHATSAPP_TOKEN
      - BASE_WEBHOOK_URL=http://pi-agent-harness:8787/webhook/whatsapp
      - DISABLED_CALLBACKS=onPresenceChanged,onGroupNotification
      - ENABLE_LOCAL_CALLBACK_EXAMPLE=FALSE
    networks:
      - vpn_net
```

And add `whatsapp_sessions:` to your `volumes:` block.

### 2. Start the bridge and scan the QR code

```bash
docker compose up -d whatsapp-bridge
docker compose logs -f whatsapp-bridge
```

Then start a session — open this URL in your browser (replace the IP with your Pi's IP):

```
http://<pi-ip>:3000/session/start/default
```

Watch the logs — a QR code will appear. On your phone:
- WhatsApp → Settings → Linked Devices → Link a Device
- Scan the QR code

Once linked, the session is saved to the `whatsapp_sessions` volume and survives restarts.

### 3. Get your chat ID

Send any message to the linked WhatsApp number from your phone. The bridge will deliver it to the harness webhook. Check the harness logs to see the `chat_id`:

```bash
docker compose logs pi-agent-harness | grep chat_id
```

It will look like `15551234567@c.us` for personal chats or `1234567890-1234567890@g.us` for groups.

### 4. Set the env vars

In your `docker-compose.yml` under `pi-agent-harness`:

```yaml
- WHATSAPP_SEND_URL=http://whatsapp-bridge:3000/client/sendMessage/default
- WHATSAPP_TOKEN=your_secret_token_here
- WHATSAPP_DEFAULT_CHAT_ID=15551234567@c.us
- WEBHOOK_SECRET=          # optional, leave blank unless you add auth
```

Then restart:

```bash
docker compose up -d pi-agent-harness
```

### 5. Test it

```bash
curl -X POST http://<pi-ip>:8787/message \
  -H "Content-Type: application/json" \
  -d '{"chat_id": "15551234567@c.us", "text": "hello", "send_whatsapp": true}'
```

You should receive the reply on your phone.

---

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `ROUTER_BASE_URL` | yes | Base URL of your ai-gateway, e.g. `http://ai-gateway:8080` |
| `ROUTER_MODEL` | yes | Model to use, e.g. `openrouter/auto` |
| `ROUTER_API_KEY` | if set | Must match `GATEWAY_API_KEY` in ai-gateway |
| `HOME_ASSISTANT_BASE_URL` | for HA tools | e.g. `http://homeassistant:8123` |
| `HOME_ASSISTANT_TOKEN` | for HA tools | Long-lived access token from HA profile |
| `PAPERLESS_BASE_URL` | for Paperless tools | e.g. `http://paperless-webserver:8000` |
| `PAPERLESS_TOKEN` | for Paperless tools | API token from Paperless UI → Settings |
| `WHATSAPP_SEND_URL` | yes | Bridge send endpoint |
| `WHATSAPP_TOKEN` | if set | Must match `API_KEY` in whatsapp-bridge |
| `WHATSAPP_DEFAULT_CHAT_ID` | yes | Your personal chat ID (`number@c.us`) |
| `WATCH_ENTITY_IDS` | optional | JSON array of HA entity IDs to monitor |
| `HEARTBEAT_INTERVAL_SECONDS` | optional | How often the heartbeat runs (default 1800) |

## Heartbeat

Edit `prompts/HEARTBEAT.md` to define what the agent checks on each heartbeat cycle. The volume mount in the docker-compose service means you can edit this file live without rebuilding.

If the agent has nothing to report, it replies `HEARTBEAT_OK` internally and stays silent.

## API endpoints

- `GET /healthz` — health check
- `POST /message` — send a message directly (for testing)
- `POST /webhook/whatsapp` — inbound webhook from the bridge
- `POST /watchers/run-once` — manually trigger all watcher checks

## Notes

- `WATCH_ENTITY_IDS` must be a JSON array string: `["sensor.foo","binary_sensor.bar"]`
- Fallback tool-call format for models without native tool support: `{"type":"tool_call","tool":"tool_name","arguments":{...}}`
- Agent-scheduled jobs survive restarts — they are stored in SQLite and restored on boot
