import { RefObject, useCallback, useEffect, useRef, useState } from 'react';
import { grabFrame } from '../lib/frame';
import { playPcmChunk } from '../lib/audio';

type Args = {
  videoRef: RefObject<HTMLVideoElement>;
  language: string;
  clipId?: string;
};

const SAMPLE_FPS = 0.7;
const BUFFER_AHEAD_CUES = 1;
const TIMESTAMP_EPS = 0.05;

export type Source = 'game' | 'chat';

export type HistoryItem = {
  ts: number;
  text: string;
  event: string;
  importance: number;
  source: Source;
  comment?: { author: string; text: string };
};

export type Score = Record<string, number>;

export type ScoringSnapshot = {
  ts: number;
  g_raw: number;
  g_smoothed: number;
  c_score: number;
  priority_game: number;
  priority_comment: number;
  mode: Source;
  reason: string;
  speak: boolean;
  event: string;
};

type Cue = {
  ts: number;
  text: string;
  audio: { data: string; mime: string }[];
  resolved: boolean;
  fired: boolean;
  isSkip: boolean;
  event: string;
  importance: number;
  source: Source;
  comment?: { author: string; text: string };
};

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

export function useCommentaryWS({ videoRef, language, clipId }: Args) {
  const wsRef = useRef<WebSocket | null>(null);
  const rafRef = useRef<number | null>(null);
  const cuesRef = useRef<Cue[]>([]);
  const pendingCommentRef = useRef<Record<string, { author: string; text: string }>>({});
  const expectedRef = useRef(0);
  const resolvedRef = useRef(0);
  const playingRef = useRef(false);

  const [line, setLine] = useState('');
  const [lineSource, setLineSource] = useState<Source>('game');
  const [chatComment, setChatComment] = useState<{ author: string; text: string } | null>(null);
  const [status, setStatus] = useState('idle');
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [score, setScore] = useState<Score>({});
  const [scoring, setScoring] = useState<ScoringSnapshot | null>(null);

  useEffect(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'config', language, clip_id: clipId }));
    }
  }, [language, clipId]);

  const tick = useCallback(() => {
    const video = videoRef.current;
    if (!video || !playingRef.current) return;
    const t = video.currentTime;
    for (const cue of cuesRef.current) {
      if (!cue.fired && cue.resolved && cue.ts <= t) {
        cue.fired = true;
        if (!cue.isSkip && cue.text) {
          setLine(cue.text);
          setLineSource(cue.source);
          setChatComment(cue.source === 'chat' ? cue.comment ?? null : null);
          setHistory((h) => [
            ...h,
            {
              ts: cue.ts,
              text: cue.text,
              event: cue.event,
              importance: cue.importance,
              source: cue.source,
              comment: cue.comment,
            },
          ]);
          for (const chunk of cue.audio) playPcmChunk(chunk.data, chunk.mime);
        }
      }
    }
    rafRef.current = requestAnimationFrame(tick);
  }, [videoRef]);

  const start = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;

    cuesRef.current = [];
    pendingCommentRef.current = {};
    expectedRef.current = 0;
    resolvedRef.current = 0;
    setLine('');
    setChatComment(null);
    setHistory([]);
    setScore({});
    setScoring(null);

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${window.location.host}/api/ws/commentary`);
    wsRef.current = ws;
    setStatus('connecting…');

    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);

      if (msg.type === 'score') {
        setScore(msg.score);
        return;
      }

      if (msg.type === 'scoring') {
        setScoring(msg as ScoringSnapshot);
        return;
      }

      if (msg.type === 'chat_comment') {
        // The next chat_reaction with the same ts will reference this comment.
        pendingCommentRef.current[String(msg.timestamp)] = {
          author: msg.comment.author,
          text: msg.comment.text,
        };
        return;
      }

      if (typeof msg.timestamp !== 'number') return;
      const cue = cuesRef.current.find((c) => Math.abs(c.ts - msg.timestamp) < TIMESTAMP_EPS);
      if (!cue) return;

      if (msg.type === 'commentary' || msg.type === 'chat_reaction') {
        cue.text = msg.text;
        cue.event = msg.event ?? (msg.type === 'chat_reaction' ? 'chat_reaction' : 'commentary');
        cue.importance = msg.importance ?? 0;
        cue.source = msg.type === 'chat_reaction' ? 'chat' : 'game';
        if (msg.type === 'chat_reaction') {
          cue.comment = {
            author: msg.comment_author,
            text: msg.comment_text,
          };
        } else {
          cue.comment = pendingCommentRef.current[String(msg.timestamp)];
        }
        cue.resolved = true;
        resolvedRef.current += 1;
        bumpStatus();
        maybeStartPlayback();
      } else if (msg.type === 'skip') {
        cue.isSkip = true;
        cue.event = 'skip';
        cue.resolved = true;
        resolvedRef.current += 1;
        bumpStatus();
        maybeStartPlayback();
      } else if (msg.type === 'audio') {
        cue.audio.push({ data: msg.data, mime: msg.mime });
        if (cue.fired && !cue.isSkip) playPcmChunk(msg.data, msg.mime);
      }
    };

    ws.onclose = () => {
      setStatus('disconnected');
      setRunning(false);
      playingRef.current = false;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
    ws.onerror = () => setStatus('error');

    function bumpStatus() {
      if (resolvedRef.current >= expectedRef.current) {
        setStatus('live');
      } else if (playingRef.current) {
        setStatus(`live · processing ${resolvedRef.current}/${expectedRef.current}…`);
      } else {
        setStatus(`preparing ${resolvedRef.current}/${expectedRef.current}…`);
      }
    }

    function maybeStartPlayback() {
      if (playingRef.current) return;
      if (resolvedRef.current < BUFFER_AHEAD_CUES) return;
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

    ws.send(JSON.stringify({ type: 'config', language, clip_id: clipId }));
    setRunning(true);
    setStatus('preparing commentary…');

    video.pause();
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
      resolved: false,
      fired: false,
      isSkip: false,
      event: '',
      importance: 0,
      source: 'game',
    }));
    setStatus(`preparing 0/${stamps.length}…`);

    for (const ts of stamps) {
      await seekTo(video, ts);
      const frame = grabFrame(video);
      if (!frame) continue;
      ws.send(JSON.stringify({ type: 'frame', data: frame, timestamp: ts }));
    }
    await seekTo(video, 0);
  }, [videoRef, language, clipId, tick]);

  const stop = useCallback(() => {
    wsRef.current?.close();
    playingRef.current = false;
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    videoRef.current?.pause();
    setRunning(false);
  }, [videoRef]);

  useEffect(() => () => stop(), [stop]);

  return {
    line,
    lineSource,
    chatComment,
    status,
    start,
    stop,
    running,
    history,
    score,
    scoring,
  };
}
