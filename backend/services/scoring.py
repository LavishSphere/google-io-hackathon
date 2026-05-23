"""Game-vs-chat decision engine — implements backend/scoring/SCORING.md.

Two scores per utterance slot:
  • G ∈ [0,100] — game intensity, EMA-smoothed across frames, with hard-event override
  • C ∈ [0,100] — comment-worthiness of the best candidate in the chat window

Decision rule:
  priority_game    = G + GAME_BIAS
  priority_comment = C − chat_penalty(G)   # high when boring, low when exciting
  → pick whichever wins, with hysteresis + minimum dwell + chat cooldown + hard-event preempt.

Per-connection state lives in `ScoringState`. Tuning knobs come from env vars
so the demo can flip them without code changes.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .triage import FrameTriage

log = logging.getLogger(__name__)


class Mode(str, Enum):
    game = "game"
    chat = "chat"


@dataclass
class Decision:
    mode: Mode
    g_score: float           # smoothed game intensity used for the decision
    g_raw: float             # raw per-frame intensity from this frame
    c_score: float           # best chat candidate's score (0 if none)
    priority_game: float
    priority_comment: float
    reason: str              # short tag explaining why this mode was chosen
    speak: bool              # whether to actually utter anything this slot


# ---- Tuning knobs (env-overridable for the demo) -----------------------------

GAME_BIAS = float(os.getenv("GAME_BIAS", "20"))
BORING_THRESHOLD = float(os.getenv("BORING_THRESHOLD", "30"))     # G below this → chat gate fully open
EXCITING_THRESHOLD = float(os.getenv("EXCITING_THRESHOLD", "80")) # G above this → chat heavily suppressed
HYSTERESIS_DELTA = float(os.getenv("HYSTERESIS_DELTA", "15"))
MIN_DWELL_SECONDS = float(os.getenv("MIN_DWELL_SECONDS", "4.0"))
CHAT_COOLDOWN_SECONDS = float(os.getenv("CHAT_COOLDOWN_SECONDS", "10.0"))
EMA_ALPHA = float(os.getenv("EMA_ALPHA", "0.6"))                  # weight of the new frame
SPEAK_THRESHOLD = float(os.getenv("SPEAK_THRESHOLD", "35"))       # below this priority, stay silent (lull)
COMMENT_GAP_SECONDS = float(os.getenv("COMMENT_GAP_SECONDS", "2.0"))  # min gap between *any* two utterances

# Continuous-signal weights (SCORING.md §1). Summed × 100 = continuous component of G.
W_BALL_ATTACKING_THIRD = 0.25
W_SET_PIECE = 0.20
W_DENSITY = 0.15
W_PACE = 0.15

HARD_EVENT_G = 100.0


def _hard_event(triage: FrameTriage) -> bool:
    return any([
        triage.hard_goal,
        triage.hard_card,
        triage.hard_penalty,
        triage.hard_save,
        triage.hard_var,
        triage.hard_injury,
    ])


def compute_g_raw(triage: FrameTriage) -> float:
    """Combine the per-frame signals into a single 0-100 intensity, pre-smoothing."""
    if _hard_event(triage):
        return HARD_EVENT_G

    continuous = 100.0 * (
        W_BALL_ATTACKING_THIRD * triage.ball_attacking_third
        + W_SET_PIECE * triage.set_piece_live
        + W_DENSITY * triage.player_density_near_ball
        + W_PACE * triage.pace
    )
    # Blend with the model's coarse intensity so a smart vision call can override
    # weak signal extraction — and vice versa.
    blended = 0.5 * float(triage.intensity) + 0.5 * continuous
    return max(0.0, min(100.0, blended))


def chat_penalty(g_smoothed: float) -> float:
    """Dynamic suppression of chat as the game heats up (SCORING.md §3).

    g < BORING_THRESHOLD          → 0  (chat freely)
    BORING ≤ g ≤ EXCITING         → linear ramp 0..40
    g > EXCITING_THRESHOLD        → 40 (chat strongly suppressed)
    """
    if g_smoothed <= BORING_THRESHOLD:
        return 0.0
    if g_smoothed >= EXCITING_THRESHOLD:
        return 40.0
    span = EXCITING_THRESHOLD - BORING_THRESHOLD
    return 40.0 * (g_smoothed - BORING_THRESHOLD) / span


@dataclass
class ScoringState:
    """Per-WebSocket state for the decision engine. One per active connection."""

    g_smoothed: float = 0.0
    current_mode: Mode = Mode.game
    last_mode_switch_ts: float = -1e9          # video-time of last switch
    last_utterance_ts: float = -1e9            # video-time of last spoken line (any mode)
    last_chat_utterance_ts: float = -1e9       # video-time of last *chat* utterance

    # Visible-for-debugging trace of the most recent decision.
    last_decision: Optional[Decision] = field(default=None)

    def update_intensity(self, triage: FrameTriage) -> tuple[float, float]:
        """Apply EMA smoothing (hard events bypass). Returns (g_raw, g_smoothed)."""
        g_raw = compute_g_raw(triage)
        if _hard_event(triage):
            self.g_smoothed = HARD_EVENT_G   # hard preempt resets smoothing
        else:
            self.g_smoothed = EMA_ALPHA * g_raw + (1.0 - EMA_ALPHA) * self.g_smoothed
        return g_raw, self.g_smoothed

    def decide(
        self,
        ts: float,
        triage: FrameTriage,
        best_comment_score: float,
    ) -> Decision:
        g_raw, g = self.update_intensity(triage)

        priority_game = g + GAME_BIAS
        priority_comment = best_comment_score - chat_penalty(g)

        target_mode = self.current_mode
        reason = "stable"

        # Hard preempt — goals/cards/penalties always force game mode immediately.
        if _hard_event(triage):
            if self.current_mode is Mode.chat:
                reason = "hard_event_preempt"
            target_mode = Mode.game

        # Chat cooldown — after speaking a chat reaction, don't speak another for a while.
        chat_locked = (ts - self.last_chat_utterance_ts) < CHAT_COOLDOWN_SECONDS

        # Minimum dwell — once we've picked a mode, stay there for at least 4s.
        in_dwell = (ts - self.last_mode_switch_ts) < MIN_DWELL_SECONDS

        if not _hard_event(triage) and not in_dwell:
            # Hysteresis: to switch mode you must beat the current preference by HYSTERESIS_DELTA.
            if self.current_mode is Mode.game:
                if (
                    priority_comment - priority_game > HYSTERESIS_DELTA
                    and not chat_locked
                ):
                    target_mode = Mode.chat
                    reason = "comment_won"
            else:  # currently chat
                if priority_game - priority_comment > HYSTERESIS_DELTA:
                    target_mode = Mode.game
                    reason = "game_won"

        if target_mode is Mode.chat and chat_locked:
            target_mode = Mode.game
            reason = "chat_cooldown"

        if target_mode != self.current_mode:
            self.last_mode_switch_ts = ts
            self.current_mode = target_mode

        # Should we actually speak this slot? Two gates:
        #   1. enforce a minimum gap between consecutive utterances
        #   2. if it's just a lull and nothing in chat is interesting, stay quiet
        winning_priority = priority_game if target_mode is Mode.game else priority_comment
        too_soon = (ts - self.last_utterance_ts) < COMMENT_GAP_SECONDS
        is_lull = winning_priority < SPEAK_THRESHOLD
        speak = not too_soon and (not is_lull or _hard_event(triage))

        decision = Decision(
            mode=target_mode,
            g_score=g,
            g_raw=g_raw,
            c_score=best_comment_score,
            priority_game=priority_game,
            priority_comment=priority_comment,
            reason=reason,
            speak=speak,
        )
        self.last_decision = decision
        return decision

    def record_utterance(self, ts: float, mode: Mode) -> None:
        self.last_utterance_ts = ts
        if mode is Mode.chat:
            self.last_chat_utterance_ts = ts
