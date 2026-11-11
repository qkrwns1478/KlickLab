"""원인 분석 답변 채점.

* rule_judge: 정답 사실(시드에 심은 패턴)의 키워드가 답변에 있는지 본다. 빠르고 재현 가능하지만
  표현이 다르면 놓치고, 틀린 맥락에서 단어만 언급해도 맞았다고 본다.
* LLMJudge: 주장마다 인용한 SQL 결과가 그 주장을 실제로 뒷받침하는지(근거 충실성)와 정답 사실을
  다뤘는지를 모델에게 묻는다. 규칙 채점이 못 보는 "숫자와 맞지 않는 주장"을 잡는다.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.llm import LLMClient, Usage

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

EVIDENCE_ROWS = 15  # 심판 모델에게 보여 줄 근거 행 수


def answer_text(answer: dict[str, Any] | None) -> str:
    if not answer:
        return ""
    claims = [f.get("claim", "") for f in answer.get("findings") or []]
    return "\n".join([answer.get("summary") or "", *claims])


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def fill(keyword: str, values: dict[str, Any]) -> str:
    return _PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), m.group(0))), keyword)


def fact_found(text: str, fact: dict[str, Any], values: dict[str, Any] | None = None) -> bool:
    """keywords 의 모든 그룹에서 하나 이상이 text 에 있으면 True (대소문자·공백 무시)."""
    haystack = _norm(text)
    values = values or {}
    return all(
        any(_norm(fill(str(k), values)) in haystack for k in group)
        for group in fact.get("keywords") or []
    )


@dataclass
class RuleVerdict:
    found: list[str]
    missing: list[str]
    required: int

    @property
    def passed(self) -> bool:
        return len(self.found) >= self.required

    @property
    def coverage(self) -> float:
        total = len(self.found) + len(self.missing)
        return len(self.found) / total if total else 0.0


def rule_judge(
    answer: dict[str, Any] | None, item: dict[str, Any], values: dict[str, Any] | None = None
) -> RuleVerdict:
    text = answer_text(answer)
    found, missing = [], []
    for fact in item["facts"]:
        (found if fact_found(text, fact, values) else missing).append(fact["id"])
    return RuleVerdict(found, missing, int(item.get("required", 1)))


# ---------------------------------------------------------------------------
# LLM-as-judge
# ---------------------------------------------------------------------------

JUDGE_SYSTEM = """\
너는 데이터 분석 답변을 채점하는 심사자다. 답변의 주장(claim)마다 인용한 SQL 결과를 직접 읽고 판정한다.
- supported: 인용한 결과의 숫자·행으로 그 주장을 확인할 수 있으면 true. 수치가 다르거나, 결과에 없는 내용을
  단정하거나, 인용한 결과와 무관하면 false. 결과로 확인할 수 없는 원인 추정은 "가설"로 표현했을 때만 true.
- covered: 정답 사실이 답변(요약 또는 주장)에 같은 의미로 들어 있으면 true. 단어만 같고 뜻이 다르면 false.
반드시 아래 형식의 JSON 객체 하나만 출력한다.
{"claims": [{"index": 1, "supported": true, "reason": "..."}],
 "facts": [{"id": "...", "covered": true}],
 "comment": "한두 문장 총평"}"""


@dataclass
class JudgeVerdict:
    claims: list[dict[str, Any]] = field(default_factory=list)
    facts: dict[str, bool] = field(default_factory=dict)
    comment: str = ""
    usage: Usage = field(default_factory=Usage)
    error: str | None = None

    @property
    def grounded(self) -> float | None:
        """근거로 뒷받침되는 주장 비율. 주장이 없으면 None."""
        if not self.claims:
            return None
        return sum(bool(c.get("supported")) for c in self.claims) / len(self.claims)

    @property
    def fact_coverage(self) -> float | None:
        if not self.facts:
            return None
        return sum(self.facts.values()) / len(self.facts)


def judge_messages(
    question: str,
    answer: dict[str, Any],
    evidence: dict[int, dict[str, Any]],
    facts: list[dict[str, Any]],
) -> list[dict[str, str]]:
    lines = [
        f"## 질문\n{question}",
        "",
        f"## 답변 요약\n{answer.get('summary', '')}",
        "",
        "## 주장",
    ]
    for i, finding in enumerate(answer.get("findings") or [], start=1):
        lines.append(f"{i}. {finding.get('claim', '')} (근거 step: {finding.get('evidence')})")
    lines += ["", "## 근거 SQL 결과"]
    for seq, step in sorted(evidence.items()):
        output = step.get("output") or {}
        rows = output.get("rows") or []
        lines += [
            f"### step {seq}",
            f"SQL: {output.get('sql', '')}",
            f"columns: {json.dumps(output.get('columns'), ensure_ascii=False)}",
            f"rows (총 {output.get('rowCount', len(rows))}행 중 앞 {min(len(rows), EVIDENCE_ROWS)}행):",
            json.dumps(rows[:EVIDENCE_ROWS], ensure_ascii=False, default=str),
        ]
    lines += ["", "## 정답 사실"]
    lines += [f"- {f['id']}: {f['description']}" for f in facts]
    return [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": "\n".join(lines)},
    ]


def parse_verdict(content: str, fact_ids: list[str]) -> JudgeVerdict:
    match = _JSON_OBJECT.search(content or "")
    if not match:
        return JudgeVerdict(error="심사 결과 JSON 없음")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as e:
        return JudgeVerdict(error=f"심사 결과 JSON 해석 실패: {e.msg}")
    claims = [c for c in data.get("claims") or [] if isinstance(c, dict)]
    facts = {
        str(f.get("id")): bool(f.get("covered"))
        for f in data.get("facts") or []
        if isinstance(f, dict) and str(f.get("id")) in fact_ids
    }
    return JudgeVerdict(claims=claims, facts=facts, comment=str(data.get("comment") or ""))


class LLMJudge:
    def __init__(self, llm: LLMClient, **params: Any):
        self._llm = llm
        self._params = params

    @property
    def model(self) -> str:
        return self._llm.model

    async def judge(
        self,
        question: str,
        answer: dict[str, Any] | None,
        evidence: dict[int, dict[str, Any]],
        facts: list[dict[str, Any]],
    ) -> JudgeVerdict:
        if not answer or not answer.get("findings"):
            return JudgeVerdict(error="채점할 주장이 없음")
        chat = await self._llm.chat(
            judge_messages(question, answer, evidence, facts), **self._params
        )
        verdict = parse_verdict(chat.content, [f["id"] for f in facts])
        verdict.usage = chat.usage
        return verdict

    async def aclose(self) -> None:
        await self._llm.aclose()
