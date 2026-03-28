# "Do-It Agent" — Full Build Spec

> A voice-enabled meeting agent that listens to live conversations and executes real-world actions (schedule meetings, send emails, post to Slack, create tasks) via Scalekit Agent Auth. Confirms every action back in the meeting chat.

## Hackathon Context

- **Event:** MeetStream x Scalekit Build Day, March 28 2026, San Francisco
- **Tracks hit:** MeetStream Track 1 (Real-Time Co-Pilot) + Scalekit Track 02 (autonomous agent tool calls)
- **Code freeze:** 5:00 PM PT · **Demos:** 5:30 PM (3 min each)
- **Judging:** Innovation, Technical Execution, Impact, Depth of Integration, Demo Quality

---

## Architecture Overview

```
┌────────────────────────────────────────────────────────┐
│                   Google Meet / Zoom / Teams            │
│                                                        │
│   MeetStream Bot joins the call                        │
│   ┌──────────────────────────────────────────────┐     │
│   │  WebSocket /bridge       (control + chat)    │─────┤
│   │  WebSocket /bridge/audio (PCM 48kHz)         │─────┤
│   └──────────────────────────────────────────────┘     │
└──────────────────┬─────────────────────────────────────┘
                   │ wss:// via ngrok tunnel
                   ▼
┌────────────────────────────────────────────────────────┐
│              Your Bridge Server (FastAPI)               │
│              meetstream-agent repo                      │
│                                                        │
│   app/agent.py  ← YOU MODIFY THIS                      │
│   ┌──────────────────────────────────────────────┐     │
│   │  OpenAI Realtime Agent                       │     │
│   │  ┌────────────────────────────────────┐      │     │
│   │  │  Tools:                            │      │     │
│   │  │  - schedule_meeting()              │──────┤─────┤──→ Scalekit → Google Calendar API
│   │  │  - send_email()                    │──────┤─────┤──→ Scalekit → Gmail API
│   │  │  - post_slack_message()            │──────┤─────┤──→ Scalekit → Slack API
│   │  │  - create_notion_page()            │──────┤─────┤──→ Scalekit → Notion API
│   │  │  - current_time()                  │      │     │
│   │  └────────────────────────────────────┘      │     │
│   └──────────────────────────────────────────────┘     │
│                                                        │
│   app/scalekit_client.py  ← YOU CREATE THIS            │
│   (Scalekit SDK wrapper — shared across all tools)     │
│                                                        │
│   app/realtime/pipeline.py (untouched — glue layer)    │
│   app/meetstream/ (untouched — audio codec layer)      │
└────────────────────────────────────────────────────────┘
```

---

## Step-by-Step Build Plan

### Phase 1: Setup (45 min)

#### 1A. Clone and run the base repo

```bash
git clone https://github.com/meetstream-ai/meetstream-agent.git
cd meetstream-agent
cp .env.example .env
# Set OPENAI_API_KEY in .env
uv sync
uv run uvicorn app.server:app --host 0.0.0.0 --port 8000
# Verify: http://localhost:8000/health should return OK
```

#### 1B. Start ngrok tunnel

```bash
# In a second terminal:
ngrok http 8000
# Note the https URL, e.g. https://abc123.ngrok-free.app
# Your WebSocket URLs become:
#   wss://abc123.ngrok-free.app/bridge
#   wss://abc123.ngrok-free.app/bridge/audio
```

#### 1C. Add Scalekit + MeetStream credentials to .env

Add these lines to the `.env` file:

```env
# Existing
OPENAI_API_KEY=sk-...

# MeetStream (for creating bots via HTTP — not used by the bridge itself, but handy for a helper script)
MEETSTREAM_API_KEY=your_meetstream_api_key

# Scalekit Agent Auth
SCALEKIT_ENV_URL=https://your-env.scalekit.cloud
SCALEKIT_CLIENT_ID=skc_...
SCALEKIT_CLIENT_SECRET=sks_...

# Bot config
MEETSTREAM_BOT_NAME=Do-It Agent
```

**Where to get credentials:**
- MeetStream API key: https://app.meetstream.ai → Dashboard → API Key
- Scalekit: https://app.scalekit.com → Developers → Settings → API Credentials
- If hackathon organizers provided shared credentials, check the event Slack/Discord

