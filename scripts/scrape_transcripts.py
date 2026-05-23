"""Pull captions from a list of YouTube URLs into backend/data/transcripts/.

Used to build a few-shot persona corpus (sarcastic commentator clips, MOTD
parodies, etc.). NOT for fine-tuning — just for seeding the system prompt
and an optional RAG store later.

Usage:
    python scripts/scrape_transcripts.py urls.txt

`urls.txt` is one YouTube URL per line. Skips videos with no captions.
"""

import re
import sys
from pathlib import Path

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    print("pip install youtube-transcript-api", file=sys.stderr)
    raise

OUT_DIR = Path(__file__).resolve().parents[1] / "backend" / "data" / "transcripts"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def video_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|shorts/)([\w-]{11})", url)
    return m.group(1) if m else None


def main(list_path: str) -> None:
    urls = [u.strip() for u in Path(list_path).read_text().splitlines() if u.strip()]
    for url in urls:
        vid = video_id(url)
        if not vid:
            print(f"skip (no id): {url}")
            continue
        out = OUT_DIR / f"{vid}.txt"
        if out.exists():
            print(f"have: {vid}")
            continue
        try:
            chunks = YouTubeTranscriptApi.get_transcript(vid)
            text = "\n".join(c["text"] for c in chunks)
            out.write_text(text)
            print(f"saved: {vid} ({len(text)} chars)")
        except Exception as e:
            print(f"fail: {vid} — {e}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/scrape_transcripts.py urls.txt")
        sys.exit(1)
    main(sys.argv[1])
