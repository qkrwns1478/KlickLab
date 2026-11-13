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

    # 로컬 추론 서버 (Ollama 등 OpenAI 호환). LLM_PROVIDER=local 또는 폴백 대상
    local_base_url: str = "http://localhost:11434/v1"
    # Ollama 는 기본 num_ctx(4096)를 넘는 입력을 조용히 자르므로 num_ctx 를 늘린 파생 모델을 쓴다
    local_model: str = "gpt-oss-20b-ctx32k"
    local_api_key: str = "local"
    local_num_ctx: int = 32768  # 서버 쪽 설정값. 시작 시 확인하고 다르면 경고한다
    local_temperature: float = 1.0  # gpt-oss 권장값
    local_top_p: float = 1.0
    local_max_concurrency: int = 1  # GPU 하나에서 동시에 처리할 요청 수
    # 로컬 모델로 진행하는 실행의 시간 한도 배율 (Phase 0: 단일 턴 지연이 Groq 의 약 1.4배)
    local_time_factor: float = 2.0
    local_timeout_seconds: float = 300.0
    # 추론 강도 상한. gpt-oss-20b 는 high 에서 추론만으로 단계 출력 한도(AGENT_STEP_MAX_TOKENS)를
    # 다 써서 도구 호출 없이 끝나는 경우가 많았다 (Phase 4). 빈 값이면 제한하지 않는다
    local_max_reasoning_effort: str = "medium"

    # 폴백: 기본 공급자가 한도 초과·장애로 실패하면 같은 요청을 대체 공급자에 보낸다
    llm_fallback_provider: str = "none"  # none | local
    llm_fallback_statuses: str = "402,429,413,500,502,503,504"  # 408 을 넣으면 시간 초과도 넘긴다
    # 폴백이 있을 때 기본 공급자의 재시도 대기 상한과 재시도 횟수. 더 기다려야 하면 바로 넘긴다
    llm_primary_max_wait_seconds: float = 5.0
    llm_primary_max_retries: int = 1
    # 실패한 공급자를 건너뛰는 시간 (retry-after 가 있으면 그 값). 하루 한도는 따로 길게 둔다
    llm_fallback_cooldown_seconds: float = 60.0
    llm_fallback_daily_cooldown_seconds: float = 3600.0

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
    # 고른 지표 문서의 계산 테이블 문서를 최대 이만큼 더 넣는다 (0 = 끔)
    knowledge_expand_sources: int = 0
    # local: sentence-transformers(bge-m3) / none: 키워드 검색만
    embedding_provider: str = "local"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dimension: int = 1024  # agent_knowledge.embedding vector(1024)
    embedding_device: str = "cpu"

    anthropic_api_key: str = ""

    # 관측 (Phase 6). host 와 키 두 개가 모두 있어야 Langfuse 로 트레이스를 보낸다
    langfuse_host: str = ""  # 예: http://localhost:3000
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_environment: str = "development"  # 트레이스를 환경별로 나눈다 (평가는 eval)
    langfuse_flush_interval_seconds: float = 1.0
    langfuse_timeout_seconds: float = 10.0
    metrics_enabled: bool = True  # GET /metrics (Prometheus)
    # 토큰 단가 덮어쓰기: "모델=입력:출력,..." (USD / 100만 토큰). 기본값은 app/llm/pricing.py
    llm_prices: str = ""

    # SQL 실행 제한
    sql_statement_timeout_ms: int = 5000
    sql_max_rows: int = 1000
    sql_result_rows: int = 200
    sql_max_plan_cost: float = 200_000.0

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_host and self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    def dsn(self, *, read_only: bool) -> str:
        user = self.db_ro_user if read_only else self.db_rw_user
        password = self.db_ro_password if read_only else self.db_rw_password

        # libpq 키워드 형식: 값에 공백·'·\ 가 있어도 읽히도록 따옴표로 감싸고 이스케이프한다
        def quote(value: str) -> str:
            return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"

        return (
            f"host={quote(self.db_host)} port={self.db_port} dbname={quote(self.db_name)} "
            f"user={quote(user)} password={quote(password)}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
