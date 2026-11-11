from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    db_host: str = "localhost"
    db_port: int = 5433
    db_name: str = "klicklab"
    db_ro_user: str = "klicklab_agent_ro"
    db_ro_password: str = ""
    db_rw_user: str = "klicklab_agent"
    db_rw_password: str = ""

    jwt_secret: str = ""
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # LLM (OpenAI 호환 Chat Completions). Phase 2 부터 기본값은 Groq gpt-oss-120b
    llm_provider: str = "groq"
    exaone_api_key: str = ""
    exaone_base_url: str = "https://api.exaone.ai/v1"
    exaone_model: str = "k-exaone_v2.5"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
    # Groq 무료 등급 RPM 30 → 요청 간 2초
    groq_min_interval_seconds: float = 2.0
    # 추론 토큰이 max_tokens 에 포함되므로 SQL 생성에는 넉넉하게 둔다
    llm_sql_max_tokens: int = 16384
    llm_sql_reasoning_effort: str = "high"
    llm_answer_max_tokens: int = 4096
    llm_answer_reasoning_effort: str = "low"
    llm_temperature: float = 1.0
    llm_top_p: float = 0.95
    llm_timeout_seconds: float = 180.0
    # 공급자 레이트 리밋 대응 (K-EXAONE 2.5 무료 등급: 초당 1회)
    llm_min_interval_seconds: float = 1.0
    llm_max_retries: int = 3

    # Tool Loop (Phase 2)
    agent_classify_max_tokens: int = 1024
    agent_classify_reasoning_effort: str = "low"
    agent_step_max_tokens: int = 3072
    # 요청 하나의 입력 토큰 상한 (0 = 제한 없음). Groq 무료 등급은 TPM 8K 를 넘는 요청을 413 으로
    # 거절하며, 이때 요청 크기에 max_tokens 가 더해지는 것으로 보여 8000 - 3072 보다 작게 둔다
    agent_max_prompt_tokens: int = 4800
    # LLM 에 돌려주는 SQL 결과 행 수 (토큰 절약). 실행 로그에는 sql_result_rows 까지 남긴다
    agent_tool_result_rows: int = 20

    # 지식 베이스 (Phase 3)
    #  prompt: 스키마 요약·지표 정의를 시스템 프롬프트에 직접 넣는다 (Phase 1~2 기준선)
    #  rag   : 질문으로 검색한 문서만 넣고, 루프에서는 search_knowledge 로 더 찾는다
    knowledge_mode: str = "prompt"
    # 질문마다 미리 넣을 문서 수 (종류별). 기본값은 스키마 요약과 비슷한 크기(약 5,100자)
    knowledge_context_quota: str = "table:2,metric:2,glossary:3,example:1"
    knowledge_search_k: int = 4  # search_knowledge 도구 결과 수
    # local: sentence-transformers(bge-m3) / none: 키워드 검색만
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024  # agent_knowledge.embedding vector(1024)
    embedding_device: str = "cpu"

    anthropic_api_key: str = ""

    # SQL 실행 제한
    sql_statement_timeout_ms: int = 5000
    sql_max_rows: int = 1000
    sql_result_rows: int = 200
    sql_max_plan_cost: float = 200_000.0

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    def dsn(self, *, read_only: bool) -> str:
        user = self.db_ro_user if read_only else self.db_rw_user
        password = self.db_ro_password if read_only else self.db_rw_password
        return (
            f"host={self.db_host} port={self.db_port} dbname={self.db_name} "
            f"user={user} password={password}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
