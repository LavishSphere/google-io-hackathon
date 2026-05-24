"""WebSocket route — orchestrates triage → scoring → dispatch.

Per frame:
  1. Triage (Gemini Vision JSON) → intensity + signals + hard events + scene
  2. Score the best chat candidate in the sliding window (C)
  3. Scoring state machine combines G + C → Decision (mode, speak?)
  4. If `speak`: route to game commentary or chat reaction (Gemini 3.1 Flash Lite)
  5. Stream TTS audio chunks tagged with the cue timestamp
  6. Emit `score`, `scoring`, `chat_comment`, `commentary`/`chat_reaction`, `skip`

Most state is per-connection (one `MatchContext` + one `ScoringState` + one
`ChatWindow`) — there's no shared global mutable state.
"""

import asyncio
import base64
import json
import logging
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Deque

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..services.chat_feed import ChatWindow, load_chat_for_clip
from ..services.minimax_tts import MiniMaxTTS
from ..services.roster import (
    Roster,
    format_for_prompt as format_roster_for_prompt,
    get_or_fetch as get_or_fetch_roster,
    roster_to_payload,
)
from ..services.scoring import Mode, ScoringState
from ..services.triage import triage_frame

log = logging.getLogger(__name__)
router = APIRouter()

MAX_RECENT_EVENTS = 4

# How many frames to process in parallel. Each frame is two LLM calls (vision
# triage + commentary), so the practical ceiling is whatever your Gemini RPM
# allows. With free-tier this should stay ≤4; with credits push to 6–10.
FRAME_CONCURRENCY = int(os.getenv("FRAME_CONCURRENCY", "6"))


@dataclass
class MatchContext:
    """Score + recent commentary lines for narrative continuity in the LLM prompt."""
    score: dict[str, int] = field(default_factory=dict)
    recent_events: Deque[dict] = field(default_factory=lambda: deque(maxlen=MAX_RECENT_EVENTS))

    def record_goal(self, team_color: str | None) -> None:
        key = team_color or "team_unknown"
        self.score[key] = self.score.get(key, 0) + 1

    def record_event(self, ts: float, event: str, line: str) -> None:
        self.recent_events.append({"ts": round(ts, 1), "event": event, "line": line})


