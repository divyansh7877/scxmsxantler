import os
import json
import logging
import threading

from dotenv import load_dotenv
from flask import Flask, request, jsonify
from openai import OpenAI

from scalekit_client import (
    ensure_connected,
    create_calendar_event,
    fetch_emails,
    send_slack_message,
    CONNECTION_GMAIL,
    CONNECTION_CALENDAR,
    CONNECTION_SLACK,
)
from meeting_summary import generate_meeting_summary

load_dotenv()
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("do-it-agent")

MEETSTREAM_API_KEY = os.getenv("MEET_STREAM_API_KEY")
MEETSTREAM_BASE_URL = "https://api.meetstream.ai/api/v1"
SUMMARY_SLACK_CHANNEL = os.getenv("SUMMARY_SLACK_CHANNEL", "#social")

_openai_client = None


def _get_openai():
    global _openai_client
    if _openai_client is None:
        logger.info("Initializing OpenAI client")
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
            "name": "fetch_emails",
            "description": (
                "Fetch emails from Gmail. Use when someone says "
                "'check my emails', 'read my inbox', 'any new emails', "
                "'show unread messages', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Gmail search query, e.g. 'is:unread', 'from:boss@company.com', 'subject:meeting'",
                        "default": "is:unread",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Max number of emails to fetch",
                        "default": 5,
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_slack_message",
            "description": (
                "Send a message to a Slack channel. Use when someone says "
                "'send a message to slack', 'notify the team', 'post in channel', "
                "'alert the team on slack', 'message the channel', etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {
                        "type": "string",
                        "description": "Slack channel name (e.g. '#general', '#engineering') or channel ID",
                    },
                    "text": {
                        "type": "string",
                        "description": "The message text to send",
                    },
                },
                "required": ["channel", "text"],
            },
        },
    },
]

SYSTEM_PROMPT = (
    "You are an AI meeting assistant that listens to live meeting transcriptions. "
    "When participants request actions like scheduling meetings or checking emails, "
    "call the appropriate tool with the extracted parameters. "
    "If the transcription does not contain an actionable request, respond with "
    "a short JSON: {\"action\": \"none\"}. "
    "For relative dates like 'tomorrow' or 'next Tuesday', resolve them relative to "
    "the current date and use America/Los_Angeles timezone by default. "
    "Today's date is 2026-03-28."
)


def detect_and_execute(transcription_text: str) -> dict | None:
    """Feed transcription into OpenAI, detect intents, execute actions."""
    logger.debug(f"[INTENT] Sending to OpenAI: {transcription_text[:300]}")
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
    logger.debug(f"[INTENT] OpenAI response: tool_calls={message.tool_calls is not None}, content={message.content[:200] if message.content else 'None'}")

    if not message.tool_calls:
        logger.info("[INTENT] No action detected in transcription")
        return None

    results = []
    for tool_call in message.tool_calls:
        fn_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)
        logger.info(f"[ACTION] Detected: {fn_name}")
        logger.debug(f"[ACTION] Args: {json.dumps(args, indent=2)}")

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
                logger.info(f"[ACTION] Calendar event created: {args['title']}")
                logger.debug(f"[ACTION] Calendar result: {result}")
                results.append({"action": "schedule_meeting", "result": str(result)})

            elif fn_name == "fetch_emails":
                logger.info(f"[ACTION] Fetching emails: query={args.get('query', 'is:unread')}")
                result = fetch_emails(
                    query=args.get("query", "is:unread"),
                    max_results=args.get("max_results", 5),
                )
                logger.info(f"[ACTION] Emails fetched successfully")
                logger.debug(f"[ACTION] Email result: {result}")
                results.append({"action": "fetch_emails", "result": str(result)})

            elif fn_name == "send_slack_message":
                logger.info(f"[ACTION] Sending Slack message to {args['channel']}")
                result = send_slack_message(
                    channel=args["channel"],
                    text=args["text"],
                )
                logger.info(f"[ACTION] Slack message sent to {args['channel']}")
                logger.debug(f"[ACTION] Slack result: {result}")
                results.append({"action": "send_slack_message", "result": str(result)})

        except Exception as e:
            logger.error(f"[ACTION] Failed to execute {fn_name}: {e}", exc_info=True)
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


def _generate_and_post_summary(bot_id: str, channel: str = "") -> dict:
    """End-to-end: fetch audio -> transcribe -> summarize -> post to Slack."""
    channel = channel or SUMMARY_SLACK_CHANNEL
    result = generate_meeting_summary(bot_id)

    slack_message = f":memo: *Meeting Summary* (bot `{bot_id}`)\n\n{result['summary']}"
    slack_result = send_slack_message(channel=channel, text=slack_message)
    logger.info(f"[SUMMARY] Posted meeting summary to {channel}")

    result["slack_result"] = str(slack_result)
    return result


app = Flask(__name__)


def startup_auth_check():
    """Verify Scalekit connections on startup. Non-fatal if credentials missing."""
    print("\nChecking Scalekit connections...")
    try:
        for conn in [CONNECTION_GMAIL, CONNECTION_CALENDAR, CONNECTION_SLACK]:
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
        logger.warning("[WEBHOOK] Received empty payload")
        return "", 200

    event = data.get("event", "")
    bot_id = data.get("bot_id", "unknown")
    logger.info(f"[WEBHOOK] Event: {event} | Bot: {bot_id}")
    logger.debug(f"[WEBHOOK] Full payload: {json.dumps(data, indent=2)}")

    if event == "audio.processed" and data.get("status") == "success":
        logger.info(f"[WEBHOOK] Audio ready, generating summary for {bot_id}")
        thread = threading.Thread(
            target=_safe_generate_and_post_summary, args=(bot_id,), daemon=True
        )
        thread.start()
        return "", 200

    if not event.startswith("transcription."):
        logger.debug(f"[WEBHOOK] Ignoring non-transcription event: {event}")
        return "", 200

    # Extract transcription text from the webhook payload
    transcription_text = data.get("data", {}).get("transcript", "")
    if not transcription_text:
        transcription_text = data.get("transcript", "")
    if not transcription_text:
        transcription_text = json.dumps(data.get("data", {}))

    logger.info(f"[TRANSCRIPT] Bot {bot_id}: {transcription_text[:300]}")

    results = detect_and_execute(transcription_text)
    if results:
        logger.info(f"[RESULT] Actions executed for bot {bot_id}: {json.dumps(results, indent=2)}")
    else:
        logger.debug(f"[RESULT] No actions for this transcription")

    return "", 200


def _safe_generate_and_post_summary(bot_id: str):
    """Wrapper that catches exceptions so the background thread doesn't crash."""
    try:
        _generate_and_post_summary(bot_id)
    except Exception as e:
        logger.error(f"[SUMMARY] Failed to generate summary for bot {bot_id}: {e}", exc_info=True)


@app.route("/summary/<bot_id>", methods=["POST"])
def trigger_summary(bot_id: str):
    """Manually trigger a meeting summary for a given bot_id."""
    channel = request.args.get("channel", SUMMARY_SLACK_CHANNEL)
    try:
        result = _generate_and_post_summary(bot_id, channel=channel)
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"[SUMMARY] Manual trigger failed for bot {bot_id}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return "OK", 200


if __name__ == "__main__":
    startup_auth_check()
    app.run(port=8999, debug=True)
