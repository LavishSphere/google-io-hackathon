import { Source } from '../hooks/useCommentaryWS';

type Props = {
  line: string;
  source: Source;
  chatComment?: { author: string; text: string } | null;
};

export default function CommentaryOverlay({ line, source, chatComment }: Props) {
  return (
    <div className="overlay">
      {source === 'chat' && chatComment && (
        <div className="overlay-chat-context">
          <span className="overlay-chat-author">{chatComment.author}</span>
          <span className="overlay-chat-text">{chatComment.text}</span>
        </div>
      )}
      <div className="overlay-line">
        <span className={`overlay-source overlay-source-${source}`}>
          {source === 'chat' ? 'reacting to chat' : 'on the pitch'}
        </span>
        <span className="overlay-text">{line || '…'}</span>
      </div>
    </div>
  );
}