@router.websocket("/ws/commentary")
async def commentary_ws(ws: WebSocket) -> None:
    await ws.accept()
    language = "en"
    pipeline = ws.app.state.commentary
    tts = MiniMaxTTS()
    ctx = MatchContext()
    scoring = ScoringState()
    chat: ChatWindow = ChatWindow([])  # populated when client sends config
    roster: Roster | None = None

    # Parallelism plumbing. Frame processing runs as background tasks so the WS
    # receive loop doesn't block on LLM round-trips. The semaphore caps how
    # many LLM calls fly in parallel (Gemini RPM safety). The state lock
    # serializes mutations to scoring + match-context state, which is pure CPU
    # work so contention is negligible. The send lock serializes WebSocket
    # writes — Starlette doesn't guarantee that concurrent send_text calls are
    # safe, and a corrupted JSON write would drop the connection or worse.
    frame_sem = asyncio.Semaphore(FRAME_CONCURRENCY)
    state_lock = asyncio.Lock()
    send_lock = asyncio.Lock()
    in_flight: set[asyncio.Task] = set()

    async def send_json(payload: dict) -> None:
        async with send_lock:
            try:
                await ws.send_text(json.dumps(payload))
            except Exception as e:
                log.debug("ws send dropped: %s", e)

    # Defense-in-depth: skip frames whose timestamp we've already begun
    # processing on THIS WS. Prevents repeat commentary if the frontend
    # double-fires start() or sends a duplicate frame for any reason.
    processed_ts: set[float] = set()

    async def process_frame(msg: dict, ts: float, language_at_send: str) -> None:
        async with frame_sem:
            try:
                triage = await triage_frame(msg["data"])
                if not triage:
                    await _send_skip(send_json, ts, reason="triage_failed")
                    return

                # State mutation + decision (fast, CPU only — safe under lock).
                hard_event_local = any([
                    triage.hard_goal, triage.hard_card, triage.hard_penalty,
                    triage.hard_save, triage.hard_var, triage.hard_injury,
                ])
                async with state_lock:
                    if triage.goal_scored:
                        ctx.record_goal(triage.team_color)
                        try:
                            await send_json({
                                "type": "score", "score": ctx.score, "timestamp": ts,
                            })
                        except Exception:
                            pass

                    candidate = chat.best_candidate(
                        now_ts=ts,
                        scene_text=triage.scene,
                        g_smoothed=scoring.g_smoothed,
                    )
                    c_score = candidate.score if candidate else 0.0
                    decision = scoring.decide(ts=ts, triage=triage, best_comment_score=c_score)
                    score_snapshot = dict(ctx.score)
                    recent_events_snapshot = list(ctx.recent_events)

                # Send the scoring trace (outside the lock).
                try:
                    await send_json({
                        "type": "scoring",
                        "timestamp": ts,
                        "g_raw": round(decision.g_raw, 1),
                        "g_smoothed": round(decision.g_score, 1),
                        "c_score": round(decision.c_score, 1),
                        "priority_game": round(decision.priority_game, 1),
                        "priority_comment": round(decision.priority_comment, 1),
                        "mode": decision.mode.value,
                        "reason": decision.reason,
                        "speak": decision.speak,
                        "event": triage.event.value,
                    })
                except Exception:
                    pass

                if not decision.speak:
                    await _send_skip(send_json, ts, reason=f"silent:{decision.reason}")
                    return

                roster_payload = roster_to_payload(roster)
                visible_numbers_payload = [vn.model_dump() for vn in triage.visible_numbers]

                if decision.mode is Mode.game:
                    line = await pipeline.commentate(
                        mode="game",
                        scene=triage.scene,
                        language=language_at_send,
                        event=triage.event.value,
                        score=score_snapshot,
                        recent_events=recent_events_snapshot,
                        hard_event=hard_event_local,
                        roster=roster_payload,
                        visible_numbers=visible_numbers_payload,
                    )
                    if not line:
                        await _send_skip(send_json, ts, reason="llm_empty")
                        return
                    async with state_lock:
                        ctx.record_event(ts, triage.event.value, line)
                        scoring.record_utterance(ts, Mode.game)
                    log.info(
                        "ts=%.2f COMMENT (imp=%.0f event=%s) → %s",
                        ts, decision.g_score, triage.event.value, line[:80],
                    )
                    await send_json({
                        "type": "commentary",
                        "text": line,
                        "language": language_at_send,
                        "timestamp": ts,
                        "importance": int(decision.g_score),
                        "event": triage.event.value,
                        "source": "game",
                    })
                    asyncio.create_task(_stream_tts(send_json, tts, line, language_at_send, ts))

                else:
                    if not candidate:
                        await _send_skip(send_json, ts, reason="chat_mode_no_candidate")
                        return
                    chosen = candidate.comment
                    await send_json({
                        "type": "chat_comment",
                        "timestamp": ts,
                        "comment": {
                            "ts": chosen.ts, "text": chosen.text, "author": chosen.author,
                            "controversy": chosen.controversy, "reactions": chosen.reactions,
                        },
                        "score_parts": candidate.parts,
                    })
                    line = await pipeline.commentate(
                        mode="chat",
                        scene=triage.scene,
                        language=language_at_send,
                        event=triage.event.value,
                        score=score_snapshot,
                        recent_events=recent_events_snapshot,
                        comment={"text": chosen.text, "author": chosen.author},
                        hard_event=False,
                        roster=roster_payload,
                        visible_numbers=visible_numbers_payload,
                    )
                    if not line:
                        await _send_skip(send_json, ts, reason="llm_empty")
                        return
                    async with state_lock:
                        chat.mark_uttered(chosen)
                        ctx.record_event(ts, "chat_reaction", line)
                        scoring.record_utterance(ts, Mode.chat)
                    await send_json({
                        "type": "chat_reaction",
                        "text": line,
                        "language": language_at_send,
                        "timestamp": ts,
                        "source": "chat",
                        "comment_author": chosen.author,
                        "comment_text": chosen.text,
                    })
                    asyncio.create_task(_stream_tts(send_json, tts, line, language_at_send, ts))

            except WebSocketDisconnect:
                raise
            except Exception as e:
                log.exception("frame processing failed: %s", e)
                try:
                    await _send_skip(send_json, ts, reason="error")
                except Exception:
                    pass

    try:
        async for raw in ws.iter_text():
            try:
                msg = json.loads(raw)
                kind = msg.get("type")

                if kind == "config":
                    language = msg.get("language", "en")
                    clip_id = msg.get("clip_id")
                    match_query = (msg.get("match") or "").strip() or None
                    disable_auto_chat = bool(msg.get("disable_auto_chat", False))
                    if clip_id and not disable_auto_chat:
                        loaded_comments = load_chat_for_clip(clip_id)
                        chat = ChatWindow(loaded_comments)
                        log.info(
                            "ws language=%s clip=%s chat_comments=%d",
                            language, clip_id, len(loaded_comments),
                        )
                        # Push the full feed to the client so it can render
                        # comments at their scheduled ts (Twitch-style).
                        await send_json({
                            "type": "chat_feed",
                            "comments": [
                                {
                                    "ts": c.ts,
                                    "text": c.text,
                                    "author": c.author,
                                    "controversy": c.controversy,
                                    "reactions": c.reactions,
                                }
                                for c in loaded_comments
                            ],
                        })
                    else:
                        chat = ChatWindow([])
                        await send_json({"type": "chat_feed", "comments": []})
                        log.info(
                            "ws language=%s (auto-chat=%s)",
                            language, "off" if disable_auto_chat else "no clip_id",
                        )

                    # Fire-and-forget roster lookup so the WS loop isn't blocked.
                    if clip_id:
                        async def _load_roster(cid: str, mq: str | None) -> None:
                            nonlocal roster
                            await send_json({
                                "type": "roster_status",
                                "state": "loading",
                                "match": mq,
                            })
                            r = await get_or_fetch_roster(cid, mq)
                            roster = r
                            if r:
                                await send_json({
                                    "type": "roster_status",
                                    "state": "ready",
                                    "match": r.match,
                                    "teams": [
                                        {"name": t.name, "kit_color": t.kit_color, "n_players": len(t.players)}
                                        for t in r.teams
                                    ],
                                })
                            else:
                                await send_json({
                                    "type": "roster_status",
                                    "state": "none",
                                    "match": mq,
                                })
                        asyncio.create_task(_load_roster(clip_id, match_query))
                    continue

                if kind == "inject_comment":
                    # Operator-injected comment — bypasses scoring, fires a reaction NOW.
                    inj_text = (msg.get("text") or "").strip()
                    inj_author = msg.get("author") or "@you"
                    inj_ts = float(msg.get("timestamp", 0.0))
                    if not inj_text:
                        continue

                    # Echo the comment so the UI can render the bubble.
                    await send_json({
                        "type": "chat_comment",
                        "timestamp": inj_ts,
                        "manual": True,
                        "comment": {
                            "ts": inj_ts,
                            "text": inj_text,
                            "author": inj_author,
                            "controversy": 1.0,
                            "reactions": 0,
                        },
                        "score_parts": {"manual": True},
                    })

                    line = await pipeline.commentate(
                        mode="chat",
                        scene="(operator-injected fan comment — react directly)",
                        language=language,
                        event="manual_inject",
                        score=ctx.score,
                        recent_events=list(ctx.recent_events),
                        comment={"text": inj_text, "author": inj_author},
                        hard_event=False,
                        roster=roster_to_payload(roster),
                    )
                    if not line:
                        await _send_skip(send_json, inj_ts, reason="llm_empty_inject")
                        continue
                    ctx.record_event(inj_ts, "chat_reaction", line)
                    scoring.record_utterance(inj_ts, Mode.chat)
                    await send_json({
                        "type": "chat_reaction",
                        "text": line,
                        "language": language,
                        "timestamp": inj_ts,
                        "source": "chat",
                        "comment_author": inj_author,
                        "comment_text": inj_text,
                        "manual": True,
                    })
                    asyncio.create_task(_stream_tts(send_json, tts, line, language, inj_ts))
                    continue

                if kind != "frame":
                    continue

                ts = float(msg.get("timestamp", 0.0))
                ts_key = round(ts, 3)
                if ts_key in processed_ts:
                    log.info("ts=%.3f duplicate frame, ignoring", ts_key)
                    continue
                processed_ts.add(ts_key)
                # Fire-and-forget: process this frame in the background so the
                # receive loop can keep accepting frames in parallel.
                task = asyncio.create_task(process_frame(msg, ts, language))
                in_flight.add(task)
                task.add_done_callback(in_flight.discard)

            except WebSocketDisconnect:
                raise
            except Exception as e:
                log.exception("frame processing failed: %s", e)
                try:
                    bad_ts = float(msg.get("timestamp", 0.0) if isinstance(msg, dict) else 0.0)
                    await _send_skip(send_json, bad_ts, reason="error")
                except Exception:
                    pass

    except WebSocketDisconnect:
        log.info("ws disconnected")
    finally:
        # Give any in-flight frame tasks a moment to finish their final WS sends.
        if in_flight:
            try:
                await asyncio.wait(in_flight, timeout=2.0)
            except Exception:
                pass


async def _send_skip(send_json, ts: float, reason: str) -> None:
    await send_json({
        "type": "skip",
        "timestamp": ts,
        "reason": reason,
    })


async def _stream_tts(
    send_json,
    tts: MiniMaxTTS,
    text: str,
    language: str,
    timestamp: float,
) -> None:
    try:
        n = 0
        async for chunk, mime in tts.synthesize(text, language=language):
            n += len(chunk)
            await send_json({
                "type": "audio",
                "data": base64.b64encode(chunk).decode(),
                "mime": mime,
                "timestamp": timestamp,
            })
        log.info("tts ts=%.2f delivered %d bytes", timestamp, n)
    except Exception as e:
        log.warning("tts failed for ts=%.2f: %s", timestamp, e)
        try:
            await send_json({
                "type": "tts_error",
                "timestamp": timestamp,
                "error": str(e)[:200],
            })
        except Exception:
            pass
