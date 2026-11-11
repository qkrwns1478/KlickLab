"""Phase 1 단일 턴 Text-to-SQL: 질문 → SQL 1회 생성 → 검증 → 실행 → 자연어 답변."""

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from app.agent import prompts
from app.llm import LLMClient, Usage
from app.sql.executor import QueryResult, SQLExecutionError, SQLExecutor
from app.sql.guard import SQLRejected, guard

KST = timezone(timedelta(hours=9))  # 한국은 서머타임이 없다
ANSWER_ROWS = 50

Status = Literal["succeeded", "rejected", "failed", "out_of_scope"]

_SQL_BLOCK = re.compile(r"```(?:sql|postgresql|postgres)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_NO_SQL = re.compile(r"^\s*NO_SQL\s*:\s*(.*)", re.DOTALL)


def today_kst() -> date:
    return datetime.now(KST).date()


@dataclass
class SQLDraft:
    sql: str | None
    no_sql_reason: str | None
    usage: Usage
    latency_ms: int
    truncated: bool = False  # 토큰 한도에서 출력이 잘림


@dataclass
class AskResult:
    status: Status
    question: str
    sql: str | None = None
    executed_sql: str | None = None
    result: QueryResult | None = None
    answer: str | None = None
    error: str | None = None
    usage: Usage = field(default_factory=Usage)
    timings: dict[str, int] = field(default_factory=dict)


def extract_sql(content: str) -> tuple[str | None, str | None]:
    """모델 출력에서 (sql, no_sql_reason) 을 꺼낸다."""
    text = content.strip()
    matched = _NO_SQL.match(text)
    if matched:
        return None, matched.group(1).strip() or "데이터 조회로 답할 수 없는 질문입니다."
    blocks = _SQL_BLOCK.findall(text)
    if blocks:
        return blocks[-1].strip(), None
    if re.match(r"(?is)^\s*(select|with)\b", text):
        return text, None
    return None, None


class TextToSQL:
    def __init__(
        self,
        llm: LLMClient,
        executor: SQLExecutor,
        *,
        sql_params: dict[str, Any] | None = None,
        answer_params: dict[str, Any] | None = None,
        max_rows: int = 1000,
    ):
        self._llm = llm
        self._executor = executor
        self._sql_params = sql_params or {}
        self._answer_params = answer_params or {}
        self._max_rows = max_rows

    async def generate_sql(self, question: str, *, today: date | None = None) -> SQLDraft:
        chat = await self._llm.chat(
            prompts.sql_messages(question, today or today_kst()), **self._sql_params
        )
        sql, reason = extract_sql(chat.content)
        return SQLDraft(sql, reason, chat.usage, chat.latency_ms, chat.finish_reason == "length")

    async def ask(self, question: str, sdk_key: str) -> AskResult:
        draft = await self.generate_sql(question)
        out = AskResult(status="failed", question=question, usage=draft.usage)
        out.timings["generate_ms"] = draft.latency_ms

        if draft.sql is None:
            if draft.no_sql_reason:
                out.status, out.answer = "out_of_scope", draft.no_sql_reason
            elif draft.truncated:
                out.error = "모델 출력이 토큰 한도에서 잘렸습니다."
            else:
                out.error = "모델 출력에서 SQL 을 찾지 못했습니다."
            return out

        out.sql = draft.sql
        try:
            guarded = guard(draft.sql, max_rows=self._max_rows)
        except SQLRejected as e:
            out.status, out.error = "rejected", e.reason
            return out
        out.executed_sql = guarded.sql

        try:
            result = await asyncio.to_thread(self._executor.execute, guarded.sql, sdk_key)
        except SQLExecutionError as e:
            out.error = e.message
            return out
        out.result = result
        out.timings["execute_ms"] = result.elapsed_ms

        chat = await self._llm.chat(
            prompts.answer_messages(question, draft.sql, _result_json(result)),
            **self._answer_params,
        )
        out.usage = out.usage + chat.usage
        out.timings["answer_ms"] = chat.latency_ms
        out.answer = chat.content or None
        out.status = "succeeded"
        return out

    async def aclose(self) -> None:
        await self._llm.aclose()
        await asyncio.to_thread(self._executor.close)


def _result_json(result: QueryResult) -> str:
    rows = result.rows[:ANSWER_ROWS]
    payload = {
        "columns": result.columns,
        "rows": rows,
        "row_count": result.row_count,
        "truncated": result.row_count > len(rows),
    }
    return json.dumps(payload, ensure_ascii=False, default=str)
