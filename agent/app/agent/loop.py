"""Tool Loop: 난이도 분류 → (rag 모드) 지식 검색 → 예산 안에서 도구 호출 반복 → 근거가 있는 답변.

run() 은 실행 과정을 이벤트로 내보내는 async generator 다 (SSE 로 그대로 전달된다).
    started → classified → (tool_call → tool_result)* → answer → done
    오류 시: error → done
    기본 LLM 공급자가 실패해 대체 공급자로 넘어가면 그 시점에 fallback 을 한 번 낸다.
"""

import asyncio
import json
import logging
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app import metrics
from app.agent import prompts
from app.agent.budget import Budget, Difficulty
from app.agent.router import Router
from app.agent.store import RunStore, RunTotals
from app.agent.text_to_sql import today_kst
from app.agent.tools import (
    RunState,
    Step,
    ToolOutcome,
    describe_table,
    final_answer,
    parse_arguments,
    request_more_budget,
    run_sql,
    search_knowledge,
)
from app.agent.tools.final_answer import FinalAnswer, SubmitFinalAnswer
from app.agent.turn import Turn
from app.knowledge.context import KnowledgeContext
from app.llm import (
    TIMEOUT_STATUS,
    ChatResult,
    LLMClient,
    LLMError,
    ToolCall,
    Usage,
    open_session,
)
from app.llm.pricing import Pricing
from app.sql.executor import SQLExecutor
from app.tracing import NullRunTrace, NullTracer, TracedLLM, label_generation, now

log = logging.getLogger(__name__)

MAX_LLM_CALLS = 30  # 예산과 별개의 안전 상한
# 공급자가 도구 호출 형식 오류(tool_use_failed)를 돌려준 경우 연속 재시도 횟수.
# Groq gpt-oss 는 도구 없이 끝내거나 없는 도구('json')를 부르는 경우가 종종 있다.
MAX_FORMAT_RETRIES = 3
# 오래된 도구 결과는 줄여서 보낸다 (입력 토큰 절약. Groq 무료 등급은 요청 하나가 TPM 8K 를
# 넘으면 413 으로 거절한다). level 이 클수록 강하게 줄인다. 원본 이력은 그대로 둔다.
COMPACT_ROWS = 5
MAX_COMPACTION = 2
SQL_PREVIEW_CHARS = 160
MAX_FORCED_CALLS = 2  # 예산 소진 후 final_answer 강제 호출 횟수
# 결론 강제 단계에서 다른 도구를 부른 응답을 바로잡는 횟수. tool_choice 함수 지정을 무시하는
# 공급자(로컬 Ollama)에서만 쓴다 (Phase 0: 도구가 하나뿐이어도 3회 중 1회 다른 도구를 불렀다)
MAX_FINAL_ONLY_RETRIES = 2
# 모델 호출 하나의 응답 시간 제한. 남은 시간 예산을 넘기지 못하게 하되 하한을 둔다.
# 결론 제출은 이미 모은 근거로 쓰는 마지막 호출이라 예산이 끝난 뒤에도 이만큼은 기다린다.
MIN_CALL_TIMEOUT_S = 30.0
FINAL_CALL_TIMEOUT_S = 60.0

# 메트릭의 tool 레이블 값. 모델이 지어낸 도구 이름이 레이블이 되지 않게 한다
KNOWN_TOOLS = {
    run_sql.NAME,
    describe_table.NAME,
    search_knowledge.NAME,
    final_answer.NAME,
    request_more_budget.NAME,
}

# 트레이스 메타데이터에 옮기는 실행 요약 항목
TRACE_SUMMARY_KEYS = (
    "difficulty",
    "toolCalls",
    "sqlRuns",
    "llmCalls",
    "formatErrors",
    "rateLimitWaitMs",
    "usage",
    "latencyMs",
    "costUsd",
    "models",
    "fallbackCalls",
    "primaryError",
)

FORCE_FINAL = {"type": "function", "function": {"name": final_answer.NAME}}

