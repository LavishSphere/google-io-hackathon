import { useEffect, useRef, useState } from 'react';
import VideoPlayer from './components/VideoPlayer';
import CommentaryOverlay from './components/CommentaryOverlay';
import LanguageToggle from './components/LanguageToggle';
import Scoreboard from './components/Scoreboard';
import CommentaryHistory from './components/CommentaryHistory';
import ScoringMeter from './components/ScoringMeter';
import CommentInjector from './components/CommentInjector';
import LiveChat from './components/LiveChat';
import { useCommentaryWS } from './hooks/useCommentaryWS';

type Clip = { id: string; filename: string; url: string };

export default function App() {
  const [clips, setClips] = useState<Clip[]>([]);
  const [selectedClip, setSelectedClip] = useState<Clip | null>(null);
  const [language, setLanguage] = useState<string>('en');
  const [disableAutoChat, setDisableAutoChat] = useState<boolean>(false);
  const [match, setMatch] = useState<string>('2022 FIFA World Cup Final — Argentina vs France');
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
    injectComment,
    roster,
    liveChat,
    reactingToTs,
  } = useCommentaryWS({
    videoRef,
    language,
    clipId: selectedClip?.id,
    disableAutoChat,
    match,
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
          <div className="subtitle">Gemini 3.1 Flash Lite · Google AI Studio · Gemini Live TTS</div>
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

            <input
              className="match-input"
              placeholder='Match (e.g. "Spain vs Germany, World Cup 2026 final")'
              value={match}
              onChange={(e) => setMatch(e.target.value)}
              disabled={running}
              title="Used to fetch the roster via Gemini grounded search. Optional but recommended — without it the AI can't name players."
            />

            <button className="btn" onClick={running ? stop : start} disabled={!selectedClip}>
              {running ? 'Stop' : 'Start commentary'}
            </button>

            <label className="auto-chat-toggle" title="When off, the pre-baked fan-comment feed is ignored. Only your manually injected comments trigger chat reactions.">
              <input
                type="checkbox"
                checked={!disableAutoChat}
                onChange={(e) => setDisableAutoChat(!e.target.checked)}
              />
              auto chat
            </label>

            <span className="status">{status}</span>
          </div>

          {roster.state !== 'idle' && (
            <div className={`roster-status roster-status-${roster.state}`}>
              {roster.state === 'loading' && <>📋 looking up roster for <em>{roster.match || 'this match'}</em>…</>}
              {roster.state === 'ready' && (
                <>
                  📋 roster loaded: <strong>{roster.match}</strong>
                  {' — '}
                  {roster.teams.map((t, i) => (
                    <span key={t.name}>
                      {t.name} ({t.kit_color}, {t.n_players})
                      {i < roster.teams.length - 1 && ' vs '}
                    </span>
                  ))}
                </>
              )}
              {roster.state === 'none' && <>📋 no roster — player names won't be used. Add a match string above to enable.</>}
            </div>
          )}

          <CommentInjector onSend={injectComment} disabled={!running} />

          <ScoringMeter scoring={scoring} />
        </div>

        <aside className="stage-side">
          <div className="side-title">Live chat</div>
          <LiveChat items={liveChat} reactingToTs={reactingToTs} />
          <div className="side-title side-title-secondary">Commentary log</div>
          <CommentaryHistory items={history} />
        </aside>
      </div>
    </div>
  );
}
