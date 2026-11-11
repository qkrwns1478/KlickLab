import asyncio
import re
from typing import Any

from app.agent.tools import RunState, ToolOutcome, function_schema
from app.sql.executor import QueryResult, SQLExecutionError, SQLExecutor
from app.sql.guard import SQLRejected, guard

NAME = "run_sql"

SCHEMA = function_schema(
    NAME,
    "읽기 전용 SELECT 쿼리 하나를 실행하고 결과를 돌려준다. 실패하면 사유를 돌려준다.",
    {
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "PostgreSQL SELECT 또는 WITH ... SELECT 한 문장",
            },
            "purpose": {"type": "string", "description": "이 쿼리로 확인하려는 것 (한 문장)"},
        },
        "required": ["sql", "purpose"],
    },
)


def normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().rstrip(";").strip()


class RunSQL:
    def __init__(self, executor: SQLExecutor, *, max_rows: int = 1000, model_rows: int = 30):
        self._executor = executor
        self._max_rows = max_rows
        self._model_rows = model_rows

    async def __call__(self, state: RunState, args: dict[str, Any], seq: int) -> ToolOutcome:
        sql = args.get("sql")
        if not isinstance(sql, str) or not sql.strip():
            return ToolOutcome.fail("sql 인자가 필요합니다.")

        key = normalize_sql(sql)
        cached = state.sql_step(state.sql_cache.get(key))
        if cached is not None:  # 같은 SQL 은 다시 실행하지 않고 예산도 차감하지 않는다
            outcome = self._for_model(cached.seq, cached.result)
            outcome.for_model["cached"] = True
            outcome.output = {"cachedFrom": cached.seq}
            outcome.charged = False
            return outcome

        if not state.budget.can_run_sql():
            return ToolOutcome.fail(
                "SQL 실행 예산을 모두 썼다. 지금까지의 결과로 submit_report 를 제출하라.",
                kind="budget",
            )

        try:
            guarded = guard(sql, max_rows=self._max_rows)
        except SQLRejected as e:
            return ToolOutcome.fail(e.reason, kind="rejected")

        state.budget.sql_runs += 1
        try:
            result = await asyncio.to_thread(self._executor.execute, guarded.sql, state.sdk_key)
        except SQLExecutionError as e:
            outcome = ToolOutcome.fail(e.message, kind=e.kind)
            outcome.output = {"sql": guarded.sql}
            return outcome

        state.sql_cache[key] = seq
        outcome = self._for_model(seq, result)
        outcome.result = result
        outcome.output = {
            "sql": guarded.sql,
            "limitApplied": guarded.limit_applied,
            "columns": result.columns,
            "rows": result.rows,
            "rowCount": result.row_count,
            "truncated": result.truncated,
            "elapsedMs": result.elapsed_ms,
        }
        return outcome

    def _for_model(self, seq: int, result: QueryResult) -> ToolOutcome:
        shown = [[_round(v) for v in row] for row in result.rows[: self._model_rows]]
        for_model: dict[str, Any] = {
            "ok": True,
            "step_id": seq,
            "columns": result.columns,
            "rows": shown,
            "row_count": result.row_count,
        }
        if result.row_count > len(shown):
            for_model["note"] = (
                f"{result.row_count}행 중 앞 {len(shown)}행만 보여 준다. "
                "필요하면 집계하거나 ORDER BY / LIMIT 으로 좁혀 다시 조회하라."
            )
        return ToolOutcome(for_model=for_model)


def _round(value: Any) -> Any:
    """모델에게 보내는 소수는 유효숫자 6자리로 줄인다 (52.38095238095238 → 52.381, 토큰 절약)."""
    if isinstance(value, float):
        return float(f"{value:.6g}")
    return value