#### 1D. Install Scalekit SDK

```bash
uv add scalekit-sdk-python
```

#### 1E. Set up Scalekit connectors in dashboard

Go to https://app.scalekit.com → Agent Auth → Connections → + Create Connection for each:

1. **Gmail** (likely enabled by default)
2. **Google Calendar** (likely enabled by default)
3. **Slack** — you'll need a Slack app with appropriate scopes
4. **Notion** — built-in connector available

Note the `connection_name` for each (e.g. `gmail`, `googlecalendar`, `slack`, `notion`). These are the slugs you use in code.

---

### Phase 2: Create Scalekit Wrapper (30 min)

Create a new file `app/scalekit_client.py`. This is the single integration point for all Scalekit operations.

```python
# app/scalekit_client.py
"""
Scalekit Agent Auth wrapper.
Handles OAuth token vault, connected accounts, and proxied API calls.

Reference:
- Hackathon guide: https://scalekitinc.notion.site/scalekit-meetstream-ai-hackathon-guide
- Scalekit docs: https://docs.scalekit.com/
- Python SDK: pip install scalekit-sdk-python
"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Import the Scalekit client
from scalekit.client import ScalekitClient

# Initialize once, reuse everywhere
_client = ScalekitClient(
    env_url=os.getenv("SCALEKIT_ENV_URL"),
    client_id=os.getenv("SCALEKIT_CLIENT_ID"),
    client_secret=os.getenv("SCALEKIT_CLIENT_SECRET"),
)
actions = _client.actions

# Fixed identifier for the hackathon demo user
# In production this would be your app's user ID
USER_ID = "hackathon_user_1"


def ensure_connected(connection_name: str) -> dict:
    """
    Check if a connector is authorized. Returns the connected account dict.
    If not ACTIVE, logs the authorization link (user must visit it once).
    
    Call this at startup for each connector you plan to use.
    """
    response = actions.get_or_create_connected_account(
        connection_name=connection_name,
        identifier=USER_ID,
    )
    account = response.connected_account

    if account.status != "ACTIVE":
        link_response = actions.get_authorization_link(
            connection_name=connection_name,
            identifier=USER_ID,
        )
        logger.warning(
            f"Connector '{connection_name}' not authorized. "
            f"Visit: {link_response.link}"
        )
        print(f"\n🔗 Authorize {connection_name}: {link_response.link}\n")
        return {"status": "INACTIVE", "link": link_response.link}

    logger.info(f"Connector '{connection_name}' is ACTIVE (id={account.id})")
    return {"status": "ACTIVE", "id": account.id}


def proxy_request(connection_name: str, path: str, method: str = "GET",
                  query_params: dict = None, body: dict = None) -> dict:
    """
    Make an API call through Scalekit's proxy. Scalekit injects the user's
    OAuth token automatically — no manual token handling needed.
    
    `path` is relative to the provider's base URL. Examples:
      - Gmail: "/gmail/v1/users/me/messages"
      - Calendar: "/calendar/v3/calendars/primary/events"
      - Slack: (use execute_tool instead for Slack)
    """
    kwargs = {
        "connection_name": connection_name,
        "identifier": USER_ID,
        "path": path,
        "method": method,
    }
    if query_params:
        kwargs["params"] = query_params
    if body:
        kwargs["body"] = body

    return actions.request(**kwargs)


def execute_tool(tool_name: str, tool_input: dict) -> dict:
    """
    Use Scalekit's pre-built optimized tools. These return AI-friendly
    structured responses. Available for built-in connectors only.
    
    Examples:
      execute_tool("gmail_fetch_mails", {"query": "is:unread", "max_results": 5})
      execute_tool("gmail_send_email", {"to": "...", "subject": "...", "body": "..."})
      execute_tool("notion_page_create", {"properties": {...}, "child_blocks": [...]})
    """
    # First get the connected account ID
    response = actions.get_or_create_connected_account(
        connection_name=_infer_connection(tool_name),
        identifier=USER_ID,
    )
    return actions.execute_tool(
        tool_name=tool_name,
        identifier=USER_ID,
        tool_input=tool_input,
    )


def _infer_connection(tool_name: str) -> str:
    """Map tool names to connection names."""
    if tool_name.startswith("gmail"):
        return "gmail"
    elif tool_name.startswith("notion"):
        return "notion"
    elif tool_name.startswith("slack"):
        return "slack"
    elif tool_name.startswith("google_calendar") or tool_name.startswith("gcal"):
        return "googlecalendar"
    return tool_name.split("_")[0]
```

