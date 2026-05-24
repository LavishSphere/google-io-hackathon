// Audio playback for both legacy streamed PCM (from Gemini Live) and complete
// MP3 files (from MiniMax via GMI). All chunks queue back-to-back via a shared
// `queueTime` cursor so consecutive cues play gaplessly.

let ctx: AudioContext | null = null;
let queueTime = 0;

function getCtx(): AudioContext {
  // Don't pin sampleRate — for MP3 the decoded buffer carries its own rate and
  // AudioContext resamples on playback; for PCM we set the rate on the buffer
  // itself, so the context rate doesn't need to match either.
  if (!ctx) ctx = new AudioContext();
  return ctx;
}

function scheduleBuffer(audioCtx: AudioContext, buf: AudioBuffer): void {
  const src = audioCtx.createBufferSource();
  src.buffer = buf;
  src.connect(audioCtx.destination);
  const now = audioCtx.currentTime;
  const startAt = Math.max(now, queueTime);
  src.start(startAt);
  queueTime = startAt + buf.duration;
}

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const buf = new ArrayBuffer(binary.length);
  const view = new Uint8Array(buf);
  for (let i = 0; i < binary.length; i++) view[i] = binary.charCodeAt(i);
  return buf;
}

async function playMp3(base64: string): Promise<void> {
  const audioCtx = getCtx();
  try {
    const arrayBuf = base64ToArrayBuffer(base64);
    const audioBuf = await audioCtx.decodeAudioData(arrayBuf);
    scheduleBuffer(audioCtx, audioBuf);
  } catch (e) {
    console.warn('mp3 decode failed', e);
  }
}

function playPcm(base64: string, mime: string): void {
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
  scheduleBuffer(audioCtx, buf);
}

/** Dispatch one audio chunk based on its MIME type. */
export function playAudioChunk(base64: string, mime: string): void {
  if (!mime) return;
  if (mime.includes('mpeg') || mime.includes('mp3')) {
    void playMp3(base64);
  } else if (mime.includes('pcm')) {
    playPcm(base64, mime);
  } else {
    // Default: try MP3 (covers wav and most compressed formats via decodeAudioData).
    void playMp3(base64);
  }
}

// Back-compat alias for callers that still import the old name.
export const playPcmChunk = playAudioChunk;
