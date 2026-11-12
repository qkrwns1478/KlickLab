from app.config import Settings
from app.llm.base import ChatResult, LLMClient, LLMError, ToolCall, Usage, open_session
from app.llm.fallback import FallbackLLMClient, FallbackSession
from app.llm.openai_compat import TIMEOUT_STATUS, OpenAICompatClient

__all__ = [
    "TIMEOUT_STATUS",
    "ChatResult",
    "FallbackLLMClient",
    "FallbackSession",
    "LLMClient",
    "LLMError",
    "ToolCall",
    "Usage",
    "build_llm_client",
    "build_provider_client",
    "fallback_statuses",
    "open_session",
]

PROVIDERS = ("groq", "exaone", "local")


def build_llm_client(settings: Settings) -> LLMClient:
    """LLM_PROVIDER 클라이언트. LLM_FALLBACK_PROVIDER 가 있으면 폴백 체인으로 감싼다."""
    fallback = settings.llm_fallback_provider.strip().lower()
    if fallback in ("", "none") or fallback == settings.llm_provider:
        return build_provider_client(settings, settings.llm_provider)
    if fallback not in PROVIDERS:
        raise LLMError(f"지원하지 않는 폴백 공급자입니다: {fallback}")
    # 대체 공급자 장애는 원래 오류로 바로 돌려줘야 하므로 재시도하지 않는다
    secondary = build_provider_client(settings, fallback, max_retries=0)
    primary = build_provider_client(
        settings,
        settings.llm_provider,
        max_retries=settings.llm_primary_max_retries,
        max_retry_wait=settings.llm_primary_max_wait_seconds,
    )
    return FallbackLLMClient(
        [primary, secondary],
        statuses=fallback_statuses(settings),
        cooldown_s=settings.llm_fallback_cooldown_seconds,
        daily_cooldown_s=settings.llm_fallback_daily_cooldown_seconds,
    )


def fallback_statuses(settings: Settings) -> set[int]:
    return {int(s) for s in settings.llm_fallback_statuses.split(",") if s.strip()}


def build_provider_client(
    settings: Settings,
    provider: str,
    *,
    max_retries: int | None = None,
    max_retry_wait: float | None = None,
) -> OpenAICompatClient:
    retries = settings.llm_max_retries if max_retries is None else max_retries
    if provider == "exaone":
        if not settings.exaone_api_key:
            raise LLMError("EXAONE_API_KEY 가 설정되지 않았습니다.")
        return OpenAICompatClient(
            provider="exaone",
            base_url=settings.exaone_base_url,
            api_key=settings.exaone_api_key,
            model=settings.exaone_model,
            default_params={"temperature": settings.llm_temperature, "top_p": settings.llm_top_p},
            timeout=settings.llm_timeout_seconds,
            min_interval=settings.llm_min_interval_seconds,
            max_retries=retries,
            max_retry_wait=max_retry_wait,
        )
    if provider == "groq":
        if not settings.groq_api_key:
            raise LLMError("GROQ_API_KEY 가 설정되지 않았습니다.")
        return OpenAICompatClient(
            provider="groq",
            base_url=settings.groq_base_url,
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            default_params={"temperature": settings.llm_temperature, "top_p": settings.llm_top_p},
            timeout=settings.llm_timeout_seconds,
            min_interval=settings.groq_min_interval_seconds,
            max_retries=retries,
            max_retry_wait=max_retry_wait,
        )
    if provider == "local":
        return OpenAICompatClient(
            provider="local",
            base_url=settings.local_base_url,
            api_key=settings.local_api_key or "local",
            model=settings.local_model,
            default_params={
                "temperature": settings.local_temperature,
                "top_p": settings.local_top_p,
            },
            # reasoning_effort 는 gpt-oss 계열만 받는다 (Ollama 는 최상위 파라미터로 반영한다)
            drop_params=() if "gpt-oss" in settings.local_model else ("reasoning_effort",),
            timeout=settings.local_timeout_seconds,
            max_retries=retries,
            max_retry_wait=max_retry_wait,
            max_concurrency=settings.local_max_concurrency,
            context_window=settings.local_num_ctx,
            time_factor=settings.local_time_factor,
            forced_tool_unreliable=True,  # Ollama 는 tool_choice 함수 지정을 무시한다 (Phase 0)
            max_reasoning_effort=settings.local_max_reasoning_effort or None,
        )
    raise LLMError(f"지원하지 않는 LLM 공급자입니다: {provider}")
