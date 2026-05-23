"""Wraps the RocketRide commentary pipeline as a long-lived service.

Pipeline started once at app boot; each request reuses the same token.
See ROCKETRIDE_COMMON_MISTAKES.md (Mistake 9) for why.
"""

import json
import logging
from pathlib import Path

from rocketride import RocketRideClient
from rocketride.schema import Question

log = logging.getLogger(__name__)

_PIPELINE_PATH = Path(__file__).resolve().parents[2] / "pipelines" / "commentary.pipe"


class CommentaryPipeline:
    def __init__(self) -> None:
        self._client: RocketRideClient | None = None
        self._token: str | None = None

    async def start(self) -> None:
        self._client = RocketRideClient()
        await self._client.connect()
        result = await self._client.use(
            filepath=str(_PIPELINE_PATH),
            use_existing=True,
        )
        self._token = result["token"]
        log.info("RocketRide commentary pipeline ready (token=%s)", self._token)

    async def stop(self) -> None:
        if self._client:
            try:
                if self._token:
                    await self._client.terminate(self._token)
            finally:
                await self._client.disconnect()

    async def commentate(self, scene: str, language: str = "en") -> str | None:
        if not self._client or not self._token:
            return None

        payload = json.dumps({"scene": scene, "language": language})
        question = Question()
        question.addQuestion(payload)
        question.addInstruction(
            "Language",
            f"Respond natively in language code '{language}'. Do not translate from English.",
        )

        response = await self._client.chat(token=self._token, question=question)
        answers = response.get("answers") or []
        if not answers:
            return None
        first = answers[0]
        return first if isinstance(first, str) else str(first)
