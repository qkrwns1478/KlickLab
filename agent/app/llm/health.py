"""로컬 추론 서버 시작 시 점검. 실패해도 에이전트 서버는 뜨고 경고만 남긴다."""

import logging
import re

import httpx

from app.config import Settings

log = logging.getLogger(__name__)

_NUM_CTX = re.compile(r"^\s*num_ctx\s+(\d+)", re.MULTILINE)


def uses_local(settings: Settings) -> bool:
    return "local" in (settings.llm_provider, settings.llm_fallback_provider.strip().lower())


async def check_local_server(
    settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None
) -> list[str]:
    """문제 목록을 돌려준다 (비어 있으면 정상). 서버 연결, 모델 등록, Ollama num_ctx 를 본다."""
    base = settings.local_base_url.rstrip("/")
    model = settings.local_model
    async with httpx.AsyncClient(timeout=3.0, transport=transport) as http:
        try:
            response = await http.get(f"{base}/models")
            response.raise_for_status()
        except httpx.HTTPError as e:
            return [f"로컬 LLM 서버에 연결하지 못했다 ({base}): {type(e).__name__}"]
        ids = {m.get("id", "") for m in response.json().get("data") or []}
        if model not in ids and f"{model}:latest" not in ids:
            return [f"로컬 LLM 서버에 모델 {model} 이 없다. 있는 모델: {sorted(ids)}"]
        # Ollama 전용 API. 다른 서버면 건너뛴다
        root = base.removesuffix("/v1")
        try:
            show = await http.post(f"{root}/api/show", json={"model": model})
        except httpx.HTTPError:
            return []
        if show.status_code != 200:
            return []
        matched = _NUM_CTX.search(show.json().get("parameters") or "")
        num_ctx = int(matched.group(1)) if matched else None
        if num_ctx is None or num_ctx < settings.local_num_ctx:
            return [
                f"로컬 모델 {model} 의 num_ctx 가 {num_ctx or '기본값(4096)'} 이다. "
                f"LOCAL_NUM_CTX={settings.local_num_ctx} 보다 작으면 긴 입력의 앞부분이 잘린다. "
                "Modelfile 에 PARAMETER num_ctx 를 지정한 파생 모델을 쓴다."
            ]
    return []


async def log_local_server_status(settings: Settings) -> None:
    if not uses_local(settings):
        return
    try:
        problems = await check_local_server(settings)
    except Exception:
        log.exception("로컬 LLM 서버 점검 실패")
        return
    for problem in problems:
        log.warning(problem)
    if not problems:
        log.info("로컬 LLM 서버 정상: %s", settings.local_model)
