"""Frame → terse scene description via Gemini Flash Lite (vision).

Kept deliberately small: the commentary LLM does the witty lift; this step
only produces a neutral observation so we can swap personas without
re-doing vision calls.
"""

import base64
import logging
import os

from google import genai
from google.genai import types

log = logging.getLogger(__name__)

_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-3-flash-lite")
_SYSTEM = (
    "Describe what is happening in this World Cup soccer frame in ONE sentence. "
    "Be factual: who has the ball, where on the pitch, body language, what looks "
    "imminent. No commentary, no opinions, no flourishes. Under 25 words."
)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    return _client


async def describe_frame(frame_b64: str) -> str | None:
    """Return a short factual description of the frame, or None on failure."""
    try:
        jpeg = base64.b64decode(frame_b64)
        resp = await _get_client().aio.models.generate_content(
            model=_MODEL,
            contents=[
                types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
                _SYSTEM,
            ],
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=80,
            ),
        )
        return (resp.text or "").strip() or None
    except Exception as e:
        log.warning("vision failed: %s", e)
        return None
