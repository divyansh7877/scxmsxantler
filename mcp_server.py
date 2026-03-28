#!/usr/bin/env python3
"""Self-hosted MCP server with ScaleKit OAuth + Agent Auth tool execution.

Run: uv run python mcp_server.py
Expose: ngrok http 3002
"""
import os
import json
import logging
import httpx

from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse, HTMLResponse, RedirectResponse, Response
from scalekit.client import ScalekitClient
from scalekit.common.scalekit import TokenValidationOptions

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mcp-server")

# --- Config ---
PORT = int(os.getenv("PORT", "3002"))
PUBLIC_URL = os.getenv("PUBLIC_URL", f"http://localhost:{PORT}")
MCP_SERVER_ID = os.getenv("MCP_SERVER_ID", "")
SK_ENV_URL = os.getenv("SCALEKIT_ENV_URL", "")
SK_CLIENT_ID = os.getenv("SCALEKIT_CLIENT_ID", "")
SK_CLIENT_SECRET = os.getenv("SCALEKIT_CLIENT_SECRET", "")
IDENTIFIER = os.getenv("IDENTIFIER", "hackathon_user_1")

PROTECTED_RESOURCE_METADATA = os.getenv("PROTECTED_RESOURCE_METADATA", "")

# --- ScaleKit client ---
scalekit_client = ScalekitClient(
    env_url=SK_ENV_URL,
    client_id=SK_CLIENT_ID,
    client_secret=SK_CLIENT_SECRET,
)

# --- FastMCP server ---
mcp = FastMCP(name="Do-It Agent MCP", version="1.0.0")


# =====================================================================
# OAuth / Discovery endpoints (custom routes on the same HTTP server)
# =====================================================================

@mcp.custom_route("/.well-known/oauth-protected-resource", methods=["GET"])
async def oauth_discovery(request: Request) -> JSONResponse:
    if PROTECTED_RESOURCE_METADATA:
        metadata = json.loads(PROTECTED_RESOURCE_METADATA)
    else:
        metadata = {
            "authorization_servers": [
                f"{SK_ENV_URL}/resources/{MCP_SERVER_ID}"
            ],
            "bearer_methods_supported": ["header"],
            "resource": PUBLIC_URL,
            "scopes_supported": [
                "openid", "profile", "email",
                "gmail:read", "slack:write",
                "calendar:read", "calendar:write",
            ],
        }
    metadata["resource"] = PUBLIC_URL
    return JSONResponse(metadata)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "server": "Do-It Agent MCP",
        "version": "1.0.0",
    })


@mcp.custom_route("/register", methods=["POST"])
async def register_client(request: Request) -> JSONResponse:
    body = await request.json()
    logger.info("OAuth client registration: %s", body.get("client_name"))
    return JSONResponse({
        "client_id": SK_CLIENT_ID,
        "client_secret": SK_CLIENT_SECRET,
        "client_name": body.get("client_name"),
        "redirect_uris": body.get("redirect_uris"),
        "grant_types": body.get("grant_types", ["authorization_code", "refresh_token"]),
        "response_types": body.get("response_types", ["code"]),
        "token_endpoint_auth_method": body.get("token_endpoint_auth_method", "client_secret_post"),
        "scope": body.get("scope", "openid profile email gmail:read slack:write calendar:read calendar:write"),
    })


@mcp.custom_route("/oauth/authorize", methods=["GET"])
async def oauth_authorize(request: Request) -> RedirectResponse:
    redirect_uri = request.query_params.get("redirect_uri", "")
    state = request.query_params.get("state", "")
    scope = request.query_params.get("scope", "openid profile email gmail:read")
    scopes = scope.split(" ") if scope else ["openid", "profile", "email", "gmail:read"]

    logger.info("OAuth authorize: redirect_uri=%s state=%s scopes=%s", redirect_uri, state, scopes)

    from scalekit.common.scalekit import AuthorizationUrlOptions
    options = AuthorizationUrlOptions(state=state, scopes=scopes)
    auth_url = scalekit_client.get_authorization_url(redirect_uri, options)
    return RedirectResponse(str(auth_url))


