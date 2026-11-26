"""평가용으로 에이전트(Tool Loop)를 프로세스 안에서 실행하고 실행 과정을 모은다.

실행 로그는 DB(agent_runs)에 남기지 않고 메모리에 모은다.
평가 실행이 사용자 실행 기록에 섞이지 않게 하기 위함이다.
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.agent.loop import AgentEvent, AgentLoop
from app.agent.store import RunTotals
from app.agent.turn import Turn


@dataclass
class CapturedRun:
    question: str
    sdk_key: str
    difficulty: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    totals: RunTotals | None = None


class CaptureStore:
    """RunStore 구현. 실행 단계를 메모리에 남긴다."""

    def __init__(self) -> None:
        self.runs: dict[str, CapturedRun] = {}

    def resolve_conversation(
        self, *, sdk_key: str, user_id: str, conversation_id: str | None
    ) -> tuple[str, list[Turn]]:
        return conversation_id or str(uuid.uuid4()), []  # 평가는 질문마다 독립 실행이다

    def create_run(
        self, *, sdk_key: str, user_id: str, question: str, conversation_id: str | None = None
    ) -> str:
        run_id = str(uuid.uuid4())
        self.runs[run_id] = CapturedRun(question=question, sdk_key=sdk_key)
        return run_id

    def set_difficulty(self, run_id: str, difficulty: str) -> None:
        self.runs[run_id].difficulty = difficulty

    def add_step(self, run_id: str, **step: Any) -> None:
        self.runs[run_id].steps.append(step)

    def finish_run(self, run_id: str, totals: RunTotals) -> None:
        self.runs[run_id].totals = totals


@dataclass
class AgentTrace:
    """에이전트 실행 한 번의 결과."""

    question: str
    sdk_key: str
    events: list[AgentEvent]
    steps: list[dict[str, Any]]

    def _first(self, type_: str) -> dict[str, Any] | None:
        return next((e.data for e in self.events if e.type == type_), None)

    @property
    def run_id(self) -> str:
        return (self._first("started") or {}).get("runId", "")

    @property
    def summary(self) -> dict[str, Any]:
        return self._first("done") or {}

    @property
    def classified(self) -> dict[str, Any]:
        return self._first("classified") or {}

    @property
    def answer(self) -> dict[str, Any] | None:
        return self._first("answer")

    @property
    def error(self) -> str | None:
        error = self._first("error")
        return error.get("message") if error else None

    @property
    def status(self) -> str:
        return self.summary.get("status", "failed")

    def sql_steps(self, *, ok: bool | None = None) -> list[dict[str, Any]]:
        """run_sql step. ok=True 면 실행에 성공한 step (캐시 재사용 제외)만."""
        steps = [s for s in self.steps if s["tool"] == "run_sql"]
        if ok is None:
            return steps
        return [s for s in steps if (s["error"] is None and "rows" in (s["output"] or {})) == ok]

    def step(self, seq: int) -> dict[str, Any] | None:
        return next((s for s in self.steps if s["seq"] == seq), None)

    def evidence_steps(self) -> list[dict[str, Any]]:
        """답변이 근거로 인용한 성공 run_sql step (인용 순서, 중복 제거)."""
        seqs: list[int] = []
        for finding in (self.answer or {}).get("findings") or []:
            seqs += [e for e in finding.get("evidence") or [] if e not in seqs]
        ok = {s["seq"]: s for s in self.sql_steps(ok=True)}
        return [ok[seq] for seq in seqs if seq in ok]

    def sql_stats(self) -> dict[str, int | bool | None]:
        """SQL 자가 수정 지표.

        first_ok: 첫 run_sql 이 바로 성공했는가 (guard 거부·DB 오류 없이)
        corrections: 실패한 run_sql 뒤에 성공한 run_sql 이 이어진 횟수 (모델이 스스로 고친 횟수)
        """
        sql = [s for s in self.sql_steps() if "cachedFrom" not in (s["output"] or {})]
        oks = [s["error"] is None for s in sql]
        corrections = sum(1 for i in range(1, len(oks)) if oks[i] and not oks[i - 1])
        return {
            "attempts": len(sql),
            "failures": oks.count(False),
            "first_ok": oks[0] if oks else None,
            "corrections": corrections,
        }


async def run_agent(
    agent: AgentLoop, store: CaptureStore, question: str, *, sdk_key: str
) -> AgentTrace:
    events = [e async for e in agent.run(question, sdk_key=sdk_key, user_id="eval")]
    run_id = events[0].data["runId"]
    steps = store.runs[run_id].steps if run_id in store.runs else []
    return AgentTrace(question=question, sdk_key=sdk_key, events=events, steps=steps)
