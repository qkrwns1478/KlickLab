"""질문 난이도별 실행 예산: 툴 호출 수, SQL 실행 수, 누적 토큰, 경과 시간.

* 예산의 80% 에 닿으면 루프가 한 번 "남은 예산 안에서 결론을 내라" 고 알린다.
* 툴 호출 수·토큰·시간·입력 크기(context_full) 중 하나라도 소진되면 final_answer 만 허용한다.
  SQL 실행 수가 다 차면 run_sql 만 빠진다 (마지막 SQL 뒤에 결론을 내는 것은 정상 흐름이다).
* 루프 중 1회에 한해 상위 난이도로 승격할 수 있다 (request_more_budget).
* 경과 시간에서 공급자 레이트 리밋 대기(요청 간격, 429 재시도)는 뺀다. 예산은 에이전트가 한 일의
  양을 제한하려는 것이고, 무료 등급 대기열 때문에 결론 없이 끝나지 않게 하기 위함이다.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

Difficulty = Literal["lookup", "compare", "diagnose", "out_of_scope"]
DIFFICULTIES: tuple[Difficulty, ...] = ("lookup", "compare", "diagnose", "out_of_scope")

WARN_RATIO = 0.8


@dataclass(frozen=True)
class BudgetLimits:
    max_tool_calls: int  # final_answer 를 제외한 툴 호출
    max_sql: int  # DB 까지 간 run_sql (guard 거부는 세지 않는다)
    max_tokens: int  # 누적 입력 + 출력 토큰
    timeout_s: float
    reasoning_effort: str


# 계획 문서의 타임아웃(15/40/120초)은 Claude 기준이다.
# Groq 무료 등급은 요청 간 2초 간격과 429 대기가 섞이므로 넉넉하게 둔다.
LIMITS: dict[Difficulty, BudgetLimits] = {
    "lookup": BudgetLimits(3, 1, 20_000, 30, "medium"),
    "compare": BudgetLimits(6, 3, 50_000, 60, "high"),
    "diagnose": BudgetLimits(15, 8, 120_000, 180, "high"),
}

NEXT_DIFFICULTY: dict[Difficulty, Difficulty] = {"lookup": "compare", "compare": "diagnose"}


class Budget:
    def __init__(self, difficulty: Difficulty, *, clock: Callable[[], float] = time.monotonic):
        if difficulty not in LIMITS:
            raise ValueError(f"예산이 없는 난이도입니다: {difficulty}")
        self.difficulty: Difficulty = difficulty
        self.limits = LIMITS[difficulty]
        self.tool_calls = 0
        self.sql_runs = 0
        self.tokens = 0
        self.promoted = False
        self.warned = False
        self.excluded_s = 0.0  # 레이트 리밋 대기
        self.context_full = False  # 이력을 압축해도 입력 토큰 상한을 넘는다
        self.timed_out = False  # 모델 호출이 남은 시간 안에 끝나지 않았다
        self.time_factor = 1.0  # 느린 공급자(로컬 모델)로 진행할 때 시간 한도 배율
        self._clock = clock
        self._started = clock()

    @property
    def timeout_s(self) -> float:
        return self.limits.timeout_s * self.time_factor

    @property
    def elapsed_s(self) -> float:
        return self._clock() - self._started - self.excluded_s

    def ratio(self) -> float:
        """가장 많이 쓴 항목의 사용 비율."""
        limits = self.limits
        return max(
            self.tool_calls / limits.max_tool_calls,
            self.sql_runs / limits.max_sql,
            self.tokens / limits.max_tokens,
            self.elapsed_s / self.timeout_s,
        )

    def exhausted(self) -> bool:
        limits = self.limits
        return (
            self.context_full
            or self.timed_out
            or self.tool_calls >= limits.max_tool_calls
            or self.tokens >= limits.max_tokens
            or self.elapsed_s >= self.timeout_s
        )

    def exhausted_reason(self) -> str | None:
        """소진된 항목 (모델에게 알릴 사유). 소진되지 않았으면 None."""
        limits = self.limits
        if self.context_full:
            return "입력 길이"
        if self.timed_out or self.elapsed_s >= self.timeout_s:
            return f"시간({int(self.timeout_s)}초)"
        if self.tool_calls >= limits.max_tool_calls:
            return f"툴 호출({limits.max_tool_calls}회)"
        if self.tokens >= limits.max_tokens:
            return f"토큰({limits.max_tokens:,})"
        return None

    def should_warn(self) -> bool:
        """80% 에 처음 닿았을 때 한 번만 True."""
        if self.warned or self.ratio() < WARN_RATIO:
            return False
        self.warned = True
        return True

    def can_call_tool(self) -> bool:
        return not self.exhausted()

    def can_run_sql(self) -> bool:
        return self.sql_runs < self.limits.max_sql

    def can_promote(self) -> bool:
        return not self.promoted and self.difficulty in NEXT_DIFFICULTY

    def promote(self) -> bool:
        """상위 난이도 예산으로 바꾼다. 사용량과 경과 시간은 그대로 이어진다."""
        if not self.can_promote():
            return False
        self.difficulty = NEXT_DIFFICULTY[self.difficulty]
        self.limits = LIMITS[self.difficulty]
        self.promoted = True
        self.warned = False
        return True

    def remaining(self) -> dict[str, int]:
        limits = self.limits
        return {
            "toolCalls": max(limits.max_tool_calls - self.tool_calls, 0),
            "sqlRuns": max(limits.max_sql - self.sql_runs, 0),
            "tokens": max(limits.max_tokens - self.tokens, 0),
            "seconds": max(int(self.timeout_s - self.elapsed_s), 0),
        }
