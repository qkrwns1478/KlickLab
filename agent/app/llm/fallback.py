"""공급자 체인: 앞 공급자가 한도 초과·장애로 실패하면 같은 요청을 다음 공급자에 보낸다.

* 폴백 대상 오류(statuses, 연결 실패)만 넘긴다. 인증·요청 오류는 그대로 드러낸다.
* 쿨다운: 실패한 공급자는 retry-after(없으면 cooldown_s, 하루 한도면 daily_cooldown_s) 동안
  건너뛴다. 상태는 이 객체(프로세스)가 가진다.
* 실행 내 고정: session() 으로 받은 세션은 한 번 넘어간 공급자를 실행이 끝날 때까지 쓴다.
  호출마다 모델이 바뀌면 추론 스타일이 섞여 결과를 설명하기 어렵다.
* 대체 공급자까지 실패하면 첫 공급자의 원래 오류를 낸다 (로컬 서버가 꺼져 있을 때 연결 오류 대신
  "사용 한도에 도달했습니다" 가 보이게).
"""

import copy
import logging
import time
from collections.abc import Callable, Collection, Sequence
from typing import Any

from app.llm.base import ChatResult, LLMClient, LLMError

log = logging.getLogger(__name__)


class FallbackLLMClient:
    def __init__(
        self,
        clients: Sequence[LLMClient],
        *,
        statuses: Collection[int],
        cooldown_s: float = 60.0,
        daily_cooldown_s: float = 3600.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        if len(clients) < 2:
            raise ValueError("폴백 체인에는 공급자가 둘 이상 필요하다.")
        self.clients = list(clients)
        self._statuses = set(statuses)
        self._cooldown_s = cooldown_s
        self._daily_cooldown_s = daily_cooldown_s
        self._clock = clock
        self._skip_until = [0.0] * len(self.clients)
        self._last_error: list[LLMError | None] = [None] * len(self.clients)

    @property
    def model(self) -> str:
        return self.clients[0].model

    @property
    def provider(self) -> str:
        return getattr(self.clients[0], "provider", "")

    def session(self) -> "FallbackSession":
        return FallbackSession(self)

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ChatResult:
        """세션 없이 부르면 호출 하나만큼의 세션을 쓴다 (단일 턴 Text-to-SQL)."""
        return await FallbackSession(self).chat(messages, **kwargs)

    async def aclose(self) -> None:
        for client in self.clients:
            await client.aclose()

    # ------------------------------------------------------------------

    def eligible(self, error: LLMError) -> bool:
        return error.unavailable or error.status in self._statuses

    def cooling(self, index: int) -> bool:
        return self._clock() < self._skip_until[index]

    def fail(self, index: int, error: LLMError) -> None:
        """폴백 대상 오류를 낸 공급자를 한동안 건너뛴다."""
        self._last_error[index] = error
        if error.status == 413:  # 요청 크기 문제라 다음 요청은 받을 수 있다
            return
        if error.retry_after is not None:
            skip = error.retry_after
        elif error.daily:
            skip = self._daily_cooldown_s
        else:
            skip = self._cooldown_s
        self._skip_until[index] = max(self._skip_until[index], self._clock() + skip)
        log.warning(
            "LLM 공급자 %s(%s) 실패, %.0f초 동안 건너뛴다: %s",
            getattr(self.clients[index], "provider", index),
            self.clients[index].model,
            skip,
            str(error)[:200],
        )

    def last_error(self, index: int) -> LLMError | None:
        return self._last_error[index]


class FallbackSession:
    """실행 하나 동안의 공급자 선택. 대체 공급자로 넘어가면 실행이 끝날 때까지 그대로 쓴다."""

    def __init__(self, owner: FallbackLLMClient):
        self._owner = owner
        self._index = 0
        self._used_fallback = False  # 413 처럼 고정하지 않고 한 번만 대체 공급자를 쓴 경우 포함
        self.primary_error: LLMError | None = None  # 폴백하게 만든 첫 공급자의 오류

    @property
    def _current(self) -> LLMClient:
        return self._owner.clients[self._index]

    @property
    def model(self) -> str:
        return self._current.model

    @property
    def provider(self) -> str:
        return getattr(self._current, "provider", "")

    @property
    def fallback_active(self) -> bool:
        return self._index > 0 or self._used_fallback

    @property
    def time_factor(self) -> float:
        return getattr(self._current, "time_factor", 1.0)

    @property
    def forced_tool_unreliable(self) -> bool:
        return getattr(self._current, "forced_tool_unreliable", False)

    async def chat(self, messages: list[dict[str, Any]], **kwargs: Any) -> ChatResult:
        owner = self._owner
        last = len(owner.clients) - 1
        candidates = [i for i in range(self._index, last + 1) if i == last or not owner.cooling(i)]
        if self._index == 0 and candidates[0] > 0 and self.primary_error is None:
            # 쿨다운 중이라 첫 공급자를 건너뛴다. 그 오류를 이 실행의 폴백 사유로 쓴다
            self.primary_error = owner.last_error(0)
        waited = 0
        size_fails, other_fails = 0, False  # 앞선 실패 중 요청 크기(413) 수 / 그 밖의 실패 여부
        for i in candidates:
            client = owner.clients[i]
            try:
                result = await client.chat(messages, **kwargs)
            except LLMError as e:
                waited += e.wait_ms
                if not owner.eligible(e):
                    raise self._with_wait(e, waited) from None
                owner.fail(i, e)
                if e.status == 413:
                    size_fails += 1
                else:
                    other_fails = True
                if i == 0:
                    self.primary_error = e
                if i < last:
                    continue
                raise self._with_wait(self.primary_error or e, waited) from None
            if i != self._index:
                log.warning(
                    "폴백: %s → %s(%s)",
                    getattr(owner.clients[self._index], "provider", self._index),
                    getattr(client, "provider", i),
                    client.model,
                )
                if size_fails and not other_fails:
                    # 요청 크기 때문에 넘어간 것이다. 기본 공급자는 다음 요청을 받을 수 있으므로
                    # 실행을 고정하지 않고 이번 호출만 대체 공급자를 쓴다
                    self._used_fallback = True
                else:
                    self._index = i
            result.wait_ms += waited
            result.latency_ms += waited
            result.fallback = i > 0
            return result
        raise AssertionError("unreachable")  # 마지막 공급자는 항상 후보다

    @staticmethod
    def _with_wait(error: LLMError, waited: int) -> LLMError:
        # 쿨다운 중 다른 실행이 같은 오류 객체를 받으므로 복사해서 쓴다
        error = copy.copy(error)
        error.wait_ms = waited
        return error

    async def aclose(self) -> None:  # 클라이언트는 FallbackLLMClient 가 닫는다
        return None
