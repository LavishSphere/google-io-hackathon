"""ffmpeg-based frame sampler — used for server-side clip preprocessing.

The live demo path samples frames in the browser (canvas → base64 JPEG) so the
backend just receives them via WebSocket. This module exists for offline
preprocessing of demo clips into still galleries for debugging the prompt.
"""

import base64
import io
from pathlib import Path
from typing import Iterator

import cv2
from PIL import Image


def sample_frames(video_path: Path, fps: float = 1.5) -> Iterator[bytes]:
    """Yield JPEG bytes at the requested sample rate."""
    cap = cv2.VideoCapture(str(video_path))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    stride = max(1, int(round(src_fps / fps)))
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                return
            if idx % stride == 0:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                buf = io.BytesIO()
                Image.fromarray(rgb).save(buf, format="JPEG", quality=80)
                yield buf.getvalue()
            idx += 1
    finally:
        cap.release()


def to_base64(jpeg_bytes: bytes) -> str:
    return base64.b64encode(jpeg_bytes).decode()
