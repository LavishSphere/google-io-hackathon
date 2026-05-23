import { useEffect, useRef, useState } from 'react';
import VideoPlayer from './components/VideoPlayer';
import CommentaryOverlay from './components/CommentaryOverlay';
import LanguageToggle from './components/LanguageToggle';
import { useCommentaryWS } from './hooks/useCommentaryWS';

type Clip = { id: string; filename: string; url: string };

export default function App() {
  const [clips, setClips] = useState<Clip[]>([]);
  const [selectedClip, setSelectedClip] = useState<Clip | null>(null);
  const [language, setLanguage] = useState<string>('en');
  const videoRef = useRef<HTMLVideoElement>(null);

  const { line, status, start, stop, running } = useCommentaryWS({
    videoRef,
    language,
  });

  useEffect(() => {
    fetch('/api/clips/')
      .then((r) => r.json())
      .then((data: Clip[]) => {
        setClips(data);
        if (data.length && !selectedClip) setSelectedClip(data[0]);
      })
      .catch(() => setClips([]));
  }, []);

  return (
    <div className="app">
      <header className="header">
        <div>
          <div className="title">Sarcastic World Cup Commentator</div>
          <div className="subtitle">Gemini 3.1 Flash Lite · GMI Cloud · RocketRide · NVIDIA</div>
        </div>
        <LanguageToggle value={language} onChange={setLanguage} />
      </header>

      <div className="player-wrap">
        <VideoPlayer ref={videoRef} src={selectedClip?.url ?? ''} />
        <CommentaryOverlay line={line} />
      </div>

      <div className="controls">
        <select
          className="clip-select"
          value={selectedClip?.id ?? ''}
          onChange={(e) => {
            const c = clips.find((x) => x.id === e.target.value) ?? null;
            setSelectedClip(c);
          }}
        >
          {clips.length === 0 && <option value="">No clips found — drop .mp4 files into demo_clips/</option>}
          {clips.map((c) => (
            <option key={c.id} value={c.id}>{c.filename}</option>
          ))}
        </select>

        <button className="btn" onClick={running ? stop : start} disabled={!selectedClip}>
          {running ? 'Stop' : 'Start commentary'}
        </button>

        <span className="status">{status}</span>
      </div>
    </div>
  );
}
