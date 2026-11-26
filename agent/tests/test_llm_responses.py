import json

import httpx
import pytest

from app.config import Settings
from app.llm import LLMError, build_llm_client
from app.llm.openai_responses import OpenAIResponsesClient, build_request, to_input

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_sql",
            "description": "SQL 실행",
            "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}},
        },
    }
]

CALL = {
    "status": "completed",
    "output": [
        {"type": "reasoning", "id": "rs_1", "summary": []},
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "run_sql",
            "arguments": '{"sql": "SELECT 1"}',
        },
    ],
    "usage": {
        "input_tokens": 80,
        "output_tokens": 40,
        "output_tokens_details": {"reasoning_tokens": 9},
    },
}


def _client(handler, **kwargs) -> OpenAIResponsesClient:
    return OpenAIResponsesClient(
        base_url="https://llm.test/v1",
        api_key="k",
        model="gpt-6-luna",
        provider="openai",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_history_is_converted_to_responses_items():
    messages = [
        {"role": "system", "content": "규칙"},
        {"role": "user", "content": "어제 방문자 수"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "run_sql", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": '{"rows": [[575]]}'},
        {"role": "system", "content": "[예산 소진]"},
    ]
    assert to_input(messages) == [
        {"role": "system", "content": "규칙"},
        {"role": "user", "content": "어제 방문자 수"},
        {"type": "function_call", "call_id": "call_1", "name": "run_sql", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "call_1", "output": '{"rows": [[575]]}'},
        {"role": "system", "content": "[예산 소진]"},
    ]


def test_request_maps_chat_completions_parameters():
    body = build_request(
        "gpt-6-luna",
        [{"role": "user", "content": "q"}],
        max_tokens=3072,
        tools=TOOLS,
        tool_choice={"type": "function", "function": {"name": "submit_report"}},
        params={"reasoning_effort": "high", "top_p": 0.95, "temperature": 1.0},
    )
    assert body["max_output_tokens"] == 3072 and "max_tokens" not in body
    assert body["reasoning"] == {"effort": "high"} and "reasoning_effort" not in body
    assert "top_p" not in body and body["temperature"] == 1.0
    assert body["store"] is False
    assert body["tools"][0]["name"] == "run_sql" and "function" not in body["tools"][0]
    assert body["tool_choice"] == {"type": "function", "name": "submit_report"}
    plain = build_request("m", [], tools=TOOLS, tool_choice="required")
    assert plain["tool_choice"] == "required" and "reasoning" not in plain


async def test_chat_parses_function_calls_and_usage():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=CALL)

    llm = _client(handler)
    result = await llm.chat(
        [{"role": "user", "content": "q"}], tools=TOOLS, tool_choice="required", max_tokens=100
    )
    assert seen["path"] == "/v1/responses"
    assert seen["body"]["tools"][0]["name"] == "run_sql"
    assert [(c.id, c.name, c.arguments) for c in result.tool_calls] == [
        ("call_1", "run_sql", '{"sql": "SELECT 1"}')
    ]
    assert result.finish_reason == "tool_calls" and result.content == ""
    assert (result.usage.prompt_tokens, result.usage.completion_tokens) == (80, 40)
    assert result.usage.reasoning_tokens == 9
    assert (result.provider, result.model) == ("openai", "gpt-6-luna")
    # 다음 턴 이력은 Chat Completions 형식으로 쌓인다
    assert result.assistant_message()["tool_calls"][0]["id"] == "call_1"
    await llm.aclose()


async def test_chat_reads_text_and_truncation():
    message = {
        "status": "incomplete",
        "incomplete_details": {"reason": "max_output_tokens"},
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": "어제 방문자는 "},
                    {"type": "output_text", "text": "575명"},
                ],
            }
        ],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    llm = _client(lambda r: httpx.Response(200, json=message))
    result = await llm.chat([{"role": "user", "content": "q"}])
    assert result.content == "어제 방문자는 575명" and result.finish_reason == "length"
    await llm.aclose()


async def test_errors_and_retries_follow_chat_client():
    attempts = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"retry-after-ms": "1"}, json={})
        return httpx.Response(200, json=CALL)

    llm = _client(handler, max_retries=2)
    result = await llm.chat([{"role": "user", "content": "q"}])
    assert len(attempts) == 2 and result.wait_ms >= 0
    await llm.aclose()

    bad = _client(lambda r: httpx.Response(400, json={"error": {"message": "bad"}}))
    with pytest.raises(LLMError) as e:
        await bad.chat([{"role": "user", "content": "q"}])
    assert e.value.status == 400
    await bad.aclose()

    broken = _client(lambda r: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(LLMError, match="해석"):
        await broken.chat([{"role": "user", "content": "q"}])
    await broken.aclose()


async def test_build_openai_provider():
    llm = build_llm_client(Settings(_env_file=None, llm_provider="openai", openai_api_key="o"))
    assert isinstance(llm, OpenAIResponsesClient)
    assert llm.provider == "openai" and llm.model == "gpt-6-luna"
    await llm.aclose()
    with pytest.raises(LLMError, match="OPENAI_API_KEY"):
        build_llm_client(Settings(_env_file=None, llm_provider="openai"))
