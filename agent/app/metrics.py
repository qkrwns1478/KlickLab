"""Prometheus 메트릭. GET /metrics 로 노출한다 (app/main.py).

레이블은 값의 종류가 정해진 것만 쓴다 (난이도, 모델, 도구, 상태). 질문·sdk_key·사용자는 넣지 않는다.
"""

import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from prometheus_client import Counter, Gauge, Histogram

RUN_BUCKETS = (1, 2, 5, 10, 20, 40, 60, 120, 300)
CALL_BUCKETS = (0.1, 0.5, 1, 2, 5, 10, 20, 40, 60, 120)

RUNS = Counter("agent_runs_total", "에이전트 실행 수", ["status", "difficulty"])
RUN_SECONDS = Histogram(
    "agent_run_duration_seconds", "에이전트 실행 시간", ["difficulty"], buckets=RUN_BUCKETS
)
RUNS_IN_PROGRESS = Gauge("agent_runs_in_progress", "진행 중인 에이전트 실행 수")
FALLBACK_RUNS = Counter("agent_fallback_runs_total", "대체 LLM 공급자로 넘어간 실행 수", ["model"])

LLM_CALLS = Counter("agent_llm_calls_total", "LLM 호출 수", ["model", "fallback"])
LLM_SECONDS = Histogram(
    "agent_llm_call_duration_seconds", "LLM 호출 시간 (대기 포함)", ["model"], buckets=CALL_BUCKETS
)
LLM_TOKENS = Counter("agent_llm_tokens_total", "LLM 토큰 수", ["model", "type"])
LLM_COST = Counter("agent_llm_cost_usd_total", "LLM 비용 (단가를 아는 모델만)", ["model"])
LLM_ERRORS = Counter("agent_llm_errors_total", "LLM 호출 실패 수", ["status"])

TOOL_CALLS = Counter("agent_tool_calls_total", "도구 호출 수", ["tool", "outcome"])
TOOL_SECONDS = Histogram(
    "agent_tool_duration_seconds", "도구 실행 시간", ["tool"], buckets=CALL_BUCKETS
)

FEEDBACK = Counter("agent_feedback_total", "실행 결과 피드백", ["value"])

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP 요청 수 (응답 시작 기준)", ["method", "path", "status"]
)
HTTP_SECONDS = Histogram(
    "http_request_duration_seconds",
    "응답이 시작될 때까지의 시간 (SSE 는 스트림 전체가 아니다)",
    ["method", "path"],
    buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10),
)

UNKNOWN = "unknown"


def record_llm_call(
    model: str,
    *,
    prompt_tokens: int,
    completion_tokens: int,
    fallback: bool,
    seconds: float | None = None,
    cost: float | None = None,
) -> None:
    model = model or UNKNOWN
    LLM_CALLS.labels(model, str(fallback).lower()).inc()
    LLM_TOKENS.labels(model, "prompt").inc(prompt_tokens)
    LLM_TOKENS.labels(model, "completion").inc(completion_tokens)
    if seconds is not None:
        LLM_SECONDS.labels(model).observe(seconds)
    if cost is not None:
        LLM_COST.labels(model).inc(cost)


def record_llm_error(status: int | None) -> None:
    # 연결 실패는 상태 코드가 없다
    LLM_ERRORS.labels(str(status) if status else "none").inc()


def record_tool(tool: str, *, ok: bool, seconds: float) -> None:
    TOOL_CALLS.labels(tool, "ok" if ok else "error").inc()
    TOOL_SECONDS.labels(tool).observe(seconds)


def record_run(status: str, difficulty: str | None, seconds: float) -> None:
    difficulty = difficulty or UNKNOWN
    RUNS.labels(status, difficulty).inc()
    RUN_SECONDS.labels(difficulty).observe(seconds)


Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]


class HttpMetricsMiddleware:
    """ASGI 미들웨어. BaseHTTPMiddleware 는 스트리밍 응답과 연결 끊김 전파를 방해해 쓰지 않는다."""

    def __init__(self, app: Callable[[Scope, Receive, Send], Awaitable[None]]):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] == "/metrics":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()

        async def observing_send(message: MutableMapping[str, Any]) -> None:
            if message["type"] == "http.response.start":
                # 경로 템플릿(/agent/runs/{run_id})을 쓴다. 실제 경로는 값이 무한하다
                route = scope.get("route")
                path = getattr(route, "path", None) or "unmatched"
                method = scope["method"]
                HTTP_REQUESTS.labels(method, path, str(message["status"])).inc()
                HTTP_SECONDS.labels(method, path).observe(time.perf_counter() - started)
            await send(message)

        await self.app(scope, receive, observing_send)
