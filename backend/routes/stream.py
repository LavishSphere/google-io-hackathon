"""WebSocket route: frames in, sarcastic commentary (text + TTS audio) out."""

import asyncio
import base64
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.gemini_live import GeminiLiveTTS
from ..services.gemini_vision import describe_frame

log = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/commentary")
async def commentary_ws(ws: WebSocket) -> None:
    """
    Client protocol (JSON messages):
      → { type: "config", language: "en" | "es" | "hi" | ... }
      → { type: "frame", data: "<base64 jpeg>", timestamp: 12.34 }
      ← { type: "commentary", text: "...", language: "es", timestamp: 12.34 }
      ← { type: "audio", data: "<base64 pcm/opus>", mime: "audio/..." }
    """
    await ws.accept()
    language = "en"
    pipeline = ws.app.state.commentary
    tts = GeminiLiveTTS()

    try:
        async for raw in ws.iter_text():
            msg = json.loads(raw)
            kind = msg.get("type")

            if kind == "config":
                language = msg.get("language", "en")
                log.info("ws language=%s", language)
                continue

            if kind != "frame":
                continue

            frame_b64 = msg["data"]
            ts = msg.get("timestamp", 0.0)

            scene = await describe_frame(frame_b64)
            if not scene:
                continue

            line = await pipeline.commentate(scene=scene, language=language)
            if not line:
                continue

            await ws.send_text(json.dumps({
                "type": "commentary",
                "text": line,
                "language": language,
                "timestamp": ts,
            }))

            # TTS streaming runs concurrently — don't block the next frame.
            asyncio.create_task(_stream_tts(ws, tts, line, language))

    except WebSocketDisconnect:
        log.info("ws disconnected")


async def _stream_tts(ws: WebSocket, tts: GeminiLiveTTS, text: str, language: str) -> None:
    try:
        async for chunk, mime in tts.synthesize(text, language=language):
            await ws.send_text(json.dumps({
                "type": "audio",
                "data": base64.b64encode(chunk).decode(),
                "mime": mime,
            }))
    except Exception as e:
        log.warning("tts failed: %s", e)