---

### Phase 3: Add Tools to the Agent (2 hours)

Edit `app/agent.py`. You're adding new `@function_tool` definitions and wiring them into the `RealtimeAgent`.

**Key file to modify:** `app/agent.py`

The existing file already has `current_time` and `weather_now` tools. You add your Scalekit-powered tools alongside them.

#### 3A. Add imports at the top of agent.py

```python
# Add near the top imports
from app.scalekit_client import proxy_request, execute_tool, ensure_connected
```

#### 3B. Add the action tools

Add these function definitions after the existing `weather_now` tool:

```python
@function_tool(
    name_override="schedule_meeting",
    description_override=(
        "Schedule a Google Calendar event. Provide: title (string), "
        "start_time (ISO 8601 datetime string e.g. '2026-03-28T14:00:00-07:00'), "
        "end_time (ISO 8601 datetime string), "
        "attendees (comma-separated email addresses, optional), "
        "description (optional string)."
    ),
)
async def schedule_meeting(
    title: str,
    start_time: str,
    end_time: str,
    attendees: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    try:
        event_body = {
            "summary": title,
            "start": {"dateTime": start_time},
            "end": {"dateTime": end_time},
        }
        if description:
            event_body["description"] = description
        if attendees:
            emails = [e.strip() for e in attendees.split(",")]
            event_body["attendees"] = [{"email": e} for e in emails]

        result = proxy_request(
            connection_name="googlecalendar",
            path="/calendar/v3/calendars/primary/events",
            method="POST",
            body=event_body,
        )
        # Extract useful info from response
        link = result.get("htmlLink", "")
        return f"Meeting '{title}' scheduled. Calendar link: {link}"
    except Exception as e:
        return f"Failed to schedule meeting: {e}"


@function_tool(
    name_override="send_email",
    description_override=(
        "Send an email via Gmail. Provide: to (email address), "
        "subject (string), body (plain text string). "
        "Use this when someone says 'send an email to...', 'email them about...', etc."
    ),
)
async def send_email(to: str, subject: str, body: str) -> str:
    try:
        import base64
        from email.mime.text import MIMEText

        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        result = proxy_request(
            connection_name="gmail",
            path="/gmail/v1/users/me/messages/send",
            method="POST",
            body={"raw": raw},
        )
        return f"Email sent to {to} with subject '{subject}'."
    except Exception as e:
        return f"Failed to send email: {e}"


@function_tool(
    name_override="post_slack_message",
    description_override=(
        "Post a message to a Slack channel. Provide: channel (channel name without #, "
        "e.g. 'general'), message (the text to post). "
        "Use when someone says 'post to Slack', 'notify the team', etc."
    ),
)
async def post_slack_message(channel: str, message: str) -> str:
    try:
        result = proxy_request(
            connection_name="slack",
            path="/api/chat.postMessage",
            method="POST",
            body={"channel": channel, "text": message},
        )
        ok = result.get("ok", False)
        if ok:
            return f"Posted to #{channel}: '{message}'"
        else:
            error = result.get("error", "unknown")
            return f"Slack error: {error}"
    except Exception as e:
        return f"Failed to post to Slack: {e}"


@function_tool(
    name_override="create_notion_page",
    description_override=(
        "Create a page in Notion. Provide: title (string), content (markdown-ish text). "
        "Use when someone says 'save this to Notion', 'create a doc', 'write this down', etc."
    ),
)
async def create_notion_page(title: str, content: str) -> str:
    try:
        result = execute_tool(
            tool_name="notion_page_create",
            tool_input={
                "properties": {
                    "title": [{"type": "text", "text": {"content": title}}]
                },
                "child_blocks": [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": content}}]
                        },
                    }
                ],
            },
        )
        url = result.data.get("url", "created")
        return f"Notion page '{title}' created: {url}"
    except Exception as e:
        return f"Failed to create Notion page: {e}"
```

