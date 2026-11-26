"""질문 난이도 분류 → 실행 예산 결정."""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from app.agent import prompts
from app.agent.budget import DIFFICULTIES, Difficulty
from app.agent.turn import Turn
from app.llm import LLMClient, Usage

# 분류에 실패하면 중간 예산으로 시작한다. 모자라면 루프에서 승격을 요청할 수 있다.
FALLBACK: Difficulty = "compare"

_JSON_OBJECT = re.compile(r"\{.*?\}", re.DOTALL)


@dataclass
class Classification:
    difficulty: Difficulty
    reason: str
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0
    fallback: bool = False  # 모델 출력을 해석하지 못해 기본값을 썼다
    model: str = ""  # 분류에 쓴 모델
    via_fallback: bool = False  # 대체 LLM 공급자가 답했다


def parse_classification(content: str) -> tuple[Difficulty, str] | None:
    for match in _JSON_OBJECT.finditer(content):
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        difficulty = str(data.get("difficulty", "")).strip().lower()
        if difficulty in DIFFICULTIES:
            return difficulty, str(data.get("reason") or "").strip()  # type: ignore[return-value]
    words = re.findall(r"[a-z_]+", content.lower())
    found = [w for w in words if w in DIFFICULTIES]
    if found:
        return found[0], ""  # type: ignore[return-value]
    return None


class Router:
    def __init__(self, llm: LLMClient, *, params: dict[str, Any] | None = None):
        self._llm = llm
        self._params = params or {}

    async def classify(
        self, question: str, history: Sequence[Turn] = (), *, llm: LLMClient | None = None
    ) -> Classification:
        """llm: 실행 세션 (폴백 공급자를 실행 끝까지 유지한다). 없으면 생성 시 받은 클라이언트."""
        chat = await (llm or self._llm).chat(
            prompts.classify_messages(question, history), **self._params
        )
        parsed = parse_classification(chat.content)
        served = {"model": chat.model, "via_fallback": chat.fallback}
        if parsed is None:
            return Classification(
                FALLBACK, "", chat.usage, chat.latency_ms, fallback=True, **served
            )
        difficulty, reason = parsed
        return Classification(difficulty, reason, chat.usage, chat.latency_ms, **served)
