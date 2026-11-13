from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(Exception):
    """LLM 공급자 호출 실패 (네트워크, 4xx/5xx, 빈 응답)."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        wait_ms: int = 0,
        retry_after: float | None = None,
        daily: bool = False,
        unavailable: bool = False,
    ):
        super().__init__(message)
        self.status = status
        self.wait_ms = wait_ms  # 실패 전까지 레이트 리밋 간격·재시도로 기다린 시간
        self.retry_after = retry_after  # 공급자가 알려 준 재시도 가능 시점까지의 초
        self.daily = daily  # 하루 한도 초과 (몇 분~몇 시간 뒤에야 풀린다)
        self.unavailable = unavailable  # 서버에 연결하지 못했다 (응답 자체가 없음)

    @property
    def user_message(self) -> str:
        """사용자에게 보여 줄 문구. 공급자 응답 원문(조직 ID 등)은 담지 않고 로그에만 남긴다."""
        if self.status in (402, 429):
            return "LLM 사용 한도에 도달했습니다. 잠시 후 다시 시도해 주세요."
        if self.status == 408:
            return "LLM 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요."
        if self.status in (401, 403):
            return "LLM 서비스 인증에 문제가 있습니다. 관리자에게 문의해 주세요."
        return "LLM 서비스에 문제가 생겼습니다. 잠시 후 다시 시도해 주세요."


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
class ToolCall:
    id: str
    name: str
    arguments: str  # 모델이 만든 JSON 문자열 그대로 (해석 실패도 결과로 돌려주기 위해)


@dataclass
class ChatResult:
    content: str
    reasoning: str | None = None
    finish_reason: str | None = None
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0  # wait_ms 포함
    tool_calls: list[ToolCall] = field(default_factory=list)
    wait_ms: int = 0  # 요청 간 최소 간격·429/5xx 재시도·동시 실행 대기로 기다린 시간
    provider: str = ""
    model: str = ""
    fallback: bool = False  # 기본 공급자가 실패해 대체 공급자가 답했다

    def assistant_message(self) -> dict[str, Any]:
        """대화 이력에 다시 넣을 assistant 메시지 (OpenAI Chat Completions 형식)."""
        message: dict[str, Any] = {"role": "assistant", "content": self.content or None}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.arguments},
                }
                for c in self.tool_calls
            ]
        return message


class LLMClient(Protocol):
    """채팅 완성 모델 공통 인터페이스. 공급자별 파라미터는 **params 로 넘긴다.

    tools 는 OpenAI function 스키마 목록, tool_choice 는 "auto" / "required" / 함수 지정 dict.
    timeout 은 이 호출의 응답 시간 제한(초)이고, 넘으면 status=408 LLMError 를 낸다.
    """

    model: str
    provider: str

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        timeout: float | None = None,
        **params: Any,
    ) -> ChatResult: ...

    async def aclose(self) -> None: ...


def open_session(client: LLMClient) -> LLMClient:
    """실행 하나 동안 쓸 클라이언트. 폴백 클라이언트는 실행 도중 바뀐 모델을 끝까지 유지한다.

    session() 이 없는 클라이언트(테스트용 가짜 등)는 그대로 쓴다.
    """
    session = getattr(client, "session", None)
    return session() if callable(session) else client
