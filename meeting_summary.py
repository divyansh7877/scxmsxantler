"""Shared meeting-summary pipeline: MeetStream audio -> AssemblyAI transcription -> Minimax summarization."""

import os
import logging

import assemblyai as aai
import requests
from openai import OpenAI

logger = logging.getLogger("meeting-summary")

MEETSTREAM_API_KEY = os.getenv("MEET_STREAM_API_KEY")
MEETSTREAM_BASE_URL = "https://api.meetstream.ai/api/v1"
ASSEMBLYAI_API_KEY = os.getenv("ASSEMBLYAI_API_KEY")
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY")
MINIMAX_MODEL = os.getenv("MINIMAX_MODEL", "MiniMax-M2.5")

aai.settings.api_key = ASSEMBLYAI_API_KEY

_minimax_client = None

SUMMARY_SYSTEM_PROMPT = (
    "You are a meeting notes assistant. Given a meeting transcript, "
    "produce a concise summary with:\n"
    "1. **Meeting Overview** - one paragraph summary\n"
    "2. **Key Discussion Points** - bullet list\n"
    "3. **Action Items** - bullet list with owners if mentioned\n"
    "4. **Decisions Made** - bullet list\n"
    "Keep it concise and professional."
)


def _get_minimax_client() -> OpenAI:
    global _minimax_client
    if _minimax_client is None:
        _minimax_client = OpenAI(
            api_key=MINIMAX_API_KEY,
            base_url="https://api.minimax.io/v1",
        )
    return _minimax_client


def fetch_bot_audio_url(bot_id: str) -> str:
    """Get the pre-signed audio URL from MeetStream for a given bot."""
    resp = requests.get(
        f"{MEETSTREAM_BASE_URL}/bots/{bot_id}/audio",
        headers={"Authorization": f"Token {MEETSTREAM_API_KEY}"},
    )
    resp.raise_for_status()
    audio_url = resp.json().get("audio_url")
    if not audio_url:
        raise ValueError(f"No audio_url returned for bot {bot_id}")
    logger.info("[AUDIO] Got audio URL for bot %s", bot_id)
    return audio_url


def transcribe_audio(audio_url: str) -> str:
    """Transcribe audio using AssemblyAI from a URL."""
    logger.info("[TRANSCRIBE] Starting AssemblyAI transcription...")
    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(audio_url)

    if transcript.status == aai.TranscriptStatus.error:
        raise RuntimeError(f"AssemblyAI transcription failed: {transcript.error}")

    logger.info("[TRANSCRIBE] Transcription complete (%d chars)", len(transcript.text))
    return transcript.text


def summarize_transcript(transcript_text: str) -> str:
    """Use Minimax to generate a meeting summary from the transcript."""
    logger.info("[SUMMARY] Generating meeting summary with Minimax (%s)...", MINIMAX_MODEL)
    response = _get_minimax_client().chat.completions.create(
        model=MINIMAX_MODEL,
        messages=[
            {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": transcript_text},
        ],
    )
    summary = response.choices[0].message.content
    logger.info("[SUMMARY] Summary generated successfully")
    return summary


def generate_meeting_summary(bot_id: str) -> dict:
    """Full pipeline: fetch audio -> transcribe -> summarize. Returns dict with transcript and summary."""
    logger.info("[SUMMARY] Starting pipeline for bot %s", bot_id)
    audio_url = fetch_bot_audio_url(bot_id)
    transcript_text = transcribe_audio(audio_url)
    summary = summarize_transcript(transcript_text)
    return {
        "bot_id": bot_id,
        "transcript_length": len(transcript_text),
        "transcript": transcript_text,
        "summary": summary,
    }
