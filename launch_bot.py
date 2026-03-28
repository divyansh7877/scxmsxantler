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
    "video_required": True,
    "bot_message": "Hey Everyone :wave: , I'm Do-It Agent. I can send Slack messages, read emails, and manage your calendar.",
    "bot_image_url": "https://www.malwarebytes.com/wp-content/uploads/sites/2/2024/08/Grok_logo.jpg",
    "agent_config_id": "4046c44f-57f1-4691-bdb6-ed432cbdcccc",
    "callback_url": callback_url,
    "custom_attributes": {
        "tag": "Meetstream",
        "sample": "testing",
    },
  "socket_connection_url": {
    "websocket_url": "wss://agent-meetstream-prd-main.meetstream.ai/bridge"
  },
  "live_audio_required": {
    "websocket_url": "wss://agent-meetstream-prd-main.meetstream.ai/bridge/audio"
  },
    "automatic_leave": {
        "waiting_room_timeout": 100,
        "everyone_left_timeout": 100,
        "voice_inactivity_timeout": 100,
        "in_call_recording_timeout": 14400,
        "recording_permission_denied_timeout": 60,
    },
    "recording_config": {
        "retention": {
            "type": "timed",
            "hours": 24,
        },
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
