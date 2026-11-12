"""Phase 6 관측: 단가 계산, Langfuse 트레이서, 루프 트레이싱·메트릭, /metrics."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app import tracing
from app.api.runs import get_run_store, get_tracer
from app.config import Settings, get_settings
from app.llm import ChatResult, LLMError, Usage
from app.llm.pricing import Pricing, parse_prices
from app.main import app
from app.tracing import TracedLLM, Tracer, build_tracer
from tests.test_agent_loop import (
    ROWS,
    SQL_OK,
    calls,
    classify,
    collect,
    make_agent,
    report,
)
from tests.test_runs_api import SECRET, FakeStore, _headers

# ---------------------------------------------------------------------------
# 단가
# ---------------------------------------------------------------------------


def test_default_price_and_unknown_model():
    pricing = Pricing.from_settings(Settings())
    cost = pricing.cost("openai/gpt-oss-120b", Usage(1_000_000, 1_000_000, 0))
    assert (cost.input, cost.output, cost.total) == (0.15, 0.60, pytest.approx(0.75))
    assert pricing.cost("k-exaone_v2.5", Usage(100, 100, 0)) is None  # 모르면 0 이 아니라 None


def test_local_model_is_free():
    settings = Settings(local_model="my-local")
    cost = Pricing.from_settings(settings).cost("my-local", Usage(5000, 5000, 0))
    assert cost.total == 0.0


def test_prices_can_be_overridden_by_setting():
    settings = Settings(llm_prices="openai/gpt-oss-120b=1:2, k-exaone_v2.5=0.5:0.5")
    pricing = Pricing.from_settings(settings)
    assert pricing.cost("openai/gpt-oss-120b", Usage(1_000_000, 0, 0)).total == 1.0
    assert pricing.cost("k-exaone_v2.5", Usage(0, 2_000_000, 0)).total == 1.0


@pytest.mark.parametrize("text", ["model", "=1:2", "model=a:b", "model=1"])
def test_malformed_prices_are_rejected(text):
    with pytest.raises(ValueError, match="LLM_PRICES"):
        parse_prices(text)


# ---------------------------------------------------------------------------
# Tracer: Langfuse ingestion
# ---------------------------------------------------------------------------


class FakeLangfuse:
    """Langfuse ingestion 엔드포인트 대역. 받은 이벤트를 모은다."""

    def __init__(self, *responses: httpx.Response):
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.responses:
            return self.responses.pop(0)
        return httpx.Response(207, json={"successes": [], "errors": []})

    @property
    def events(self) -> list[dict]:
        return [e for r in self.requests for e in json.loads(r.content)["batch"]]

    def of(self, event_type: str) -> list[dict]:
        return [e["body"] for e in self.events if e["type"] == event_type]


def make_tracer(server: FakeLangfuse, **kwargs) -> Tracer:
    http = httpx.AsyncClient(
        base_url="http://langfuse.test", auth=("pk", "sk"), transport=httpx.MockTransport(server)
    )
    return Tracer(
        host="http://langfuse.test",
        public_key="pk",
        secret_key="sk",
        flush_interval=0.01,
        http=http,
        **kwargs,
    )


async def test_tracer_sends_batch_with_basic_auth():
    server = FakeLangfuse()
    tracer = make_tracer(server, environment="test")
    trace = tracer.start(run_id="run-1", name="agent-run", question="어제 방문자?", user_id="u1")
    now = tracing.now()
    trace.span("run_sql", input={"sql": "SELECT 1"}, output={"rowCount": 1}, start=now, end=now)
    tracer.score("run-1", "user_feedback", -1.0, comment="틀림")
    await tracer.aclose()

    request = server.requests[0]
    assert request.url.path == "/api/public/ingestion"
    assert request.headers["authorization"].startswith("Basic ")
    assert [e["type"] for e in server.events] == ["trace-create", "span-create", "score-create"]
    trace_body, span_body, score_body = (e["body"] for e in server.events)
    assert trace_body["id"] == "run-1" and trace_body["environment"] == "test"
    assert trace_body["userId"] == "u1" and trace_body["input"] == "어제 방문자?"
    assert span_body["traceId"] == "run-1" and span_body["name"] == "run_sql"
    assert score_body["id"] == "run-1:user_feedback"  # 같은 점수를 다시 보내면 덮어쓴다
    assert score_body["value"] == -1.0 and score_body["comment"] == "틀림"
    assert tracer.sent == 3


async def test_tracer_splits_large_queue_into_batches():
    server = FakeLangfuse()
    tracer = make_tracer(server)
    for i in range(tracing.BATCH_SIZE + 5):
        tracer.score("t", f"s{i}", 1.0)
    await tracer.aclose()
    sizes = [len(json.loads(r.content)["batch"]) for r in server.requests]
    assert sum(sizes) == tracing.BATCH_SIZE + 5
    assert max(sizes) <= tracing.BATCH_SIZE


async def test_tracer_retries_server_error_once(monkeypatch):
    monkeypatch.setattr(tracing.asyncio, "sleep", _no_sleep)
    server = FakeLangfuse(httpx.Response(503, text="down"))
    tracer = make_tracer(server)
    tracer.score("t", "s", 1.0)
    await tracer.aclose()
    assert len(server.requests) == 2 and tracer.sent == 1 and tracer.failed == 0


async def test_tracer_drops_events_after_repeated_failure_without_raising(monkeypatch):
    monkeypatch.setattr(tracing.asyncio, "sleep", _no_sleep)
    server = FakeLangfuse(httpx.Response(500), httpx.Response(500))
    tracer = make_tracer(server)
    tracer.score("t", "s", 1.0)
    await tracer.aclose()
    assert tracer.sent == 0 and tracer.failed == 1


async def test_tracer_does_not_retry_bad_credentials():
    server = FakeLangfuse(httpx.Response(401, text="unauthorized"))
    tracer = make_tracer(server)
    tracer.score("t", "s", 1.0)
    await tracer.aclose()
    assert len(server.requests) == 1 and tracer.failed == 1


async def test_tracer_counts_events_rejected_inside_207():
    rejected = httpx.Response(207, json={"successes": [], "errors": [{"id": "x", "status": 400}]})
    server = FakeLangfuse(rejected)
    tracer = make_tracer(server)
    tracer.score("t", "a", 1.0)
    tracer.score("t", "b", 1.0)
    await tracer.aclose()
    assert (tracer.sent, tracer.failed) == (1, 1)


async def test_tracer_drops_oldest_when_queue_is_full(monkeypatch):
    monkeypatch.setattr(tracing, "MAX_QUEUE", 3)
    server = FakeLangfuse()
    tracer = make_tracer(server)
    for i in range(5):
        tracer.score("t", f"s{i}", 1.0)
    await tracer.aclose()
    assert [e["name"] for e in server.of("score-create")] == ["s2", "s3", "s4"]


def test_clip_keeps_small_values_and_truncates_large_ones():
    assert tracing.clip({"a": 1}) == {"a": 1}
    assert tracing.clip(None) is None
    clipped = tracing.clip({"rows": ["x" * 100] * 100}, limit=500)
    assert clipped["truncated"] is True and len(clipped["preview"]) == 500


def test_build_tracer_is_null_without_langfuse_settings():
    assert build_tracer(Settings()).enabled is False
    partial = Settings(langfuse_host="http://x", langfuse_public_key="pk")
    assert build_tracer(partial).enabled is False
    full = Settings(langfuse_host="http://x", langfuse_public_key="pk", langfuse_secret_key="sk")
    assert build_tracer(full, environment="eval").environment == "eval"


async def _no_sleep(_seconds):
    return None


# ---------------------------------------------------------------------------
# 루프 트레이싱
# ---------------------------------------------------------------------------


def traced_agent(replies, results=(), server=None, **kwargs):
    server = server or FakeLangfuse()
    tracer = make_tracer(server)
    pricing = Pricing({"fake": (1.0, 2.0)})
    agent, llm, executor, store = make_agent(
        replies, results, tracer=tracer, pricing=pricing, **kwargs
    )
    return agent, server, tracer, store


async def test_run_becomes_trace_with_generations_and_spans():
    agent, server, tracer, store = traced_agent(
        [classify("lookup"), calls(("run_sql", {"sql": SQL_OK, "purpose": "p"})), report()],
        [ROWS],
    )
    events = await collect(agent)
    await tracer.aclose()

    # 트레이스 id = 실행 id. 실행 기록에도 남겨 서로 찾을 수 있다
    traces = server.of("trace-create")
    assert (
        traces[0]["id"] == "r1" and traces[0]["sessionId"] == "c1" and traces[0]["userId"] == "u1"
    )
    assert traces[0]["input"] == "어제 방문자 수는?"
    assert store.runs["r1"]["totals"].trace_id == "r1"

    generations = server.of("generation-create")
    assert [g["name"] for g in generations] == ["classify", "step-1", "step-2"]
    first, second = generations[0], generations[1]
    assert first["traceId"] == "r1" and first["model"] == "fake"
    assert first["usageDetails"] == {"input": 10, "output": 2, "total": 12}
    assert second["output"]["tool_calls"][0]["name"] == "run_sql"
    assert second["input"][-1]["role"] != "assistant"  # 모델에 보낸 메시지가 입력이다
    assert second["costDetails"]["total"] == pytest.approx((100 * 1.0 + 20 * 2.0) / 1_000_000)

    spans = server.of("span-create")
    assert [s["name"] for s in spans] == ["run_sql", "submit_report"]
    assert spans[0]["input"]["sql"] == SQL_OK and spans[0]["metadata"]["seq"] == 1

    final = traces[-1]
    assert final["id"] == "r1" and final["output"]["summary"]
    assert final["tags"] == ["lookup", "succeeded"]
    assert final["metadata"]["status"] == "succeeded" and final["metadata"]["toolCalls"] == 2

    # 실행 비용 = 호출 비용의 합. 실행 기록과 done 요약에 같은 값을 남긴다
    expected = round((10 + 100 + 100) * 1.0 / 1_000_000 + (2 + 20 + 20) * 2.0 / 1_000_000, 6)
    assert store.runs["r1"]["totals"].cost_usd == expected
    done = [e.data for e in events if e.type == "done"][0]
    assert done["costUsd"] == expected


async def test_failed_llm_call_is_recorded_as_error_generation():
    agent, server, tracer, store = traced_agent([classify("lookup"), LLMError("boom", status=500)])
    await collect(agent)
    await tracer.aclose()

    failed = server.of("generation-create")[-1]
    assert failed["name"] == "step-1" and failed["level"] == "ERROR"
    assert failed["output"] is None and failed["metadata"]["status"] == 500
    assert server.of("trace-create")[-1]["tags"] == ["lookup", "failed"]


async def test_tracing_is_off_without_tracer():
    agent, _, _, store = make_agent([classify("lookup"), report(evidence=())])
    assert agent.tracer.enabled is False
    events = await collect(agent)
    assert store.runs["r1"]["totals"].trace_id is None
    assert [e for e in events if e.type == "done"][0].data["costUsd"] is None  # 단가를 모르는 모델


async def test_unreachable_langfuse_does_not_break_the_run(monkeypatch):
    monkeypatch.setattr(tracing.asyncio, "sleep", _no_sleep)

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    http = httpx.AsyncClient(base_url="http://langfuse.test", transport=httpx.MockTransport(refuse))
    tracer = Tracer(
        host="http://x", public_key="pk", secret_key="sk", flush_interval=0.01, http=http
    )
    agent, *_ = make_agent([classify("lookup"), report(evidence=())], tracer=tracer)
    events = await collect(agent)
    await tracer.aclose()
    assert [e for e in events if e.type == "done"][0].data["status"] == "succeeded"
    assert tracer.failed > 0


async def test_traced_llm_delegates_session_attributes():
    class Inner:
        model = "m1"
        provider = "groq"
        forced_tool_unreliable = True

        async def chat(self, messages, **kwargs):
            return ChatResult(content="ok", usage=Usage(1, 1, 0), provider="groq", model="m1")

    server = FakeLangfuse()
    tracer = make_tracer(server)
    llm = TracedLLM(Inner(), tracer.start(run_id="r", name="n", question="q"), Pricing())
    assert (llm.model, llm.provider, llm.forced_tool_unreliable) == ("m1", "groq", True)
    result = await llm.chat([{"role": "user", "content": "hi"}], reasoning_effort="low")
    assert result.content == "ok"
    await tracer.aclose()
    generation = server.of("generation-create")[0]
    assert generation["modelParameters"] == {"reasoning_effort": "low"}
    assert "costDetails" not in generation  # 단가를 모르면 비용을 지어내지 않는다


# ---------------------------------------------------------------------------
# Prometheus 메트릭
# ---------------------------------------------------------------------------


def sample(name: str, **labels) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_run_updates_prometheus_metrics():
    labels = {"status": "succeeded", "difficulty": "lookup"}
    before = {
        "runs": sample("agent_runs_total", **labels),
        "tokens": sample("agent_llm_tokens_total", model="fake", type="prompt"),
        "sql": sample("agent_tool_calls_total", tool="run_sql", outcome="ok"),
        "submit": sample("agent_tool_calls_total", tool="submit_report", outcome="ok"),
        "llm": sample("agent_llm_calls_total", model="fake", fallback="false"),
    }
    agent, *_ = make_agent(
        [classify("lookup"), calls(("run_sql", {"sql": SQL_OK, "purpose": "p"})), report()],
        [ROWS],
    )
    await collect(agent)

    assert sample("agent_runs_total", **labels) == before["runs"] + 1
    assert sample("agent_llm_tokens_total", model="fake", type="prompt") == before["tokens"] + 210
    assert sample("agent_tool_calls_total", tool="run_sql", outcome="ok") == before["sql"] + 1
    assert (
        sample("agent_tool_calls_total", tool="submit_report", outcome="ok") == before["submit"] + 1
    )
    assert sample("agent_llm_calls_total", model="fake", fallback="false") == before["llm"] + 3
    assert sample("agent_runs_in_progress") == 0  # 끝난 실행은 진행 중에 남지 않는다


async def test_invented_tool_names_do_not_become_metric_labels():
    agent, *_ = make_agent([classify("lookup"), calls(("json", {"x": 1})), report(evidence=())], [])
    before = sample("agent_tool_calls_total", tool="unknown", outcome="error")
    await collect(agent)
    assert sample("agent_tool_calls_total", tool="unknown", outcome="error") == before + 1
    assert (
        REGISTRY.get_sample_value("agent_tool_calls_total", {"tool": "json", "outcome": "error"})
        is None
    )


async def test_llm_failure_counts_error_status_and_failed_run():
    before_err = sample("agent_llm_errors_total", status="500")
    before_run = sample("agent_runs_total", status="failed", difficulty="lookup")
    agent, *_ = make_agent([classify("lookup"), LLMError("boom", status=500)])
    await collect(agent)
    assert sample("agent_llm_errors_total", status="500") == before_err + 1
    assert sample("agent_runs_total", status="failed", difficulty="lookup") == before_run + 1
    assert sample("agent_runs_in_progress") == 0


# ---------------------------------------------------------------------------
# HTTP: /metrics, 피드백 점수
# ---------------------------------------------------------------------------


class RecordingTracer:
    enabled = True

    def __init__(self):
        self.scores = []

    def score(self, trace_id, name, value, **kwargs):
        self.scores.append((trace_id, name, value, kwargs))


@pytest.fixture
def http():
    tracer, store = RecordingTracer(), FakeStore()
    app.dependency_overrides[get_settings] = lambda: Settings(jwt_secret=SECRET)
    app.dependency_overrides[get_run_store] = lambda: store
    app.dependency_overrides[get_tracer] = lambda: tracer
    yield TestClient(app), tracer
    app.dependency_overrides.clear()


def test_metrics_endpoint_exposes_prometheus_text(http):
    client, _ = http
    client.get("/agent/health")
    client.get("/agent/runs/r1", headers=_headers())
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "agent_runs_total" in body and "agent_llm_tokens_total" in body
    # 실제 id 가 아니라 경로 템플릿이 레이블이다 (레이블 값이 무한히 늘지 않게)
    assert 'path="/agent/runs/{run_id}"' in body and 'path="/agent/runs/r1"' not in body
    assert 'path="/metrics"' not in body


def test_feedback_is_scored_on_trace(http):
    client, tracer = http
    r = client.post(
        "/agent/runs/r1/feedback", json={"feedback": -1, "note": "틀림"}, headers=_headers()
    )
    assert r.status_code == 204
    assert tracer.scores == [("r1", "user_feedback", -1.0, {"comment": "틀림"})]
    before = sample("agent_feedback_total", value="up")
    client.post("/agent/runs/r1/feedback", json={"feedback": 1}, headers=_headers())
    assert sample("agent_feedback_total", value="up") == before + 1


def test_feedback_for_unknown_run_is_not_scored(http):
    client, tracer = http
    r = client.post("/agent/runs/x/feedback", json={"feedback": 1}, headers=_headers())
    assert r.status_code == 404 and tracer.scores == []
