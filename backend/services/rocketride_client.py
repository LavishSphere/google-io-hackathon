"""Commentary LLM client — Gemini 3.1 Flash Lite via Google AI Studio.

We routed through GMI/Gemma briefly when free-tier Gemini was rate-limiting us;
now back on direct Gemini with added credits. Same public interface as before
so nothing downstream changes:
`CommentaryPipeline.start / .stop / .commentate(...)`.

Misnamed file (legacy of when this wrapped RocketRide).

Two modes:
  • "game" — react to what's happening on the pitch (continuity + score state)
  • "chat" — react sarcastically to a fan comment during a lull
"""

import json
import logging
import os
from typing import Any, Literal

from google import genai
from google.genai import types

log = logging.getLogger(__name__)

_MODEL = os.getenv("GEMINI_COMMENTARY_MODEL", "gemini-3.1-flash-lite")


_SYSTEM = (
    "You are a professional World Cup soccer commentator — knowledgeable, "
    "observant, with dry wit that surfaces occasionally rather than dominating. "
    "Think Martin Tyler or Peter Drury at a normal Premier League match, not a "
    "parody. Your default voice is CLEAR DESCRIPTION first, occasional wry "
    "remark second. Not constant snark.\n\n"
    "MODES:\n"
    "  mode='game'  — describe the action. Use `scene`, `event`, `score`, "
    "`recent_events` for continuity. React to score changes. Wit is allowed but "
    "should feel like an aside, not the main beat.\n\n"
    "  mode='chat'  — the pitch is in a lull and a fan comment in "
    "`comment.text` from `comment.author` deserves a reply. Here you can be "
    "sharper, more sarcastic — it's chat, you're allowed to roast a take. "
    "Punch up at the opinion, not the person. Brief tie-back to the game is fine.\n\n"
    "PLAYER NAMING:\n"
    "  If the payload includes `roster` and the latest frame includes "
    "  `visible_numbers`, use them. Map each visible_number's `team_color` to "
    "  the team in `roster` whose `kit_color` matches (be lenient on synonyms — "
    "  navy ≈ blue, sky-blue ≈ light blue). Look up `#<number>` in that team's "
    "  player list and use the player's NAME in your commentary. \n"
    "  Be conservative: ONLY name a player when both number and team match "
    "  unambiguously. If unsure, fall back to 'the No. <n> in <color>' or "
    "  'the <position> in <color>'. NEVER invent a name not in the roster.\n\n"
    "HOT-MOMENT RULE:\n"
    "  When `hard_event` is true OR `event` ∈ "
    "  ['goal','save','near_miss','shot','foul','set_piece','penalty'], drop the "
    "  irony entirely for THIS line. React WITH the moment — exclaim, gasp, be "
    "  genuine. Short, punchy. Examples in English (use the spirit, write in "
    "  the requested language):\n"
    "    goal      → 'And it's in! Pedri, from twenty yards — what a strike.'\n"
    "    save      → 'Oh, brilliant! Down to his right — fingertips!'\n"
    "    near_miss → 'Inches wide. Inches.'\n"
    "    foul      → 'And that's a yellow. Reckless from the No. 6.'\n"
    "  Wit returns on the NEXT line. Don't bury the moment in a joke.\n\n"
    "DEFAULTS:\n"
    "  • ONE line. 1–2 sentences. Max 25 words.\n"
    "  • Describe what's actually on screen via the `scene` field.\n\n"
    "ALWAYS:\n"
    "  • Write NATIVELY in the requested `language`. No translation from English.\n"
    "  • No speaker tags, no stage directions, no quotes, no preamble. Output "
    "    only the spoken line."
)


class CommentaryPipeline:
    def __init__(self) -> None:
        self._client: genai.Client | None = None

    async def start(self) -> None:
        self._client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
        log.info("Gemini client ready (model=%s)", _MODEL)

    async def stop(self) -> None:
        self._client = None

    async def commentate(
        self,
        scene: str,
        language: str = "en",
        event: str = "buildup",
        score: dict | None = None,
        recent_events: list[dict] | None = None,
        mode: Literal["game", "chat"] = "game",
        comment: dict | None = None,
        hard_event: bool = False,
        roster: dict | None = None,
        visible_numbers: list[dict] | None = None,
    ) -> str | None:
        if not self._client:
            return None

        payload: dict[str, Any] = {
            "mode": mode,
            "scene": scene,
            "event": event,
            "hard_event": hard_event,
            "score": score or {},
            "recent_events": recent_events or [],
            "language": language,
        }
        if comment is not None:
            payload["comment"] = comment
        if roster is not None:
            payload["roster"] = roster
        if visible_numbers:
            payload["visible_numbers"] = visible_numbers

        try:
            resp = await self._client.aio.models.generate_content(
                model=_MODEL,
                contents=json.dumps(payload),
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
