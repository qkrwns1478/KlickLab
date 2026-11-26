"""Langfuse 트레이싱. 실행 하나가 트레이스 하나이고, LLM 호출은 generation, 도구 호출은 span 이다.

Langfuse 공개 ingestion API(POST /api/public/ingestion)에 HTTP 로 직접 보낸다. SDK 대신 이미 있는
httpx 를 쓰므로 의존성이 늘지 않고, 보내는 내용을 테스트에서 그대로 확인할 수 있다.

* 트레이스 id 는 실행 id(agent_runs.id)와 같다. 실행 기록과 Langfuse 를 같은 id 로 찾는다.
* 이벤트는 메모리 큐에 쌓고 백그라운드 작업이 묶어서 보낸다. Langfuse 가 느리거나 죽어도 실행은
  기다리지 않고, 전송 실패는 경고 로그만 남기고 버린다 (관측 때문에 답변이 막히면 안 된다).
* 설정(LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY)이 없으면 NullTracer 가 되어 아무
  것도 하지 않는다.
"""

import asyncio
import json
import logging
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import Settings
from app.llm.base import ChatResult, LLMClient, LLMError
from app.llm.pricing import Pricing

log = logging.getLogger(__name__)

MAX_PAYLOAD_CHARS = 60_000  # 이보다 큰 입력·출력은 앞부분만 보낸다
MAX_QUEUE = 2000
BATCH_SIZE = 50
SEND_ATTEMPTS = 2


def now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def clip(value: Any, limit: int = MAX_PAYLOAD_CHARS) -> Any:
    """너무 큰 값은 JSON 앞부분만 남긴다. 표 결과 등은 실행 기록에 전체가 있다."""
    if value is None:
        return None
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) <= limit:
        return json.loads(text)
    return {"truncated": True, "chars": len(text), "preview": text[:limit]}


# --- 실행 하나의 트레이스 ----------------------------------------------------


class NullRunTrace:
    id = ""

    def generation(self, name: str, **kwargs: Any) -> None: ...

    def span(self, name: str, **kwargs: Any) -> None: ...

    def end(self, **kwargs: Any) -> None: ...


