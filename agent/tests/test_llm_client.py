import json

import httpx
import pytest

from app.llm import LLMError, Usage
from app.llm.openai_compat import OpenAICompatClient

OK = {
    "choices": [
        {
            "finish_reason": "stop",
            "message": {"content": "\n\n```sql\nSELECT 1\n```", "reasoning_content": "생각"},
        }
    ],
    "usage": {"prompt_tokens": 12, "completion_tokens": 8, "reasoning_tokens": 5},
}


def _client(handler, **kwargs) -> OpenAICompatClient:
    return OpenAICompatClient(
        base_url="https://llm.test/v1",
        api_key="k",
        model="m",
        default_params={"temperature": 1.0},
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def test_sends_openai_compatible_request_and_parses_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK)

    client = _client(handler)
    result = await client.chat(
        [{"role": "user", "content": "q"}], max_tokens=100, reasoning_effort="low", top_p=None
    )

    assert seen["url"] == "https://llm.test/v1/chat/completions"
    assert seen["auth"] == "Bearer k"
    assert seen["body"] == {
        "model": "m",
        "messages": [{"role": "user", "content": "q"}],
        "stream": False,
        "temperature": 1.0,
        "reasoning_effort": "low",
        "max_tokens": 100,
    }
    assert result.content == "```sql\nSELECT 1\n```"
    assert result.reasoning == "생각"
    assert result.usage == Usage(12, 8, 5)


async def test_retries_rate_limit_using_retry_after():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"retry-after-ms": "10"}, json={})
        return httpx.Response(200, json=OK)

    result = await _client(handler).chat([{"role": "user", "content": "q"}])
    assert len(attempts) == 2
    assert result.finish_reason == "stop"


async def test_raises_on_client_error_without_retry():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(401, json={"detail": "invalid key"})

    with pytest.raises(LLMError) as e:
        await _client(handler).chat([{"role": "user", "content": "q"}])
    assert e.value.status == 401
    assert len(attempts) == 1


async def test_gives_up_after_max_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, headers={"retry-after-ms": "1"}, json={})

    with pytest.raises(LLMError) as e:
        await _client(handler, max_retries=2).chat([{"role": "user", "content": "q"}])
    assert e.value.status == 503
