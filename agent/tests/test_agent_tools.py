from dataclasses import dataclass, field

import pytest

from app.agent.budget import Budget
from app.agent.tools import RunState, Step
from app.agent.tools.describe_table import DescribeTable, sample_sql
from app.agent.tools.final_answer import SubmitFinalAnswer, validate
from app.agent.tools.request_more_budget import request_more_budget
from app.agent.tools.run_sql import RunSQL, normalize_sql
from app.sql.executor import QueryResult, SQLExecutionError


@dataclass
class FakeExecutor:
    results: list = field(default_factory=list)  # QueryResult 또는 SQLExecutionError
    executed: list = field(default_factory=list)

    def execute(self, sql, sdk_key, **kwargs):
        self.executed.append((sql, sdk_key))
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


def _result(columns, rows):
    return QueryResult(columns, rows, len(rows), False, 1)


def _state(difficulty="compare") -> RunState:
    return RunState(sdk_key="key-1", budget=Budget(difficulty))


def _add_sql_step(state, seq, result):
    state.steps.append(Step(seq=seq, tool="run_sql", input={}, result=result))


SQL = "SELECT summary_date, count(*) AS v FROM agg_daily_users GROUP BY 1"


async def test_run_sql_executes_with_callers_key_and_returns_step_id():
    executor = FakeExecutor([_result(["v"], [[1.23456789]])])
    state = _state()
    outcome = await RunSQL(executor)(state, {"sql": SQL, "purpose": "p"}, 3)

    assert outcome.error is None
    assert outcome.for_model["step_id"] == 3
    assert outcome.for_model["rows"] == [[1.23457]]  # 모델에게는 유효숫자 6자리
    assert outcome.output["rows"] == [[1.23456789]]  # 실행 로그에는 원본
    assert executor.executed[0][1] == "key-1"
    assert "LIMIT 1000" in executor.executed[0][0]
    assert state.budget.sql_runs == 1


async def test_run_sql_returns_guard_reason_without_executing():
    executor = FakeExecutor()
    state = _state()
    outcome = await RunSQL(executor)(state, {"sql": "SELECT email FROM users"}, 1)

    assert outcome.for_model["ok"] is False
    assert outcome.for_model["kind"] == "rejected"
    assert "users" in outcome.error
    assert executor.executed == []
    assert state.budget.sql_runs == 0  # DB 까지 가지 않은 실패는 SQL 예산을 쓰지 않는다


async def test_run_sql_returns_db_error_for_self_correction():
    executor = FakeExecutor([SQLExecutionError("error", 'column "x" does not exist')])
    state = _state()
    outcome = await RunSQL(executor)(state, {"sql": SQL}, 1)

    assert outcome.for_model == {
        "ok": False,
        "error": 'column "x" does not exist',
        "kind": "error",
    }
    assert state.budget.sql_runs == 1


async def test_run_sql_caches_same_sql_without_charging():
    executor = FakeExecutor([_result(["v"], [[1]])])
    state = _state()
    tool = RunSQL(executor)
    first = await tool(state, {"sql": SQL}, 1)
    _add_sql_step(state, 1, first.result)

    again = await tool(state, {"sql": "  " + SQL.replace(" ", "\n  ") + ";"}, 2)

    assert len(executor.executed) == 1
    assert again.for_model["step_id"] == 1
    assert again.for_model["cached"] is True
    assert again.charged is False
    assert again.result is None  # 근거는 원래 step 을 인용한다
    assert state.budget.sql_runs == 1


async def test_run_sql_refuses_when_sql_budget_is_spent():
    state = _state("lookup")
    state.budget.sql_runs = 1
    outcome = await RunSQL(FakeExecutor())(state, {"sql": SQL}, 1)
    assert outcome.for_model["kind"] == "budget"


async def test_run_sql_truncates_rows_for_model():
    rows = [[i] for i in range(50)]
    state = _state()
    outcome = await RunSQL(FakeExecutor([_result(["v"], rows)]), model_rows=20)(
        state, {"sql": SQL}, 1
    )
    assert len(outcome.for_model["rows"]) == 20
    assert outcome.for_model["row_count"] == 50
    assert "note" in outcome.for_model
    assert len(outcome.output["rows"]) == 50


def test_normalize_sql():
    assert normalize_sql("SELECT 1\n  FROM t ;") == "SELECT 1 FROM t"


