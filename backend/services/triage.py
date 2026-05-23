"""Frame triage — produces the raw inputs for the game-intensity score G.

Single Gemini Vision call per frame returns a structured JSON judgment with:
  • a coarse intensity 0-100
  • the continuous signals from SCORING.md (ball position, density, pace, set piece)
  • hard-event flags that bypass smoothing (goal, card, penalty, save, etc.)
  • a one-line factual scene description (fed into the commentary LLM later)
  • optional team_color of a scoring team for the scoreboard

The scoring state machine (services/scoring.py) consumes this output, applies
EMA smoothing, and decides whether to commentate.
"""

import base64
import logging
import os
from enum import Enum
from typing import Optional

from google import genai
from google.genai import types
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-3.1-flash-lite")


class Event(str, Enum):
    nothing = "nothing"
    buildup = "buildup"
    shot = "shot"
    near_miss = "near_miss"
    goal = "goal"
    save = "save"
    foul = "foul"
    set_piece = "set_piece"
    celebration = "celebration"
    replay = "replay"
    off_play = "off_play"


class VisibleJersey(BaseModel):
    """One legible jersey number visible in the frame."""
    number: int
    team_color: str   # color word; will be matched to the roster's kit_color


class FrameTriage(BaseModel):
    """Raw vision output — gets folded into the scoring state machine."""

    # Coarse 0-100 judgment of how interesting this single frame is, before
    # the scoring service applies EMA smoothing or hard-event overrides.
    intensity: int = Field(ge=0, le=100)

    event: Event
    scene: str  # one factual sentence, under 25 words, no flourishes

    # Continuous signals from SCORING.md. Each 0.0–1.0; the scoring service
    # weights and combines them. We over-collect here so the scoring service
    # can re-tune weights without re-prompting the model.
    ball_attacking_third: float = Field(ge=0.0, le=1.0)
    set_piece_live: float = Field(ge=0.0, le=1.0)
    player_density_near_ball: float = Field(ge=0.0, le=1.0)
    pace: float = Field(ge=0.0, le=1.0)

    # Hard-event flags. ANY true value forces G ≈ 100 for this frame and
    # bypasses EMA smoothing in the scoring service.
    hard_goal: bool
    hard_card: bool         # red/yellow shown
    hard_penalty: bool      # penalty awarded
    hard_save: bool         # big keeper save / shot on target denied
    hard_var: bool          # VAR review on screen
    hard_injury: bool

    # Scoreboard hints.
    goal_scored: bool       # mirrors hard_goal but we keep both for clarity
    team_color: Optional[str] = None

    # Jersey numbers the vision model can read in this frame. Empty when the
    # camera angle / motion blur makes them unreadable. The commentary LLM
    # uses these (plus the roster) to name players by number.
    visible_numbers: list[VisibleJersey] = []


_INSTRUCTION = (
    "You are a triage system watching a World Cup soccer broadcast. For each "
    "frame, return a structured JSON judgment.\n\n"
    "Be strict on `intensity` — most frames are mundane:\n"
    "  0–20  : midfield buildup, neutral play, throw-ins, crowd, replay angles\n"
    "  20–40 : attack in opposition half, ball recoveries, off-ball runs\n"
    "  40–60 : shot setup, dangerous cross, breakaway, close defense\n"
    "  60–80 : shot on target, big save, near-miss, hard tackle, VAR check\n"
    "  80–100: GOAL, red card, penalty awarded, last-minute drama\n\n"
    "Continuous signals (each 0.0–1.0, be generous with non-zero values when "
    "the cue is plausibly present):\n"
    "  ball_attacking_third      — ball in/near the opposition's defensive third\n"
    "  set_piece_live            — corner, free-kick or throw-in being taken\n"
    "  player_density_near_ball  — many players in tight quarters around the ball\n"
    "  pace                      — sprint, counter-attack, fast transition\n\n"
    "Hard-event flags are TRUE only if you are clearly confident. False otherwise:\n"
    "  hard_goal     — ball clearly crossed the goal line, or unmistakable celebration\n"
    "  hard_card     — referee showing yellow/red\n"
    "  hard_penalty  — penalty being awarded / set up on the spot\n"
    "  hard_save     — keeper making a clear save\n"
    "  hard_var      — VAR review banner / referee at monitor\n"
    "  hard_injury   — player down receiving treatment\n\n"
    "scene: one neutral sentence. Who has the ball, where, what's about to "
    "happen. No opinion, no flourish, under 25 words.\n"
    "team_color: kit color of the team in possession during a key moment, only "
    "if clearly visible. Null otherwise.\n\n"
    "visible_numbers: list any jersey numbers you can clearly read in this "
    "frame, with the kit color of the player wearing them. Use one-word colors "
    "(red, white, navy, sky-blue, etc.). DO NOT GUESS — if a number is blurry, "
    "obscured, or you're unsure, OMIT it. An empty list is the correct answer "
    "for most frames. Typical legibility: 0–2 numbers per frame in close shots, "
    "0 in wide shots."
)


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    return _client


async def triage_frame(frame_b64: str) -> FrameTriage | None:
    try:
        jpeg = base64.b64decode(frame_b64)
        resp = await _get_client().aio.models.generate_content(
            model=_MODEL,
            contents=[
                types.Part.from_bytes(data=jpeg, mime_type="image/jpeg"),
                _INSTRUCTION,
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=FrameTriage,
            ),
        )
        if not resp.text:
            return None
        return FrameTriage.model_validate_json(resp.text)
    except Exception as e:
        log.warning("triage failed: %s", e)
        return None
