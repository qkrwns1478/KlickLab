import asyncio
import json
import time
from dataclasses import dataclass
from datetime import date

import httpx
import pytest

from app.agent.loop import AgentLoop
from app.config import Settings
from app.llm import (
    ChatResult,
    FallbackLLMClient,
    LLMError,
    OpenAICompatClient,
    build_llm_client,
    open_session,
)
from app.llm.health import check_local_server
from tests.test_agent_loop import (
    ROWS,
    SQL_OK,
    FakeExecutor,
    MemoryStore,
    ScriptedLLM,
    by_type,
    calls,
    classify,
    collect,
    report,
)


def ok(content: str = "답") -> dict:
    return {
        "choices": [{"finish_reason": "stop", "message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Server:
    """httpx.MockTransport 처리기. 응답 목록을 차례로 돌려주고 요청을 남긴다."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(json.loads(request.content))
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item


def client(server: Server, provider: str, **kwargs) -> OpenAICompatClient:
    return OpenAICompatClient(
        provider=provider,
        base_url=f"https://{provider}.test/v1",
        api_key="k",
        model=f"{provider}-model",
        transport=httpx.MockTransport(server),
        **kwargs,
    )


def chain(primary: Server, local: Server, clock: Clock | None = None, **primary_kwargs):
    primary_kwargs.setdefault("max_retries", 1)
    primary_kwargs.setdefault("max_retry_wait", 5.0)
    return FallbackLLMClient(
        [client(primary, "groq", **primary_kwargs), client(local, "local", max_retries=0)],
        statuses={429, 413, 500, 502, 503, 504},
        cooldown_s=60.0,
        clock=clock or Clock(),
    )


MESSAGES = [{"role": "user", "content": "q"}]


# --- OpenAICompatClient -----------------------------------------------------


async def test_drop_params_and_param_map_change_the_request_body():
    server = Server(httpx.Response(200, json=ok()))
    llm = client(
        server,
        "local",
        default_params={"temperature": 0.7},
        drop_params=("reasoning_effort",),
        param_map={"max_tokens": "max_completion_tokens"},
    )
    result = await llm.chat(MESSAGES, max_tokens=100, reasoning_effort="high")
    body = server.requests[0]
    assert "reasoning_effort" not in body
    assert body["temperature"] == 0.7
    # max_tokens 는 param_map 이 적용된 뒤에 넣으므로 이름이 그대로다
    assert body["max_tokens"] == 100
    assert (result.provider, result.model, result.fallback) == ("local", "local-model", False)


async def test_retry_after_longer_than_cap_fails_without_waiting():
    server = Server(httpx.Response(429, headers={"retry-after": "30"}, json={}))
    llm = client(server, "groq", max_retries=1, max_retry_wait=5.0)
    started = time.monotonic()
    with pytest.raises(LLMError) as e:
        await llm.chat(MESSAGES)
    assert time.monotonic() - started < 1.0
    assert len(server.requests) == 1
    assert e.value.status == 429 and e.value.retry_after == 30.0


async def test_retry_after_within_cap_still_retries():
    server = Server(
        httpx.Response(429, headers={"retry-after-ms": "10"}, json={}),
        httpx.Response(200, json=ok()),
    )
    llm = client(server, "groq", max_retries=1, max_retry_wait=5.0)
    assert (await llm.chat(MESSAGES)).content == "답"
    assert len(server.requests) == 2


async def test_connection_failure_is_marked_unavailable():
    server = Server(httpx.ConnectError("refused"))
    with pytest.raises(LLMError) as e:
        await client(server, "local", max_retries=0).chat(MESSAGES)
    assert e.value.unavailable and e.value.status is None


async def test_concurrency_limit_serializes_requests():
    active = [0]
    peak = [0]

    async def handler(request: httpx.Request) -> httpx.Response:
        active[0] += 1
        peak[0] = max(peak[0], active[0])
        await asyncio.sleep(0.02)
        active[0] -= 1
        return httpx.Response(200, json=ok())

    llm = OpenAICompatClient(
        base_url="https://local.test/v1",
        api_key="k",
        model="m",
        max_concurrency=1,
        transport=httpx.MockTransport(handler),
    )
    results = await asyncio.gather(*(llm.chat(MESSAGES) for _ in range(3)))
    assert peak[0] == 1
    assert max(r.wait_ms for r in results) >= 30  # 앞 요청을 기다린 시간


# --- FallbackLLMClient ------------------------------------------------------


@pytest.mark.parametrize("status", [429, 413, 500, 503])
async def test_falls_back_on_rate_limit_size_and_server_errors(status):
    primary = Server(httpx.Response(status, headers={"retry-after": "30"}, json={}))
    local = Server(httpx.Response(200, json=ok("로컬")))
    result = await chain(primary, local).chat(MESSAGES, max_tokens=50)
    assert result.content == "로컬"
    assert result.fallback and result.provider == "local"
    assert local.requests[0]["messages"] == MESSAGES
    assert local.requests[0]["max_tokens"] == 50


@pytest.mark.parametrize("status", [401, 403, 400, 408])
async def test_does_not_fall_back_on_auth_request_or_timeout_errors(status):
    primary = Server(httpx.Response(status, json={}))
    local = Server(httpx.Response(200, json=ok()))
    with pytest.raises(LLMError) as e:
        await chain(primary, local).chat(MESSAGES)
    assert e.value.status == status
    assert local.requests == []


async def test_cooldown_skips_primary_then_returns_after_it_ends():
    clock = Clock()
    primary = Server(
        httpx.Response(429, headers={"retry-after": "30"}, json={}),
        httpx.Response(200, json=ok("기본")),
    )
    local = Server(httpx.Response(200, json=ok("로컬")))
    llm = chain(primary, local, clock)

    assert (await llm.chat(MESSAGES)).content == "로컬"
    clock.now += 10  # retry-after(30초) 안
    assert (await llm.chat(MESSAGES)).content == "로컬"
    assert len(primary.requests) == 1  # 쿨다운 동안 기본 공급자를 부르지 않았다
    clock.now += 30
    assert (await llm.chat(MESSAGES)).content == "기본"
    assert len(local.requests) == 2


async def test_daily_limit_uses_long_cooldown():
    clock = Clock()
    primary = Server(
        httpx.Response(429, text="Rate limit reached ... tokens per day (TPD)"),
        httpx.Response(200, json=ok("기본")),
    )
    local = Server(httpx.Response(200, json=ok("로컬")))
    llm = FallbackLLMClient(
        [client(primary, "groq", max_retries=1), client(local, "local", max_retries=0)],
        statuses={429},
        cooldown_s=60.0,
        daily_cooldown_s=3600.0,
        clock=clock,
    )
    await llm.chat(MESSAGES)
    assert len(primary.requests) == 1  # 하루 한도는 재시도하지 않는다
    clock.now += 600
    assert (await llm.chat(MESSAGES)).content == "로컬"
    clock.now += 3600
    assert (await llm.chat(MESSAGES)).content == "기본"


async def test_size_error_does_not_start_cooldown():
    primary = Server(httpx.Response(413, json={}), httpx.Response(200, json=ok("기본")))
    local = Server(httpx.Response(200, json=ok("로컬")))
    llm = chain(primary, local)
    assert (await llm.chat(MESSAGES)).content == "로컬"
    assert (await llm.chat(MESSAGES)).content == "기본"  # 다음 요청은 받을 수 있다


async def test_size_error_does_not_pin_the_session_to_fallback():
    primary = Server(httpx.Response(413, json={}), httpx.Response(200, json=ok("기본")))
    local = Server(httpx.Response(200, json=ok("로컬")))
    session = chain(primary, local).session()
    assert (await session.chat(MESSAGES)).content == "로컬"
    assert session.fallback_active
    assert (await session.chat(MESSAGES)).content == "기본"  # 고정되지 않아 기본 공급자로 돌아온다


async def test_cooldown_errors_are_copied_per_session():
    clock = Clock()
    primary = Server(httpx.Response(429, headers={"retry-after": "30"}, json={}))
    local = Server(httpx.Response(500, json={}), httpx.Response(500, json={}))
    llm = chain(primary, local, clock)
    errors = []
    for _ in range(2):
        with pytest.raises(LLMError) as e:
            await llm.session().chat(MESSAGES)
        errors.append(e.value)
    assert errors[0] is not errors[1]
    assert errors[0] is not llm.last_error(0)


async def test_session_stays_on_fallback_for_the_rest_of_the_run():
    clock = Clock()
    primary = Server(
        httpx.Response(429, headers={"retry-after": "1"}, json={}),
        httpx.Response(200, json=ok("기본")),
    )
    local = Server(httpx.Response(200, json=ok("로컬")))
    llm = chain(primary, local, clock, max_retry_wait=0.5)
    session = llm.session()

    assert (await session.chat(MESSAGES)).content == "로컬"
    clock.now += 120  # 쿨다운이 끝나도
    second = await session.chat(MESSAGES)
    assert second.content == "로컬" and second.fallback
    assert session.fallback_active and session.provider == "local"
    assert session.primary_error.status == 429
    assert len(primary.requests) == 1
    # 새 실행은 다시 기본 공급자부터
    assert (await llm.session().chat(MESSAGES)).content == "기본"


async def test_session_started_during_cooldown_reports_primary_error():
    clock = Clock()
    primary = Server(httpx.Response(429, headers={"retry-after": "30"}, json={}))
    local = Server(httpx.Response(200, json=ok("로컬")))
    llm = chain(primary, local, clock)
    await llm.chat(MESSAGES)
    session = llm.session()
    await session.chat(MESSAGES)
    assert session.fallback_active and session.primary_error.status == 429


async def test_local_server_down_returns_primary_error_message():
    primary = Server(httpx.Response(429, headers={"retry-after": "30"}, json={}))
    local = Server(httpx.ConnectError("refused"))
    with pytest.raises(LLMError) as e:
        await chain(primary, local).chat(MESSAGES)
    assert e.value.status == 429
    assert e.value.user_message == "LLM 사용 한도에 도달했습니다. 잠시 후 다시 시도해 주세요."


async def test_pinned_session_with_local_down_returns_primary_error():
    primary = Server(httpx.Response(429, headers={"retry-after": "30"}, json={}))
    local = Server(httpx.Response(200, json=ok("로컬")), httpx.ConnectError("refused"))
    session = chain(primary, local).session()
    await session.chat(MESSAGES)
    with pytest.raises(LLMError) as e:
        await session.chat(MESSAGES)
    assert e.value.status == 429


async def test_wait_before_fallback_is_reported_as_wait():
    primary = Server(
        httpx.Response(429, headers={"retry-after-ms": "20"}, json={}),
        httpx.Response(429, headers={"retry-after": "30"}, json={}),
    )
    local = Server(httpx.Response(200, json=ok()))
    result = await chain(primary, local).chat(MESSAGES)
    assert result.wait_ms >= 20


# --- 설정 -----------------------------------------------------------------


def settings(**kwargs) -> Settings:
    return Settings(_env_file=None, groq_api_key="g", **kwargs)


async def test_build_without_fallback_is_plain_client():
    llm = build_llm_client(settings())
    assert isinstance(llm, OpenAICompatClient) and llm.provider == "groq"
    assert open_session(llm) is llm
    await llm.aclose()


async def test_build_local_provider_keeps_reasoning_effort_for_gpt_oss():
    llm = build_llm_client(settings(llm_provider="local", local_model="gpt-oss-20b-ctx32k"))
    assert isinstance(llm, OpenAICompatClient)
    assert llm.provider == "local" and llm.time_factor == 2.0 and llm.forced_tool_unreliable
    assert llm._drop_params == ()
    await llm.aclose()
    other = build_llm_client(settings(llm_provider="local", local_model="qwen3:14b"))
    assert other._drop_params == ("reasoning_effort",)
    await other.aclose()


async def test_build_with_local_fallback_limits_primary_waiting():
    llm = build_llm_client(settings(llm_fallback_provider="local"))
    assert isinstance(llm, FallbackLLMClient)
    primary, local = llm.clients
    assert (primary.provider, local.provider) == ("groq", "local")
    assert primary._max_retries == 1 and primary._max_retry_wait == 5.0
    assert local._max_retries == 0
    assert llm.model == primary.model
    await llm.aclose()


def test_unknown_fallback_provider_is_rejected():
    with pytest.raises(LLMError):
        build_llm_client(settings(llm_fallback_provider="claude"))


async def test_local_health_check_reports_small_context():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "gpt-oss:20b"}]})
        return httpx.Response(200, json={"parameters": "temperature 1"})

    s = settings(local_model="gpt-oss:20b", llm_fallback_provider="local")
    problems = await check_local_server(s, transport=httpx.MockTransport(handler))
    assert len(problems) == 1 and "num_ctx" in problems[0]


async def test_local_health_check_accepts_derived_model_and_reports_down_server():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "gpt-oss-20b-ctx32k:latest"}]})
        return httpx.Response(200, json={"parameters": "num_ctx                        32768"})

    s = settings(llm_fallback_provider="local")
    assert await check_local_server(s, transport=httpx.MockTransport(handler)) == []

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    problems = await check_local_server(s, transport=httpx.MockTransport(down))
    assert "연결하지 못했다" in problems[0]


# --- 루프 통합 ----------------------------------------------------------------


@dataclass
class ProviderLLM(ScriptedLLM):
    provider: str = "groq"
    time_factor: float = 1.0
    forced_tool_unreliable: bool = False

    async def chat(self, messages, **kwargs):
        result = await super().chat(messages, **kwargs)
        result.provider, result.model = self.provider, self.model
        return result


def fallback_agent(primary_replies, local_replies, results=(), **local_kwargs):
    primary = ProviderLLM(list(primary_replies), model="groq-model")
    local = ProviderLLM(list(local_replies), model="local-model", provider="local", **local_kwargs)
    llm = FallbackLLMClient([primary, local], statuses={429}, clock=Clock())
    executor = FakeExecutor(list(results))
    store = MemoryStore()
    agent = AgentLoop(llm, executor, store, today=lambda: date(2026, 11, 11))
    return agent, primary, local, store


async def test_run_continues_on_local_model_after_mid_run_rate_limit():
    agent, primary, local, store = fallback_agent(
        [
            classify("lookup"),
            calls(("run_sql", {"sql": SQL_OK, "purpose": "p"})),
            LLMError("rate", status=429, retry_after=30),
        ],
        [ChatResult(content="정리 중"), report()],  # 도구 없는 응답 → 한 번 더 요청
        [ROWS],
        time_factor=2.0,
    )
    events = await collect(agent)

    assert [e.type for e in events].count("fallback") == 1
    assert by_type(events, "fallback")[0] == {
        "provider": "local",
        "model": "local-model",
        "primaryStatus": 429,
    }
    # 폴백 응답의 tool_calls 가 기본 모델의 이력에 이어진다
    history = [m for m in local.requests[0]["messages"] if m["role"] != "system"]
    assert [m["role"] for m in history[-2:]] == ["assistant", "tool"]
    assert history[-2]["tool_calls"][0]["function"]["name"] == "run_sql"
    done = by_type(events, "done")[0]
    assert done["status"] == "succeeded"
    assert done["fallbackCalls"] == 2 and done["primaryError"] == 429
    assert done["models"] == {"groq-model": 2, "local-model": 2}
    assert done["model"] == "local-model"
    assert by_type(events, "answer")[0]["findings"][0]["evidence"] == [1]
    # 로컬 모델로 넘어간 뒤의 호출부터 시간 제한에 배율이 붙는다
    assert local.requests[1]["params"]["timeout"] >= 30.0 * 2


async def test_fallback_at_classification_announces_before_classified():
    agent, primary, local, _ = fallback_agent(
        [LLMError("rate", status=429)],
        [classify("lookup"), calls(("run_sql", {"sql": SQL_OK})), report()],
        [ROWS],
    )
    events = await collect(agent)
    types = [e.type for e in events]
    assert types.index("fallback") < types.index("classified")
    assert len(primary.requests) == 1  # 실행 내 고정: 이후 호출은 모두 로컬
    assert len(local.requests) == 3


async def test_no_fallback_summary_fields_when_primary_answers():
    agent, primary, local, _ = fallback_agent(
        [classify("lookup"), calls(("run_sql", {"sql": SQL_OK})), report()], [], [ROWS]
    )
    events = await collect(agent)
    assert "fallback" not in [e.type for e in events]
    done = by_type(events, "done")[0]
    assert done["fallbackCalls"] == 0 and done["primaryError"] is None
    assert local.requests == []


async def test_rate_limit_with_local_down_shows_limit_message():
    agent, *_ = fallback_agent(
        [classify("lookup"), LLMError("rate", status=429)],
        [LLMError("refused", unavailable=True)],
    )
    events = await collect(agent)
    assert by_type(events, "error")[0]["message"].startswith("LLM 사용 한도에 도달했습니다")


async def test_local_model_gets_corrected_when_ignoring_forced_final():
    replies = [classify("lookup")]
    replies += [calls(("describe_table", {"table_name": "agg_daily_users"}))] * 3
    replies += [calls(("run_sql", {"sql": SQL_OK}))]  # 결론 강제를 무시
    replies += [calls(("run_sql", {"sql": SQL_OK}))]  # 한 번 더 무시
    replies += [report(summary="결론", evidence=())]
    agent, _, local, _ = fallback_agent(
        [LLMError("rate", status=429)], replies, forced_tool_unreliable=True
    )
    from app.sql.executor import QueryResult

    columns = QueryResult(["column_name", "data_type"], [["summary_date", "date"]], 1, False, 1)
    agent._executor.results = [columns, ROWS, ROWS, ROWS]
    events = await collect(agent)
    answer = by_type(events, "answer")[0]
    assert answer["summary"] == "결론"
    retry = local.requests[-1]["messages"]
    assert any("submit_report 만 호출할 수 있다" in (m.get("content") or "") for m in retry)


async def test_reliable_provider_keeps_existing_forced_final_limit():
    replies = [classify("lookup")]
    replies += [calls(("describe_table", {"table_name": "agg_daily_users"}))] * 3
    replies += [calls(("run_sql", {"sql": SQL_OK}))] * 2
    replies += [report(summary="결론", evidence=())]
    agent, _, local, _ = fallback_agent([LLMError("rate", status=429)], replies)
    from app.sql.executor import QueryResult

    columns = QueryResult(["column_name", "data_type"], [["summary_date", "date"]], 1, False, 1)
    agent._executor.results = [columns, ROWS, ROWS, ROWS]
    events = await collect(agent)
    assert by_type(events, "answer")[0]["summary"] != "결론"  # 강제 2회 소진 → 서버 요약


async def test_local_reasoning_effort_is_capped():
    server = Server(httpx.Response(200, json=ok()))
    llm = client(server, "local", max_reasoning_effort="medium")
    await llm.chat(MESSAGES, reasoning_effort="high")
    await llm.chat(MESSAGES, reasoning_effort="low")
    assert [r["reasoning_effort"] for r in server.requests] == ["medium", "low"]


async def test_ollama_tool_parse_error_is_a_format_error_not_an_outage():
    body = {"error": {"message": "error parsing tool call: raw='{\"chart\": null'"}}
    primary = Server(httpx.Response(429, headers={"retry-after": "30"}, json={}))
    local = Server(httpx.Response(500, json=body))
    with pytest.raises(LLMError) as e:
        await chain(primary, local).chat(MESSAGES)
    # 루프의 tool_use_failed 재시도 경로로 가도록 400 으로 바꾼다 (한도 초과 문구로 숨기지 않는다)
    assert e.value.status == 400 and "tool_use_failed" in str(e.value)
    assert len(local.requests) == 1
