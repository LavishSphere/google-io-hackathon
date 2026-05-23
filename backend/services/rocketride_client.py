"""Direct Google AI Studio (Gemini) client for commentary.

Misnamed file (legacy of when this wrapped RocketRide) — kept to avoid churning
imports in main.py and routes/stream.py. Same public interface:
`CommentaryPipeline.start / .stop / .commentate(scene, language) -> str | None`.
"""

import json
import logging
import os

from google import genai
from google.genai import types

log = logging.getLogger(__name__)

_MODEL = os.getenv("GEMINI_COMMENTARY_MODEL", "gemini-3.1-flash-lite")

_SYSTEM = (
    "You are a sarcastic, witty World Cup soccer commentator with a dry sense of "
    "humor — think Peter Drury crossed with Anthony Bourdain.\n"
    "You will receive a JSON payload describing what just happened in a game "
    "(scene description, players visible, ball position, recent events) plus a "
    "target language code.\n"
    "Reply with ONE short live-commentary line — 1 to 2 sentences, max 25 words.\n"
    "Be sarcastic but not mean. Reference what's actually on screen. Roast the "
    "players' decisions, not their identities.\n"
    "Write the line NATIVELY in the requested language. Do NOT translate from "
    "English — sarcasm dies in translation. Match the rhythm and idioms of that "
    "language.\n"
    "Do not include speaker tags, stage directions, quotes, or any preamble. "
    "Output only the spoken line."
)


class CommentaryPipeline:
    def __init__(self) -> None:
        self._client: genai.Client | None = None

    async def start(self) -> None:
        self._client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        log.info("Gemini client ready (model=%s)", _MODEL)

    async def stop(self) -> None:
        self._client = None

    async def commentate(self, scene: str, language: str = "en") -> str | None:
        if not self._client:
            return None
        try:
            resp = await self._client.aio.models.generate_content(
                model=_MODEL,
                contents=json.dumps({"scene": scene, "language": language}),
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM,
                    temperature=0.85,
                    max_output_tokens=int(os.getenv("COMMENTARY_MAX_TOKENS", "80")),
                ),
            )
            return (resp.text or "").strip() or None
        except Exception as e:
            log.warning("Gemini commentary call failed: %s", e)
            return None
