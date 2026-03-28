# Do-It Agent -- Runbook

## Architecture

```
You speak in meeting
        |
MeetStream MIA (cloud -- LLM, STT, TTS)
        |  MCP tool calls (Streamable HTTP)
        v
ngrok (public URL)
        |
        v
mcp_server.py (local, port 3002)
   ├── OAuth endpoints (proxied to ScaleKit)
   └── 4 MCP tools:
        ├── send_slack_message  →  ScaleKit → Slack (#social)
        ├── create_calendar_event  →  ScaleKit → Google Calendar
        ├── list_calendar_events  →  ScaleKit → Google Calendar
        └── fetch_emails  →  ScaleKit → Gmail
```

Webhook server (`main.py`, port 8999) handles meeting transcription events separately via Cloudflare tunnel.

---

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- [ngrok](https://ngrok.com/) installed and authenticated
- [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/) installed
- ScaleKit account with API credentials
- MeetStream account with API key

---

## One-Time Setup

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure `.env`

```
OPENAI_API_KEY=<your-openai-key>
MEET_STREAM_API_KEY=<your-meetstream-key>
SCALEKIT_ENV_URL=https://antler.scalekit.dev
SCALEKIT_CLIENT_ID=<your-scalekit-client-id>
SCALEKIT_CLIENT_SECRET=<your-scalekit-client-secret>
CONNECTION_NAME_GMAIL=gmail
CONNECTION_NAME_CALENDAR=googlecalendar
CONNECTION_NAME_SLACK=slack
IDENTIFIER=hackathon_user_1
MCP_SERVER_ID=<from-scalekit-dashboard>
PUBLIC_URL=<your-ngrok-url>
PROTECTED_RESOURCE_METADATA=<optional-from-scalekit-dashboard>
```

### 3. ScaleKit Dashboard

1. **MCP Servers → Add MCP Server**
   - Name: `Do-It Agent MCP`
   - Enable Dynamic Client Registration + CIMD
   - Set Server URL to your ngrok URL (e.g. `https://xxx.ngrok-free.dev`)
   - Add scopes: `gmail:read`, `slack:write`, `calendar:read`, `calendar:write`
   - Copy the **MCP Server ID** (`res_xxx`) → put in `.env` as `MCP_SERVER_ID`
   - Copy **Metadata JSON** → put in `.env` as `PROTECTED_RESOURCE_METADATA` (optional)

2. **Add redirect URL**: `https://<your-ngrok-url>/oauth/callback`

3. **Agent Auth → Connections** -- verify gmail, googlecalendar, slack connections are ACTIVE:
   ```bash
   uv run python setup_mcp.py
   ```

### 4. MeetStream MIA Dashboard

1. Go to **app.meetstream.ai → MIA → your agent**
2. Set **MCP Server URL**: `https://<your-ngrok-url>/mcp`
3. Click **Fetch** → should see 4 tools
4. Select all tools → **Save**
5. Note the `agent_config_id` and update it in `launch_bot.py` if needed

---

## Running

Open 4 terminals:

### Terminal 1 -- ngrok (MCP server tunnel)

```bash
ngrok http 3002
```

Note the public URL and update `PUBLIC_URL` in `.env` if it changed.

### Terminal 2 -- Cloudflare tunnel (webhook server)

```bash
cloudflared tunnel run --token <YOUR_CLOUDFLARE_TUNNEL_TOKEN>
```

Or for a quick anonymous tunnel:
```bash
cloudflared tunnel --url http://localhost:8999
```

### Terminal 3 -- MCP server

```bash
cd /Users/divagarwal/Projects/scxmsxantler
uv run python mcp_server.py
```

Verify it's running:
```bash
curl http://localhost:3002/health
```

### Terminal 4 -- Launch bot into a meeting

```bash
cd /Users/divagarwal/Projects/scxmsxantler
uv run python launch_bot.py <CLOUDFLARE_TUNNEL_URL> <MEETING_LINK>
```

Example:
```bash
uv run python launch_bot.py https://your-tunnel.trycloudflare.com https://meet.google.com/abc-defg-hij
```

### Optional: Terminal 5 -- Webhook server (transcript processing)

Only needed if you want the old webhook-based intent detection alongside MIA:
```bash
cd /Users/divagarwal/Projects/scxmsxantler
uv run python main.py
```

---

## Testing

Once the bot joins the meeting, say:

- **Slack**: "Send a message to Slack saying hello from the meeting"
- **Calendar**: "Schedule a meeting tomorrow at 2pm called Team Sync"
- **Email**: "Check my unread emails"
- **Calendar read**: "What meetings do I have today?"

MIA picks up your voice, calls the MCP tool, ScaleKit executes it.

---

## Stopping

Kill all services:
```bash
lsof -ti:3002,8999 | xargs kill -9 2>/dev/null
killall ngrok 2>/dev/null
killall cloudflared 2>/dev/null
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| MIA can't fetch tools | Check ngrok is running on 3002 and MCP URL ends with `/mcp` |
| "Port already in use" | Run the kill command above to free ports |
| ScaleKit auth errors | Run `uv run python setup_mcp.py` to check connection status |
| Bot doesn't join meeting | Verify `MEET_STREAM_API_KEY` and `agent_config_id` in `launch_bot.py` |
| Tools execute but fail | Check ScaleKit connections are ACTIVE (not expired) |
| ngrok URL changed | Update `PUBLIC_URL` in `.env`, update ScaleKit dashboard Server URL + redirect URL, update MIA MCP Server URL |