def test_final_answer_requires_evidence_from_successful_sql():
    state = _state()
    _add_sql_step(state, 1, _result(["channel", "rate"], [["naver", 1.0]]))
    state.steps.append(Step(seq=2, tool="run_sql", input={}, error="실패"))

    answer, problems, dropped = validate(
        state,
        {
            "summary": "요약",
            "findings": [
                {"claim": "근거 있음", "evidence": [1, 1]},
                {"claim": "근거 없음", "evidence": []},
                {"claim": "실패한 step 인용", "evidence": [2]},
                {"claim": "없는 step 인용", "evidence": [9]},
            ],
        },
    )
    assert [f.claim for f in answer.findings] == ["근거 있음"]
    assert answer.findings[0].evidence == [1]
    assert len(problems) == 3
    assert dropped == 3
    assert "인용할 수 있는 step: [1]" in problems[1]


def test_final_answer_validates_chart_columns():
    state = _state()
    _add_sql_step(state, 1, _result(["channel", "rate"], [["naver", 1.0]]))
    base = {"summary": "s", "findings": []}

    answer, problems, _ = validate(
        state, {**base, "chart": {"type": "bar", "step_id": 1, "x": "channel", "y": "rate"}}
    )
    assert problems == []
    assert answer.chart.y == ["rate"]

    _, problems, _ = validate(
        state, {**base, "chart": {"type": "bar", "step_id": 1, "x": "channel", "y": ["nope"]}}
    )
    assert "컬럼" in problems[0]
    _, problems, _ = validate(
        state, {**base, "chart": {"type": "pie", "step_id": 1, "x": "channel", "y": ["rate"]}}
    )
    assert "chart.type" in problems[0]


async def test_submit_rejects_then_accepts_supported_findings_only():
    state = _state()
    _add_sql_step(state, 1, _result(["v"], [[1]]))
    args = {
        "summary": "요약",
        "findings": [{"claim": "a", "evidence": [1]}, {"claim": "b", "evidence": [7]}],
    }
    submit = SubmitFinalAnswer(max_rejections=2)

    for _ in range(2):
        outcome = await submit(state, args, 2)
        assert outcome.final is None
        assert outcome.for_model["ok"] is False
        assert outcome.charged is False

    outcome = await submit(state, args, 4)
    assert outcome.final is not None
    assert [f.claim for f in outcome.final.findings] == ["a"]
    assert outcome.final.dropped_findings == 1


async def test_submit_never_accepts_empty_summary():
    submit = SubmitFinalAnswer(max_rejections=0)
    outcome = await submit(_state(), {"summary": " ", "findings": []}, 1)
    assert outcome.final is None


async def test_request_more_budget_promotes_once():
    state = _state("lookup")
    outcome = await request_more_budget(state, {"reason": "원인 분석 필요"}, 1)
    assert outcome.for_model["difficulty"] == "compare"
    assert outcome.output == {"from": "lookup", "to": "compare", "reason": "원인 분석 필요"}
    again = await request_more_budget(state, {"reason": "x"}, 2)
    assert again.for_model["ok"] is False


async def test_describe_table_rejects_tables_outside_whitelist():
    executor = FakeExecutor()
    outcome = await DescribeTable(executor)(_state(), {"table_name": "users"}, 1)
    assert outcome.for_model["ok"] is False
    assert executor.executed == []


async def test_describe_table_returns_columns_and_sample():
    executor = FakeExecutor(
        [
            _result(
                ["column_name", "data_type"], [["summary_date", "date"], ["client_id", "text"]]
            ),
            _result(["summary_date", "client_id"], [["2026-11-10", "c1"]]),
            _result(["summary_date", "client_id"], [["2026-11-10", "c1"]]),
        ]
    )
    tool = DescribeTable(executor)
    outcome = await tool(_state(), {"table_name": "public.agg_daily_users"}, 1)
    assert outcome.for_model["columns"] == [
        {"name": "summary_date", "type": "date"},
        {"name": "client_id", "type": "text"},
    ]
    assert 'ORDER BY "summary_date" DESC LIMIT 3' in executor.executed[1][0]

    await tool(_state(), {"table_name": "agg_daily_users"}, 2)
    assert len(executor.executed) == 3  # 컬럼 정보는 캐시한다


@pytest.mark.parametrize(
    ("table", "columns", "expected"),
    [
        ("events", [], "WHERE timestamp >= current_date - 1"),
        ("daily_metrics", [{"name": "date"}], 'ORDER BY "date" DESC'),
        ("conversion_events", [{"name": "event_name"}], "SELECT * FROM conversion_events LIMIT 3"),
    ],
)
def test_sample_sql(table, columns, expected):
    assert expected in sample_sql(table, columns)
