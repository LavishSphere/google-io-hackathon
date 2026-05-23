import { Score } from '../hooks/useCommentaryWS';

type Props = { score: Score };

export default function Scoreboard({ score }: Props) {
  const entries = Object.entries(score);
  if (entries.length === 0) return null;
  return (
    <div className="scoreboard">
      {entries.map(([team, n]) => (
        <div key={team} className="scoreboard-team">
          <span className="scoreboard-team-name">{team}</span>
          <span className="scoreboard-team-score">{n}</span>
        </div>
      ))}
    </div>
  );
}
