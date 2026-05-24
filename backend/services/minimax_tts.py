"""MiniMax TTS via GMI Cloud's async request-queue API.

Flow per `synthesize(text)`:
  1. POST /api/v1/ie/requestqueue/apikey/requests  →  {request_id, status: 'dispatched'}
  2. Poll GET .../requests/{request_id} every POLL_INTERVAL until status='success'
     or 'failed' or POLL_TIMEOUT elapses.
  3. On success, download the MP3 from `outcome.audio_url` and yield it as one
     chunk. (MiniMax returns a complete MP3, not a stream.)

The interface matches GeminiLiveTTS so routes/stream.py can swap implementations
with one import change. Yields `(audio_bytes, mime)` — here always exactly one
tuple with mime='audio/mpeg' since we get the whole file at once.

Voice selection: set MINIMAX_VOICE_ID in .env (e.g. 'English_expressive_narrator').
For voice CLONING use the cloned-voice variant which needs `source_audio` URL;
this client uses plain preset voices.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import AsyncIterator

import httpx

log = logging.getLogger(__name__)

_HOST = os.getenv("MINIMAX_BASE_URL", "https://console.gmicloud.ai")
_MODEL = os.getenv("MINIMAX_TTS_MODEL", "minimax-tts-speech-2.6-hd")
_DEFAULT_VOICE = os.getenv("MINIMAX_VOICE_ID", "English_expressive_narrator")
_POLL_TIMEOUT = float(os.getenv("MINIMAX_POLL_TIMEOUT_S", "30"))
_POLL_INTERVAL = float(os.getenv("MINIMAX_POLL_INTERVAL_S", "1.5"))

# Optional per-language voice override. Add real MiniMax voice IDs as you find
# good ones; falls back to MINIMAX_VOICE_ID for any unmapped language.
_VOICE_BY_LANG: dict[str, str] = {
    "en": _DEFAULT_VOICE,
}


_http: httpx.AsyncClient | None = None


def _get_http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(
            base_url=_HOST,
            headers={
                "Authorization": f"Bearer {os.environ['ROCKETRIDE_GMI_APIKEY']}",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0, connect=5.0),
        )
    return _http


class MiniMaxTTS:
    """Drop-in replacement for GeminiLiveTTS — same `synthesize` signature."""

    async def synthesize(
        self,
        text: str,
        language: str = "en",
    ) -> AsyncIterator[tuple[bytes, str]]:
        if not text.strip():
            return

        http = _get_http()
        voice_id = _VOICE_BY_LANG.get(language, _DEFAULT_VOICE)

        # Step 1 — submit the job.
        try:
            resp = await http.post(
                "/api/v1/ie/requestqueue/apikey/requests",
                json={
                    "model": _MODEL,
                    "payload": {"text": text, "voice_id": voice_id},
                },
            )
            resp.raise_for_status()
            request_id = resp.json().get("request_id")
        except Exception as e:
            log.warning("minimax submit failed: %s", e)
            return

        if not request_id:
            log.warning("minimax submit returned no request_id")
            return

        # Step 2 — poll until success / failed / timeout.
        loop = asyncio.get_event_loop()
        deadline = loop.time() + _POLL_TIMEOUT
        audio_url: str | None = None
        last_status = "?"

        while loop.time() < deadline:
            await asyncio.sleep(_POLL_INTERVAL)
            try:
                poll = await http.get(
                    f"/api/v1/ie/requestqueue/apikey/requests/{request_id}"
                )
                data = poll.json()
            except Exception as e:
                log.warning("minimax poll error: %s", e)
                continue

            last_status = data.get("status", "?")
            if last_status == "success":
                outcome = data.get("outcome", {}) or {}
                # The docs show two shapes; favour audio_url, fall back to media_urls.
                audio_url = outcome.get("audio_url") or (
                    (outcome.get("media_urls") or [{}])[0].get("url")
                )
                break
            if last_status == "failed":
                log.warning("minimax tts failed: %s", data)
                return

        if not audio_url:
            log.warning(
                "minimax tts timed out (req=%s status=%s)", request_id, last_status
            )
            return

        # Step 3 — download the MP3. The audio_url is on storage.googleapis.com
        # and rejects our GMI Bearer header (401), so use a fresh client that
        # doesn't carry the API key.
        try:
            async with httpx.AsyncClient(timeout=20.0) as plain:
                audio_resp = await plain.get(audio_url, follow_redirects=True)
                audio_resp.raise_for_status()
                mp3 = audio_resp.content
        except Exception as e:
            log.warning("minimax download failed: %s", e)
            return

        if not mp3:
            return
        yield mp3, "audio/mpeg"
