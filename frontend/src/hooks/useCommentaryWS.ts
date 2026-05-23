import { RefObject, useCallback, useEffect, useRef, useState } from 'react';
import { grabFrame } from '../lib/frame';
import { playPcmChunk } from '../lib/audio';

type Args = {
  videoRef: RefObject<HTMLVideoElement>;
  language: string;
};

const SAMPLE_INTERVAL_MS = 700;

export function useCommentaryWS({ videoRef, language }: Args) {
  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | null>(null);
  const [line, setLine] = useState('');
  const [status, setStatus] = useState('idle');
  const [running, setRunning] = useState(false);

  // Re-send language when it changes mid-session.
  useEffect(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'config', language }));
    }
  }, [language]);

  const start = useCallback(async () => {
    const video = videoRef.current;
    if (!video) return;

    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${window.location.host}/api/ws/commentary`);
    wsRef.current = ws;
    setStatus('connecting…');

    ws.onopen = () => {
      setStatus('live');
      setRunning(true);
      ws.send(JSON.stringify({ type: 'config', language }));
      video.play().catch(() => {});

      timerRef.current = window.setInterval(async () => {
        if (video.paused || video.ended) return;
        const frame = grabFrame(video);
        if (!frame) return;
        ws.send(JSON.stringify({
          type: 'frame',
          data: frame,
          timestamp: video.currentTime,
        }));
      }, SAMPLE_INTERVAL_MS);
    };

    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === 'commentary') {
        setLine(msg.text);
      } else if (msg.type === 'audio') {
        playPcmChunk(msg.data, msg.mime);
      }
    };

    ws.onclose = () => {
      setStatus('disconnected');
      setRunning(false);
      if (timerRef.current) window.clearInterval(timerRef.current);
    };

    ws.onerror = () => setStatus('error');
  }, [videoRef, language]);

  const stop = useCallback(() => {
    wsRef.current?.close();
    if (timerRef.current) window.clearInterval(timerRef.current);
    videoRef.current?.pause();
    setRunning(false);
  }, [videoRef]);

  useEffect(() => () => stop(), [stop]);

  return { line, status, start, stop, running };
}
