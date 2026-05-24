# HotMic: Sarcastic AI World Cup Commentator

Hackathon project for Google I/O / GDG Newport Beach × NVIDIA × Gemma × RocketRide.

Drop in a World Cup clip and HotMic streams a sarcastic live commentary track
(text overlay + voice) in your language of choice. It also watches a
Twitch-style fan-chat feed and decides on-the-fly whether to call the game or
react to the crowd. Vision triage and the persona LLM both run on Gemini 3.1
Flash Lite via Google AI Studio; MiniMax TTS (via GMI Cloud) handles the
voice.

## What it does

- **Frame triage**: every video frame is described by Gemini Vision as
  structured JSON (scene, event type, intensity signals, hard events, visible
  jersey numbers). See [services/triage.py](backend/services/triage.py).
- **Game vs chat scoring**: a per-connection state machine computes a game
  intensity score `G` and a comment-worthiness score `C`, applies hysteresis +
  dwell + cooldown, and picks a mode per utterance slot. Design doc:
  [SCORING.md](backend/scoring/SCORING.md).
- **Persona LLM**: a direct Gemini 3.1 Flash Lite call turns scene + context +
  roster + recent events into one short sarcastic line, natively in the target
  language (no translation). See
  [services/rocketride_client.py](backend/services/rocketride_client.py); the
  name is a legacy from when this routed through RocketRide, and the `.pipe`
  file is still in the repo and can be swapped back in.
- **Roster grounding**: at clip load, Gemini grounded search fetches the real
  match roster + kit colors so the commentator can name players from visible
  jersey numbers instead of saying "the guy in blue". Hand-curated rosters in
  [backend/data/rosters/](backend/data/rosters/) short-circuit the search for
  known demo matches.
- **Live chat + comment injection**: pre-baked fan comments stream
  Twitch-style alongside the video; an operator panel lets you inject a
  comment mid-clip to force a chat reaction.
- **TTS**: commentary lines are sent to MiniMax TTS via GMI Cloud's async
  request-queue API and played back as MP3 in the browser.

## Architecture

```
clip ──► browser frame sampler (1.5 fps, base64 JPEG)
     ──► FastAPI WS /api/ws/commentary  (per-connection state)
            ├─► triage           : Gemini Vision → JSON scene + signals
            ├─► scoring          : G + C → Decision { mode, speak? }
            ├─► commentary LLM   : Gemini 3.1 Flash Lite (persona + roster
            │                       + recent events → one short line)
            └─► MiniMax TTS      : text → MP3 (GMI Cloud request queue)
     ◄── { score, scoring, chat_comment, commentary | chat_reaction, audio }
```

Roster lookup runs out-of-band on `config` (Gemini grounded search →
structured-parse → disk cache).

## Layout

```
pipelines/commentary.pipe         # legacy RocketRide pipeline (not in the hot path)
backend/                          # FastAPI + Gemini + MiniMax TTS
  main.py                         #   app entry, lifespan starts the LLM client once
  routes/stream.py                #   WS: frames in, commentary+audio out
  routes/clips.py                 #   demo-clip catalogue
  services/triage.py              #   frame → structured JSON (scene + signals)
  services/scoring.py             #   G + C state machine, hysteresis, dwell
  services/chat_feed.py           #   sliding-window chat scoring (C)
  services/roster.py              #   match roster lookup (grounded search + cache)
  services/gemini_vision.py       #   raw vision wrapper (helper for triage)
  services/frame_sampler.py       #   optional server-side frame sampler
  services/minimax_tts.py         #   text → MP3 via GMI Cloud (MiniMax)
  services/rocketride_client.py   #   commentary LLM client (legacy filename)
  scoring/SCORING.md              #   design doc for the decision model
  personas/                       #   per-language voice notes (few-shot reference)
  data/chat/                      #   pre-baked fan-comment feeds per clip
  data/rosters/                   #   cached + hand-curated rosters per clip
frontend/                         # Vite + React + TS
  src/App.tsx                     #   stage layout + clip/match/language controls
  src/hooks/useCommentaryWS.ts    #   frame-sampling WS client
  src/components/
    VideoPlayer.tsx               #   <video> with ref-forwarding for sampling
    CommentaryOverlay.tsx         #   live subtitle overlay
    Scoreboard.tsx                #   running score widget
    ScoringMeter.tsx              #   G/C debug HUD
    LiveChat.tsx                  #   Twitch-style chat feed
    CommentInjector.tsx           #   manual fan-comment injector
    CommentaryHistory.tsx         #   utterance log
    LanguageToggle.tsx
  src/lib/audio.ts                #   MP3 playback for streamed TTS
  src/lib/frame.ts                #   <video> → JPEG frame extraction
demo_clips/                       # drop pre-trimmed .mp4 clips here
scripts/scrape_transcripts.py     # YouTube captions → persona corpus
scripts/check.py                  # smoke test (env + LLM wiring)
```

## Setup

```bash
# 1. env
cp env.example .env
# fill in GOOGLE_API_KEY (vision + commentary) and
# ROCKETRIDE_GMI_APIKEY (MiniMax TTS via GMI Cloud).
# MINIMAX_VOICE_ID picks the speaking voice.

# 2. backend
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
python -m scripts.check        # verifies env + Gemini wiring

# 3. frontend
cd frontend && npm install && cd ..

# 4. demo clips
# Drop 3–5 short .mp4 clips into demo_clips/ (15–30s near-goal moments work best).
# Optionally drop a matching <clip-id>.json of fan comments into backend/data/chat/.
# For known matches you can hand-edit a roster JSON into backend/data/rosters/.

# 5. run
# terminal A:
python -m backend.main
# terminal B:
cd frontend && npm run dev
# open http://localhost:5173
```

## Using the demo

1. Pick a clip from the dropdown.
2. Type the real match name (e.g. *"2022 FIFA World Cup Final, Argentina vs
   France"*). This enables roster grounding so the AI can name players by
   jersey number.
3. Toggle the **auto chat** checkbox off if you want a clean game-only run.
4. Hit **Start commentary**. Use the inject panel to drop in fan comments
   mid-clip and force a chat reaction.

## Sponsor hooks

- **NVIDIA**: frame triage can be moved to an NVIDIA NIM endpoint
  (swap [services/triage.py](backend/services/triage.py) /
  [services/gemini_vision.py](backend/services/gemini_vision.py)).
- **Gemma**: drop in a Gemma-hosted commentary model alongside the current
  Gemini call to generate a second "hot take" voice; render as a second
  subtitle line.
- **RocketRide**: [pipelines/commentary.pipe](pipelines/commentary.pipe) is
  the original persona pipeline (chat → prompt → llm_gmi_cloud →
  response_answers). Currently bypassed for direct Gemini after free-tier
  rate-limit issues during the build; re-enable by pointing
  `rocketride_client.py` back at the long-lived pipeline wrapper.
- **GMI Cloud**: hosts MiniMax TTS (request-queue API). Also configured for
  Gemma/Gemini hosting via `GMI_*` env vars if the commentary path moves back
  off direct Gemini.

## Known constraints

- Vision triage latency means commentary lags video by ~1s; the overlay
  acknowledges that visually rather than fighting it.
- Live World Cup feeds are DRM'd; this app ships with pre-trimmed clips.
- Frame concurrency is capped by `FRAME_CONCURRENCY` (default 6) to respect
  Gemini RPM limits. Push higher if you have paid quota.
- MiniMax TTS is a poll-until-done request queue, not a true stream; the
  first audio chunk for a line lands a couple of seconds after the text does.
