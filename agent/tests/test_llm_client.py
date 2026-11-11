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


async def test_sends_tools_and_parses_tool_calls():
    seen = {}
    reply = {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "run_sql", "arguments": '{"sql": "SELECT 1"}'},
                        },
                        {"type": "function", "function": {"name": "x", "arguments": {"a": 1}}},
                    ],
                },
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=reply)

    tools = [{"type": "function", "function": {"name": "run_sql", "parameters": {}}}]
    result = await _client(handler).chat(
        [{"role": "user", "content": "q"}], tools=tools, tool_choice="required"
    )

    assert seen["body"]["tools"] == tools
    assert seen["body"]["tool_choice"] == "required"
    assert [(c.id, c.name, c.arguments) for c in result.tool_calls] == [
        ("call_1", "run_sql", '{"sql": "SELECT 1"}'),
        ("call_1", "x", '{"a": 1}'),  # id 가 없으면 순번으로 만들고, 객체 인자는 JSON 으로 바꾼다
    ]
    assert result.assistant_message() == {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "run_sql", "arguments": '{"sql": "SELECT 1"}'},
            },
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "x", "arguments": '{"a": 1}'},
            },
        ],
    }


async def test_omits_tool_fields_without_tools():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=OK)

    await _client(handler).chat([{"role": "user", "content": "q"}], tool_choice="required")
    assert "tools" not in seen["body"] and "tool_choice" not in seen["body"]


async def test_reports_rate_limit_wait():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"retry-after-ms": "30"}, json={})
        return httpx.Response(200, json=OK)

    result = await _client(handler).chat([{"role": "user", "content": "q"}])
    assert result.wait_ms >= 30


async def test_does_not_retry_daily_limit():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        body = {"error": {"message": "Rate limit reached on tokens per day (TPD)"}}
        return httpx.Response(429, headers={"retry-after": "1"}, json=body)

    with pytest.raises(LLMError) as e:
        await _client(handler).chat([{"role": "user", "content": "q"}])
    assert e.value.status == 429
    assert len(attempts) == 1
