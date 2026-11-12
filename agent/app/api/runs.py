"""Phase 2 에이전트 실행 API.

POST /agent/runs                 질문(+이어갈 conversationId) → SSE 스트림 (started, classified,
                                 tool_call, tool_result, answer, error, done)
GET  /agent/conversations        내 대화 목록 (같은 conversationId 의 실행 묶음)
GET  /agent/conversations/{id}   대화 상세 (실행들을 오래된 순서로, 단계 포함)
PATCH /agent/conversations/{id}  대화 이름 변경 {title}
DELETE /agent/conversations/{id} 대화 삭제 (실행·단계 포함)
GET  /agent/runs                 내 실행 목록
GET  /agent/runs/{id}            실행 상세 (단계별 도구 호출, SQL, 결과)
POST /agent/runs/{id}/feedback   👍(1) / 👎(-1) + 코멘트
"""

import json
import threading
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from app.agent.loop import AgentEvent, AgentLoop
from app.agent.store import PostgresRunStore, build_run_store
from app.auth import AuthUser, current_user
from app.config import Settings, get_settings
from app.knowledge.context import get_knowledge_context
from app.llm import LLMError, build_llm_client
from app.sql.executor import build_executor

router = APIRouter(prefix="/agent/runs")
conversations_router = APIRouter(prefix="/agent/conversations")
_build_lock = threading.Lock()


class RunRequest(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    question: str = Field(min_length=1, max_length=500)
    # 이어서 질문할 대화. 없거나 내 대화가 아니면 새 대화로 시작한다
    conversation_id: str | None = Field(default=None, max_length=64)


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)

    @field_validator("title")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("제목이 비어 있습니다.")
        return value


class FeedbackRequest(BaseModel):
    feedback: Literal[1, -1]
    note: str | None = Field(default=None, max_length=1000)


def get_run_store(request: Request, settings: Settings = Depends(get_settings)) -> PostgresRunStore:
    state = request.app.state
    with _build_lock:  # 동기 의존성이라 스레드풀에서 실행된다
        if getattr(state, "run_store", None) is None:
            state.run_store = build_run_store(settings.dsn(read_only=False))
    return state.run_store


def build_agent(settings: Settings, store: PostgresRunStore) -> AgentLoop:
    executor = build_executor(
        settings.dsn(read_only=True),
        token_dsn=settings.dsn(read_only=False),
        statement_timeout_ms=settings.sql_statement_timeout_ms,
        result_rows=settings.sql_result_rows,
        max_plan_cost=settings.sql_max_plan_cost,
    )
    return AgentLoop(
        build_llm_client(settings),
        executor,
        store,
        classify_params={
            "max_tokens": settings.agent_classify_max_tokens,
            "reasoning_effort": settings.agent_classify_reasoning_effort,
        },
        step_max_tokens=settings.agent_step_max_tokens,
        max_prompt_tokens=settings.agent_max_prompt_tokens,
        max_rows=settings.sql_max_rows,
        model_rows=settings.agent_tool_result_rows,
        knowledge=get_knowledge_context(settings),
    )


def get_agent(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: PostgresRunStore = Depends(get_run_store),
) -> AgentLoop:
    state = request.app.state
    with _build_lock:
        if getattr(state, "agent", None) is None:
            try:
                state.agent = build_agent(settings, store)
            except LLMError as e:
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None
    return state.agent


def sse(event: AgentEvent) -> str:
    data = json.dumps(event.data, ensure_ascii=False, default=str)
    return f"event: {event.type}\ndata: {data}\n\n"


@router.post("")
async def create_run(
    body: RunRequest,
    user: AuthUser = Depends(current_user),
    agent: AgentLoop = Depends(get_agent),
) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        events = agent.run(
            body.question.strip(),
            sdk_key=user.sdk_key,
            user_id=user.user_id,
            conversation_id=body.conversation_id,
        )
        try:
            async for event in events:
                yield sse(event)
        finally:
            await events.aclose()  # 연결이 끊기면 실행을 중단하고 실패로 기록한다

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("")
def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    user: AuthUser = Depends(current_user),
    store: PostgresRunStore = Depends(get_run_store),
) -> list[dict[str, Any]]:
    return store.list_runs(sdk_key=user.sdk_key, user_id=user.user_id, limit=limit)


@conversations_router.get("")
def list_conversations(
    limit: int = Query(default=50, ge=1, le=200),
    user: AuthUser = Depends(current_user),
    store: PostgresRunStore = Depends(get_run_store),
) -> list[dict[str, Any]]:
    return store.list_conversations(sdk_key=user.sdk_key, user_id=user.user_id, limit=limit)


@conversations_router.get("/{conversation_id}")
def get_conversation(
    conversation_id: str,
    user: AuthUser = Depends(current_user),
    store: PostgresRunStore = Depends(get_run_store),
) -> dict[str, Any]:
    conversation = store.get_conversation(
        conversation_id, sdk_key=user.sdk_key, user_id=user.user_id
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "대화가 없습니다.")
    return conversation


@conversations_router.patch("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def rename_conversation(
    conversation_id: str,
    body: RenameRequest,
    user: AuthUser = Depends(current_user),
    store: PostgresRunStore = Depends(get_run_store),
) -> Response:
    renamed = store.rename_conversation(
        conversation_id, sdk_key=user.sdk_key, user_id=user.user_id, title=body.title
    )
    if not renamed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "대화가 없습니다.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@conversations_router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    user: AuthUser = Depends(current_user),
    store: PostgresRunStore = Depends(get_run_store),
) -> Response:
    if not store.delete_conversation(conversation_id, sdk_key=user.sdk_key, user_id=user.user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "대화가 없습니다.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{run_id}")
def get_run(
    run_id: str,
    user: AuthUser = Depends(current_user),
    store: PostgresRunStore = Depends(get_run_store),
) -> dict[str, Any]:
    run = store.get_run(run_id, sdk_key=user.sdk_key, user_id=user.user_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "실행 기록이 없습니다.")
    return run


@router.post("/{run_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def set_feedback(
    run_id: str,
    body: FeedbackRequest,
    user: AuthUser = Depends(current_user),
    store: PostgresRunStore = Depends(get_run_store),
) -> Response:
    updated = store.set_feedback(
        run_id, sdk_key=user.sdk_key, user_id=user.user_id, feedback=body.feedback, note=body.note
    )
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "실행 기록이 없습니다.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