#### 3C. Update the agent instructions

Replace the `_build_agent_instructions()` function body:

```python
def _build_agent_instructions() -> str:
    return """You are a meeting action agent called "Do-It Agent". You join live meetings and execute real-world actions when participants ask.

YOUR CAPABILITIES:
- schedule_meeting: Create Google Calendar events with title, time, attendees
- send_email: Send emails via Gmail to any address
- post_slack_message: Post messages to Slack channels
- create_notion_page: Create pages in Notion with meeting notes or content
- current_time: Get the current time in any timezone
- weather_now: Check weather for any city

BEHAVIOR RULES:
1. Listen carefully for action requests. Common triggers:
   - "Schedule a follow-up..." / "Set up a meeting..."
   - "Send an email to..." / "Email them about..."
   - "Post to Slack..." / "Notify the team..."
   - "Save this to Notion..." / "Write this down..."
2. When you detect an action request, confirm what you're about to do, then execute it.
3. After executing, announce the result clearly: "Done — I've scheduled a meeting for Tuesday at 2pm" or "Email sent to sarah@company.com".
4. If you're missing required info (like an email address or specific time), ask for it.
5. Keep spoken responses concise. Don't ramble.
6. For scheduling: if someone says "next Tuesday" or "tomorrow at 3", use current_time first to resolve the exact date, then create the event.
7. You may also proactively suggest actions based on the conversation. E.g., if people agree on a follow-up, offer to schedule it.

IMPORTANT: Only use tools that appear in your available tool list. Do not invent tool names."""
```

#### 3D. Update the agent's tools list

Find the `assistant_agent = RealtimeAgent(...)` block and update it:

```python
assistant_agent = RealtimeAgent(
    name="Do-It Agent",
    handoff_description="Meeting action agent that executes real-world tasks via voice commands.",
    instructions=AGENT_INSTRUCTIONS,
    tools=[current_time, weather_now, schedule_meeting, send_email, post_slack_message, create_notion_page],
    mcp_servers=MCP_REGISTRY.servers,
)
```

---

### Phase 4: Startup Auth Check (15 min)

Add a startup hook so the server verifies all connectors are authorized before accepting meetings. 

Edit `app/server.py` — add to the lifespan or startup event:

```python
# In server.py, inside the lifespan or startup:
from app.scalekit_client import ensure_connected

# Check all connectors on startup
for connector in ["gmail", "googlecalendar", "slack", "notion"]:
    result = ensure_connected(connector)
    if result["status"] != "ACTIVE":
        print(f"⚠️  {connector} needs authorization — visit the link above")
```

This prints auth links for any connectors that need OAuth. You visit each link once in your browser, and they stay authorized for the session.

---

### Phase 5: Create a Bot Launch Script (15 min)

Create `launch_bot.py` in the project root — a quick way to send the bot into a meeting:

```python
#!/usr/bin/env python3
"""Send a MeetStream bot into a meeting, pointing at your local bridge."""
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

MEETSTREAM_API_KEY = os.getenv("MEETSTREAM_API_KEY")
NGROK_URL = sys.argv[1] if len(sys.argv) > 1 else input("Enter your ngrok https URL: ").strip()
MEETING_LINK = sys.argv[2] if len(sys.argv) > 2 else input("Enter meeting link: ").strip()

# Convert https:// to wss://
WSS_BASE = NGROK_URL.replace("https://", "wss://").replace("http://", "ws://")

payload = {
    "meeting_link": MEETING_LINK,
    "bot_name": "Do-It Agent",
    "video_required": False,
    "socket_connection_url": {
        "websocket_url": f"{WSS_BASE}/bridge"
    },
    "live_audio_required": {
        "websocket_url": f"{WSS_BASE}/bridge/audio"
    },
    "automatic_leave": {
        "waiting_room_timeout": 600,
        "everyone_left_timeout": 120,
    },
}

resp = requests.post(
    "https://api.meetstream.ai/api/v1/bots/create_bot",
    headers={
        "Authorization": f"Token {MEETSTREAM_API_KEY}",
        "Content-Type": "application/json",
    },
    json=payload,
)

print(resp.status_code, resp.json())
```

