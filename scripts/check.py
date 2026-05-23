"""Smoke test: verify .env, the RocketRide pipeline, and Gemini both work.

Run after installing deps:
    python -m scripts.check
"""

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REQUIRED = ["ROCKETRIDE_GMI_APIKEY", "GOOGLE_API_KEY"]


async def main() -> int:
    missing = [k for k in REQUIRED if not os.getenv(k)]
    if missing:
        print(f"missing env vars: {missing}")
        return 1

    print("env: ok")

    from backend.services.rocketride_client import CommentaryPipeline

    pipeline = CommentaryPipeline()
    await pipeline.start()
    try:
        line = await pipeline.commentate(
            scene="Striker shapes to shoot from 25 yards, defender slips",
            language="en",
        )
        print(f"commentary: {line!r}")
        if not line:
            print("(no commentary — check the GMI key, base url, or model name)")
            return 1
    finally:
        await pipeline.stop()

    print("all good.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
