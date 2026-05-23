import { ScoringSnapshot } from '../hooks/useCommentaryWS';

type Props = { scoring: ScoringSnapshot | null };

function clamp(n: number, lo = 0, hi = 100): number {
  return Math.max(lo, Math.min(hi, n));
}

export default function ScoringMeter({ scoring }: Props) {
  if (!scoring) {
    return <div className="meter meter-empty">scoring will appear here…</div>;
  }
  const g = clamp(scoring.g_smoothed);
  const c = clamp(scoring.c_score);
  const winnerGame = scoring.mode === 'game';

  return (
    <div className="meter">
      <div className="meter-row">
        <div className="meter-label">
          <span>game (G)</span>
          <span className="meter-val">{g.toFixed(0)}</span>
        </div>
        <div className="meter-bar">
          <div
            className={`meter-fill meter-fill-game ${winnerGame ? 'is-winner' : ''}`}
            style={{ width: `${g}%` }}
          />
        </div>
      </div>
      <div className="meter-row">
        <div className="meter-label">
          <span>chat (C)</span>
          <span className="meter-val">{c.toFixed(0)}</span>
        </div>
        <div className="meter-bar">
          <div
            className={`meter-fill meter-fill-chat ${!winnerGame ? 'is-winner' : ''}`}
            style={{ width: `${c}%` }}
          />
        </div>
      </div>
      <div className="meter-meta">
        <span className={`meter-mode meter-mode-${scoring.mode}`}>{scoring.mode}</span>
        <span className="meter-reason">{scoring.reason}</span>
        {!scoring.speak && <span className="meter-silent">silent</span>}
      </div>
    </div>
  );
}
