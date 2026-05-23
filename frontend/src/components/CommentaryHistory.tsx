import { useEffect, useRef } from 'react';
import { HistoryItem } from '../hooks/useCommentaryWS';

type Props = { items: HistoryItem[] };

function formatTs(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function CommentaryHistory({ items }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' });
  }, [items.length]);

  return (
    <div className="history" ref={ref}>
      {items.length === 0 && <div className="history-empty">commentary will appear here…</div>}
      {items.map((item, i) => (
        <div key={i} className={`history-item history-item-${item.source}`}>
          <div className="history-meta">
            <span className="history-ts">{formatTs(item.ts)}</span>
            <span className={`history-event history-event-${item.event}`}>{item.event}</span>
            <span className={`history-source history-source-${item.source}`}>{item.source}</span>
          </div>
          {item.source === 'chat' && item.comment && (
            <div className="history-comment">
              <span className="history-comment-author">{item.comment.author}</span>
              <span className="history-comment-text">“{item.comment.text}”</span>
            </div>
          )}
          <div className="history-text">{item.text}</div>
        </div>
      ))}
    </div>
  );
}
