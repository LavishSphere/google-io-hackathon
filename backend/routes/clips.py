"""Demo-clip catalogue served to the frontend."""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter()

CLIPS_DIR = Path(__file__).resolve().parents[2] / "demo_clips"


@router.get("/")
async def list_clips() -> list[dict]:
    if not CLIPS_DIR.exists():
        return []
    return [
        {"id": p.stem, "filename": p.name, "url": f"/api/clips/{p.name}"}
        for p in sorted(CLIPS_DIR.glob("*.mp4"))
    ]


@router.get("/{filename}")
async def get_clip(filename: str):
    path = CLIPS_DIR / filename
    if not path.exists() or path.suffix != ".mp4":
        return {"error": "not found"}
    return FileResponse(path, media_type="video/mp4")
