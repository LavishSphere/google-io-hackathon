"""Roster lookup — pulls a match roster via Gemini's grounded Google Search,
then parses the prose into structured JSON. Cached per clip on disk.

Workflow when the WS receives `config` with a `match` string:
  1. If `backend/data/rosters/{clip_id}.json` exists, load it (fast path —
     also where you'd drop hand-edited rosters for demo clips you've vetted).
  2. Otherwise: Gemini grounded-search → prose with citations.
  3. Second Gemini call with `response_schema=Roster` parses that prose into
     a Pydantic-typed roster.
  4. Write to cache and return.

Returned to the commentary LLM as: roster summary + the visible_numbers the
vision model picked out per frame. The LLM maps `#10 in red` → `Pedri` only
when the match is unambiguous; otherwise falls back to a description.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from pydantic import BaseModel

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[2] / "backend" / "data" / "rosters"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Hand-curated rosters for demo clips. Keyed by lowercase keyword sets that
# must ALL appear in the match query. First match wins — order matters.
_HARDCODED_ROSTER_RULES: list[tuple[set[str], str]] = [
    ({"argentina", "france", "2022"}, "argentina-vs-france-2022.json"),
    ({"argentina", "france", "final"}, "argentina-vs-france-2022.json"),
    ({"messi", "mbappe"}, "argentina-vs-france-2022.json"),
]

# Use the heavier model for roster work — it's a one-time call per clip, and
# the quality bump matters more here than the latency.
_SEARCH_MODEL = os.getenv("GEMINI_ROSTER_MODEL", "gemini-3.1-pro")
_PARSE_MODEL = os.getenv("GEMINI_VISION_MODEL", "gemini-3.1-flash-lite")


class Player(BaseModel):
    number: int
    name: str
    position: str = ""


class Team(BaseModel):
    name: str
    kit_color: str   # e.g. "red", "white", "navy" — should match what vision sees
    players: list[Player]


class Roster(BaseModel):
    match: str
    teams: list[Team]


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    return _client


def _cache_path(clip_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in clip_id)
    return CACHE_DIR / f"{safe}.json"


def load_cached(clip_id: str) -> Optional[Roster]:
    path = _cache_path(clip_id)
    if not path.exists():
        return None
    try:
        return Roster.model_validate_json(path.read_text())
    except Exception as e:
        log.warning("roster cache parse failed (%s): %s", path, e)
        return None


def load_hardcoded_for_match(match_query: str) -> Optional[Roster]:
    """Pre-baked rosters for known demo clips. Lets us skip the web search."""
    q = (match_query or "").lower()
    for keywords, filename in _HARDCODED_ROSTER_RULES:
        if all(k in q for k in keywords):
            path = CACHE_DIR / filename
            if path.exists():
                try:
                    return Roster.model_validate_json(path.read_text())
                except Exception as e:
                    log.warning("hardcoded roster parse failed (%s): %s", path, e)
    return None


async def fetch_roster(match_query: str) -> Optional[Roster]:
    """Two-step grounded search → structured parse."""
    if not match_query.strip():
        return None
    client = _get_client()

    # Step 1: grounded search for the lineup text.
    try:
        search_resp = await client.aio.models.generate_content(
            model=_SEARCH_MODEL,
            contents=(
                f"Search the web for the starting lineup / roster of the match: "
                f"{match_query!r}. For EACH team list:\n"
                "  - team name\n"
                "  - kit color worn in this specific match (one word, e.g. red, white, navy)\n"
                "  - every player with jersey number, full name, and position.\n"
                "Be precise. If unsure about a number/name, omit that player."
            ),
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
                temperature=0.1,
            ),
        )
        prose = (search_resp.text or "").strip()
    except Exception as e:
        log.warning("roster search step failed: %s", e)
        return None

    if not prose:
        log.warning("roster search returned empty for %r", match_query)
        return None

    # Step 2: parse the prose into a structured Roster.
    try:
        parse_resp = await client.aio.models.generate_content(
            model=_PARSE_MODEL,
            contents=(
                "Parse this match roster text into the required JSON schema. "
                "If a player's number or name is unclear, omit that player.\n\n"
                f"{prose}"
            ),
            config=types.GenerateContentConfig(
                temperature=0.0,
                response_mime_type="application/json",
                response_schema=Roster,
            ),
        )
        if not parse_resp.text:
            return None
        return Roster.model_validate_json(parse_resp.text)
    except Exception as e:
        log.warning("roster parse step failed: %s", e)
        return None


async def get_or_fetch(clip_id: str, match_query: Optional[str]) -> Optional[Roster]:
    # 1. Per-clip cache (web search results, or a hand-edited file).
    cached = load_cached(clip_id)
    if cached:
        log.info("roster cache hit (%s teams=%d)", clip_id, len(cached.teams))
        return cached

    # 2. Hand-curated demo rosters (keyword match against match_query).
    if match_query:
        hardcoded = load_hardcoded_for_match(match_query)
        if hardcoded:
            log.info(
                "roster hardcoded match for %r → %s (teams=%d)",
                match_query, hardcoded.match, len(hardcoded.teams),
            )
            # Cache to clip_id so subsequent reloads skip the lookup entirely.
            _cache_path(clip_id).write_text(hardcoded.model_dump_json(indent=2))
            return hardcoded

    # 3. Live Gemini grounded search.
    if not match_query:
        return None
    roster = await fetch_roster(match_query)
    if roster:
        _cache_path(clip_id).write_text(roster.model_dump_json(indent=2))
        log.info("roster fetched & cached (%s teams=%d)", clip_id, len(roster.teams))
    return roster


def format_for_prompt(roster: Roster) -> str:
    """Compact text representation for the commentary LLM context."""
    lines = [f"MATCH: {roster.match}"]
    for team in roster.teams:
        lines.append(f"  {team.name} ({team.kit_color}):")
        for p in team.players:
            pos = f" {p.position}" if p.position else ""
            lines.append(f"    #{p.number} {p.name}{pos}")
    return "\n".join(lines)


def roster_to_payload(roster: Optional[Roster]) -> Optional[dict]:
    """Compact JSON-able form for embedding in the commentary user payload."""
    if not roster:
        return None
    return roster.model_dump()
