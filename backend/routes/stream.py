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
            try:
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
                    log.warning("ts=%.2f: no scene description (vision returned empty)", ts)
                    await ws.send_text(json.dumps({
                        "type": "commentary", "text": "...", "language": language, "timestamp": ts,
                    }))
                    continue

                line = await pipeline.commentate(scene=scene, language=language)
                if not line:
                    log.warning("ts=%.2f: no commentary (LLM returned empty)", ts)
                    await ws.send_text(json.dumps({
                        "type": "commentary", "text": "...", "language": language, "timestamp": ts,
                    }))
                    continue

                log.info("ts=%.2f → %s", ts, line[:80])
                await ws.send_text(json.dumps({
                    "type": "commentary",
                    "text": line,
                    "language": language,
                    "timestamp": ts,
                }))

                # TTS streaming runs concurrently — don't block the next frame.
                asyncio.create_task(_stream_tts(ws, tts, line, language, ts))

            except WebSocketDisconnect:
                raise
            except Exception as e:
                log.exception("frame processing failed: %s", e)
                # Keep the session alive — emit a placeholder so the cue resolves.
                try:
                    await ws.send_text(json.dumps({
                        "type": "commentary", "text": "...", "language": language,
                        "timestamp": msg.get("timestamp", 0.0) if isinstance(msg, dict) else 0.0,
                    }))
                except Exception:
                    pass

    except WebSocketDisconnect:
        log.info("ws disconnected")


async def _stream_tts(
    ws: WebSocket,
    tts: GeminiLiveTTS,
    text: str,
    language: str,
    timestamp: float,
) -> None:
    try:
        async for chunk, mime in tts.synthesize(text, language=language):
            await ws.send_text(json.dumps({
                "type": "audio",
                "data": base64.b64encode(chunk).decode(),
                "mime": mime,
                "timestamp": timestamp,
            }))
    except Exception as e:
        log.warning("tts failed: %s", e)
