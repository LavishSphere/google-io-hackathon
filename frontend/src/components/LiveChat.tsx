import { useEffect, useRef } from 'react';
import { FanComment } from '../hooks/useCommentaryWS';

type Props = {
  items: FanComment[];
  reactingToTs: number | null;
};

function formatTs(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export default function LiveChat({ items, reactingToTs }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ref.current?.scrollTo({ top: ref.current.scrollHeight, behavior: 'smooth' });
  }, [items.length]);

  return (
    <div className="live-chat" ref={ref}>
      {items.length === 0 && (
        <div className="live-chat-empty">fan tweets will appear here as the match plays…</div>
      )}
      {items.map((item, i) => {
        const reacted = reactingToTs !== null && Math.abs(item.ts - reactingToTs) < 0.01;
        return (
          <div key={`${item.ts}-${i}`} className={`live-chat-item ${reacted ? 'live-chat-reacted' : ''}`}>
            <div className="live-chat-row">
              <span className="live-chat-author">{item.author}</span>
              <span className="live-chat-ts">{formatTs(item.ts)}</span>
              {item.reactions > 0 && (
                <span className="live-chat-reactions">♥ {item.reactions}</span>
              )}
              {reacted && <span className="live-chat-badge">AI replied</span>}
            </div>
            <div className="live-chat-text">{item.text}</div>
          </div>
        );
      })}
    </div>
  );
}
