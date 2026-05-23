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

REQUIRED = ["ROCKETRIDE_APIKEY", "ROCKETRIDE_GMI_APIKEY", "GOOGLE_API_KEY"]


async def main() -> int:
    missing = [k for k in REQUIRED if not os.getenv(k)]
    if missing:
        print(f"missing env vars: {missing}")
        return 1

    print("env: ok")

    pipe = Path(__file__).resolve().parents[1] / "pipelines" / "commentary.pipe"
    if not pipe.exists():
        print(f"pipeline file missing: {pipe}")
        return 1
    print(f"pipeline file: {pipe}")

    try:
        from rocketride import RocketRideClient
        from rocketride.schema import Question
    except ImportError:
        print("rocketride not installed — pip install -r backend/requirements.txt")
        return 1

    async with RocketRideClient() as client:
        result = await client.use(filepath=str(pipe), use_existing=True)
        token = result["token"]
        print(f"pipeline started: {token}")

        q = Question()
        q.addQuestion('{"scene":"Striker shapes to shoot from 25 yards","language":"en"}')
        response = await client.chat(token=token, question=q)
        answers = response.get("answers") or []
        print(f"commentary sample: {answers[:1]}")

    print("all good.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
