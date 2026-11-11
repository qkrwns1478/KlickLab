"""Tool Loop 에서 모델이 호출하는 도구.

각 도구는 OpenAI function 스키마(SCHEMA)와 handler 를 가진다. handler 의 실패는 예외가 아니라
ToolOutcome.error 로 돌려주고, 루프는 이를 그대로 모델에게 보여 줘 스스로 고치게 한다.
"""

import json
from dataclasses import dataclass, field
from typing import Any

from app.agent.budget import Budget
from app.sql.executor import QueryResult


@dataclass
class Step:
    seq: int
    tool: str
    input: dict[str, Any]
    output: dict[str, Any] | None = None
    error: str | None = None
    duration_ms: int = 0
    result: QueryResult | None = None  # run_sql 성공 결과 (근거·차트 검증용)
    for_model: dict[str, Any] = field(default_factory=dict)  # 모델에게 돌려준 내용
    final: Any = None  # 받아들여진 final_answer (FinalAnswer)


@dataclass
class RunState:
    """한 번의 실행 동안 도구들이 공유하는 상태."""

    sdk_key: str
    budget: Budget
    steps: list[Step] = field(default_factory=list)
    sql_cache: dict[str, int] = field(default_factory=dict)  # 정규화한 SQL → step seq

    def sql_step(self, seq: Any) -> Step | None:
        """성공한 run_sql step (근거로 인용할 수 있는 step)."""
        if isinstance(seq, bool) or not isinstance(seq, int):
            return None
        for step in self.steps:
            if step.seq == seq and step.tool == "run_sql" and step.result is not None:
                return step
        return None


@dataclass
class ToolOutcome:
    for_model: dict[str, Any]  # 모델에게 돌려줄 내용
    output: dict[str, Any] | None = None  # 실행 로그·SSE 에 남길 내용
    error: str | None = None
    result: QueryResult | None = None
    final: Any = None  # final_answer 가 받아들여진 경우 FinalAnswer
    charged: bool = True  # 툴 호출 예산 차감 여부

    @classmethod
    def fail(cls, message: str, *, charged: bool = True, **extra: Any) -> "ToolOutcome":
        return cls(
            for_model={"ok": False, "error": message, **extra}, error=message, charged=charged
        )


def parse_arguments(raw: str) -> dict[str, Any]:
    """모델이 만든 인자 JSON. 해석할 수 없으면 ValueError."""
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as e:
        raise ValueError(f"도구 인자가 올바른 JSON 이 아닙니다: {e.msg}") from None
    if not isinstance(data, dict):
        raise ValueError("도구 인자는 JSON 객체여야 합니다.")
    return data


def function_schema(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }
