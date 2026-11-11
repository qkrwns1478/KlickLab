import asyncio
import json
import time
from typing import Any

import httpx

from app.llm.base import ChatResult, LLMError, ToolCall, Usage

_RETRYABLE = {429, 500, 502, 503, 504}


class OpenAICompatClient:
    """OpenAI Chat Completions 호환 API 클라이언트 (K-EXAONE 등).

    * 요청 간 최소 간격을 지켜 초 단위 레이트 리밋을 넘지 않는다.
    * 429/5xx 는 retry-after 헤더(없으면 지수 백오프)만큼 기다렸다 재시도한다.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        default_params: dict[str, Any] | None = None,
        timeout: float = 180.0,
        min_interval: float = 0.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.model = model
        self._default_params = default_params or {}
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._lock = asyncio.Lock()
        self._last_sent = 0.0
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
            transport=transport,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        **params: Any,
    ) -> ChatResult:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        body.update(self._default_params)
        body.update({k: v for k, v in params.items() if v is not None})
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = tools
            if tool_choice is not None:
                body["tool_choice"] = tool_choice

        started = time.monotonic()
        waited = [0.0]
        try:
            response = await self._post_with_retry(body, waited)
        except LLMError as e:
            e.wait_ms = int(waited[0] * 1000)
            raise
        data = response.json()
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError):
            raise LLMError(f"응답 형식을 해석할 수 없습니다: {str(data)[:300]}") from None

        usage = data.get("usage") or {}
        details = usage.get("completion_tokens_details") or {}
        return ChatResult(
            content=(message.get("content") or "").strip(),
            reasoning=message.get("reasoning_content") or message.get("reasoning"),
            finish_reason=choice.get("finish_reason"),
            usage=Usage(
                prompt_tokens=usage.get("prompt_tokens") or 0,
                completion_tokens=usage.get("completion_tokens") or 0,
                reasoning_tokens=usage.get("reasoning_tokens")
                or details.get("reasoning_tokens")
                or 0,
            ),
            latency_ms=int((time.monotonic() - started) * 1000),
            wait_ms=int(waited[0] * 1000),
            tool_calls=[_tool_call(c, i) for i, c in enumerate(message.get("tool_calls") or [])],
        )

    async def _post_with_retry(self, body: dict[str, Any], waited: list[float]) -> httpx.Response:
        for attempt in range(self._max_retries + 1):
            waited[0] += await self._throttle()
            try:
                response = await self._http.post("/chat/completions", json=body)
            except httpx.HTTPError as e:
                if attempt == self._max_retries:
                    raise LLMError(f"LLM 요청 실패: {type(e).__name__}") from e
                waited[0] += 2**attempt
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code < 400:
                return response
            if (
                response.status_code in _RETRYABLE
                and attempt < self._max_retries
                and not _daily_limit(response)
            ):
                delay = _retry_delay(response, attempt)
                waited[0] += delay
                await asyncio.sleep(delay)
                continue
            raise LLMError(
                f"LLM 응답 오류 {response.status_code}: {response.text[:300]}",
                status=response.status_code,
            )
        raise AssertionError("unreachable")

    async def _throttle(self) -> float:
        """요청 간 최소 간격을 지킨다. 기다린 시간(초)을 돌려준다."""
        started = time.monotonic()
        async with self._lock:
            wait = self._last_sent + self._min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_sent = time.monotonic()
        return self._last_sent - started

    async def aclose(self) -> None:
        await self._http.aclose()


def _tool_call(raw: dict[str, Any], index: int) -> ToolCall:
    function = raw.get("function") or {}
    arguments = function.get("arguments")
    if not isinstance(arguments, str):  # 일부 공급자는 객체로 돌려준다
        arguments = json.dumps(arguments or {}, ensure_ascii=False)
    return ToolCall(
        id=raw.get("id") or f"call_{index}",
        name=function.get("name") or "",
        arguments=arguments,
    )


def _daily_limit(response: httpx.Response) -> bool:
    """하루 한도 초과 429 는 몇 분~몇 시간 뒤에야 풀리므로 재시도하지 않는다 (Groq TPD/RPD)."""
    return response.status_code == 429 and "per day" in response.text


def _retry_delay(response: httpx.Response, attempt: int) -> float:
    for header, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        value = response.headers.get(header)
        if value:
            try:
                return min(float(value) * scale, 60.0)
            except ValueError:
                pass
    return float(2**attempt)
