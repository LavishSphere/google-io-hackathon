type Props = { line: string };

export default function CommentaryOverlay({ line }: Props) {
  return <div className="overlay">{line || '...'}</div>;
}
