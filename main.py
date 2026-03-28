import os
import json
import logging

from dotenv import load_dotenv
from flask import Flask, request
from openai import OpenAI

from scalekit_client import (
    ensure_connected,
    create_calendar_event,
    send_email,
    CONNECTION_GMAIL,
    CONNECTION_CALENDAR,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MEETSTREAM_API_KEY = os.getenv("MEET_STREAM_API_KEY")
MEETSTREAM_BASE_URL = "https://api.meetstream.ai/api/v1"

_openai_client = None


def _get_openai():
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai_client

# OpenAI function calling tools for intent detection
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "schedule_meeting",
            "description": (
                "Schedule a Google Calendar event. Use when someone says "
                "'schedule a meeting', 'set up a call', 'book a follow-up', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Event title"},
                    "start_time": {
                        "type": "string",
                        "description": "Start time in RFC3339 format, e.g. 2026-03-28T14:00:00-07:00",
                    },
                    "duration_minutes": {
                        "type": "integer",
                        "description": "Duration in minutes",
                        "default": 30,
                    },
                    "attendees": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Attendee email addresses",
                    },
                    "description": {"type": "string", "description": "Event description"},
                    "timezone": {
                        "type": "string",
                        "description": "IANA timezone, e.g. America/Los_Angeles",
                        "default": "America/Los_Angeles",
                    },
                },
                "required": ["title", "start_time"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": (
                "Send an email via Gmail. Use when someone says "
                "'send an email to', 'email them about', 'write to', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject line"},
                    "body": {"type": "string", "description": "Email body text"},
                },
                "required": ["to", "subject", "body"],
            },
        },
    },
]

SYSTEM_PROMPT = (
    "You are an AI meeting assistant that listens to live meeting transcriptions. "
    "When participants request actions like scheduling meetings or sending emails, "
    "call the appropriate tool with the extracted parameters. "
    "If the transcription does not contain an actionable request, respond with "
    "a short JSON: {\"action\": \"none\"}. "
    "For relative dates like 'tomorrow' or 'next Tuesday', resolve them relative to "
    "the current date and use America/Los_Angeles timezone by default. "
    "Today's date is 2026-03-28."
)


def detect_and_execute(transcription_text: str) -> dict | None:
    """Feed transcription into OpenAI, detect intents, execute actions."""
    try:
        response = _get_openai().chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": transcription_text},
            ],
            tools=TOOLS,
            tool_choice="auto",
        )
    except Exception as e:
        logger.error(f"OpenAI API error: {e}")
        return None

    message = response.choices[0].message

    if not message.tool_calls:
        logger.info("No action detected in transcription")
        return None

    results = []
    for tool_call in message.tool_calls:
        fn_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        logger.info(f"Detected action: {fn_name} with args: {args}")

        try:
            if fn_name == "schedule_meeting":
                result = create_calendar_event(
                    summary=args["title"],
                    start_datetime=args["start_time"],
                    duration_minutes=args.get("duration_minutes", 30),
                    attendees_emails=args.get("attendees"),
                    description=args.get("description"),
                    timezone=args.get("timezone", "America/Los_Angeles"),
                )
                results.append({"action": "schedule_meeting", "result": str(result)})
                print(f"\n  Calendar event created: {args['title']}\n")

            elif fn_name == "send_email":
                result = send_email(
                    to=args["to"],
                    subject=args["subject"],
                    body=args["body"],
                )
                results.append({"action": "send_email", "result": str(result)})
                print(f"\n  Email sent to {args['to']}: {args['subject']}\n")

        except Exception as e:
            logger.error(f"Failed to execute {fn_name}: {e}")
            results.append({"action": fn_name, "error": str(e)})

    return results


def get_bot_details(bot_id: str) -> dict:
    """Fetch bot metadata from MeetStream."""
    import requests

    resp = requests.get(
        f"{MEETSTREAM_BASE_URL}/bots/{bot_id}/detail",
        headers={"Authorization": f"Token {MEETSTREAM_API_KEY}"},
    )
    resp.raise_for_status()
    return resp.json().get("bot_details", {})


app = Flask(__name__)


def startup_auth_check():
    """Verify Scalekit connections on startup. Non-fatal if credentials missing."""
    print("\nChecking Scalekit connections...")
    try:
        for conn in [CONNECTION_GMAIL, CONNECTION_CALENDAR]:
            result = ensure_connected(conn)
            if result["status"] != "ACTIVE":
                print(f"  WARNING: {conn} needs authorization -- visit the link above")
    except Exception as e:
        print(f"  Scalekit auth check failed: {e}")
        print("  Set credentials in .env and restart to enable actions.\n")
    print()


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True)
    if not data:
        return "", 200

    event = data.get("event", "")
    logger.info(f"Webhook event: {event}")

    if not event.startswith("transcription."):
        return "", 200

    # Extract transcription text from the webhook payload
    transcription_text = data.get("data", {}).get("transcript", "")
    if not transcription_text:
        # Try alternative payload shapes
        transcription_text = data.get("transcript", "")
    if not transcription_text:
        transcription_text = json.dumps(data.get("data", {}))

    bot_id = data.get("bot_id", "unknown")
    logger.info(f"Transcription from bot {bot_id}: {transcription_text[:200]}")

    results = detect_and_execute(transcription_text)
    if results:
        print(
            "\n"
            "=" * 50 + "\n"
            f"  Actions executed for bot {bot_id}:\n"
            f"  {json.dumps(results, indent=2)}\n"
            "=" * 50 + "\n"
        )

    return "", 200


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":
    startup_auth_check()
    app.run(port=8999, debug=True)