OUT_OF_SCOPE_ANSWER = "사이트 분석 데이터 조회로 답할 수 없는 질문이라 처리하지 않았습니다."
NO_CONCLUSION = (
    "예산 안에서 결론을 정리하지 못했습니다. 실행한 조회 결과는 실행 단계에서 확인할 수 있습니다."
)


@dataclass
class AgentEvent:
    type: str  # started / classified / tool_call / tool_result / answer / error / done
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Run:
    run_id: str
    question: str
    sdk_key: str
    started: float
    conversation_id: str = ""
    history: list[Turn] = field(default_factory=list)  # 같은 대화의 이전 턴 (질문 + 답변 요약)
    persisted: bool = True
    difficulty: Difficulty | None = None
    status: str = "running"
    error: str | None = None  # 사용자에게 보여 준 실패 사유 (실행 기록에도 남긴다)
    answer: FinalAnswer | None = None
    usage: Usage = field(default_factory=Usage)
    state: RunState | None = None
    llm_calls: int = 0
    format_errors: int = 0
    chars_per_token: float = 2.0  # 첫 호출 전 보수적 추정치 (한국어가 섞여 영어보다 작다)
    wait_ms: int = 0  # LLM 레이트 리밋 대기 합
    knowledge: list[str] = field(default_factory=list)  # 시스템 프롬프트에 넣은 지식 문서
    llm: Any = None  # 이 실행의 LLM 세션 (폴백 공급자로 넘어가면 끝까지 유지한다)
    models: Counter[str] = field(default_factory=Counter)  # 모델별 호출 수
    fallback_calls: int = 0
    fallback_announced: bool = False
    cost_usd: float | None = None  # 단가를 아는 모델의 호출 비용 합 (모르면 None)
    trace: Any = field(default_factory=NullRunTrace)  # Langfuse 트레이스