@mcp.custom_route("/oauth/token", methods=["POST"])
async def oauth_token(request: Request) -> JSONResponse:
    body = await request.form()
    grant_type = body.get("grant_type", "")
    logger.info("OAuth token: grant_type=%s", grant_type)

    params = {
        "grant_type": grant_type,
        "client_id": body.get("client_id") or SK_CLIENT_ID,
        "client_secret": body.get("client_secret") or SK_CLIENT_SECRET,
    }

    if grant_type == "authorization_code":
        params["code"] = body.get("code", "")
        params["redirect_uri"] = body.get("redirect_uri", "")
    elif grant_type == "refresh_token":
        params["refresh_token"] = body.get("refresh_token", "")
    else:
        return JSONResponse(
            {"error": "unsupported_grant_type"},
            status_code=400,
        )

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{SK_ENV_URL}/oauth/token",
            data=params,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if resp.status_code != 200:
        logger.error("Token exchange failed: %s %s", resp.status_code, resp.text)
        return JSONResponse(
            {"error": "token_exchange_failed", "detail": resp.text},
            status_code=resp.status_code,
        )

    return JSONResponse(resp.json())


@mcp.custom_route("/oauth/callback", methods=["GET"])
async def oauth_callback(request: Request) -> HTMLResponse:
    error = request.query_params.get("error")
    if error:
        return HTMLResponse(
            f"<html><body><h1>Auth Failed</h1><p>{error}</p></body></html>",
            status_code=400,
        )
    return HTMLResponse("""
    <html><head><title>Authenticated</title></head>
    <body style="font-family:system-ui;text-align:center;padding:3rem">
    <h1>Authentication Successful</h1>
    <p>You can close this window.</p>
    <script>setTimeout(()=>window.close(),2000)</script>
    </body></html>
    """)


@mcp.custom_route("/mcp-metadata", methods=["GET"])
async def mcp_metadata(request: Request) -> JSONResponse:
    return JSONResponse({
        "name": "Do-It Agent MCP",
        "version": "1.0.0",
        "description": "Slack, Calendar, Gmail MCP Server with ScaleKit OAuth",
        "capabilities": {"tools": True, "resources": False, "prompts": False},
        "authentication": {
            "type": "oauth2",
            "authorizationUrl": f"{PUBLIC_URL}/oauth/authorize",
            "tokenUrl": f"{PUBLIC_URL}/oauth/token",
            "registrationUrl": f"{PUBLIC_URL}/register",
            "scopes": ["gmail:read", "slack:write", "calendar:read", "calendar:write"],
        },
        "discoveryUrl": f"{PUBLIC_URL}/.well-known/oauth-protected-resource",
    })


# =====================================================================
# Helper: execute a ScaleKit tool
# =====================================================================

def _execute_tool(tool_name: str, tool_input: dict) -> dict:
    logger.info("Executing ScaleKit tool: %s", tool_name)
    result = scalekit_client.actions.execute_tool(
        tool_name=tool_name,
        identifier=IDENTIFIER,
        tool_input=tool_input,
    )
    logger.info("Tool %s executed successfully", tool_name)
    return result


def _ensure_connected(connection_name: str) -> dict:
    response = scalekit_client.actions.get_or_create_connected_account(
        connection_name=connection_name,
        identifier=IDENTIFIER,
    )
    account = response.connected_account
    if account.status != "ACTIVE":
        link_response = scalekit_client.actions.get_authorization_link(
            connection_name=connection_name,
            identifier=IDENTIFIER,
        )
        return {"connected": False, "link": link_response.link}
    return {"connected": True}


# =====================================================================
# MCP Tools
# =====================================================================

@mcp.tool()
def send_slack_message(text: str) -> str:
    """Send a message to the #social Slack channel."""
    status = _ensure_connected("slack")
    if not status["connected"]:
        return f"Slack not authorized. Authorize here: {status['link']}"
    result = _execute_tool("slack_send_message", {
        "channel": "#social",
        "text": text,
    })
    return json.dumps(result, default=str)


@mcp.tool()
def create_calendar_event(
    title: str,
    start_time: str,
    duration_minutes: int = 30,
    description: str = "",
    timezone: str = "America/Los_Angeles",
) -> str:
    """Create a Google Calendar event.

    Args:
        title: Event title/summary.
        start_time: Start time in RFC3339 format (e.g. 2026-03-28T14:00:00-07:00).
        duration_minutes: Duration in minutes (default 30).
        description: Optional event description.
        timezone: IANA timezone (default America/Los_Angeles).
    """
    status = _ensure_connected("googlecalendar")
    if not status["connected"]:
        return f"Google Calendar not authorized. Authorize here: {status['link']}"
    tool_input = {
        "summary": title,
        "start_datetime": start_time,
        "event_duration_minutes": duration_minutes,
        "timezone": timezone,
    }
    if description:
        tool_input["description"] = description
    result = _execute_tool("googlecalendar_create_event", tool_input)
    return json.dumps(result, default=str)


