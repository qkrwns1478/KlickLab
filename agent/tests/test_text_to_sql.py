from dataclasses import dataclass, field
from typing import Any

import pytest

from app.agent.text_to_sql import TextToSQL, extract_sql
from app.llm import ChatResult, Usage
from app.sql.executor import QueryResult, SQLExecutionError


@dataclass
class FakeLLM:
    replies: list[str]
    model: str = "fake"
    calls: list[list[dict[str, str]]] = field(default_factory=list)

    async def chat(self, messages, *, max_tokens=None, **params: Any) -> ChatResult:
        self.calls.append(messages)
        return ChatResult(content=self.replies.pop(0), usage=Usage(10, 5, 2), latency_ms=1)

    async def aclose(self) -> None:
        pass


@dataclass
class FakeExecutor:
    result: QueryResult | None = None
    error: SQLExecutionError | None = None
    executed: list[tuple[str, str]] = field(default_factory=list)

    def execute(self, sql: str, sdk_key: str) -> QueryResult:
        self.executed.append((sql, sdk_key))
        if self.error:
            raise self.error
        return self.result

    def close(self) -> None:
        pass


ROWS = QueryResult(columns=["visitors"], rows=[[575]], row_count=1, truncated=False, elapsed_ms=3)
SQL = "SELECT count(*) AS visitors FROM agg_daily_users WHERE summary_date = current_date - 1"


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (f"```sql\n{SQL}\n```", (SQL, None)),
        (f"\n\n```SQL\n{SQL};\n```\n", (SQL + ";", None)),
        (f"```\n{SQL}\n```", (SQL, None)),
        (f"초안\n```sql\nSELECT 1\n```\n수정\n```sql\n{SQL}\n```", (SQL, None)),
        (SQL, (SQL, None)),
        ("NO_SQL: 데이터 변경 요청입니다.", (None, "데이터 변경 요청입니다.")),
        ("잘 모르겠습니다.", (None, None)),
    ],
)
def test_extract_sql(content, expected):
    assert extract_sql(content) == expected


async def test_ask_runs_generated_sql_with_callers_sdk_key():
    llm = FakeLLM([f"```sql\n{SQL}\n```", "어제 순 방문자는 575명입니다."])
    executor = FakeExecutor(result=ROWS)
    result = await TextToSQL(llm, executor).ask("어제 방문자 수는?", "key-1")

    assert result.status == "succeeded"
    assert result.answer == "어제 순 방문자는 575명입니다."
    assert executor.executed[0][1] == "key-1"
    assert "LIMIT 1000" in executor.executed[0][0]
    assert result.usage == Usage(20, 10, 4)
    assert "575" in llm.calls[1][1]["content"]  # 답변 프롬프트에 실행 결과가 들어간다


async def test_ask_does_not_execute_rejected_sql():
    executor = FakeExecutor(result=ROWS)
    llm = FakeLLM(["```sql\nSELECT email FROM users\n```"])
    result = await TextToSQL(llm, executor).ask("회원 이메일 목록", "key-1")

    assert result.status == "rejected"
    assert "users" in result.error
    assert executor.executed == []
    assert len(llm.calls) == 1


async def test_ask_reports_execution_error_without_answer_call():
    llm = FakeLLM([f"```sql\n{SQL}\n```"])
    executor = FakeExecutor(error=SQLExecutionError("error", 'column "x" does not exist'))
    result = await TextToSQL(llm, executor).ask("어제 방문자 수는?", "key-1")

    assert result.status == "failed"
    assert "does not exist" in result.error
    assert len(llm.calls) == 1


async def test_ask_out_of_scope():
    llm = FakeLLM(["NO_SQL: 분석 데이터와 무관한 질문입니다."])
    executor = FakeExecutor(result=ROWS)
    result = await TextToSQL(llm, executor).ask("오늘 날씨 어때?", "key-1")

    assert result.status == "out_of_scope"
    assert result.answer == "분석 데이터와 무관한 질문입니다."
    assert executor.executed == []


async def test_generate_sql_uses_knowledge_context_in_rag_mode():
    from app.knowledge.context import SchemaContext
    from app.knowledge.retriever import Hit

    class Knowledge:
        async def aschema_for(self, question):
            hits = [Hit("metric", "bounce_rate", "이탈률", "본문", 0.1)]
            return SchemaContext("## 참고 문서\n이탈률 정의", hits, elapsed_ms=7)

    llm = FakeLLM(["```sql\nSELECT 1\n```"])
    pipeline = TextToSQL(llm, FakeExecutor(), knowledge=Knowledge())  # type: ignore[arg-type]
    draft = await pipeline.generate_sql("이탈률은?")

    system = llm.calls[0][0]["content"]
    assert "이탈률 정의" in system and "## 일 단위 집계" not in system
    assert draft.knowledge == ["metric/bounce_rate"] and draft.retrieval_ms == 7