class AgentLoop:
    def __init__(
        self,
        llm: LLMClient,
        executor: SQLExecutor,
        store: RunStore,
        *,
        classify_params: dict[str, Any] | None = None,
        step_max_tokens: int = 8192,
        max_prompt_tokens: int = 0,
        max_rows: int = 1000,
        model_rows: int = 30,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], date] = today_kst,
        knowledge: KnowledgeContext | None = None,
        tracer: Any = None,
        pricing: Pricing | None = None,
        own_tracer: bool = False,
    ):
        # 앱은 트레이서를 여러 곳(피드백 점수)에서 함께 쓰므로 만든 쪽(lifespan)이 닫는다.
        # 평가처럼 에이전트 전용으로 만든 트레이서만 aclose() 가 닫는다
        self.tracer = tracer or NullTracer()
        self._own_tracer = own_tracer
        self._pricing = pricing or Pricing()
        self._llm = llm
        self._executor = executor
        self._store = store
        self._router = Router(llm, params=classify_params)
        self._run_sql = run_sql.RunSQL(executor, max_rows=max_rows, model_rows=model_rows)
        self._describe = describe_table.DescribeTable(executor)
        self._step_max_tokens = step_max_tokens
        self._max_prompt_tokens = max_prompt_tokens  # 0 이면 제한 없음
        self._model_rows = model_rows
        self._clock = clock
        self._today = today
        self._knowledge = knowledge
        self._search = (
            search_knowledge.SearchKnowledge(knowledge.retriever, k=knowledge.search_k)
            if knowledge is not None
            else None
        )

    async def run(
        self,
        question: str,
        *,
        sdk_key: str,
        user_id: str,
        conversation_id: str | None = None,
    ) -> AsyncIterator[AgentEvent]:
        run = _Run(run_id="", question=question, sdk_key=sdk_key, started=self._clock())
        run.llm = open_session(self._llm)
        try:
            run.conversation_id, run.history = await self._persist(
                self._store.resolve_conversation,
                sdk_key=sdk_key,
                user_id=user_id,
                conversation_id=conversation_id,
            )
        except Exception:
            log.exception("대화 이력 조회 실패. 이전 대화 없이 진행한다.")
            run.conversation_id, run.history = str(uuid.uuid4()), []
        try:
            run.run_id = await self._persist(
                self._store.create_run,
                sdk_key=sdk_key,
                user_id=user_id,
                question=question,
                conversation_id=run.conversation_id,
            )
        except Exception:
            log.exception("agent_runs 생성 실패. 실행 로그 없이 진행한다.")
            run.run_id, run.persisted = str(uuid.uuid4()), False
        if self.tracer.enabled:
            run.trace = self.tracer.start(
                run_id=run.run_id,
                name="agent-run",
                question=question,
                user_id=user_id,
                session_id=run.conversation_id,
                metadata={"sdkKey": sdk_key, "persisted": run.persisted},
            )
            run.llm = TracedLLM(run.llm, run.trace, self._pricing)

        metrics.RUNS_IN_PROGRESS.inc()
        try:
            # started 를 보내는 중에 연결이 끊겨도 finally 가 실행되도록 try 안에서 보낸다
            yield AgentEvent(
                "started", {"runId": run.run_id, "conversationId": run.conversation_id}
            )
            async for event in self._execute(run):
                yield event
        except LLMError as e:
            run.status, run.error = "failed", e.user_message
            log.warning("LLM 호출 실패 run_id=%s: %s", run.run_id, str(e)[:500])
            yield AgentEvent("error", {"message": run.error})
        except Exception:
            log.exception("에이전트 실행 실패 run_id=%s", run.run_id)
            run.status, run.error = "failed", "에이전트 실행 중 오류가 발생했습니다."
            yield AgentEvent("error", {"message": run.error})
        finally:
            if run.status == "running":  # 클라이언트 연결 종료 등으로 중단됨
                run.status, run.error = "failed", "실행이 중단되었습니다."
            metrics.RUNS_IN_PROGRESS.dec()
            await self._finish(run)
        yield AgentEvent("done", self._summary(run))

    # ------------------------------------------------------------------

    async def _execute(self, run: _Run) -> AsyncIterator[AgentEvent]:
        label_generation(run.llm, "classify")
        try:
            classification = await self._router.classify(run.question, run.history, llm=run.llm)
        except LLMError as e:
            metrics.record_llm_error(e.status)
            raise
        run.usage += classification.usage
        self._count_call(
            run,
            classification.model,
            classification.via_fallback,
            classification.usage,
            classification.latency_ms,
        )
        if (event := self._fallback_event(run)) is not None:
            yield event
        run.difficulty = classification.difficulty
        await self._persist_quietly(self._store.set_difficulty, run, classification.difficulty)

        if classification.difficulty == "out_of_scope":
            yield AgentEvent(
                "classified", {"difficulty": "out_of_scope", "reason": classification.reason}
            )
            run.answer = FinalAnswer(summary=classification.reason or OUT_OF_SCOPE_ANSWER)
            run.status = "rejected"
            yield AgentEvent("answer", run.answer.to_dict())
            return

        budget = Budget(classification.difficulty, clock=self._clock)
        budget.time_factor = _time_factor(run.llm)
        state = run.state = RunState(sdk_key=run.sdk_key, budget=budget)
        schema = await self._schema(run, state)
        classified: dict[str, Any] = {
            "difficulty": classification.difficulty,
            "reason": classification.reason,
            "fallback": classification.fallback,
            "budget": budget.remaining(),
        }
        if self._knowledge is not None:
            classified["knowledge"] = run.knowledge
        yield AgentEvent("classified", classified)

        limits = budget.limits
        messages: list[dict[str, Any]] = prompts.agent_messages(
            run.question,
            self._today(),
            max_tool_calls=limits.max_tool_calls,
            max_sql=limits.max_sql,
            result_rows=self._model_rows,
            schema=schema,
            search_tool=self._search is not None,
            history=run.history,
        )
        submit = SubmitFinalAnswer()
        nudged = False
        must_answer = False  # 도구 없이 답한 모델에게 final_answer 를 강제한다
        forced_calls = format_errors = final_only_retries = 0
        exhausted = False

        while run.answer is None and run.llm_calls < MAX_LLM_CALLS:
            force = budget.exhausted() or must_answer
            if force:
                if forced_calls >= MAX_FORCED_CALLS:
                    break
                if budget.exhausted() and not exhausted:
                    messages.append({"role": "system", "content": prompts.BUDGET_EXHAUSTED})
                    exhausted = True
                forced_calls += 1
            elif budget.should_warn():
                messages.append(
                    {
                        "role": "system",
                        "content": prompts.BUDGET_WARNING.format(**budget.remaining()),
                    }
                )

            tools = [final_answer.SCHEMA] if force else self._tool_schemas(budget)
            prepared = self._fit(run, messages, tools, budget)
            if prepared is None:  # 압축해도 입력 상한을 넘는다 -> 다음 호출에서 결론을 강제한다
                log.warning("입력 토큰 상한 도달 run_id=%s", run.run_id)
                budget.context_full = True
                if force:
                    forced_calls -= 1  # 모델을 부르지 않았으므로 강제 호출 횟수를 쓰지 않는다
                continue

            try:
                chat = await self._chat(run, prepared, tools, budget, force=force)
            except LLMError as e:
                if e.status == TIMEOUT_STATUS:
                    # 같은 요청을 다시 보내도 같은 시간이 걸린다. 모은 근거로 결론을 내게 한다.
                    log.warning("모델 호출 시간 초과 run_id=%s force=%s", run.run_id, force)
                    budget.timed_out = True
                    continue
                if e.status == 413 and not budget.context_full:  # 공급자 요청 크기 한도
                    log.warning("요청 크기 초과 run_id=%s: %s", run.run_id, str(e)[:300])
                    budget.context_full = True
                    if force:
                        forced_calls -= 1  # 가장 강하게 압축한 이력으로 다시 시도한다
                    continue
                if (
                    e.status == 400
                    and "tool_use_failed" in str(e)
                    and format_errors < MAX_FORMAT_RETRIES
                ):
                    format_errors += 1
                    run.format_errors += 1
                    log.warning("도구 호출 형식 오류 run_id=%s: %s", run.run_id, str(e)[:500])
                    messages.append({"role": "user", "content": prompts.TOOL_FORMAT_RETRY})
                    continue
                raise
            format_errors = 0
            if (event := self._fallback_event(run)) is not None:
                yield event

            if chat.content or chat.tool_calls:
                messages.append(chat.assistant_message())
            if not chat.tool_calls:
                log.warning(
                    "도구 호출 없는 응답 run_id=%s finish=%s content=%r",
                    run.run_id,
                    chat.finish_reason,
                    chat.content[:200],
                )
                if nudged:
                    must_answer = True
                else:
                    messages.append({"role": "user", "content": prompts.ANSWER_WITH_TOOL})
                    nudged = True
                continue

            for call in chat.tool_calls:
                if run.answer is not None:  # 같은 응답에서 submit_report 뒤에 온 호출
                    messages.append(
                        _tool_message(call, {"ok": False, "error": "이미 답변을 제출했다."})
                    )
                    continue
                async for event in self._call_tool(run, state, submit, call, final_only=force):
                    yield event
                step = state.steps[-1]
                messages.append(_tool_message(call, step.for_model))
                if step.final is not None:
                    run.answer = step.final
                    run.answer.forced = exhausted
            if (
                force
                and run.answer is None
                and getattr(run.llm, "forced_tool_unreliable", False)
                and final_only_retries < MAX_FINAL_ONLY_RETRIES
            ):
                # 결론 강제를 무시하고 다른 도구를 불렀다. 강제 횟수에서 빼고 다시 요청한다
                log.warning("결론 강제 단계의 다른 도구 호출 run_id=%s", run.run_id)
                messages.append({"role": "user", "content": prompts.FINAL_ONLY_RETRY})
                final_only_retries += 1
                forced_calls -= 1

        if run.answer is None:
            run.answer = FinalAnswer(summary=NO_CONCLUSION, forced=True)
            exhausted = True
        run.status = "budget_exhausted" if exhausted else "succeeded"
        yield AgentEvent("answer", run.answer.to_dict())

    async def _schema(self, run: _Run, state: RunState) -> str:
        """시스템 프롬프트의 스키마 부분. rag 모드에서 검색이 실패하면 스키마 요약으로 진행한다."""
        if self._knowledge is None:
            return prompts.SCHEMA_SUMMARY
        try:
            # 후속 질문("그럼 지난주는?")은 그 자체로는 검색되지 않으므로 직전 질문을 함께 쓴다
            query = " ".join([*(t.question for t in run.history[-1:]), run.question])
            context = await self._knowledge.aschema_for(query)
        except Exception:
            log.exception("지식 베이스 검색 실패 run_id=%s. 스키마 요약으로 진행한다.", run.run_id)
            return prompts.SCHEMA_SUMMARY
        run.knowledge = context.doc_ids
        state.knowledge_seen.update(context.doc_ids)
        return context.text

    def _fit(
        self,
        run: _Run,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        budget: Budget,
    ) -> list[dict[str, Any]] | None:
        """입력 토큰 상한에 맞을 때까지 이력을 단계적으로 압축한다. 맞출 수 없으면 None.

        이미 상한에 닿은 뒤(결론 강제 단계)에는 가장 강하게 압축한 이력을 그대로 쓴다.
        """
        if budget.context_full:
            return compact_history(messages, level=MAX_COMPACTION)
        if not self._max_prompt_tokens:
            return compact_history(messages)
        for level in range(MAX_COMPACTION + 1):
            candidate = compact_history(messages, level=level)
            if _chars(candidate, tools) / run.chars_per_token <= self._max_prompt_tokens:
                return candidate
        return None

    async def _chat(
        self,
        run: _Run,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        budget: Budget,
        *,
        force: bool,
    ) -> ChatResult:
        run.llm_calls += 1
        label_generation(run.llm, f"step-{run.llm_calls}")
        try:
            chat = await run.llm.chat(
                messages,
                tools=tools,
                # auto 면 gpt-oss 가 도구 호출 없이 빈 응답으로 끝내기도 해 항상 도구를 고르게 한다
                tool_choice=FORCE_FINAL if force else "required",
                max_tokens=self._step_max_tokens,
                reasoning_effort=budget.limits.reasoning_effort,
                timeout=_call_timeout(budget, force),
            )
        except LLMError as e:
            self._waited(run, budget, e.wait_ms)
            metrics.record_llm_error(e.status)
            raise
        self._waited(run, budget, chat.wait_ms)
        self._count_call(run, chat.model, chat.fallback, chat.usage, chat.latency_ms)
        budget.time_factor = _time_factor(run.llm)
        run.usage += chat.usage
        budget.tokens += chat.usage.prompt_tokens + chat.usage.completion_tokens
        if chat.usage.prompt_tokens > 0:  # 다음 요청의 토큰 추정에 쓴다
            run.chars_per_token = _chars(messages, tools) / chat.usage.prompt_tokens
        return chat

    def _count_call(
        self, run: _Run, model: str, fallback: bool, usage: Usage, latency_ms: int
    ) -> None:
        """모델별 호출 수·비용을 실행에 더하고 메트릭에 남긴다."""
        model = model or getattr(run.llm, "model", "") or "unknown"
        run.models[model] += 1
        if fallback:
            run.fallback_calls += 1
        cost = self._pricing.cost(model, usage)
        if cost is not None:
            run.cost_usd = (run.cost_usd or 0.0) + cost.total
        metrics.record_llm_call(
            model,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            fallback=fallback,
            seconds=latency_ms / 1000,
            cost=cost.total if cost else None,
        )

    @staticmethod
    def _fallback_event(run: _Run) -> AgentEvent | None:
        """세션이 대체 공급자로 넘어갔으면 실행 중 한 번만 알린다."""
        if run.fallback_announced or not getattr(run.llm, "fallback_active", False):
            return None
        run.fallback_announced = True
        error = getattr(run.llm, "primary_error", None)
        metrics.FALLBACK_RUNS.labels(run.llm.model or metrics.UNKNOWN).inc()
        if error is not None:
            metrics.record_llm_error(error.status)
        log.warning(
            "폴백 공급자로 진행 run_id=%s model=%s primary_status=%s",
            run.run_id,
            run.llm.model,
            error.status if error else None,
        )
        return AgentEvent(
            "fallback",
            {
                "provider": run.llm.provider,
                "model": run.llm.model,
                "primaryStatus": error.status if error else None,
            },
        )

    @staticmethod
    def _waited(run: _Run, budget: Budget, wait_ms: int) -> None:
        run.wait_ms += wait_ms
        budget.excluded_s += wait_ms / 1000

    def _tool_schemas(self, budget: Budget) -> list[dict[str, Any]]:
        schemas = [describe_table.SCHEMA, final_answer.SCHEMA]
        if self._search is not None:
            schemas.insert(0, search_knowledge.SCHEMA)
        if budget.can_run_sql():
            schemas.insert(0, run_sql.SCHEMA)
        if budget.can_promote():
            schemas.append(request_more_budget.SCHEMA)
        return schemas

    async def _call_tool(
        self,
        run: _Run,
        state: RunState,
        submit: SubmitFinalAnswer,
        call: ToolCall,
        *,
        final_only: bool,
    ) -> AsyncIterator[AgentEvent]:
        """도구 하나를 실행해 state.steps 에 쌓고 tool_call / tool_result 이벤트를 낸다."""
        seq = len(state.steps) + 1
        try:
            args = parse_arguments(call.arguments)
            parse_error = None
        except ValueError as e:
            args, parse_error = {"raw": call.arguments}, str(e)
        yield AgentEvent("tool_call", {"seq": seq, "tool": call.name, "input": args})

        started = time.monotonic()
        span_start = now()
        if parse_error:
            outcome = ToolOutcome.fail(parse_error)
        else:
            outcome = await self._dispatch(state, submit, call.name, args, seq, final_only)
        if outcome.charged:
            state.budget.tool_calls += 1
        step = Step(
            seq=seq,
            tool=call.name or "(unknown)",
            input=args,
            output=outcome.output,
            error=outcome.error,
            duration_ms=int((time.monotonic() - started) * 1000),
            result=outcome.result,
            for_model=outcome.for_model,
            final=outcome.final,
        )
        state.steps.append(step)
        metrics.record_tool(
            step.tool if step.tool in KNOWN_TOOLS else metrics.UNKNOWN,
            ok=step.error is None,
            seconds=step.duration_ms / 1000,
        )
        run.trace.span(
            step.tool,
            input=step.input,
            output=step.output,
            start=span_start,
            end=now(),
            metadata={"seq": seq, "charged": outcome.charged},
            error=step.error,
        )
        await self._persist_quietly(self._save_step, run, step)
        yield AgentEvent(
            "tool_result",
            {
                "seq": seq,
                "tool": step.tool,
                "output": step.output,
                "error": step.error,
                "durationMs": step.duration_ms,
            },
        )

    async def _dispatch(
        self,
        state: RunState,
        submit: SubmitFinalAnswer,
        name: str,
        args: dict[str, Any],
        seq: int,
        final_only: bool,
    ) -> ToolOutcome:
        if name == final_answer.NAME:
            return await submit(state, args, seq)
        if final_only:
            return ToolOutcome.fail(
                "예산을 모두 썼다. submit_report 만 호출할 수 있다.", charged=False
            )
        if name == request_more_budget.NAME:
            return await request_more_budget.request_more_budget(state, args, seq)
        handlers: dict[str, Callable[..., Any]] = {
            run_sql.NAME: self._run_sql,
            describe_table.NAME: self._describe,
        }
        if self._search is not None:
            handlers[search_knowledge.NAME] = self._search
        handler = handlers.get(name)
        if handler is None:
            return ToolOutcome.fail(f"알 수 없는 도구입니다: {name}")
        if not state.budget.can_call_tool():
            reason = state.budget.exhausted_reason() or "툴 호출"
            return ToolOutcome.fail(
                f"{reason} 예산을 모두 썼다. 지금까지의 결과로 submit_report 를 제출하라.",
                charged=False,
            )
        return await handler(state, args, seq)

    # --- 실행 로그 -------------------------------------------------------

    def _save_step(self, run_id: str, step: Step) -> None:
        self._store.add_step(
            run_id,
            seq=step.seq,
            tool=step.tool,
            input=step.input,
            output=step.output,
            error=step.error,
            duration_ms=step.duration_ms,
        )

    async def _finish(self, run: _Run) -> None:
        state = run.state
        difficulty = state.budget.difficulty if state else run.difficulty  # 승격된 난이도
        totals = RunTotals(
            status=run.status,
            difficulty=difficulty,
            answer=run.answer.to_dict() if run.answer else None,
            tool_calls=len(state.steps) if state else 0,
            input_tokens=run.usage.prompt_tokens,
            output_tokens=run.usage.completion_tokens,
            latency_ms=self._latency_ms(run),
            cost_usd=round(run.cost_usd, 6) if run.cost_usd is not None else None,
            error=run.error,
            trace_id=run.run_id if self.tracer.enabled else None,
        )
        metrics.record_run(run.status, difficulty, totals.latency_ms / 1000)
        summary = self._summary(run)
        run.trace.end(
            output=totals.answer if totals.answer else {"error": run.error},
            status=run.status,
            tags=[
                t for t in (difficulty, run.status, "fallback" if run.fallback_calls else None) if t
            ],
            metadata={key: summary[key] for key in TRACE_SUMMARY_KEYS},
        )
        await self._persist_quietly(self._store.finish_run, run, totals)

    async def _persist(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(fn, *args, **kwargs)

    async def _persist_quietly(self, fn: Callable[..., Any], run: _Run, *args: Any) -> None:
        """실행 로그 저장 실패가 답변을 막지 않게 한다."""
        if not run.persisted:
            return
        try:
            await asyncio.shield(asyncio.to_thread(fn, run.run_id, *args))
        except Exception:
            log.exception("실행 로그 저장 실패 run_id=%s fn=%s", run.run_id, fn.__name__)

    def _latency_ms(self, run: _Run) -> int:
        return int((self._clock() - run.started) * 1000)

    def _summary(self, run: _Run) -> dict[str, Any]:
        state = run.state
        return {
            "runId": run.run_id,
            "status": run.status,
            "difficulty": state.budget.difficulty if state else run.difficulty,
            "toolCalls": len(state.steps) if state else 0,
            "sqlRuns": state.budget.sql_runs if state else 0,
            "llmCalls": run.llm_calls,
            "formatErrors": run.format_errors,
            "rateLimitWaitMs": run.wait_ms,
            "usage": vars(run.usage),
            "latencyMs": self._latency_ms(run),
            "knowledge": run.knowledge,
            "model": getattr(run.llm, "model", None) or self._llm.model,
            "models": dict(run.models),
            "fallbackCalls": run.fallback_calls,
            "primaryError": _primary_status(run.llm),
            "costUsd": round(run.cost_usd, 6) if run.cost_usd is not None else None,
        }

    async def aclose(self) -> None:
        await self._llm.aclose()
        if self._own_tracer:
            await self.tracer.aclose()
        await asyncio.to_thread(self._executor.close)  # 실행 로그 저장소는 앱이 따로 닫는다


def _call_timeout(budget: Budget, final: bool) -> float:
    if final:
        return FINAL_CALL_TIMEOUT_S * budget.time_factor
    return max(budget.timeout_s - budget.elapsed_s, MIN_CALL_TIMEOUT_S * budget.time_factor)


def _time_factor(llm: Any) -> float:
    factor = getattr(llm, "time_factor", 1.0)
    return float(factor) if isinstance(factor, int | float) and factor > 0 else 1.0


def _primary_status(llm: Any) -> int | None:
    """폴백하게 만든 기본 공급자의 오류 상태 (연결 실패는 0)."""
    if not getattr(llm, "fallback_active", False):
        return None
    error = getattr(llm, "primary_error", None)
    if error is None:
        return None
    return error.status or 0


def _tool_message(call: ToolCall, content: dict[str, Any]) -> dict[str, Any]:
    return {
        "role": "tool",
        "tool_call_id": call.id,
        "content": json.dumps(content, ensure_ascii=False, default=str),
    }


def compact_history(messages: list[dict[str, Any]], *, level: int = 0) -> list[dict[str, Any]]:
    """모델에게 보낼 이력 사본.

    level 0: 최근 2개를 제외한 도구 결과의 rows 를 앞 5행으로
    level 1: 최근 2개를 제외한 도구 결과의 rows 를 빼고, 지난 run_sql 인자의 SQL 을 앞부분만 남긴다
    level 2: level 1 을 최근 1개만 남기고 적용
    """
    keep = 2 if level < 2 else 1
    tool_indexes = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    old_results = set(tool_indexes[:-keep])
    call_indexes = [
        i for i, m in enumerate(messages) if m.get("role") == "assistant" and m.get("tool_calls")
    ]
    old_calls = set(call_indexes[:-keep]) if level >= 1 else set()
    rows = COMPACT_ROWS if level == 0 else 0

    compacted = []
    for i, message in enumerate(messages):
        if i in old_results:
            message = _compact_result(message, rows)
        elif i in old_calls:
            message = _compact_call(message)
        compacted.append(message)
    return compacted


def _compact_result(message: dict[str, Any], rows: int) -> dict[str, Any]:
    try:
        content = json.loads(message["content"])
    except (KeyError, TypeError, json.JSONDecodeError):
        return message
    if not isinstance(content, dict):
        return message
    if isinstance(content.get("sample"), dict):  # describe_table
        content.pop("sample")
    elif rows == 0 and any("content" in d for d in content.get("documents") or []):
        # search_knowledge: 이전 검색 결과는 문서 이름만 남긴다
        content["documents"] = [
            {"kind": d.get("kind"), "name": d.get("name")} for d in content["documents"]
        ]
        content["note"] = "이전 검색 결과라 본문을 생략했다."
    elif len(content.get("rows") or []) > rows:
        content["rows"] = content["rows"][:rows]
        content["note"] = f"이전 결과라 앞 {rows}행만 남겼다. step_id 로 근거 인용은 할 수 있다."
    else:
        return message
    return {**message, "content": json.dumps(content, ensure_ascii=False, default=str)}


def _compact_call(message: dict[str, Any]) -> dict[str, Any]:
    calls = []
    for call in message["tool_calls"]:
        function = call.get("function") or {}
        if function.get("name") == run_sql.NAME:
            try:
                args = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = None
            if isinstance(args, dict) and len(str(args.get("sql", ""))) > SQL_PREVIEW_CHARS:
                args["sql"] = str(args["sql"])[:SQL_PREVIEW_CHARS] + " ...(생략)"
                function = {**function, "arguments": json.dumps(args, ensure_ascii=False)}
                call = {**call, "function": function}
        calls.append(call)
    return {**message, "tool_calls": calls}


def _chars(messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> int:
    return len(json.dumps(messages, ensure_ascii=False)) + len(
        json.dumps(tools, ensure_ascii=False)
    )
