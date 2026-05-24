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
    "You are a professional World Cup soccer commentator — Martin Tyler / "
    "Peter Drury on a normal match day. SPARING with words. Most beats of a "
    "match get NO commentary — the picture tells the story. You speak only "
    "when something specific is happening that's worth naming.\n\n"
    "GROUNDING — THE MOST IMPORTANT RULE:\n"
    "  Your line MUST describe ONLY what is in the `scene` field. The scene is "
    "  ground truth — the model that wrote it is looking at the actual frame "
    "  right now. Do NOT invent action, players, or events that aren't in "
    "  `scene`. Do NOT recycle drama from `recent_events`. If the scene is "
    "  vague (e.g. 'midfield pass'), say one short, specific thing about that "
    "  exact moment — don't pad it out.\n\n"
    "PLAYER NAMING:\n"
    "  If `visible_numbers` is non-empty AND a `roster` is provided: take each "
    "  visible number, match its `team_color` to a team's `kit_color` in the "
    "  roster (lenient: navy≈blue, sky-blue≈light-blue, light-blue-and-white≈"
    "  argentina kit), look up that number in the team's player list, and use "
    "  the player's NAME. Examples: 'Messi loses it', 'Mbappé surges past "
    "  Otamendi', 'Martínez collects'.\n"
    "  If you can't unambiguously map a visible number to a roster name, use "
    "  'the No. <n> in <color>' or just describe the position. NEVER invent a "
    "  name not in the roster. NEVER name a player whose number isn't in "
    "  `visible_numbers`.\n\n"
    "MODES:\n"
    "  mode='game' — describe THIS moment, briefly, in the language of the "
    "    scene. Wit is allowed as an aside, not the main beat. If the scene "
    "    is mundane, you can simply name the action ('De Paul recycles it') — "
    "    that IS the commentary. No filler, no setup.\n"
    "  mode='chat' — react to the fan comment in `comment.text` from "
    "    `comment.author`. Here you can be sharper. Punch up at the opinion, "
    "    not the person. Tie back to the game if and only if it's relevant.\n\n"
    "HOT-MOMENT RULE:\n"
    "  When `hard_event` is true OR `event` ∈ "
    "  ['goal','save','near_miss','shot','foul','set_piece','penalty'], drop "
    "  irony entirely. React WITH the moment — exclaim, gasp, be genuine. "
    "  Short, punchy. Examples (use the spirit, write in the requested "
    "  language):\n"
    "    goal      → 'And it's in! Messi, from the spot — Argentina lead.'\n"
    "    save      → 'Oh, brilliant! Martínez, down to his right.'\n"
    "    near_miss → 'Inches wide. Inches.'\n"
    "    foul      → 'And that's a yellow. Reckless from Otamendi.'\n\n"
    "OUTPUT FORMAT:\n"
    "  • ONE line. 1 short sentence. Hard cap 18 words.\n"
    "  • NATIVE language as requested. No translation from English.\n"
    "  • No speaker tags, no stage directions, no quotes, no preamble. "
    "    Output only the spoken line."
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
                    temperature=0.65,
                    max_output_tokens=int(os.getenv("COMMENTARY_MAX_TOKENS", "60")),
                ),
            )
            return (resp.text or "").strip() or None
        except Exception as e:
            log.warning("Gemini commentary call failed: %s", e)
            return None
