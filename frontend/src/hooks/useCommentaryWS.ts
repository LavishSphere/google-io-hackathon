import { RefObject, useCallback, useEffect, useRef, useState } from 'react';
import { grabFrame } from '../lib/frame';
import { playPcmChunk } from '../lib/audio';

type Args = {
  videoRef: RefObject<HTMLVideoElement>;
  language: string;
};

// Broadcast-delay model: extract all frames while paused, fire them at the
// backend, then start playing as soon as the first cue (BUFFER_AHEAD_CUES) is
// ready. Later cues land progressively and dispatch when the playhead crosses
// their timestamp — if a cue arrives late, it fires on the next rAF tick.
//
// SAMPLE_FPS controls how dense the commentary is (lower = fewer LLM calls,
// fewer lines per minute of video; higher = more, slower per-cue cadence).
const SAMPLE_FPS = 0.7;
const BUFFER_AHEAD_CUES = 1;

type Cue = {
  ts: number;
  text: string;
  audio: { data: string; mime: string }[];
  textReceived: boolean;
  fired: boolean;
};

const TIMESTAMP_EPS = 0.05;

function seekTo(video: HTMLVideoElement, t: number): Promise<void> {
  return new Promise((resolve) => {
    const onSeeked = () => {
      video.removeEventListener('seeked', onSeeked);
      resolve();
    };
    video.addEventListener('seeked', onSeeked);
    video.currentTime = t;
  });
}

export function useCommentaryWS({ videoRef, language }: Args) {
  const wsRef = useRef<WebSocket | null>(null);
  const rafRef = useRef<number | null>(null);
  const cuesRef = useRef<Cue[]>([]);
  const expectedRef = useRef(0);
  const receivedRef = useRef(0);
  const playingRef = useRef(false);

  const [line, setLine] = useState('');
  const [status, setStatus] = useState('idle');
  const [running, setRunning] = useState(false);

  // Re-send language when it changes mid-session.
  useEffect(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'config', language }));
    }
  }, [language]);

  const tick = useCallback(() => {
    const video = videoRef.current;
    if (!video || !playingRef.current) return;
    const t = video.currentTime;
    for (const cue of cuesRef.current) {
      if (!cue.fired && cue.textReceived && cue.ts <= t) {
        cue.fired = true;
        setLine(cue.text);
        for (const chunk of cue.audio) playPcmChunk(chunk.data, chunk.mime);
      }
    }
    rafRef.current = requestAnimationFrame(tick);
  }, [videoRef]);

  const start = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;

    cuesRef.current = [];
    expectedRef.current = 0;
    receivedRef.current = 0;
    setLine('');

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${window.location.host}/api/ws/commentary`);
    wsRef.current = ws;
    setStatus('connecting…');

    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (typeof msg.timestamp !== 'number') return;
      const cue = cuesRef.current.find((c) => Math.abs(c.ts - msg.timestamp) < TIMESTAMP_EPS);
      if (!cue) return;

      if (msg.type === 'commentary') {
        cue.text = msg.text;
        cue.textReceived = true;
        receivedRef.current += 1;
        if (receivedRef.current >= expectedRef.current) {
          setStatus('live');
        } else if (playingRef.current) {
          setStatus(`live · generating ${receivedRef.current}/${expectedRef.current}…`);
        } else {
          setStatus(`preparing ${receivedRef.current}/${expectedRef.current}…`);
        }
        // Start playing as soon as we have a small lead — later cues catch up
        // in real time and dispatch when the playhead reaches them.
        if (!playingRef.current && receivedRef.current >= BUFFER_AHEAD_CUES) {
          startPlayback();
        }
      } else if (msg.type === 'audio') {
        cue.audio.push({ data: msg.data, mime: msg.mime });
        // If the cue's timestamp has already passed during playback, the
        // commentary line fired without audio. Play this chunk now so the
        // viewer still hears the voice (slightly late, broadcast-style).
        if (cue.fired) playPcmChunk(msg.data, msg.mime);
      }
    };

    ws.onclose = () => {
      setStatus('disconnected');
      setRunning(false);
      playingRef.current = false;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
    ws.onerror = () => setStatus('error');

    function startPlayback() {
      if (playingRef.current) return;
      playingRef.current = true;
      setStatus('live');
      video!.currentTime = 0;
      video!.play().catch(() => {});
      rafRef.current = requestAnimationFrame(tick);
    }

    await new Promise<void>((resolve) => {
      if (ws.readyState === WebSocket.OPEN) resolve();
      else ws.addEventListener('open', () => resolve(), { once: true });
    });

    ws.send(JSON.stringify({ type: 'config', language }));
    setRunning(true);
    setStatus('preparing commentary…');

    video.pause();
    // Wait for metadata so duration is known.
    if (Number.isNaN(video.duration) || !isFinite(video.duration)) {
      await new Promise<void>((res) =>
        video.addEventListener('loadedmetadata', () => res(), { once: true })
      );
    }
    const duration = video.duration;
    const stride = 1 / SAMPLE_FPS;
    const stamps: number[] = [];
    for (let t = 0; t < duration; t += stride) stamps.push(+t.toFixed(3));

    expectedRef.current = stamps.length;
    cuesRef.current = stamps.map((ts) => ({
      ts,
      text: '',
      audio: [],
      textReceived: false,
      fired: false,
    }));
    setStatus(`generating commentary 0/${stamps.length}…`);

    for (const ts of stamps) {
      await seekTo(video, ts);
      const frame = grabFrame(video);
      if (!frame) continue;
      ws.send(JSON.stringify({ type: 'frame', data: frame, timestamp: ts }));
    }
    // Snap back to 0 so play() starts cleanly when commentary fills in.
    await seekTo(video, 0);
  }, [videoRef, language, tick]);

  const stop = useCallback(() => {
    wsRef.current?.close();
    playingRef.current = false;
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    videoRef.current?.pause();
    setRunning(false);
  }, [videoRef]);

  useEffect(() => () => stop(), [stop]);

  return { line, status, start, stop, running };
}
