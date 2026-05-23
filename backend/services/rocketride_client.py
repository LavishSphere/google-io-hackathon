"""Direct GMI Cloud client — bypasses the RocketRide engine.

Same public interface as the RocketRide-backed version (`CommentaryPipeline.start`,
`.stop`, `.commentate`) so routes/main.py don't need to change. The persona
instructions that used to live in pipelines/commentary.pipe are inlined as the
system prompt below.

When the RocketRide local engine is fixed (or you switch to cloud), revert to
the RocketRide-backed implementation in git history.
"""

import json
import logging
import os
from typing import Any

import httpx

log = logging.getLogger(__name__)

_BASE_URL = os.getenv("GMI_BASE_URL", "https://api.gmi-serving.com/v1")
_MODEL = os.getenv("GMI_MODEL", "google/gemini-3-flash-preview")

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
        self._client: httpx.AsyncClient | None = None
        self._apikey = os.environ["ROCKETRIDE_GMI_APIKEY"]

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=_BASE_URL,
            headers={
                "Authorization": f"Bearer {self._apikey}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(20.0, connect=5.0),
        )
        log.info("GMI Cloud client ready (model=%s)", _MODEL)

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()

    async def commentate(self, scene: str, language: str = "en") -> str | None:
        if not self._client:
            return None

        payload: dict[str, Any] = {
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {
                    "role": "user",
                    "content": json.dumps({"scene": scene, "language": language}),
                },
            ],
            "max_tokens": int(os.getenv("COMMENTARY_MAX_TOKENS", "80")),
            "temperature": 0.85,
        }

        try:
            resp = await self._client.post("/chat/completions", json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip() or None
        except httpx.HTTPStatusError as e:
            log.warning("GMI %s: %s", e.response.status_code, e.response.text[:200])
            return None
        except Exception as e:
            log.warning("GMI call failed: %s", e)
            return None
