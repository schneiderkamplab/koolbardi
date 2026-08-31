from __future__ import annotations

import asyncio
import json
from itertools import cycle
from typing import Any, Awaitable, Callable, TypeVar

import httpx

from .config import SamplingConfig, ServerConfig

T = TypeVar("T")


class OpenAIClientPool:
    def __init__(self, config: ServerConfig):
        self.config = config
        self._urls = cycle(config.base_urls)
        self._semaphores = {
            url: asyncio.Semaphore(config.concurrency_per_server) for url in config.base_urls
        }

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict:
        url = next(self._urls).rstrip("/")
        async with self._semaphores[url]:
            headers = {"Authorization": f"Bearer {self.config.api_key}"}
            last_error: BaseException | None = None
            for attempt in range(self.config.max_retries):
                try:
                    async with httpx.AsyncClient(timeout=self.config.timeout_seconds) as client:
                        response = await client.post(f"{url}{endpoint}", headers=headers, json=payload)
                        response.raise_for_status()
                        return response.json()
                except (httpx.HTTPError, KeyError, ValueError) as exc:
                    last_error = exc
                    if attempt + 1 < self.config.max_retries:
                        await asyncio.sleep(min(30.0, 2.0**attempt))
            raise RuntimeError(
                f"OpenAI-compatible request failed after {self.config.max_retries} attempts at {url}{endpoint}"
            ) from last_error

    async def completion(
        self, prompt: str | list[int], sampling: SamplingConfig, stop: list[str], seed: int | None = None
    ) -> str:
        result = await self._post(
            "/v1/completions",
            {
                "model": self.config.model,
                "prompt": prompt,
                "temperature": sampling.temperature,
                "top_p": sampling.top_p,
                "max_tokens": sampling.max_tokens,
                "stop": stop,
                "seed": seed,
            },
        )
        return result["choices"][0]["text"]

    async def chat(
        self, messages: list[dict], sampling: SamplingConfig, seed: int | None = None
    ) -> str:
        result = await self._post(
            "/v1/chat/completions",
            {
                "model": self.config.model,
                "messages": messages,
                "temperature": sampling.temperature,
                "top_p": sampling.top_p,
                "max_tokens": sampling.max_tokens,
                "seed": seed,
            },
        )
        return result["choices"][0]["message"]["content"]


async def gather_bounded(items: list[T], fn: Callable[[T], Awaitable[Any]], concurrency: int) -> list[Any]:
    semaphore = asyncio.Semaphore(concurrency)

    async def run(item: T) -> Any:
        async with semaphore:
            return await fn(item)

    return await asyncio.gather(*(run(item) for item in items), return_exceptions=True)


def parse_json_object(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("audit response contains no JSON object")
    return json.loads(text[start : end + 1])
