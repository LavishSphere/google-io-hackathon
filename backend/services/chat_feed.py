"""Mock chat feed + comment-worthiness scoring (C, SCORING.md §2).

For the demo we load fan comments from a JSON file keyed by clip id. Each
comment has a timestamp (video-time) so it "arrives" as the clip plays.

C ∈ [0,100] is the score of the BEST comment in the sliding window. We
compute it from cheap features only (no embeddings — relevance is approximated
with keyword overlap against the scene description). Fields per comment:

  controversy : 0-1  (pre-baked into the mock data; in production this would
                      come from sentiment polarity × engagement)
  recency     : exponential decay, halflife ~15s
  relevance   : simple keyword overlap between comment text and scene
  novelty     : penalize if we already read a similar comment recently
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

log = logging.getLogger(__name__)

_CHAT_DIR = Path(__file__).resolve().parents[2] / "backend" / "data" / "chat"
RECENCY_HALFLIFE_S = 15.0
RECENT_WINDOW_S = 20.0
RECENT_UTTERED_S = 60.0  # window where we suppress similar repeats
RELEVANCE_BORING_INVERTED = True  # SCORING.md: irrelevant chat is fine during a lull


@dataclass
class Comment:
    ts: float           # video-time when the comment posts
    text: str
    author: str
    controversy: float  # 0-1
    reactions: int = 0


@dataclass
class ScoredComment:
    comment: Comment
    score: float
    parts: dict[str, float] = field(default_factory=dict)


_TOKEN_RE = re.compile(r"[a-z0-9']+")


def _tokens(s: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(s.lower()) if len(t) > 2}


def load_chat_for_clip(clip_id: str) -> list[Comment]:
    """Load mock comments for a clip. Falls back to a generic stream if no clip-specific file."""
    candidates = [_CHAT_DIR / f"{clip_id}.json", _CHAT_DIR / "default.json"]
    for path in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return [
                    Comment(
                        ts=float(c["ts"]),
                        text=c["text"],
                        author=c.get("author", "anon"),
                        controversy=float(c.get("controversy", 0.5)),
                        reactions=int(c.get("reactions", 0)),
                    )
                    for c in data
                ]
            except Exception as e:
                log.warning("chat feed load failed (%s): %s", path, e)
    return []


def score_comment(
    comment: Comment,
    now_ts: float,
    scene_text: str,
    g_smoothed: float,
    recently_uttered_texts: Iterable[str],
) -> ScoredComment:
    """Score a single candidate comment 0-100 by the SCORING.md §2 rubric."""

    # Controversy / spice (0–40)
    engagement = min(1.0, comment.reactions / 50.0)  # 50+ reactions = max
    controversy = 40.0 * (0.6 * comment.controversy + 0.4 * engagement)

    # Recency (0–20). Exponential decay, halflife 15s.
    age = max(0.0, now_ts - comment.ts)
    recency = 20.0 * (0.5 ** (age / RECENCY_HALFLIFE_S))

    # Relevance (0–25). Keyword overlap proxy. Inverted contribution during lulls.
    overlap = _tokens(comment.text) & _tokens(scene_text)
    raw_relevance = min(1.0, len(overlap) / 3.0)
    if RELEVANCE_BORING_INVERTED and g_smoothed < 30:
        # During a lull, irrelevance is acceptable — give it full marks.
        relevance = 25.0
    else:
        relevance = 25.0 * raw_relevance

    # Novelty (0–15). Penalize near-duplicates of anything we said recently.
    novelty = 15.0
    ctoks = _tokens(comment.text)
    for prior in recently_uttered_texts:
        prior_toks = _tokens(prior)
        if not prior_toks:
            continue
        jaccard = len(ctoks & prior_toks) / max(1, len(ctoks | prior_toks))
        if jaccard > 0.4:
            novelty *= 1.0 - jaccard
    novelty = max(0.0, novelty)

    score = controversy + recency + relevance + novelty
    return ScoredComment(
        comment=comment,
        score=score,
        parts={
            "controversy": controversy,
            "recency": recency,
            "relevance": relevance,
            "novelty": novelty,
        },
    )


class ChatWindow:
    """Sliding window over the chat stream. Picks the best candidate at each slot."""

    def __init__(self, comments: list[Comment]) -> None:
        self._comments = sorted(comments, key=lambda c: c.ts)
        self._recent_uttered: list[str] = []

    def best_candidate(
        self,
        now_ts: float,
        scene_text: str,
        g_smoothed: float,
    ) -> ScoredComment | None:
        # Comments that have "arrived" but are still within the sliding window.
        candidates = [
            c for c in self._comments
            if c.ts <= now_ts and (now_ts - c.ts) <= RECENT_WINDOW_S
        ]
        if not candidates:
            return None
        scored = [
            score_comment(c, now_ts, scene_text, g_smoothed, self._recent_uttered)
            for c in candidates
        ]
        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[0]

    def mark_uttered(self, comment: Comment) -> None:
        self._recent_uttered.append(comment.text)
        # Trim by count rather than time; ChatWindow lives per-connection (short-lived).
        if len(self._recent_uttered) > 20:
            self._recent_uttered = self._recent_uttered[-20:]
