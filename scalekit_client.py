import os
import json
import logging

from dotenv import load_dotenv
from scalekit.client import ScalekitClient

load_dotenv()

logger = logging.getLogger("scalekit")

IDENTIFIER = os.getenv("IDENTIFIER", "hackathon_user_1")
CONNECTION_GMAIL = os.getenv("CONNECTION_NAME_GMAIL", "gmail")
CONNECTION_CALENDAR = os.getenv("CONNECTION_NAME_CALENDAR", "googlecalendar")

_client = None


def _get_actions():
    """Lazy-init the Scalekit client on first use."""
    global _client
    if _client is None:
        env_url = os.getenv("SCALEKIT_ENV_URL")
        client_id = os.getenv("SCALEKIT_CLIENT_ID")
        client_secret = os.getenv("SCALEKIT_CLIENT_SECRET")
        if not all([env_url, client_id, client_secret]):
            raise RuntimeError(
                "Missing Scalekit credentials. Set SCALEKIT_ENV_URL, "
                "SCALEKIT_CLIENT_ID, SCALEKIT_CLIENT_SECRET in .env"
            )
        logger.info("[SCALEKIT] Initializing client with env_url=%s", env_url)
        _client = ScalekitClient(
            env_url=env_url,
            client_id=client_id,
            client_secret=client_secret,
        )
        logger.info("[SCALEKIT] Client initialized successfully")
    return _client.actions


def ensure_connected(connection_name: str) -> dict:
    """Check if a connector is authorized. Prints auth link if not ACTIVE."""
    logger.info(f"[AUTH] Checking connection: {connection_name}")
    try:
        response = _get_actions().get_or_create_connected_account(
            connection_name=connection_name,
            identifier=IDENTIFIER,
        )
    except Exception as e:
        logger.error(f"Error checking connection '{connection_name}': {e}")
        print(
            f"\n  Error: {e}\n"
            f"  Have you created a '{connection_name}' connection in Scalekit?\n"
            f"  app.scalekit.com -> Agent Auth -> Connections -> + Create Connection\n"
        )
        return {"status": "ERROR", "error": str(e)}

    account = response.connected_account

    if account.status != "ACTIVE":
        link_response = _get_actions().get_authorization_link(
            connection_name=connection_name,
            identifier=IDENTIFIER,
        )
        print(f"\n  {connection_name} not authorized (status: {account.status})")
        print(f"  Authorize here: {link_response.link}\n")
        return {"status": "INACTIVE", "link": link_response.link}

    logger.info(f"Connection '{connection_name}' is ACTIVE (id={account.id})")
    print(f"  {connection_name} is ACTIVE (id={account.id})")
    return {"status": "ACTIVE", "id": account.id}


def create_calendar_event(
    summary: str,
    start_datetime: str,
    duration_minutes: int = 30,
    attendees_emails: list[str] | None = None,
    description: str | None = None,
    timezone: str = "America/Los_Angeles",
    create_meeting_room: bool = False,
) -> dict:
    """Create a Google Calendar event via Scalekit optimized tool."""
    tool_input = {
        "summary": summary,
        "start_datetime": start_datetime,
        "event_duration_minutes": duration_minutes,
        "timezone": timezone,
    }
    if attendees_emails:
        tool_input["attendees_emails"] = attendees_emails
    if description:
        tool_input["description"] = description
    if create_meeting_room:
        tool_input["create_meeting_room"] = True

    logger.info(f"[CALENDAR] Creating event: {summary} at {start_datetime}")
    logger.debug(f"[CALENDAR] Tool input: {json.dumps(tool_input, indent=2)}")
    result = _get_actions().execute_tool(
        tool_name="googlecalendar_create_event",
        identifier=IDENTIFIER,
        tool_input=tool_input,
    )
    logger.info(f"[CALENDAR] Event created successfully")
    logger.debug(f"[CALENDAR] Result: {result}")
    return result


def fetch_emails(query: str = "is:unread", max_results: int = 5) -> dict:
    """Fetch emails from Gmail via Scalekit optimized tool."""
    logger.info(f"[GMAIL] Fetching emails: query='{query}', max_results={max_results}")
    result = _get_actions().execute_tool(
        tool_name="gmail_fetch_mails",
        identifier=IDENTIFIER,
        tool_input={"query": query, "max_results": max_results},
    )
    logger.info(f"[GMAIL] Fetched successfully")
    logger.debug(f"[GMAIL] Result: {result}")
    return result