Usage:
```bash
python launch_bot.py https://abc123.ngrok-free.app https://meet.google.com/xxx-xxxx-xxx
```

---

### Phase 6: Test End-to-End (1 hour)

#### Test sequence:

1. Start the bridge server: `uv run uvicorn app.server:app --host 0.0.0.0 --port 8000`
2. Start ngrok: `ngrok http 8000`
3. Authorize connectors: visit each link printed at startup
4. Open a Google Meet in your browser
5. Launch the bot: `python launch_bot.py <ngrok-url> <meet-link>`
6. Wait for bot to join the meeting
7. Test each tool by speaking:
   - "What time is it in New York?"
   - "Schedule a meeting called 'Design Review' for tomorrow at 2pm Pacific"
   - "Send an email to test@example.com with subject 'Meeting Notes' saying we agreed on the new design"
   - "Post to the general Slack channel: Design review meeting in progress"
   - "Create a Notion page called 'Meeting Action Items' with the content: review mockups by Friday"

#### What to verify:
- Bot joins and you can hear its voice responses
- Each tool call executes (check Google Calendar, Gmail sent folder, Slack channel, Notion)
- Bot confirms each action in its spoken response
- No echo loop (bot should filter its own audio via `MEETSTREAM_BOT_NAME`)

---

### Phase 7: Demo Polish (1 hour)

#### Demo script (3 minutes):

**Minute 0:00-0:30** — Intro
- "We built Do-It Agent: a meeting bot that doesn't just listen, it acts."
- Show the architecture slide (optional) or just jump to the live demo

**Minute 0:30-1:30** — Live demo in a Google Meet
- Bot is already in the meeting
- Say: "Schedule a team sync for next Monday at 10am with john@company.com"
- Bot responds: "Done, scheduled Team Sync for Monday March 30 at 10am. Calendar invite sent to john@company.com."
- Show Google Calendar updating in real time (split screen)

**Minute 1:30-2:15** — Second action
- Say: "Send the meeting summary to the team on Slack in the general channel"
- Bot responds: "Posted to #general: Meeting summary..."
- Show Slack updating

**Minute 2:15-2:45** — Third action
- Say: "Create a Notion doc with today's action items"
- Bot responds: "Notion page created: Action Items — March 28"
- Show Notion page appearing

**Minute 2:45-3:00** — Wrap
- "MeetStream gives the agent ears and a voice. Scalekit gives it hands to act on your tools. No OAuth plumbing, no token management. Just say what you need."

---

## Key Files Summary

| File | Action | Purpose |
|---|---|---|
| `.env` | Modify | Add MEETSTREAM_API_KEY, SCALEKIT_* credentials |
| `app/scalekit_client.py` | **Create new** | Scalekit SDK wrapper (init, ensure_connected, proxy_request, execute_tool) |
| `app/agent.py` | **Modify** | Add 4 new @function_tools, update agent instructions and tools list |
| `app/server.py` | **Modify** | Add startup auth check for all connectors |
| `launch_bot.py` | **Create new** | Helper script to send bot into a meeting |
| `app/realtime/pipeline.py` | Don't touch | Glue layer between MeetStream WebSocket and OpenAI Realtime |
| `app/meetstream/` | Don't touch | Audio codec, speaker filtering, outbound commands |

---

## Reference Links

| Resource | URL |
|---|---|
| meetstream-agent repo | https://github.com/meetstream-ai/meetstream-agent |
| MeetStream API docs | https://docs.meetstream.ai/ |
| MeetStream Create Bot API | https://docs.meetstream.ai/api-reference/ap-is/bot-endpoints/create-bot |
| MeetStream Dashboard (API key) | https://app.meetstream.ai |
| MeetStream Bridge Server Guide | https://docs.meetstream.ai/guides/get-started/bridge-server-architecture |
| Scalekit Dashboard | https://app.scalekit.com |
| Scalekit Python SDK | `pip install scalekit-sdk-python` |
| Scalekit Hackathon Guide | https://scalekitinc.notion.site/scalekit-meetstream-ai-hackathon-guide |
| Scalekit Notion connector ref | https://docs.scalekit.com/reference/agent-connectors/notion/ |
| Reference app (Scalekit+MeetStream) | https://github.com/Avinash-Kamath/scalekit-meetstream |
| OpenAI Agents SDK (voice) | https://openai.github.io/openai-agents-python/ |
| MeetStream+Scalekit Hackathon Guide | https://playful-typhoon-9eb.notion.site/MeetStream-x-Scalekit-Hackathon-Developer-Guide-3307ba32aebf81ba94a5e7d3c96b3607 |

