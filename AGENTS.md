# AGENTS.md — Do-It Agent

## Project Overview

Voice-enabled meeting agent that listens to live conversations (via MeetStream) and executes real-world actions (schedule meetings, send emails, post to Slack) via ScaleKit Agent Auth. Confirms every action in the meeting chat.

**Stack**: Python 3.11+, Flask, FastMCP, uv package manager

---

## Essential Commands

### Development
```bash
uv sync                    # Install dependencies from pyproject.toml
uv run python main.py      # Start webhook server (Flask, port 8999)
uv run python mcp_server.py # Start MCP server (FastMCP, port 3002)
```

### Tunneling (required for external access)
```bash
ngrok http 3002            # Tunnel MCP server (port 3002) for MeetStream MIA
cloudflared tunnel run --token <TOKEN>  # Tunnel webhook server (port 8999)
```

### Launching the Bot
```bash
uv run python launch_bot.py <NGROK_URL> <MEETING_LINK>
```

### Ports
| Service | Port | Purpose |
|---------|------|---------|
| `main.py` | 8999 | Flask webhook server for transcription events |
| `mcp_server.py` | 3002 | FastMCP server providing tool endpoints |
| ngrok | forwards 3002 | Public URL for MeetStream MIA |

---

## Code Organization

```
scxmsxantler/
├── main.py               # Flask webhook server (port 8999)
│                         # Handles transcription webhooks from MeetStream
│                         # Runs intent detection via OpenAI function calling
│                         # Triggers action tools from scalekit_client.py
│
├── mcp_server.py         # FastMCP server (port 3002)
│                         # Self-hosted MCP tools for MeetStream MIA
│                         # OAuth endpoints (/oauth/callback, /oauth/token)
│                         # 4 tools: send_slack_message, create_calendar_event,
│                         #          list_calendar_events, fetch_emails,
│                         #          search_emails, generate_meeting_summary
│
├── scalekit_client.py    # ScaleKit SDK wrapper (shared by main.py & mcp_server.py)
│                         # Lazy-initialized ScalekitClient
│                         # Functions: ensure_connected, create_calendar_event,
│                         #            fetch_emails, send_slack_message
│
├── meeting_summary.py    # Shared pipeline
│                         # fetch_bot_audio_url -> transcribe_audio -> summarize_transcript
│                         # Uses AssemblyAI for transcription, Minimax for summary
│
├── launch_bot.py         # MeetStream bot launcher
│                         # POSTs to api.meetstream.ai to create a bot in a meeting
│                         # Webhook callback points to main.py (Flask webhook server)
│
├── skills/               # Crush skill definitions
│   └── integrating-agent-auth/
│
├── pyproject.toml        # Project metadata and dependencies
│                         # Key deps: flask, scalekit-sdk-python, fastmcp,
│                         #           assemblyai, openai, python-dotenv
└── .env.example          # Template for required environment variables
```

---

## Environment Variables

Required in `.env`:
```
OPENAI_API_KEY=
MEET_STREAM_API_KEY=
SCALEKIT_ENV_URL=https://antler.scalekit.dev
SCALEKIT_CLIENT_ID=
SCALEKIT_CLIENT_SECRET=
CONNECTION_NAME_GMAIL=gmail
CONNECTION_NAME_CALENDAR=googlecalendar
CONNECTION_NAME_SLACK=slack
IDENTIFIER=hackathon_user_1
MCP_SERVER_ID=       # From ScaleKit dashboard MCP Servers page
PUBLIC_URL=           # ngrok URL for MCP server (e.g. https://abc123.ngrok-free.dev)
PROTECTED_RESOURCE_METADATA=  # Optional, from ScaleKit dashboard
SUMMARY_SLACK_CHANNEL=#social
```

---

## Architecture

### Dual Integration Paths

1. **Webhook path** (main.py → scalekit_client.py): MeetStream sends transcription webhooks → Flask detects intent via OpenAI function calling → calls ScaleKit tools directly. This is the legacy path.

2. **MCP path** (mcp_server.py): MeetStream MIA (cloud LLM) calls MCP tools directly → FastMCP proxies to ScaleKit. This is the primary current path.

### ScaleKit Connection Names
- `gmail` — Gmail API
- `googlecalendar` — Google Calendar API
- `slack` — Slack API

### ScaleKit Tool Names
- `googlecalendar_create_event` — create calendar event
- `googlecalendar_list_events` — list calendar events
- `gmail_fetch_mails` — fetch/search emails
- `slack_send_message` — send Slack message

---

## Code Patterns

### Lazy Initialization (scalekit_client.py)
```python
_client = None

def _get_actions():
    global _client
    if _client is None:
        _client = ScalekitClient(env_url=..., client_id=..., client_secret=...)
    return _client.actions
```

### ScaleKit Tool Execution Pattern
```python
result = _get_actions().execute_tool(
    tool_name="googlecalendar_create_event",
    identifier=IDENTIFIER,
    tool_input={"summary": title, "start_datetime": start, ...},
)
```

