"""OpenAI Responses API 클라이언트.

gpt-6 계열은 Chat Completions 에서 function tools 와 reasoning_effort 를 함께 쓸 수 없고
(`max_tokens`, `top_p` 도 받지 않는다) 추론하면서 도구를 쓰려면 /v1/responses 를 써야 한다.
에이전트의 대화 이력은 Chat Completions 형식이므로 요청 때 Responses 입력 항목으로 바꾸고,
응답은 같은 ChatResult 로 돌려준다. 상태는 서버에 저장하지 않는다 (store=false).
"""

import json
import time
from typing import Any

from app.llm.base import ChatResult, LLMError, ToolCall, Usage
from app.llm.openai_compat import OpenAICompatClient

_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")


class OpenAIResponsesClient(OpenAICompatClient):
    """요청 간격·재시도·시간 초과 처리는 OpenAICompatClient 와 같고 요청·응답 형식만 다르다."""

    path = "/responses"

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
        body = build_request(
            self.model,
            messages,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            params={**self._default_params, **params},
        )
        started = time.monotonic()
        response, waited = await self._send(body, timeout)
        result = parse_response(response.json())
        result.latency_ms = int((time.monotonic() - started) * 1000)
        result.wait_ms = int(waited * 1000)
        result.provider = self.provider
        result.model = self.model
        return result


def build_request(
    model: str,
    messages: list[dict[str, Any]],
    *,
    max_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    params = {k: v for k, v in (params or {}).items() if v is not None}
    body: dict[str, Any] = {"model": model, "input": to_input(messages), "store": False}
    effort = params.pop("reasoning_effort", None)
    if effort in _EFFORTS:
        body["reasoning"] = {"effort": effort}
    if "temperature" in params:
        body["temperature"] = params.pop("temperature")
    # top_p 등 이 API 가 받지 않는 Chat Completions 파라미터는 보내지 않는다
    if max_tokens is not None:
        body["max_output_tokens"] = max_tokens
    if tools:
        body["tools"] = [_tool(t) for t in tools]
        if tool_choice is not None:
            body["tool_choice"] = _tool_choice(tool_choice)
    return body


def to_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Chat Completions 메시지 → Responses 입력 항목."""
    items: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": message.get("tool_call_id") or "",
                    "output": _text(message.get("content")),
                }
            )
            continue
        content = _text(message.get("content"))
        if content:
            items.append({"role": role, "content": content})
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            items.append(
                {
                    "type": "function_call",
                    "call_id": call.get("id") or "",
                    "name": function.get("name") or "",
                    "arguments": function.get("arguments") or "{}",
                }
            )
    return items


def parse_response(data: dict[str, Any]) -> ChatResult:
    output = data.get("output")
    if not isinstance(output, list):
        raise LLMError(f"응답 형식을 해석할 수 없습니다: {str(data)[:300]}")
    texts: list[str] = []
    calls: list[ToolCall] = []
    for item in output:
        kind = item.get("type")
        if kind == "message":
            texts += [
                part.get("text") or ""
                for part in item.get("content") or []
                if part.get("type") == "output_text"
            ]
        elif kind == "function_call":
            arguments = item.get("arguments")
            if not isinstance(arguments, str):
                arguments = json.dumps(arguments or {}, ensure_ascii=False)
            calls.append(
                ToolCall(
                    id=item.get("call_id") or item.get("id") or f"call_{len(calls)}",
                    name=item.get("name") or "",
                    arguments=arguments,
                )
            )
    usage = data.get("usage") or {}
    details = usage.get("output_tokens_details") or {}
    return ChatResult(
        content="".join(texts).strip(),
        finish_reason=_finish_reason(data, calls),
        usage=Usage(
            prompt_tokens=usage.get("input_tokens") or 0,
            completion_tokens=usage.get("output_tokens") or 0,
            reasoning_tokens=details.get("reasoning_tokens") or 0,
        ),
        tool_calls=calls,
    )


def _finish_reason(data: dict[str, Any], calls: list[ToolCall]) -> str:
    """Chat Completions 의 finish_reason 으로 맞춘다 (루프가 length 를 출력 잘림으로 본다)."""
    if data.get("status") == "incomplete":
        reason = (data.get("incomplete_details") or {}).get("reason")
        return "length" if reason == "max_output_tokens" else str(reason or "incomplete")
    return "tool_calls" if calls else "stop"


def _tool(tool: dict[str, Any]) -> dict[str, Any]:
    """{"type": "function", "function": {...}} → {"type": "function", "name": ..., ...}."""
    function = tool.get("function")
    if tool.get("type") != "function" or not isinstance(function, dict):
        return tool
    out = {"type": "function", "name": function.get("name")}
    for key in ("description", "parameters", "strict"):
        if key in function:
            out[key] = function[key]
    return out


def _tool_choice(choice: str | dict[str, Any]) -> str | dict[str, Any]:
    if isinstance(choice, dict) and isinstance(choice.get("function"), dict):
        return {"type": "function", "name": choice["function"].get("name")}
    return choice


def _text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # [{"type": "text", "text": ...}] 형식
        return "".join(p.get("text") or "" for p in content if isinstance(p, dict))
    return json.dumps(content, ensure_ascii=False, default=str)
