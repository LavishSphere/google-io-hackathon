import { useEffect, useRef, useState } from 'react';
import VideoPlayer from './components/VideoPlayer';
import CommentaryOverlay from './components/CommentaryOverlay';
import LanguageToggle from './components/LanguageToggle';
import Scoreboard from './components/Scoreboard';
import CommentaryHistory from './components/CommentaryHistory';
import ScoringMeter from './components/ScoringMeter';
import { useCommentaryWS } from './hooks/useCommentaryWS';

type Clip = { id: string; filename: string; url: string };

export default function App() {
  const [clips, setClips] = useState<Clip[]>([]);
  const [selectedClip, setSelectedClip] = useState<Clip | null>(null);
  const [language, setLanguage] = useState<string>('en');
  const videoRef = useRef<HTMLVideoElement>(null);

  const {
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
  } = useCommentaryWS({
    videoRef,
    language,
    clipId: selectedClip?.id,
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
          <div className="subtitle">Gemma 4 31B · GMI Cloud · NVIDIA H100 · Google Gemini Vision</div>
        </div>
        <LanguageToggle value={language} onChange={setLanguage} />
      </header>

      <div className="stage">
        <div className="stage-main">
          <div className="player-wrap">
            <VideoPlayer ref={videoRef} src={selectedClip?.url ?? ''} />
            <Scoreboard score={score} />
            <CommentaryOverlay line={line} source={lineSource} chatComment={chatComment} />
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

          <ScoringMeter scoring={scoring} />
        </div>

        <aside className="stage-side">
          <div className="side-title">Commentary log</div>
          <CommentaryHistory items={history} />
        </aside>
      </div>
    </div>
  );
}