@dataclass
class RunTrace:
    tracer: "Tracer"
    id: str
    started: datetime = field(default_factory=now)

    def generation(
        self,
        name: str,
        *,
        model: str,
        input: Any,
        output: Any,
        start: datetime,
        end: datetime,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        cost_input: float | None = None,
        cost_output: float | None = None,
        params: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        body: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "traceId": self.id,
            "name": name,
            "model": model,
            "modelParameters": params or {},
            "startTime": _iso(start),
            "endTime": _iso(end),
            "input": clip(input),
            "output": clip(output),
            "usageDetails": {
                "input": prompt_tokens,
                "output": completion_tokens,
                "total": prompt_tokens + completion_tokens,
            },
            "metadata": metadata or {},
        }
        if cost_input is not None and cost_output is not None:
            body["costDetails"] = {
                "input": cost_input,
                "output": cost_output,
                "total": cost_input + cost_output,
            }
        if error:
            body["level"], body["statusMessage"] = "ERROR", error
        self.tracer.emit("generation-create", body)

    def span(
        self,
        name: str,
        *,
        input: Any,
        output: Any,
        start: datetime,
        end: datetime,
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        body: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "traceId": self.id,
            "name": name,
            "startTime": _iso(start),
            "endTime": _iso(end),
            "input": clip(input),
            "output": clip(output),
            "metadata": metadata or {},
        }
        if error:
            body["level"], body["statusMessage"] = "ERROR", error
        self.tracer.emit("span-create", body)

    def end(
        self,
        *,
        output: Any,
        status: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """같은 id 로 트레이스를 한 번 더 보내 결과를 채운다 (Langfuse 가 id 기준으로 합친다)."""
        self.tracer.emit(
            "trace-create",
            {
                "id": self.id,
                "output": clip(output),
                "tags": tags or [],
                "metadata": {"status": status, **(metadata or {})},
            },
        )


# --- 트레이서 ---------------------------------------------------------------


class NullTracer:
    enabled = False

    def start(self, **kwargs: Any) -> NullRunTrace:
        return NullRunTrace()

    def score(self, trace_id: str, name: str, value: float, **kwargs: Any) -> None: ...

    async def flush(self) -> None: ...

    async def aclose(self) -> None: ...


class Tracer:
    enabled = True

    def __init__(
        self,
        *,
        host: str,
        public_key: str,
        secret_key: str,
        environment: str = "development",
        flush_interval: float = 1.0,
        timeout: float = 10.0,
        http: httpx.AsyncClient | None = None,
    ):
        self.environment = environment
        self._flush_interval = flush_interval
        self._http = http or httpx.AsyncClient(
            base_url=host.rstrip("/"), auth=(public_key, secret_key), timeout=timeout
        )
        self._owns_http = http is None
        self._queue: deque[dict[str, Any]] = deque()
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._dropped = 0
        self.sent = 0
        self.failed = 0

    def start(
        self,
        *,
        run_id: str,
        name: str,
        question: str,
        user_id: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunTrace:
        self.emit(
            "trace-create",
            {
                "id": run_id,
                "name": name,
                "userId": user_id,
                "sessionId": session_id,
                "input": question,
                "tags": tags or [],
                "metadata": metadata or {},
                "timestamp": _iso(now()),
            },
        )
        return RunTrace(self, run_id)

    def score(
        self,
        trace_id: str,
        name: str,
        value: float,
        *,
        comment: str | None = None,
        data_type: str = "NUMERIC",
    ) -> None:
        """트레이스에 점수를 단다. 같은 (트레이스, 이름)은 덮어쓴다 (피드백을 바꿀 수 있다)."""
        self.emit(
            "score-create",
            {
                "id": f"{trace_id}:{name}",
                "traceId": trace_id,
                "name": name,
                "value": value,
                "dataType": data_type,
                "comment": comment,
            },
        )

    # --- 전송 ---------------------------------------------------------------

    def emit(self, event_type: str, body: dict[str, Any]) -> None:
        """이벤트를 큐에 넣는다. 이벤트 루프 안에서만 부른다."""
        if len(self._queue) >= MAX_QUEUE:
            self._queue.popleft()
            self._dropped += 1
            if self._dropped % 100 == 1:
                log.warning(
                    "Langfuse 전송 큐가 가득 차 오래된 이벤트를 버렸다 (누적 %d)", self._dropped
                )
        body = {"environment": self.environment, **body}
        self._queue.append(
            {"id": str(uuid.uuid4()), "type": event_type, "timestamp": _iso(now()), "body": body}
        )
        self._ensure_worker()
        self._wake.set()

    def _ensure_worker(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._flush_interval)
            except TimeoutError:
                pass
            self._wake.clear()
            # 짧은 시간에 몰린 이벤트는 한 번에 보낸다
            await asyncio.sleep(min(self._flush_interval, 0.2))
            await self.flush()

    async def flush(self) -> None:
        while self._queue:
            batch = [self._queue.popleft() for _ in range(min(BATCH_SIZE, len(self._queue)))]
            await self._send(batch)

    async def _send(self, batch: list[dict[str, Any]]) -> None:
        for attempt in range(1, SEND_ATTEMPTS + 1):
            try:
                response = await self._http.post(
                    "/api/public/ingestion",
                    json={"batch": batch, "metadata": {"sdk": "klicklab-agent"}},
                )
                # 207: 이벤트별 결과. 일부가 거절돼도 상태 코드는 성공이라 본문을 본다
                if response.status_code in (200, 201, 207):
                    errors = response.json().get("errors") or []
                    if errors:
                        log.warning(
                            "Langfuse 가 이벤트 %d건을 거절했다: %s", len(errors), errors[:2]
                        )
                    self.sent += len(batch) - len(errors)
                    self.failed += len(errors)
                    return
                if response.status_code in (400, 401, 403, 404):
                    # 다시 보내도 같다. 키·주소 설정 문제다
                    log.warning(
                        "Langfuse 전송 거절 (%d): %s", response.status_code, response.text[:200]
                    )
                    self.failed += len(batch)
                    return
                log.warning("Langfuse 전송 실패 (%d), 시도 %d", response.status_code, attempt)
            except (httpx.HTTPError, ValueError) as e:
                log.warning("Langfuse 전송 실패, 시도 %d: %s", attempt, e)
            if attempt < SEND_ATTEMPTS:
                await asyncio.sleep(0.5)
        self.failed += len(batch)

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        try:
            await asyncio.wait_for(self.flush(), timeout=5)
        except TimeoutError:
            log.warning("Langfuse 종료 전 전송을 마치지 못했다 (남은 이벤트 %d)", len(self._queue))
        if self._owns_http:
            await self._http.aclose()


def build_tracer(settings: Settings, *, environment: str | None = None) -> Tracer | NullTracer:
    if not settings.langfuse_enabled:
        return NullTracer()
    return Tracer(
        host=settings.langfuse_host,
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        environment=environment or settings.langfuse_environment,
        flush_interval=settings.langfuse_flush_interval_seconds,
        timeout=settings.langfuse_timeout_seconds,
    )


# --- LLM 호출 기록 -----------------------------------------------------------


class TracedLLM:
    """실행의 LLM 세션을 감싸 호출마다 generation 을 남긴다.

    분류와 루프가 모두 이 객체로 호출하므로 두 곳을 따로 고치지 않아도 된다. 모델, 공급자,
    폴백 여부 같은 나머지 속성은 감싼 세션 값을 그대로 돌려준다 (폴백으로 넘어가면 바뀐다).
    generation_name 은 호출 목적이며 루프가 호출 전에 바꾼다.
    """

    def __init__(self, inner: LLMClient, trace: RunTrace, pricing: Pricing):
        self._inner = inner
        self._trace = trace
        self._pricing = pricing
        self.generation_name = "llm"

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ChatResult:
        start = now()
        params = {
            k: v
            for k, v in kwargs.items()
            if k in ("max_tokens", "tool_choice", "reasoning_effort", "timeout")
        }
        try:
            result = await self._inner.chat(messages, **kwargs)
        except LLMError as e:
            self._trace.generation(
                self.generation_name,
                model=self._inner.model,
                input=messages,
                output=None,
                start=start,
                end=now(),
                params=params,
                metadata={"provider": getattr(self._inner, "provider", ""), "status": e.status},
                error=str(e)[:500],
            )
            raise
        model = result.model or self._inner.model
        cost = self._pricing.cost(model, result.usage)
        self._trace.generation(
            self.generation_name,
            model=model,
            input=messages,
            output={
                "content": result.content,
                "tool_calls": [
                    {"name": c.name, "arguments": c.arguments} for c in result.tool_calls
                ],
            },
            start=start,
            end=now(),
            prompt_tokens=result.usage.prompt_tokens,
            completion_tokens=result.usage.completion_tokens,
            cost_input=cost.input if cost else None,
            cost_output=cost.output if cost else None,
            params=params,
            metadata={
                "provider": result.provider,
                "fallback": result.fallback,
                "finishReason": result.finish_reason,
                "reasoningTokens": result.usage.reasoning_tokens,
                "waitMs": result.wait_ms,
                "reasoning": clip(result.reasoning, 4000),
            },
        )
        return result


def label_generation(llm: Any, name: str) -> None:
    """다음 LLM 호출의 generation 이름을 정한다 (트레이싱이 꺼져 있으면 아무 일도 하지 않는다)."""
    if isinstance(llm, TracedLLM):
        llm.generation_name = name
