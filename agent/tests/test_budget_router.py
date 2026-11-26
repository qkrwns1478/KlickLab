import pytest

from app.agent.budget import LIMITS, Budget
from app.agent.router import Router, parse_classification
from app.llm import ChatResult, Usage


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_budget_exhausts_on_tool_calls_tokens_time_and_context():
    clock = Clock()
    budget = Budget("lookup", clock=clock)
    assert not budget.exhausted()

    budget.tool_calls = LIMITS["lookup"].max_tool_calls
    assert budget.exhausted()

    budget = Budget("lookup", clock=clock)
    budget.tokens = LIMITS["lookup"].max_tokens
    assert budget.exhausted()

    budget = Budget("lookup", clock=clock)
    budget.context_full = True
    assert budget.exhausted()

    budget = Budget("lookup", clock=clock)
    clock.now += LIMITS["lookup"].timeout_s
    assert budget.exhausted()


def test_exhausted_reason_names_the_spent_item():
    clock = Clock()
    budget = Budget("diagnose", clock=clock)
    assert budget.exhausted_reason() is None
    clock.now += LIMITS["diagnose"].timeout_s
    assert budget.exhausted_reason() == f"시간({int(LIMITS['diagnose'].timeout_s)}초)"
    budget = Budget("diagnose", clock=clock)
    budget.tool_calls = LIMITS["diagnose"].max_tool_calls
    assert budget.exhausted_reason().startswith("툴 호출")
    budget = Budget("diagnose", clock=clock)
    budget.timed_out = True  # 모델 호출이 시간 안에 끝나지 않음
    assert budget.exhausted() and budget.exhausted_reason().startswith("시간")


def test_sql_limit_disables_run_sql_without_exhausting():
    budget = Budget("lookup")
    budget.sql_runs = LIMITS["lookup"].max_sql
    assert not budget.can_run_sql()
    assert not budget.exhausted()  # 마지막 SQL 뒤 결론을 내는 것은 정상 흐름


def test_rate_limit_wait_is_excluded_from_elapsed_time():
    clock = Clock()
    budget = Budget("lookup", clock=clock)
    clock.now += LIMITS["lookup"].timeout_s + 10
    budget.excluded_s = 20
    assert not budget.exhausted()


def test_warns_once_at_80_percent():
    budget = Budget("diagnose")
    budget.tool_calls = 11  # 11/15 < 0.8
    assert not budget.should_warn()
    budget.tool_calls = 12
    assert budget.should_warn()
    assert not budget.should_warn()


def test_promotes_once():
    budget = Budget("lookup")
    budget.tool_calls = 2
    assert budget.promote()
    assert budget.difficulty == "compare"
    assert budget.limits == LIMITS["compare"]
    assert budget.tool_calls == 2  # 사용량은 이어진다
    assert not budget.promote()
    assert not Budget("diagnose").can_promote()


def test_out_of_scope_has_no_budget():
    with pytest.raises(ValueError):
        Budget("out_of_scope")


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"difficulty": "compare", "reason": "두 기간 비교"}', ("compare", "두 기간 비교")),
        ('분류:\n```json\n{"difficulty": "DIAGNOSE", "reason": "원인"}\n```', ("diagnose", "원인")),
        ('{"difficulty": "unknown"} lookup', ("lookup", "")),
        ("out_of_scope", ("out_of_scope", "")),
        ("모르겠다", None),
    ],
)
def test_parse_classification(content, expected):
    assert parse_classification(content) == expected


class OneReplyLLM:
    model = "fake"

    def __init__(self, content: str):
        self.content = content

    async def chat(self, messages, **params):
        return ChatResult(content=self.content, usage=Usage(5, 1, 0))

    async def aclose(self):
        pass


async def test_router_falls_back_to_compare():
    result = await Router(OneReplyLLM("???")).classify("q")
    assert result.difficulty == "compare"
    assert result.fallback
    assert result.usage == Usage(5, 1, 0)