---

## Scalekit SDK Quick Reference (Python)

```python
from scalekit.client import ScalekitClient

# Init (once)
client = ScalekitClient(env_url=..., client_id=..., client_secret=...)
actions = client.actions

# Check/create connected account (idempotent)
resp = actions.get_or_create_connected_account(connection_name="gmail", identifier="user_123")
account = resp.connected_account  # .status = "ACTIVE" | "INACTIVE" | "EXPIRED"

# Get auth link if not active
link_resp = actions.get_authorization_link(connection_name="gmail", identifier="user_123")
print(link_resp.link)  # User visits this URL to OAuth

# Proxy API call (Scalekit injects tokens automatically)
result = actions.request(
    connection_name="gmail",
    identifier="user_123",
    path="/gmail/v1/users/me/messages",
    method="GET",
    params={"q": "is:unread", "maxResults": 5},
)

# Or use optimized tools (structured AI-friendly responses)
result = actions.execute_tool(
    tool_name="gmail_fetch_mails",
    identifier="user_123",
    tool_input={"query": "is:unread", "max_results": 5},
)
```

**Built-in connection names:** gmail, googlecalendar, slack, github, notion, hubspot, jira, salesforce, outlook, googledrive, linear, zoom, gong, airtable

---

## MeetStream Create Bot API Quick Reference

```bash
# Voice agent bot (bridge mode — what we use)
curl -X POST "https://api.meetstream.ai/api/v1/bots/create_bot" \
  -H "Authorization: Token YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "meeting_link": "https://meet.google.com/xxx-xxxx-xxx",
    "bot_name": "Do-It Agent",
    "video_required": false,
    "socket_connection_url": {
      "websocket_url": "wss://your-ngrok.ngrok-free.app/bridge"
    },
    "live_audio_required": {
      "websocket_url": "wss://your-ngrok.ngrok-free.app/bridge/audio"
    },
    "automatic_leave": {
      "waiting_room_timeout": 600,
      "everyone_left_timeout": 120
    }
  }'

# Response: { "bot_id": "...", "meeting_url": "...", "status": "Active" }

# Other useful endpoints:
# GET /api/v1/bots/{bot_id}/detail    — bot metadata
# GET /api/v1/bots/{bot_id}/status    — current status
# GET /api/v1/bots/remove/{bot_id}    — remove bot from meeting
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Bot joins but no voice response | Check OPENAI_API_KEY is set. Check server logs for OpenAI Realtime errors. |
| Echo loop (bot responds to itself) | Set `MEETSTREAM_BOT_NAME=Do-It Agent` in .env. The bridge filters audio from this speaker name. |
| Scalekit "not ACTIVE" error | Visit the auth link printed at startup. You need to OAuth once per connector. |
| ngrok URL changed | Restart the bot with the new URL. Kill old bot via `GET /api/v1/bots/remove/{bot_id}`. |
| Tool call fails silently | Check server terminal for Python exceptions. The `@function_tool` wrapper catches errors and returns them as strings to the model. |
| "connection_name not found" | Make sure you created the connection in Scalekit dashboard (Agent Auth → Connections → + Create Connection). |
| Gmail send fails | The Gmail API requires the `raw` field with base64-encoded MIME. Double-check the `send_email` tool encodes correctly. |
| Slack "channel_not_found" | Try using the channel ID instead of name. Or ensure the Slack app is invited to the channel. |

---

## Stretch Goals (if time permits)

1. **Read before you act:** Before scheduling, check Google Calendar for conflicts. Before emailing, pull recent threads for context.
2. **Meeting summary tool:** At end of call, auto-generate a summary and push to Notion + Slack.
3. **Multi-step chains:** "Schedule a meeting and then email everyone the invite link" — agent chains two tool calls.
4. **Confirmation before destructive actions:** Agent says "I'm about to send an email to sarah@... — should I go ahead?" and waits for "yes".
