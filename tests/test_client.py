import asyncio

from koolbardi.client import OpenAIClientPool
from koolbardi.config import SamplingConfig, ServerConfig


def test_chat_json_requests_strict_json_schema(monkeypatch):
    pool = OpenAIClientPool(ServerConfig(base_urls=["http://localhost:1"], model="test"))
    captured = {}

    async def fake_post(endpoint, payload):
        captured.update(payload)
        return {
            "choices": [{
                "message": {"content": '{"accepted":true}'},
                "finish_reason": "stop",
            }]
        }

    monkeypatch.setattr(pool, "_post", fake_post)
    result = asyncio.run(pool.chat_json(
        [{"role": "user", "content": "Judge this"}],
        SamplingConfig(),
        {
            "type": "object",
            "properties": {"accepted": {"type": "boolean"}},
            "required": ["accepted"],
            "additionalProperties": False,
        },
    ))
    asyncio.run(pool.aclose())

    assert result == {"accepted": True}
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
