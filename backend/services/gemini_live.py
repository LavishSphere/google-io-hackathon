"""Gemini Live → streamed TTS audio for the commentary line.

Yields (audio_chunk_bytes, mime) tuples as Gemini emits them.
"""

import logging
import os
from typing import AsyncIterator

from google import genai
from google.genai import types

log = logging.getLogger(__name__)

_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-live-2.5-flash-preview")

_VOICE_BY_LANG = {
    "en": "Puck",
    "es": "Charon",
    "hi": "Kore",
    "pt": "Fenrir",
    "fr": "Aoede",
    "ar": "Charon",
}


class GeminiLiveTTS:
    def __init__(self) -> None:
        self._client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])

    async def synthesize(self, text: str, language: str = "en") -> AsyncIterator[tuple[bytes, str]]:
        voice = _VOICE_BY_LANG.get(language, "Puck")
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice)
                )
            ),
        )

        async with self._client.aio.live.connect(model=_MODEL, config=config) as session:
            await session.send_client_content(
                turns={"role": "user", "parts": [{"text": f"Read aloud, in character: {text}"}]},
                turn_complete=True,
            )
            async for response in session.receive():
                data = getattr(response, "data", None)
                if data:
                    yield data, "audio/pcm;rate=24000"
