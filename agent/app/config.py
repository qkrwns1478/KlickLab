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

    # LLM (OpenAI 호환 Chat Completions). 기본값은 K-EXAONE 2.5
    llm_provider: str = "exaone"
    exaone_api_key: str = ""
    exaone_base_url: str = "https://api.exaone.ai/v1"
    exaone_model: str = "k-exaone_v2.5"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-120b"
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
