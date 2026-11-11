from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(Exception):
    """LLM 공급자 호출 실패 (네트워크, 4xx/5xx, 빈 응답)."""

    def __init__(self, message: str, *, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            self.prompt_tokens + other.prompt_tokens,
            self.completion_tokens + other.completion_tokens,
            self.reasoning_tokens + other.reasoning_tokens,
        )


@dataclass
class ChatResult:
    content: str
    reasoning: str | None = None
    finish_reason: str | None = None
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0


class LLMClient(Protocol):
    """채팅 완성 모델 공통 인터페이스. 공급자별 파라미터는 **params 로 넘긴다."""

    model: str

    async def chat(
        self, messages: list[dict[str, str]], *, max_tokens: int | None = None, **params: Any
    ) -> ChatResult: ...

    async def aclose(self) -> None: ...
