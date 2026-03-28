#!/usr/bin/env python3
"""Send a MeetStream bot into a meeting with a webhook callback."""
import os
import sys
import json
import logging
import requests
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("launch-bot")

MEETSTREAM_API_KEY = os.getenv("MEET_STREAM_API_KEY")

if not MEETSTREAM_API_KEY:
    logger.error("MEET_STREAM_API_KEY not set in .env")
    sys.exit(1)

ngrok_url = sys.argv[1] if len(sys.argv) > 1 else input("Enter your ngrok https URL: ").strip()
meeting_link = sys.argv[2] if len(sys.argv) > 2 else input("Enter meeting link: ").strip()

callback_url = f"{ngrok_url.rstrip('/')}/webhook"

payload = {
    "meeting_link": meeting_link,
    "bot_name": "Do-It Agent",
    "callback_url": callback_url,
    "agent_config_id": "4046c44f-57f1-4691-bdb6-ed432cbdcccc",
    "live_transcription_required": {
        "webhook_url": callback_url,
    },
    "automatic_leave": {
        "waiting_room_timeout": 600,
        "everyone_left_timeout": 120,
    },
}

logger.info(f"[BOT] Sending bot to: {meeting_link}")
logger.info(f"[BOT] Webhook callback: {callback_url}")
logger.debug(f"[BOT] Payload:\n{json.dumps(payload, indent=2)}")

resp = requests.post(
    "https://api.meetstream.ai/api/v1/bots/create_bot",
    headers={
        "Authorization": f"Token {MEETSTREAM_API_KEY}",
        "Content-Type": "application/json",
    },
    json=payload,
)

logger.info(f"[BOT] Response status: {resp.status_code}")
logger.info(f"[BOT] Response: {json.dumps(resp.json(), indent=2)}")

if resp.status_code == 201:
    bot_id = resp.json().get("bot_id")
    logger.info(f"[BOT] Bot created successfully! ID: {bot_id}")
    logger.info(f"[BOT] Check status: https://api.meetstream.ai/api/v1/bots/{bot_id}/status")
else:
    logger.error(f"[BOT] Failed to create bot: {resp.text}")
