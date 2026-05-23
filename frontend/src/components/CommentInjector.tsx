import { useState } from 'react';

type Props = {
  onSend: (text: string, author: string) => void;
  disabled?: boolean;
};

const PRESETS = [
  { author: '@hot_take_henrik', text: "the keeper is having flashbacks to qualifiers" },
  { author: '@var_obsessed',    text: "I swear that was offside three replays ago" },
  { author: '@dad_at_pub',      text: "my pint has more shape than that pass" },
  { author: '@grandpa_united',  text: "kids these days call THIS a counter-attack?" },
  { author: '@spicy_susan',     text: "if HE makes the highlight reel I'm cancelling my subscription" },
];

export default function CommentInjector({ onSend, disabled }: Props) {
  const [text, setText] = useState('');
  const [author, setAuthor] = useState('@you');

  const submit = () => {
    if (!text.trim()) return;
    onSend(text, author || '@you');
    setText('');
  };

  return (
    <div className="injector">
      <div className="injector-row">
        <input
          className="injector-author"
          placeholder="@author"
          value={author}
          onChange={(e) => setAuthor(e.target.value)}
          disabled={disabled}
        />
        <input
          className="injector-text"
          placeholder="type a fan comment for the AI to react to…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          disabled={disabled}
        />
        <button className="btn btn-inject" onClick={submit} disabled={disabled}>
          Send
        </button>
      </div>
      <div className="injector-presets">
        {PRESETS.map((p, i) => (
          <button
            key={i}
            className="injector-preset"
            disabled={disabled}
            onClick={() => onSend(p.text, p.author)}
            title={`${p.author}: ${p.text}`}
          >
            {p.author}
          </button>
        ))}
      </div>
    </div>
  );
}
