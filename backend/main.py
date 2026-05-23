"""FastAPI entry point for the sarcastic AI commentator."""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routes import clips, stream
from .services.rocketride_client import CommentaryPipeline

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    pipeline = CommentaryPipeline()
    await pipeline.start()
    app.state.commentary = pipeline
    try:
        yield
    finally:
        await pipeline.stop()


app = FastAPI(title="Sarcastic World Cup Commentator", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(clips.router, prefix="/api/clips", tags=["clips"])
app.include_router(stream.router, prefix="/api", tags=["stream"])


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=os.getenv("BACKEND_HOST", "0.0.0.0"),
        port=int(os.getenv("BACKEND_PORT", "8000")),
        reload=True,
    )
