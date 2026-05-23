"""Commentary LLM client — Gemma 4 31B on GMI Cloud.

Three sponsors hit in one call: Gemma (model), GMI Cloud (host), NVIDIA (GPUs).

Misnamed file (legacy of when this wrapped RocketRide). Same public interface:
`CommentaryPipeline.start / .stop / .commentate(...)`.

Two modes:
  • "game"  — react to what's happening on the pitch (the original behavior)
  • "chat"  — react sarcastically to a fan comment during a lull
"""

import json
import logging
import os
from typing import Any, Literal

import httpx

log = logging.getLogger(__name__)

_BASE_URL = os.getenv("GMI_BASE_URL", "https://api.gmi-serving.com/v1")
_MODEL = os.getenv("GMI_MODEL", "google/gemma-4-31b-it")

_SYSTEM = (
    "You are a sarcastic, witty World Cup soccer commentator — dry, theatrical, "
    "Peter Drury crossed with Anthony Bourdain.\n\n"
    "You will receive JSON describing the moment. The `mode` field tells you "
    "what to do:\n\n"
    "  mode='game'  — comment on the action. Use `scene`, `event`, `score`, and "
    "`recent_events` to keep narrative continuity. React to score changes.\n\n"
    "  mode='chat'  — the pitch is in a lull. React sarcastically to the fan "
    "comment in `comment.text` from `comment.author`. Punch up at the take, "
    "not at the person. You can briefly tie it back to the game if relevant.\n\n"
    "ALWAYS:\n"
    "  • ONE line. 1–2 sentences. Max 25 words.\n"
    "  • Sarcastic, not mean. Roast decisions, not identities.\n"
    "  • Write NATIVELY in the requested `language`. No translation from English.\n"
    "  • No speaker tags, no stage directions, no quotes, no preamble. Output "
    "    only the spoken line."
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

    async def commentate(
        self,
        scene: str,
        language: str = "en",
        event: str = "buildup",
        score: dict | None = None,
        recent_events: list[dict] | None = None,
        mode: Literal["game", "chat"] = "game",
        comment: dict | None = None,
    ) -> str | None:
        if not self._client:
            return None

        payload: dict[str, Any] = {
            "mode": mode,
            "scene": scene,
            "event": event,
            "score": score or {},
            "recent_events": recent_events or [],
            "language": language,
        }
        if comment is not None:
            payload["comment"] = comment

        try:
            resp = await self._client.post(
                "/chat/completions",
                json={
                    "model": _MODEL,
                    "messages": [
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": json.dumps(payload)},
                    ],
                    "max_tokens": int(os.getenv("COMMENTARY_MAX_TOKENS", "80")),
                    "temperature": 0.85,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip() or None
        except httpx.HTTPStatusError as e:
            log.warning("GMI %s: %s", e.response.status_code, e.response.text[:200])
            return None
        except Exception as e:
            log.warning("GMI call failed: %s", e)
            return None