@mcp.tool()
def list_calendar_events(
    max_results: int = 5,
    time_min: str = "",
) -> str:
    """List upcoming Google Calendar events.

    Args:
        max_results: Maximum number of events to return (default 5).
        time_min: Optional start time filter in RFC3339 format.
    """
    status = _ensure_connected("googlecalendar")
    if not status["connected"]:
        return f"Google Calendar not authorized. Authorize here: {status['link']}"
    tool_input = {"max_results": max_results}
    if time_min:
        tool_input["time_min"] = time_min
    result = _execute_tool("googlecalendar_list_events", tool_input)
    return json.dumps(result, default=str)


@mcp.tool()
def fetch_emails(
    query: str = "is:unread",
    max_results: int = 5,
) -> str:
    """Fetch emails from Gmail.

    Args:
        query: Gmail search query (default "is:unread").
        max_results: Maximum number of emails to fetch (default 5).
    """
    status = _ensure_connected("gmail")
    if not status["connected"]:
        return f"Gmail not authorized. Authorize here: {status['link']}"
    result = _execute_tool("gmail_fetch_mails", {
        "query": query,
        "max_results": max_results,
    })
    return json.dumps(result, default=str)


# =====================================================================
# Entry point
# =====================================================================

if __name__ == "__main__":
    import uvicorn
    from starlette.middleware.base import BaseHTTPMiddleware

    INTERNAL_HEADER = "x-auto-init"

    class AutoInitMiddleware(BaseHTTPMiddleware):
        """Auto-initialize MCP sessions for clients that skip the handshake."""

        async def dispatch(self, request, call_next):
            if (
                request.url.path != "/mcp"
                or request.method != "POST"
                or INTERNAL_HEADER in request.headers
            ):
                return await call_next(request)

            body = await request.body()
            try:
                data = json.loads(body)
            except Exception:
                return await self._forward(request, body, call_next)

            method = data.get("method", "")
            session_id = request.headers.get("mcp-session-id")

            if method == "initialize" or session_id:
                return await self._forward(request, body, call_next)

            logger.info("Auto-init: client sent '%s' without session, injecting initialize handshake", method)
            base = f"http://127.0.0.1:{PORT}"
            hdrs = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                INTERNAL_HEADER: "1",
            }

            async with httpx.AsyncClient() as client:
                init_resp = await client.post(
                    f"{base}/mcp",
                    json={
                        "jsonrpc": "2.0", "id": 0, "method": "initialize",
                        "params": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "clientInfo": {"name": "auto-init-proxy", "version": "1.0"},
                        },
                    },
                    headers=hdrs,
                )
                sid = init_resp.headers.get("mcp-session-id")
                if not sid:
                    logger.error("Auto-init: failed to get session ID: %s", init_resp.text[:200])
                    return await self._forward(request, body, call_next)

                logger.info("Auto-init: got session %s", sid)
                hdrs["mcp-session-id"] = sid

                await client.post(
                    f"{base}/mcp",
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    headers=hdrs,
                )

                resp = await client.post(
                    f"{base}/mcp",
                    content=body,
                    headers=hdrs,
                )

            resp_headers = {
                k: v for k, v in resp.headers.items()
                if k.lower() not in ("transfer-encoding", "content-encoding", "content-length")
            }
            resp_headers["mcp-session-id"] = sid
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=resp_headers,
                media_type=resp.headers.get("content-type"),
            )

        async def _forward(self, request, body, call_next):
            scope = request.scope
            async def receive():
                return {"type": "http.request", "body": body}
            request = Request(scope, receive)
            return await call_next(request)

    logger.info("Starting MCP server on port %d", PORT)
    logger.info("Public URL: %s", PUBLIC_URL)
    logger.info("MCP endpoint: %s/mcp", PUBLIC_URL)
    logger.info("ScaleKit env: %s", SK_ENV_URL)

    app = mcp.http_app(transport="streamable-http")
    app.add_middleware(AutoInitMiddleware)
    uvicorn.run(app, host="0.0.0.0", port=PORT)
