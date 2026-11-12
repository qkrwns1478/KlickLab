import asyncio
import json
import logging
import time
from typing import Any

import httpx

from app.llm.base import ChatResult, LLMError, ToolCall, Usage

log = logging.getLogger(__name__)
_RETRYABLE = {429, 500, 502, 503, 504}
_EFFORTS = ("low", "medium", "high")
# Ollama 는 모델이 만든 도구 호출 JSON 을 해석하지 못하면 500 을 돌려준다. 서버 장애가 아니라
# 모델 출력 문제이므로 Groq 의 tool_use_failed(400) 와 같이 다룬다 (루프가 형식 안내 후 재요청)
_OLLAMA_TOOL_PARSE = "error parsing tool call"
TIMEOUT_STATUS = 408  # 응답 시간 초과 (실제 HTTP 응답이 아니라 클라이언트가 붙이는 값)


class OpenAICompatClient:
    """OpenAI Chat Completions 호환 API 클라이언트 (Groq, K-EXAONE, 로컬 Ollama 등).

    * 요청 간 최소 간격을 지켜 초 단위 레이트 리밋을 넘지 않는다.
    * 429/5xx 는 retry-after 헤더(없으면 지수 백오프)만큼 기다렸다 재시도한다.
      max_retry_wait 를 주면 그보다 오래 기다려야 할 때 바로 실패한다 (폴백이 있을 때).
    * 응답 시간 초과는 재시도하지 않는다 (같은 요청은 같은 시간이 걸린다). status=408 인
      LLMError. 호출마다 timeout 으로 기본 시간 제한을 줄일 수 있다.
    * drop_params 의 파라미터는 보내지 않고, param_map 은 파라미터 이름을 바꿔 보낸다.
    * max_concurrency 가 1 이상이면 동시에 그만큼만 요청한다 (로컬 GPU). 기다린 시간은 wait_ms 다.

    time_factor, forced_tool_unreliable 은 에이전트 루프가 읽는 공급자 특성이다.
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
        max_retry_wait: float | None = None,
        provider: str = "",
        drop_params: tuple[str, ...] = (),
        param_map: dict[str, str] | None = None,
        max_concurrency: int = 0,
        context_window: int = 0,
        time_factor: float = 1.0,
        forced_tool_unreliable: bool = False,
        max_reasoning_effort: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.model = model
        self.provider = provider
        # 실행 시간 한도 배율 (느린 로컬 모델)
        self.time_factor = time_factor
        # tool_choice 함수 지정을 무시하는 서버 (Ollama). 루프가 잘못된 도구 호출을 바로잡는다
        self.forced_tool_unreliable = forced_tool_unreliable
        self._default_params = default_params or {}
        self._drop_params = drop_params
        self._param_map = param_map or {}
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._max_retry_wait = max_retry_wait
        self._context_window = context_window
        self._max_effort = max_reasoning_effort
        self._semaphore = asyncio.Semaphore(max_concurrency) if max_concurrency > 0 else None
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
        timeout: float | None = None,
        **params: Any,
    ) -> ChatResult:
        body: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        body.update(self._default_params)
        body.update({k: v for k, v in params.items() if v is not None})
        if self._max_effort in _EFFORTS and body.get("reasoning_effort") in _EFFORTS:
            cap = _EFFORTS.index(self._max_effort)
            body["reasoning_effort"] = _EFFORTS[min(_EFFORTS.index(body["reasoning_effort"]), cap)]
        for name in self._drop_params:
            body.pop(name, None)
        for name, target in self._param_map.items():
            if name in body:
                body[target] = body.pop(name)
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if tools:
            body["tools"] = tools
            if tool_choice is not None:
                body["tool_choice"] = tool_choice

        started = time.monotonic()
        waited = [0.0]
        try:
            if self._semaphore is None:
                response = await self._post_with_retry(body, waited, timeout)
            else:
                await self._semaphore.acquire()
                waited[0] += time.monotonic() - started
                try:
                    response = await self._post_with_retry(body, waited, timeout)
                finally:
                    self._semaphore.release()
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
        prompt_tokens = usage.get("prompt_tokens") or 0
        if self._context_window and prompt_tokens >= self._context_window * 0.98:
            # Ollama 는 컨텍스트를 넘는 입력의 앞부분을 오류 없이 잘라 낸다
            log.warning(
                "입력이 컨텍스트 창(%d)에 닿아 앞부분이 잘렸을 수 있다: model=%s prompt_tokens=%d",
                self._context_window,
                self.model,
                prompt_tokens,
            )
        return ChatResult(
            content=(message.get("content") or "").strip(),
            reasoning=message.get("reasoning_content") or message.get("reasoning"),
            finish_reason=choice.get("finish_reason"),
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=usage.get("completion_tokens") or 0,
                reasoning_tokens=usage.get("reasoning_tokens")
                or details.get("reasoning_tokens")
                or 0,
            ),
            latency_ms=int((time.monotonic() - started) * 1000),
            wait_ms=int(waited[0] * 1000),
            tool_calls=[_tool_call(c, i) for i, c in enumerate(message.get("tool_calls") or [])],
            provider=self.provider,
            model=self.model,
        )

    async def _post_with_retry(
        self, body: dict[str, Any], waited: list[float], timeout: float | None = None
    ) -> httpx.Response:
        options = {} if timeout is None else {"timeout": timeout}
        for attempt in range(self._max_retries + 1):
            waited[0] += await self._throttle()
            try:
                response = await self._http.post("/chat/completions", json=body, **options)
            except httpx.TimeoutException as e:
                raise LLMError(
                    f"LLM 응답 시간 초과 ({type(e).__name__})", status=TIMEOUT_STATUS
                ) from e
            except httpx.HTTPError as e:
                if attempt == self._max_retries:
                    raise LLMError(
                        f"LLM 요청 실패: {type(e).__name__}",
                        unavailable=isinstance(e, httpx.TransportError),
                    ) from e
                waited[0] += 2**attempt
                await asyncio.sleep(2**attempt)
                continue
            if response.status_code < 400:
                return response
            if response.status_code == 500 and _OLLAMA_TOOL_PARSE in response.text:
                raise LLMError(
                    f"LLM 응답 오류 400 (tool_use_failed): {response.text[:300]}", status=400
                )
            daily = _daily_limit(response)
            retry_after = _retry_after(response)
            if response.status_code in _RETRYABLE and attempt < self._max_retries and not daily:
                delay = float(2**attempt) if retry_after is None else min(retry_after, 60.0)
                if self._max_retry_wait is None or delay <= self._max_retry_wait:
                    waited[0] += delay
                    await asyncio.sleep(delay)
                    continue
            raise LLMError(
                f"LLM 응답 오류 {response.status_code}: {response.text[:300]}",
                status=response.status_code,
                retry_after=retry_after,
                daily=daily,
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

    def session(self) -> "OpenAICompatClient":
        return self  # 상태가 없으므로 실행마다 따로 둘 필요가 없다

    async def list_models(self, timeout: float = 3.0) -> list[str]:
        """서버가 제공하는 모델 id 목록 (헬스 체크). 연결 실패는 httpx.HTTPError 로 낸다."""
        response = await self._http.get("/models", timeout=timeout)
        response.raise_for_status()
        return [m.get("id", "") for m in response.json().get("data") or []]

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


def _retry_after(response: httpx.Response) -> float | None:
    for header, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        value = response.headers.get(header)
        if value:
            try:
                return float(value) * scale
            except ValueError:
                pass
    return None
