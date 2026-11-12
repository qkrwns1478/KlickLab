from dataclasses import dataclass

# 모델에 넘기는 이전 대화의 최대 턴 수
HISTORY_TURNS = 3


@dataclass
class Turn:
    """같은 대화의 이전 실행 하나: 질문과 최종 답변 요약."""

    question: str
    summary: str
