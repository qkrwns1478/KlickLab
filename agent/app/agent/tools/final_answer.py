"""final_answer(모델에게는 submit_report 로 노출): 결론 제출과 근거 연결 검증.

Groq gpt-oss 는 harmony 형식의 final 채널과 이름이 겹치는 final_answer 도구를 부르지 않고
빈 응답으로 끝내는 경향이 있어(같은 대화로 0/3 vs submit_report 3/3) 노출 이름을 바꿨다.

각 finding 은 실제로 실행에 성공한 run_sql step 을 근거(evidence)로 인용해야 한다. 근거가 없거나
존재하지 않는 step 을 인용하면 거부하고 사유를 돌려줘 모델이 고치게 한다(환각 억제).
"""

from dataclasses import asdict, dataclass, field
from typing import Any

from app.agent.tools import RunState, ToolOutcome, function_schema

NAME = "submit_report"
CHART_TYPES = ("bar", "line")

SCHEMA = function_schema(
    NAME,
    "분석 결론을 제출하고 실행을 끝낸다.",
    {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "질문에 대한 핵심 답 (한국어, 1~3문장)"},
            "findings": {
                "type": "array",
                "description": "근거가 있는 주장 목록",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim": {"type": "string", "description": "수치를 포함한 주장 한 문장"},
                        "evidence": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "주장을 뒷받침하는 run_sql 결과의 step_id 목록",
                        },
                    },
                    "required": ["claim", "evidence"],
                },
            },
            "chart": {
                "type": "object",
                "description": "선택. 결과를 그래프로 보여 줄 때만",
                "properties": {
                    "type": {"type": "string", "enum": list(CHART_TYPES)},
                    "step_id": {"type": "integer"},
                    "x": {"type": "string", "description": "x 축 컬럼명"},
                    "y": {"type": "array", "items": {"type": "string"}, "description": "값 컬럼명"},
                    "title": {"type": "string"},
                },
                "required": ["type", "step_id", "x", "y"],
            },
        },
        "required": ["summary", "findings"],
    },
)


@dataclass
class Finding:
    claim: str
    evidence: list[int]


@dataclass
class Chart:
    type: str
    step_id: int
    x: str
    y: list[str]
    title: str = ""


@dataclass
class FinalAnswer:
    summary: str
    findings: list[Finding] = field(default_factory=list)
    chart: Chart | None = None
    forced: bool = False  # 예산 소진·형식 오류로 서버가 정리한 답변
    dropped_findings: int = 0  # 근거 검증을 끝내 통과하지 못해 뺀 주장 수

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "findings": [asdict(f) for f in self.findings],
            "chart": asdict(self.chart) if self.chart else None,
            "forced": self.forced,
            "droppedFindings": self.dropped_findings,
        }


def validate(state: RunState, args: dict[str, Any]) -> tuple[FinalAnswer, list[str], int]:
    """(정리한 답변, 문제 목록, 근거가 없어 뺀 finding 수). 문제가 없으면 문제 목록이 비어 있다."""
    problems: list[str] = []
    summary = args.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        problems.append("summary 가 비어 있다.")
        summary = ""

    findings: list[Finding] = []
    dropped = 0
    raw_findings = args.get("findings") or []
    if not isinstance(raw_findings, list):
        problems.append("findings 는 배열이어야 한다.")
        raw_findings = []
    for i, raw in enumerate(raw_findings, start=1):
        claim = raw.get("claim") if isinstance(raw, dict) else None
        evidence = raw.get("evidence") if isinstance(raw, dict) else None
        if not isinstance(claim, str) or not claim.strip():
            problems.append(f"findings[{i}] 의 claim 이 비어 있다.")
            dropped += 1
            continue
        if not isinstance(evidence, list) or not evidence:
            problems.append(
                f"findings[{i}] 에 근거(evidence)가 없다. 근거가 되는 step_id 를 넣어라."
            )
            dropped += 1
            continue
        invalid = [e for e in evidence if state.sql_step(e) is None]
        if invalid:
            problems.append(
                f"findings[{i}] 의 evidence {invalid} 는 성공한 run_sql step 이 아니다. "
                f"인용할 수 있는 step: {_citable(state)}"
            )
            dropped += 1
            continue
        findings.append(Finding(claim.strip(), list(dict.fromkeys(evidence))))

    chart, chart_problem = _chart(state, args.get("chart"))
    if chart_problem:
        problems.append(chart_problem)
    return FinalAnswer(summary.strip(), findings, chart), problems, dropped


def _chart(state: RunState, raw: Any) -> tuple[Chart | None, str | None]:
    if raw in (None, {}):
        return None, None
    if not isinstance(raw, dict):
        return None, "chart 는 객체여야 한다."
    step = state.sql_step(raw.get("step_id"))
    if step is None:
        return None, f"chart.step_id 는 성공한 run_sql step 이어야 한다: {_citable(state)}"
    if raw.get("type") not in CHART_TYPES:
        return None, f"chart.type 은 {list(CHART_TYPES)} 중 하나다."
    columns = step.result.columns
    x, y = raw.get("x"), raw.get("y")
    if isinstance(y, str):
        y = [y]
    if x not in columns or not isinstance(y, list) or not y or any(c not in columns for c in y):
        return None, f"chart 의 x, y 는 step {step.seq} 결과 컬럼이어야 한다: {columns}"
    return Chart(raw["type"], step.seq, x, list(y), str(raw.get("title") or "")), None


def _citable(state: RunState) -> list[int]:
    return [s.seq for s in state.steps if s.tool == "run_sql" and s.result is not None]


class SubmitFinalAnswer:
    """검증 실패 시 max_rejections 회까지 사유를 돌려주고, 이후엔 근거 없는 주장을 빼고 받는다."""

    def __init__(self, *, max_rejections: int = 2):
        self._max_rejections = max_rejections
        self.rejections = 0

    async def __call__(self, state: RunState, args: dict[str, Any], seq: int) -> ToolOutcome:
        answer, problems, dropped = validate(state, args)
        if problems and (self.rejections < self._max_rejections or not answer.summary):
            self.rejections += 1
            message = "답변을 받아들이지 않았다. 고쳐서 다시 제출하라: " + " / ".join(problems)
            return ToolOutcome.fail(message, charged=False)
        answer.dropped_findings = dropped
        return ToolOutcome(
            for_model={"ok": True}, output=answer.to_dict(), final=answer, charged=False
        )
