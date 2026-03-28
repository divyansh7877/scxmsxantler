#!/usr/bin/env python3
"""Send a MeetStream bot into a meeting with a webhook callback."""
import os
import sys
import requests
from dotenv import load_dotenv

load_dotenv()

MEETSTREAM_API_KEY = os.getenv("MEET_STREAM_API_KEY")

if not MEETSTREAM_API_KEY:
    print("Error: MEET_STREAM_API_KEY not set in .env")
    sys.exit(1)

ngrok_url = sys.argv[1] if len(sys.argv) > 1 else input("Enter your ngrok https URL: ").strip()
meeting_link = sys.argv[2] if len(sys.argv) > 2 else input("Enter meeting link: ").strip()

callback_url = f"{ngrok_url.rstrip('/')}/webhook"

payload = {
    "meeting_link": meeting_link,
    "bot_name": "Do-It Agent",
    "video_required": False,
    "callback_url": callback_url,
    "recording_config": {
        "transcript": {
            "provider": {
                "deepgram": {
                    "model": "nova-2",
                    "smart_format": True,
                }
            }
        }
    },
    "automatic_leave": {
        "waiting_room_timeout": 600,
        "everyone_left_timeout": 120,
    },
}

print(f"Sending bot to: {meeting_link}")
print(f"Webhook callback: {callback_url}")

resp = requests.post(
    "https://api.meetstream.ai/api/v1/bots/create_bot",
    headers={
        "Authorization": f"Token {MEETSTREAM_API_KEY}",
        "Content-Type": "application/json",
    },
    json=payload,
)

print(f"Status: {resp.status_code}")
print(resp.json())
