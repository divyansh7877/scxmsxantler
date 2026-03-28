import os
import logging
import base64
from email.mime.text import MIMEText

from dotenv import load_dotenv
from scalekit.client import ScalekitClient

load_dotenv()

logger = logging.getLogger(__name__)

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
        _client = ScalekitClient(
            env_url=env_url,
            client_id=client_id,
            client_secret=client_secret,
        )
    return _client.actions


def ensure_connected(connection_name: str) -> dict:
    """Check if a connector is authorized. Prints auth link if not ACTIVE."""
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

    result = _get_actions().execute_tool(
        tool_name="googlecalendar_create_event",
        identifier=IDENTIFIER,
        tool_input=tool_input,
    )
    logger.info(f"Calendar event created: {result}")
    return result


def send_email(to: str, subject: str, body: str) -> dict:
    """Send email via Gmail. Tries execute_tool first, falls back to proxy."""
    # Try optimized tool first
    try:
        result = _get_actions().execute_tool(
            tool_name="gmail_send_email",
            identifier=IDENTIFIER,
            tool_input={"to": to, "subject": subject, "body": body},
        )
        logger.info(f"Email sent via execute_tool: {result}")
        return result
    except Exception as e:
        logger.warning(f"gmail_send_email tool failed ({e}), falling back to proxy")

    # Fallback: raw proxy with MIME encoding
    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    result = _get_actions().request(
        connection_name=CONNECTION_GMAIL,
        identifier=IDENTIFIER,
        path="/gmail/v1/users/me/messages/send",
        method="POST",
        body={"raw": raw},
    )
    logger.info(f"Email sent via proxy: {result}")
    return result
