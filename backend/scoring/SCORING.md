# Game vs. Chat Scoring Design

How the commentator decides — in any given utterance slot — whether to talk
about the game or react to a live-chat comment. Two scores, one decision rule
with a game bias and smoothing so the source doesn't flap.

## 1. Game intensity score `G ∈ [0, 100]`

Computed per frame (or per N-frame window) from the Gemini vision description.
Don't try to be clever with one number — sum weighted signals and clamp.

**Hard-event signals** (override everything, set `G ≈ 100` for a window):

- Goal / shot on target / save → 100
- Red/yellow card, VAR check, penalty awarded → 95
- Injury stoppage → 70 (high but not "exciting" — different bucket)

**Continuous signals** (extracted from scene text; each 0–1, weighted, summed, ×100):

| Signal                       | Weight | Cue from vision text                       |
| ---------------------------- | ------ | ------------------------------------------ |
| Ball in attacking third      | 0.25   | "near box", "edge of area", "18-yard line" |
| Player density near ball     | 0.15   | "crowded", "tackle", "scramble"            |
| Set piece live               | 0.20   | "corner", "free kick", "throw-in deep"     |
| Pace / motion                | 0.15   | "sprint", "counter-attack", "breakaway"    |
| Crowd reaction (if audio)    | 0.15   | volume spike / roar                        |
| Score state pressure         | 0.10   | late game + close score → multiplier       |

Apply **EMA smoothing**: `G_t = 0.6 · G_raw + 0.4 · G_{t-1}` so a single
"midfield pass" frame doesn't kill momentum after a near-goal. Hard events
bypass smoothing.

## 2. Comment-worthiness score `C ∈ [0, 100]`

Pick the best chat comment in a sliding window (last ~20s). Score each by:

- **Controversy / spice** (0–40): sentiment polarity × engagement (replies, reactions)
- **Recency** (0–20): exponential decay, halflife ~15s
- **Relevance** (0–25): cosine sim between comment text and current scene
  description — but *inverted* contribution when the scene is boring (a chat
  hot-take about a totally different topic is fine during a lull)
- **Novelty** (0–15): penalize if we already read a similar comment in last 60s

Take `C = max(scored_comments)` — only the best candidate competes with the game.

## 3. Decision function

Don't compute "which one wins" frame-by-frame — decide what to do during the
**next utterance slot** (commentary fires every ~3–5s based on
`FRAME_SAMPLE_FPS` / pipeline latency).

```
priority_game    = G + GAME_BIAS              # GAME_BIAS ≈ 20
priority_comment = C − COMMENT_PENALTY        # COMMENT_PENALTY ≈ 10 normally
                                              # → 0 if G < 30 (boring → let chat in)
                                              # → 40 if G > 80 (exciting → suppress chat)
```

Pick whichever is higher. The bias + dynamic penalty does three things at
once: game wins ties, chat is actively gated *up* when boring, and chat is
actively gated *down* when exciting.

## 4. Stability — the part that makes it not feel jittery

- **Hysteresis**: once you switch to "chat mode", you need
  `priority_game − priority_comment > 15` to switch back (and vice versa).
  Prevents one ambiguous frame from flipping the source.
- **Minimum dwell**: whichever mode you're in, stay at least 1 full utterance
  (~4s) before switching.
- **Hard-event preempt**: a goal/card resets dwell and forces game mode
  immediately. Chat *never* preempts game.
- **Chat cooldown**: after reading a comment, suppress chat for ~10s
  regardless of `C`, so it doesn't dominate even during long lulls.

## 5. How it lands in the existing pipeline

No new endpoint needed. The decision lives in `backend/routes/stream.py` just
before the call to `pipeline.commentate(...)`. Two options for the prompt:

- **Cleanest**: keep `commentate()` as-is; on "chat mode" build the scene
  payload as `{"mode": "react_to_comment", "comment": "...", "scene": "..."}`
  and update the system prompt to handle both modes.
- **Cheapest**: don't touch the persona — when in chat mode, prepend
  `"React sarcastically to this fan comment during a lull: '...'"` to the
  scene string.

## 6. Demo-friendly knobs

For the presentation, expose three sliders in the UI (the comment feed can be
mocked from JSON):

- `GAME_BIAS` (default 20) — how much the commentator favors the game
- `BORING_THRESHOLD` (default 30) — below this `G`, comments get a free pass
- `MAX_CHAT_RATIO` — hard cap, e.g. ≤30% of utterances over rolling 60s

The ratio cap is the most important — it guarantees the demo never devolves
into "AI reading Twitter for 2 minutes straight" even if intensity scoring
misfires on unfamiliar footage.

## Open questions before building

1. Where does `G` get computed — inline in the vision service, or a separate
   scoring step? (Lean toward inline — one Gemini call returns scene + an
   `"intensity": 0-100` field.)
2. Do chat reactions *interrupt* current TTS, or only queue between
   utterances? (Recommend queue — interrupting feels broken even if it's
   "more responsive".)
3. Comment feed format — JSON array with
   `{text, author, timestamp, reactions}`? Lock the shape now so you can mock
   it cleanly.
