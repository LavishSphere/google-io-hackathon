import { RefObject, useCallback, useEffect, useRef, useState } from 'react';
import { grabFrame } from '../lib/frame';
import { playPcmChunk } from '../lib/audio';

type Args = {
  videoRef: RefObject<HTMLVideoElement>;
  language: string;
  clipId?: string;
  disableAutoChat?: boolean;
  match?: string;
};

export type RosterStatus =
  | { state: 'idle' }
  | { state: 'loading'; match?: string }
  | { state: 'ready'; match: string; teams: { name: string; kit_color: string; n_players: number }[] }
  | { state: 'none'; match?: string };

// Higher fps → finer event timing. Each cue is one LLM round-trip on the
// backend, so this also scales pre-roll length. 1.5 fps catches a goal within
// ~330ms of when it happens; 2.0 within 250ms. Beyond that, Gemini RPM
// becomes the bottleneck unless we parallelize the backend.
const SAMPLE_FPS = 1.5;
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

export type FanComment = {
  ts: number;
  text: string;
  author: string;
  controversy: number;
  reactions: number;
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

export function useCommentaryWS({
  videoRef,
  language,
  clipId,
  disableAutoChat = false,
  match,
}: Args) {
  const wsRef = useRef<WebSocket | null>(null);
  const rafRef = useRef<number | null>(null);
  const cuesRef = useRef<Cue[]>([]);
  const pendingCommentRef = useRef<Record<string, { author: string; text: string }>>({});
  const expectedRef = useRef(0);
  const resolvedRef = useRef(0);
  const playingRef = useRef(false);
  // Prevents a double-click of Start (or React StrictMode re-invocation) from
  // opening a second WS and resending every frame — the source of "the AI
  // generated the same line twice" bugs.
  const startingRef = useRef(false);

  const [line, setLine] = useState('');
  const [lineSource, setLineSource] = useState<Source>('game');
  const [chatComment, setChatComment] = useState<{ author: string; text: string } | null>(null);
  const [status, setStatus] = useState('idle');
  const [running, setRunning] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [score, setScore] = useState<Score>({});
  const [scoring, setScoring] = useState<ScoringSnapshot | null>(null);
  const [roster, setRoster] = useState<RosterStatus>({ state: 'idle' });

  // Pre-baked chat feed (all comments) + the subset that's "arrived" by the
  // current playback time. liveChat updates inside the rAF tick.
  const chatFeedRef = useRef<FanComment[]>([]);
  const lastLiveChatTsRef = useRef<number>(-1);
  const [liveChat, setLiveChat] = useState<FanComment[]>([]);
  const [reactingToTs, setReactingToTs] = useState<number | null>(null);

  useEffect(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'config',
        language,
        clip_id: clipId,
        disable_auto_chat: disableAutoChat,
        match,
      }));
    }
  }, [language, clipId, disableAutoChat, match]);

  const tick = useCallback(() => {
    const video = videoRef.current;
    if (!video || !playingRef.current) return;
    const t = video.currentTime;

    // Fire commentary cues whose ts has been reached.
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
          if (cue.source === 'chat' && cue.comment) {
            // Find the matching feed comment by text+author and highlight it.
            const match = chatFeedRef.current.find(
              (c) => c.text === cue.comment?.text && c.author === cue.comment?.author
            );
            if (match) setReactingToTs(match.ts);
          }
        }
      }
    }

    // Reveal pre-baked fan comments at their scheduled ts (Twitch-style feed).
    if (chatFeedRef.current.length > 0) {
      const newlyVisible: FanComment[] = [];
      for (const c of chatFeedRef.current) {
        if (c.ts <= t && c.ts > lastLiveChatTsRef.current) {
          newlyVisible.push(c);
        }
      }
      if (newlyVisible.length > 0) {
        lastLiveChatTsRef.current = newlyVisible[newlyVisible.length - 1].ts;
        setLiveChat((prev) => [...prev, ...newlyVisible]);
      }
    }

    rafRef.current = requestAnimationFrame(tick);
  }, [videoRef]);

  const start = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;
    if (startingRef.current) return;  // re-entry guard
    if (wsRef.current && wsRef.current.readyState !== WebSocket.CLOSED) {
      // Already have a live socket — don't open a second one.
      return;
    }
    startingRef.current = true;

    cuesRef.current = [];
    pendingCommentRef.current = {};
    expectedRef.current = 0;
    resolvedRef.current = 0;
    chatFeedRef.current = [];
    lastLiveChatTsRef.current = -1;
    setLine('');
    setChatComment(null);
    setHistory([]);
    setScore({});
    setScoring(null);
    setRoster({ state: 'idle' });
    setLiveChat([]);
    setReactingToTs(null);

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

      if (msg.type === 'roster_status') {
        setRoster(msg as RosterStatus);
        return;
      }

      if (msg.type === 'chat_feed') {
        chatFeedRef.current = (msg.comments || []) as FanComment[];
        lastLiveChatTsRef.current = -1;
        setLiveChat([]);
        setReactingToTs(null);
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
        // Audio arrival for cue 0 is the gating signal for first playback.
        maybeStartPlayback();
      }
    };

    ws.onclose = () => {
      // Don't kill the dispatcher just because the WS closed mid-clip — we
      // already have cues buffered. Let the rAF loop drain them so any audio
      // we already received still plays at the right moment. Only mark the
      // session as disconnected (no more frames will be sent) — running stays
      // true so the user can keep watching what's already loaded.
      if (playingRef.current) {
        setStatus('live (ws closed) — playing buffered commentary');
      } else {
        setStatus('disconnected');
        setRunning(false);
        if (rafRef.current) cancelAnimationFrame(rafRef.current);
      }
    };
    ws.onerror = () => setStatus('ws error (still playing buffered commentary)');

    function bumpStatus() {
      if (resolvedRef.current >= expectedRef.current) {
        setStatus('live');
      } else if (playingRef.current) {
        setStatus(`live · processing ${resolvedRef.current}/${expectedRef.current}…`);
      } else {
        setStatus(`preparing ${resolvedRef.current}/${expectedRef.current}…`);
      }
    }

    function firstCueReady(): boolean {
      // Only start playback once the FIRST cue is fully ready to fire.
      // Skip cues count as ready (no audio needed). A real commentary cue
      // needs BOTH its text and at least one audio chunk in hand — otherwise
      // the viewer sees the subtitle pop in with no voice for ~700ms.
      const cues = cuesRef.current;
      if (cues.length === 0) return false;
      const first = cues[0];
      if (!first.resolved) return false;
      if (first.isSkip) return true;
      if (!first.text) return false;
      if (first.audio.length === 0) return false;
      return true;
    }

    function maybeStartPlayback() {
      if (playingRef.current) return;
      if (!firstCueReady()) return;
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

    ws.send(JSON.stringify({
      type: 'config',
      language,
      clip_id: clipId,
      disable_auto_chat: disableAutoChat,
      match,
    }));
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

    try {
      for (const ts of stamps) {
        if (ws.readyState !== WebSocket.OPEN) break;  // bail if socket died mid-sweep
        await seekTo(video, ts);
        const frame = grabFrame(video);
        if (!frame) continue;
        ws.send(JSON.stringify({ type: 'frame', data: frame, timestamp: ts }));
      }
      await seekTo(video, 0);
    } finally {
      startingRef.current = false;
    }
  }, [videoRef, language, clipId, disableAutoChat, match, tick]);

  // Operator-injected fan comment. Pauses video at the injection point so the
  // AI's reaction lands exactly when the moment "happened", then resumes once
  // the reaction's commentary cue has fired.
  const injectComment = useCallback(
    (text: string, author: string = '@you') => {
      const ws = wsRef.current;
      const video = videoRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN || !video) return;
      const trimmed = text.trim();
      if (!trimmed) return;

      const ts = +video.currentTime.toFixed(3);
      // Add an ad-hoc cue at the injection point. The chat_reaction message
      // arrival will populate it; rAF fires it as soon as the playhead is on
      // (or past) ts.
      cuesRef.current.push({
        ts,
        text: '',
        audio: [],
        resolved: false,
        fired: false,
        isSkip: false,
        event: 'manual_inject',
        importance: 0,
        source: 'chat',
        comment: { author, text: trimmed },
      });

      // Hold the video here so the reaction lands at the exact paused moment.
      const wasPaused = video.paused;
      video.pause();

      const watcher = () => {
        const cue = cuesRef.current.find((c) => Math.abs(c.ts - ts) < TIMESTAMP_EPS);
        if (cue?.fired) {
          if (!wasPaused) video.play().catch(() => {});
          clearInterval(handle);
        }
      };
      const handle = window.setInterval(watcher, 120);

      ws.send(JSON.stringify({
        type: 'inject_comment',
        text: trimmed,
        author,
        timestamp: ts,
      }));
    },
    [videoRef]
  );

  const stop = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    playingRef.current = false;
    startingRef.current = false;
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
    injectComment,
    roster,
    liveChat,
    reactingToTs,
  };
}