### MCP Tool Pattern (mcp_server.py)
```python
@mcp.tool()
def send_slack_message(text: str, channel: str = "#social") -> str:
    err = _check_connection_or_fail("slack")
    if err:
        return err
    try:
        result = _execute_tool("slack_send_message", {"channel": channel, "text": text})
        return json.dumps(result, default=str)
    except Exception as e:
        return f"Failed to send Slack message: {e}"
```

### Connection Check Pattern
```python
def _ensure_connected(connection_name: str) -> dict:
    response = scalekit_client.actions.get_or_create_connected_account(
        connection_name=connection_name, identifier=IDENTIFIER,
    )
    account = response.connected_account
    if account.status != "ACTIVE":
        link_response = scalekit_client.actions.get_authorization_link(...)
        return {"connected": False, "link": link_response.link}
    return {"connected": True}
```

### Flask Webhook Handler Pattern
```python
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    event = data.get("event", "")
    if event.startswith("transcription."):
        transcription_text = data.get("data", {}).get("transcript", "")
        results = detect_and_execute(transcription_text)
    return "", 200
```

### Background Thread for Long-Running Tasks
```python
thread = threading.Thread(
    target=_safe_generate_and_post_summary, args=(bot_id,), daemon=True
)
thread.start()
```

---

## Logging Conventions

- Logger names match module: `logger = logging.getLogger("scalekit")`
- Format: `%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- Level: `logging.DEBUG` for verbose, `logging.INFO` for production
- Prefix tags in log messages: `[CALENDAR]`, `[GMAIL]`, `[SLACK]`, `[AUTH]`, `[WEBHOOK]`, `[TRANSCRIPT]`, `[INTENT]`, `[ACTION]`, `[SUMMARY]`

---

## Testing

### Manual Testing (in a live meeting)
Say to the bot:
- "Send a message to Slack saying hello from the meeting"
- "Schedule a meeting tomorrow at 2pm called Team Sync"
- "Check my unread emails"
- "What meetings do I have today?"

### Health Checks
```bash
curl http://localhost:3002/health  # MCP server
curl http://localhost:8999/health  # Webhook server
```

### Connection Status
```python
from scalekit_client import ensure_connected
ensure_connected("gmail")   # Returns {"status": "ACTIVE", "id": "..."} or {"status": "INACTIVE", "link": "..."}
```

---

## Gotchas

1. **ScaleKit connections expire** — OAuth tokens expire. Re-authorize via the link returned by `ensure_connected()`. Run `uv run python setup_mcp.py` to check status.

2. **Two ScaleKit wrappers exist** — `scalekit_client.py` (direct SDK calls) and `mcp_server.py` (which has its own `_execute_tool`, `_ensure_connected`). Both wrap the same ScaleKit SDK but are used in different code paths. Keep them consistent.

3. **OAuth redirect URL** — Must be `https://<ngrok-url>/oauth/callback` registered in ScaleKit dashboard. If ngrok URL changes, update dashboard.

4. **Bot requires both tunnels** — ngrok for MIA MCP calls, cloudflared for webhook callbacks. Both must be running.

5. **AssemblyAI transcription** — `meeting_summary.py` requires pre-recorded audio from MeetStream. Audio is available after the bot finishes a meeting. Transcription happens async via background thread.

6. **IDENTIFIER is hardcoded** — `IDENTIFIER = os.getenv("IDENTIFIER", "hackathon_user_1")`. In production this would be the actual user ID from your auth system.

7. **`launch_bot.py` has hardcoded `agent_config_id`** — `agent_config_id: "4046c44f-57f1-4691-bdb6-ed432cbdcccc"` points to a specific MIA config in MeetStream dashboard. Update if MIA config changes.

8. **`__main__` guard in mcp_server.py** — MCP server imports FastMCP, which imports Starlette. The `if __name__ == "__main__"` block wraps in uvicorn with `BaseHTTPMiddleware` for auto-initialization. Don't run mcp_server.py as a module.

9. **Slack channel format** — Use `#channel-name` (with hash) or channel ID. The default is `#social`.

10. **Calendar RFC3339 timestamps** — `start_time` must be in RFC3339 format, e.g. `2026-03-28T14:00:00-07:00`. Default timezone is `America/Los_Angeles`.

11. **Meeting summary requires bot_id** — The `generate_meeting_summary` tool takes a bot_id returned from `launch_bot.py`. You need to save it from the launch response.

---

## Reference Links

| Resource | URL |
|----------|-----|
| MeetStream Dashboard | https://app.meetstream.ai |
| MeetStream API Docs | https://docs.meetstream.ai/ |
| ScaleKit Dashboard | https://app.scalekit.com |
| ScaleKit Python SDK | `pip install scalekit-sdk-python` |
| ScaleKit Docs | https://docs.scalekit.com/ |
| FastMCP | https://github.com/jlowin/fastmcp |
| AssemblyAI | https://www.assemblyai.com/ |
| ngrok | https://ngrok.com/ |
| cloudflared | https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/ |
