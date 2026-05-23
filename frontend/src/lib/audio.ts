// Streamed PCM playback from Gemini Live. The server tags chunks with
// mime "audio/pcm;rate=24000" — 16-bit little-endian mono.

let ctx: AudioContext | null = null;
let queueTime = 0;

function getCtx(): AudioContext {
  if (!ctx) ctx = new AudioContext({ sampleRate: 24000 });
  return ctx;
}

export function playPcmChunk(base64: string, mime: string): void {
  const audioCtx = getCtx();
  const rateMatch = /rate=(\d+)/.exec(mime);
  const sampleRate = rateMatch ? parseInt(rateMatch[1], 10) : 24000;

  const binary = atob(base64);
  const len = binary.length / 2;
  const buf = audioCtx.createBuffer(1, len, sampleRate);
  const channel = buf.getChannelData(0);

  for (let i = 0; i < len; i++) {
    const lo = binary.charCodeAt(i * 2);
    const hi = binary.charCodeAt(i * 2 + 1);
    let sample = (hi << 8) | lo;
    if (sample >= 0x8000) sample -= 0x10000;
    channel[i] = sample / 0x8000;
  }

  const src = audioCtx.createBufferSource();
  src.buffer = buf;
  src.connect(audioCtx.destination);

  const now = audioCtx.currentTime;
  const startAt = Math.max(now, queueTime);
  src.start(startAt);
  queueTime = startAt + buf.duration;
}
