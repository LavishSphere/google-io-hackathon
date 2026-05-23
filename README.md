# HotMic — Sarcastic AI World Cup Commentator

Hackathon project — Google I/O / GDG Newport Beach × NVIDIA × Gemma × RocketRide.

Drop in a World Cup clip, get a sarcastic live commentary track (text + voice)
in your language of choice. Powered by Gemini 3.1 Flash Lite (vision) + GMI Cloud
hosted Gemini 3 Flash (commentary persona) + Gemini Live (TTS).

## Architecture

```
clip ──► browser frame sampler (1.5 fps, base64 JPEG)
     ──► FastAPI WS /api/ws/commentary
            ├─► Gemini 3.1 Flash Lite — describe frame
            ├─► RocketRide pipeline (chat → prompt → llm_gmi_cloud → response_answers)
            │       persona + target language → sarcastic line
            └─► Gemini Live — stream TTS audio
     ◄── { commentary text, streamed PCM audio }
```

## Layout

```
pipelines/commentary.pipe       # RocketRide pipeline (the .pipe file)
backend/                        # FastAPI + Gemini + RocketRide client
  main.py                       #   app entry, lifespan starts the pipeline once
  routes/stream.py              #   WS: frames in, commentary+audio out
  routes/clips.py               #   demo-clip catalogue
  services/gemini_vision.py     #   frame → scene description
  services/gemini_live.py       #   text → streamed PCM audio
  services/rocketride_client.py #   long-lived pipeline wrapper
  personas/                     #   per-language voice notes (few-shot reference)
frontend/                       # Vite + React + TS
  src/App.tsx                   #   player + overlay + language toggle
  src/hooks/useCommentaryWS.ts  #   frame-sampling WS client
  src/lib/audio.ts              #   PCM playback for streamed TTS
demo_clips/                     # drop pre-trimmed .mp4 clips here
scripts/scrape_transcripts.py   # YouTube captions → persona corpus
scripts/check.py                # smoke test (env + pipeline)
```

## Setup

```bash
# 1. env
cp env.example .env
# fill in ROCKETRIDE_APIKEY, ROCKETRIDE_GMI_APIKEY, GOOGLE_API_KEY

# 2. backend
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
python -m scripts.check        # verifies pipeline + Gemini wiring

# 3. frontend
cd frontend && npm install && cd ..

# 4. demo clips
# Drop 3–5 short .mp4 clips into demo_clips/ (15–30s near-goal moments work best).

# 5. run
# terminal A:
python -m backend.main
# terminal B:
cd frontend && npm run dev
# open http://localhost:5173
```

## Roles (team of 3)

- **Frontend**: `frontend/` — player, overlay, language toggle, audio playback,
  WS plumbing.
- **Backend**: `backend/` — FastAPI WS, Gemini vision + Live, RocketRide
  pipeline wrapper.
- **Prompt / Data / Demo**: `pipelines/commentary.pipe`,
  `backend/personas/`, `scripts/scrape_transcripts.py`, picking the demo
  clips. This role decides whether the demo lands a laugh.

## Sponsor hooks

- **NVIDIA** — frame-vision can be moved to an NVIDIA NIM endpoint (swap
  `services/gemini_vision.py`).
- **Gemma** — add a parallel `llm_gmi_cloud` node configured for a Gemma model
  to generate a second "hot take" voice; render as a second subtitle line.
- **RocketRide** — `pipelines/commentary.pipe`, central to the demo. Show the
  graph in slides.

## Known constraints

- Gemini Live has concurrent-session limits — fine for one demo, plan
  fallbacks for a stage demo.
- Vision call latency means commentary lags video by ~1s — the overlay
  acknowledges that visually rather than fighting it.
- Live World Cup feeds are DRM'd; this app ships with pre-trimmed clips.
