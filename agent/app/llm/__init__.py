from app.config import Settings
from app.llm.base import ChatResult, LLMClient, LLMError, Usage
from app.llm.openai_compat import OpenAICompatClient

__all__ = ["ChatResult", "LLMClient", "LLMError", "Usage", "build_llm_client"]


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "exaone":
        if not settings.exaone_api_key:
            raise LLMError("EXAONE_API_KEY 가 설정되지 않았습니다.")
        return OpenAICompatClient(
            base_url=settings.exaone_base_url,
            api_key=settings.exaone_api_key,
            model=settings.exaone_model,
            default_params={"temperature": settings.llm_temperature, "top_p": settings.llm_top_p},
            timeout=settings.llm_timeout_seconds,
            min_interval=settings.llm_min_interval_seconds,
            max_retries=settings.llm_max_retries,
        )
    if settings.llm_provider == "groq":
        if not settings.groq_api_key:
            raise LLMError("GROQ_API_KEY 가 설정되지 않았습니다.")
        return OpenAICompatClient(
            base_url=settings.groq_base_url,
            api_key=settings.groq_api_key,
            model=settings.groq_model,
            default_params={"temperature": settings.llm_temperature, "top_p": settings.llm_top_p},
            timeout=settings.llm_timeout_seconds,
            min_interval=settings.llm_min_interval_seconds,
            max_retries=settings.llm_max_retries,
        )
    raise LLMError(f"지원하지 않는 LLM 공급자입니다: {settings.llm_provider}")
