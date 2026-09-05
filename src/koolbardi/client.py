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
        limits = httpx.Limits(
            max_connections=config.concurrency_per_server,
            max_keepalive_connections=config.concurrency_per_server,
        )
        self._clients = {
            url: httpx.AsyncClient(timeout=config.timeout_seconds, limits=limits)
            for url in config.base_urls
        }

    async def aclose(self) -> None:
        await asyncio.gather(*(client.aclose() for client in self._clients.values()))

    async def _post(self, endpoint: str, payload: dict[str, Any]) -> dict:
        url = next(self._urls).rstrip("/")
        async with self._semaphores[url]:
            headers = {"Authorization": f"Bearer {self.config.api_key}"}
            last_error: BaseException | None = None
            for attempt in range(self.config.max_retries):
                try:
                    response = await self._clients[url].post(
                        f"{url}{endpoint}", headers=headers, json=payload
                    )
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
        self,
        messages: list[dict],
        sampling: SamplingConfig,
        seed: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> str:
        result = await self.chat_result(messages, sampling, seed, json_schema=json_schema)
        return result["content"]

    async def chat_result(
        self,
        messages: list[dict],
        sampling: SamplingConfig,
        seed: int | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "temperature": sampling.temperature,
            "top_p": sampling.top_p,
            "max_tokens": sampling.max_tokens,
            "seed": seed,
        }
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "koolbardi_structured_output",
                    "schema": json_schema,
                    "strict": True,
                },
            }
        result = await self._post(
            "/v1/chat/completions",
            payload,
        )
        choice = result["choices"][0]
        return {
            "content": choice["message"]["content"],
            "finish_reason": choice.get("finish_reason"),
        }

    async def chat_json(
        self,
        messages: list[dict],
        sampling: SamplingConfig,
        json_schema: dict[str, Any],
        seed: int | None = None,
    ) -> dict[str, Any]:
        result = await self.chat_result(
            messages, sampling, seed, json_schema=json_schema
        )
        if result["finish_reason"] != "stop":
            raise ValueError(
                f"structured generation did not finish: {result['finish_reason']!r}"
            )
        parsed = json.loads(result["content"])
        if not isinstance(parsed, dict):
            raise ValueError("structured generation returned a non-object JSON value")
        return parsed


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
