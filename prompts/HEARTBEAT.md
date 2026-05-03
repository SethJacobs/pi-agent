# Heartbeat Instructions

You are running a background check. Review the following conditions and act on any that are true right now.

## Conditions to check

- If any watched Home Assistant entity is in an unusual or unexpected state, report it.
- If the host load average (1m) is above 2.0, warn the user.
- If disk free space is below 10%, warn the user.
- If it is between 07:00–09:00 UTC and you haven't sent a morning briefing today, send a short one covering: host health, any pending HA alerts, and a one-line summary of what you're watching.

## Rules

- Use tools to check facts before reporting. Do not invent data.
- If nothing needs attention, reply exactly: HEARTBEAT_OK
- Keep any message short and actionable — this is a background nudge, not a report.
