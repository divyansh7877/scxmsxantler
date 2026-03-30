# Do-It Agent

Voice-enabled meeting agent that listens to live conversations and executes real-world actions via ScaleKit Agent Auth — schedule meetings, send emails, post to Slack, and more. Confirms every action back in the meeting.

Built during the MeetStream x ScaleKit Build Day hackathon (March 28, 2026).

## Architecture

```
You speak in meeting
        |
MeetStream MIA (cloud -- LLM, STT, TTS)
        |  MCP tool calls (Streamable HTTP)
        v
ngrok tunnel (port 3002)
        |
        v
mcp_server.py (FastMCP)
   ├── OAuth endpoints
   └── Tools: send_slack_message, create_calendar_event,
              list_calendar_events, fetch_emails, search_emails,
              generate_meeting_summary
        |
        v
ScaleKit Agent Auth
   └── Gmail, Google Calendar, Slack APIs
```

A webhook path also exists (Flask on port 8999) for transcription-based intent detection.

## Quick Start

### 1. Install dependencies
```bash
uv sync
cp .env.example .env
# Fill in .env with your API keys (see Environment Variables below)
```

### 2. Start the MCP server
```bash
uv run python mcp_server.py
```

### 3. Tunnel with ngrok
```bash
ngrok http 3002
```
Note the public URL (e.g. `https://abc123.ngrok-free.dev`).

### 4. Configure ScaleKit dashboard
1. Go to **ScaleKit → MCP Servers → Add MCP Server**
   - Name: `Do-It Agent MCP`
   - Server URL: your ngrok URL
   - Redirect URL: `https://<ngrok-url>/oauth/callback`
   - Add scopes: `gmail:read`, `slack:write`, `calendar:read`, `calendar:write`
   - Copy the **MCP Server ID** → put in `.env` as `MCP_SERVER_ID`
2. Go to **Agent Auth → Connections** — ensure gmail, googlecalendar, slack are ACTIVE
3. If not active, run:
   ```bash
   uv run python -c "from scalekit_client import ensure_connected; ensure_connected('gmail')"
   # Visit the printed authorization link
   ```

### 5. Configure MeetStream MIA
1. Go to **app.meetstream.ai → MIA → your agent**
2. Set **MCP Server URL**: `https://<ngrok-url>/mcp`
3. Fetch and save tools

### 6. Launch bot into a meeting
```bash
uv run python launch_bot.py <NGROK_URL> <MEETING_LINK>
```

### 7. Test
Say to the bot:
- "Send a message to Slack saying hello"
- "Schedule a meeting tomorrow at 2pm called Team Sync"
- "Check my unread emails"
- "What meetings do I have today?"

## Environment Variables

```env
OPENAI_API_KEY=
MEET_STREAM_API_KEY=
SCALEKIT_ENV_URL=https://antler.scalekit.dev
SCALEKIT_CLIENT_ID=
SCALEKIT_CLIENT_SECRET=
CONNECTION_NAME_GMAIL=gmail
CONNECTION_NAME_CALENDAR=googlecalendar
CONNECTION_NAME_SLACK=slack
IDENTIFIER=hackathon_user_1
MCP_SERVER_ID=        # From ScaleKit dashboard MCP Servers page
PUBLIC_URL=           # Your ngrok URL (e.g. https://abc123.ngrok-free.dev)
SUMMARY_SLACK_CHANNEL=#social
ASSEMBLYAI_API_KEY=   # For meeting summaries
MINIMAX_API_KEY=      # For meeting summaries
MINIMAX_MODEL=MiniMax-M2.5
```

## Scripts

| Script | Command | Purpose |
|--------|---------|---------|
| MCP server | `uv run python mcp_server.py` | FastMCP server (port 3002) |
| Webhook server | `uv run python main.py` | Flask webhook server (port 8999) |
| Bot launcher | `uv run python launch_bot.py <url> <link>` | Send bot into a meeting |
| Auth check | `uv run python -c "from scalekit_client import ensure_connected; print(ensure_connected('gmail'))"` | Check ScaleKit connection |

## Key Files

| File | Purpose |
|------|---------|
| `mcp_server.py` | FastMCP server with OAuth endpoints and 7 tools |
| `scalekit_client.py` | ScaleKit SDK wrapper — shared by all tools |
| `main.py` | Flask webhook server for transcription events |
| `meeting_summary.py` | Pipeline: MeetStream audio → AssemblyAI → Minimax → Slack |
| `launch_bot.py` | MeetStream bot launcher |

## Tech Stack

- **Runtime**: Python 3.11+, [uv](https://docs.astral.sh/uv/)
- **MCP Server**: FastMCP, Starlette, uvicorn
- **Webhook**: Flask
- **AI Services**: OpenAI (intent detection), AssemblyAI (transcription), Minimax (summaries)
- **Auth**: ScaleKit Agent Auth
- **Meetings**: MeetStream MIA

## Reference

- [MeetStream docs](https://docs.meetstream.ai/)
- [ScaleKit docs](https://docs.scalekit.com/)
- [FastMCP](https://github.com/jlowin/fastmcp)
