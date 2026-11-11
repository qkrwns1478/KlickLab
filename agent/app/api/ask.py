import threading
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.agent.text_to_sql import AskResult, Status, TextToSQL
from app.auth import AuthUser, current_user
from app.config import Settings, get_settings
from app.knowledge.context import get_knowledge_context
from app.llm import LLMError, build_llm_client
from app.sql.executor import build_executor

router = APIRouter(prefix="/agent")
_build_lock = threading.Lock()


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class AskRequest(_Camel):
    question: str = Field(min_length=1, max_length=500)


class TableResult(_Camel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool


class UsageOut(_Camel):
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int


class AskResponse(_Camel):
    status: Status
    question: str
    sql: str | None
    answer: str | None
    error: str | None
    result: TableResult | None
    usage: UsageOut
    timings: dict[str, int]

    @classmethod
    def of(cls, r: AskResult) -> "AskResponse":
        table = None
        if r.result is not None:
            table = TableResult(
                columns=r.result.columns,
                rows=r.result.rows,
                row_count=r.result.row_count,
                truncated=r.result.truncated,
            )
        return cls(
            status=r.status,
            question=r.question,
            sql=r.sql,
            answer=r.answer,
            error=r.error,
            result=table,
            usage=UsageOut(**vars(r.usage)),
            timings=r.timings,
        )


def build_text_to_sql(settings: Settings) -> TextToSQL:
    executor = build_executor(
        settings.dsn(read_only=True),
        token_dsn=settings.dsn(read_only=False),
        statement_timeout_ms=settings.sql_statement_timeout_ms,
        result_rows=settings.sql_result_rows,
        max_plan_cost=settings.sql_max_plan_cost,
    )
    return TextToSQL(
        build_llm_client(settings),
        executor,
        sql_params={
            "max_tokens": settings.llm_sql_max_tokens,
            "reasoning_effort": settings.llm_sql_reasoning_effort,
        },
        answer_params={
            "max_tokens": settings.llm_answer_max_tokens,
            "reasoning_effort": settings.llm_answer_reasoning_effort,
        },
        max_rows=settings.sql_max_rows,
        knowledge=get_knowledge_context(settings),
    )


def get_text_to_sql(request: Request, settings: Settings = Depends(get_settings)) -> TextToSQL:
    state = request.app.state
    with _build_lock:  # 동기 의존성이라 스레드풀에서 실행된다
        if getattr(state, "text_to_sql", None) is None:
            try:
                state.text_to_sql = build_text_to_sql(settings)
            except LLMError as e:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None
    return state.text_to_sql


@router.post("/ask", response_model=AskResponse, response_model_by_alias=True)
async def ask(
    body: AskRequest,
    user: AuthUser = Depends(current_user),
    pipeline: TextToSQL = Depends(get_text_to_sql),
) -> AskResponse:
    """질문 하나에 대해 SQL 을 1회 생성·검증·실행하고 결과로 답한다 (Phase 1, 비스트리밍)."""
    try:
        result = await pipeline.ask(body.question.strip(), user.sdk_key)
    except LLMError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"LLM 호출 실패: {e}") from None
    return AskResponse.of(result)
