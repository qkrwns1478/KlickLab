-- =====================================================================
-- LLM 분석 에이전트 (agent/ Python 서비스) 용 스키마
--  * 실행 로그: agent_runs / agent_steps
--  * 지식 베이스(RAG): agent_knowledge (pgvector)
--  * 롤 분리
--      klicklab_agent_ro : LLM 이 만든 SQL 을 실행하는 연결. 화이트리스트 테이블 SELECT 만 가능하며
--                          RLS 로 app.sdk_key 에 해당하는 행만 보인다.
--      klicklab_agent    : 실행 로그/지식 베이스 읽기·쓰기 전용 연결 (원천/집계 테이블 접근 불가)
--  * 두 롤은 NOLOGIN 으로 생성한다. 비밀번호는 마이그레이션에 두지 않고 배포 시 별도로 지정한다.
--      ALTER ROLE klicklab_agent_ro LOGIN PASSWORD '...';
--      ALTER ROLE klicklab_agent    LOGIN PASSWORD '...';
--  * 테이블 소유자(앱 계정)는 RLS 를 우회하므로 기존 Spring 백엔드 동작에는 영향이 없다.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'klicklab_agent_ro') THEN
        CREATE ROLE klicklab_agent_ro NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'klicklab_agent') THEN
        CREATE ROLE klicklab_agent NOLOGIN;
    END IF;
END
$$;

-- ---------------------------------------------------------------------
-- 실행 로그
-- ---------------------------------------------------------------------
CREATE TABLE agent_runs (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sdk_key       VARCHAR(64)  NOT NULL,
    user_id       UUID         NOT NULL,
    question      TEXT         NOT NULL,
    difficulty    VARCHAR(20),
    status        VARCHAR(20)  NOT NULL DEFAULT 'running',
    answer        JSONB,
    tool_calls    INTEGER      NOT NULL DEFAULT 0,
    input_tokens  INTEGER      NOT NULL DEFAULT 0,
    output_tokens INTEGER      NOT NULL DEFAULT 0,
    cost_usd      NUMERIC(10, 6),
    latency_ms    INTEGER,
    trace_id      VARCHAR(64),
    feedback      SMALLINT,
    feedback_note TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT agent_runs_difficulty_chk
        CHECK (difficulty IS NULL OR difficulty IN ('lookup', 'compare', 'diagnose', 'out_of_scope')),
    CONSTRAINT agent_runs_status_chk
        CHECK (status IN ('running', 'succeeded', 'budget_exhausted', 'failed', 'rejected')),
    CONSTRAINT agent_runs_feedback_chk CHECK (feedback IS NULL OR feedback IN (-1, 1))
);
CREATE INDEX idx_agent_runs_sdk_created ON agent_runs (sdk_key, created_at DESC);

CREATE TABLE agent_steps (
    run_id      UUID        NOT NULL REFERENCES agent_runs (id) ON DELETE CASCADE,
    seq         SMALLINT    NOT NULL,
    tool        VARCHAR(50) NOT NULL,
    input       JSONB       NOT NULL,
    output      JSONB,
    error       TEXT,
    duration_ms INTEGER,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, seq)
);

-- ---------------------------------------------------------------------
-- 지식 베이스: 테이블/지표/예시 쿼리/용어 (시맨틱 레이어). 임베딩 차원은 bge-m3(1024) 기준
-- ---------------------------------------------------------------------
CREATE TABLE agent_knowledge (
    id         BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    kind       VARCHAR(20)  NOT NULL,
    name       VARCHAR(255) NOT NULL,
    content    TEXT         NOT NULL,
    metadata   JSONB        NOT NULL DEFAULT '{}'::jsonb,
    embedding  vector(1024),
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT agent_knowledge_kind_chk CHECK (kind IN ('table', 'metric', 'example', 'glossary')),
    CONSTRAINT agent_knowledge_uniq UNIQUE (kind, name)
);
CREATE INDEX idx_agent_knowledge_embedding ON agent_knowledge USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_agent_knowledge_trgm ON agent_knowledge USING gin ((name || ' ' || content) gin_trgm_ops);

GRANT SELECT, INSERT, UPDATE, DELETE ON agent_knowledge TO klicklab_agent;
GRANT SELECT, INSERT, UPDATE ON agent_runs  TO klicklab_agent;
GRANT SELECT, INSERT         ON agent_steps TO klicklab_agent;

-- ---------------------------------------------------------------------
-- 읽기 전용 롤: 조회 허용 테이블 + sdk_key RLS
--  * 'app.sdk_key' 가 설정되지 않았거나 다른 값이면 행이 보이지 않는다 (current_setting(..., true) → NULL)
--  * 계정/설정 테이블(users, event_rules, event_button)과 rollup_runs, BATCH_* 는 허용하지 않는다
-- ---------------------------------------------------------------------
DO $$
DECLARE
    t TEXT;
    allowed TEXT[] := ARRAY[
        'events',
        'conversion_events',
        'agg_user_session_daily', 'agg_user_session_hourly', 'agg_daily_users',
        'agg_page_daily', 'agg_event_daily', 'agg_event_page_daily', 'agg_traffic_hourly',
        'agg_funnel_links_daily', 'agg_first_pages_daily', 'agg_sankey_paths_daily'
    ];
    grain TEXT;
    family TEXT;
BEGIN
    FOREACH grain IN ARRAY ARRAY['minutes', 'hourly', 'daily', 'weekly'] LOOP
        FOREACH family IN ARRAY ARRAY['metrics', 'click_summary', 'top_elements', 'user_distribution', 'page_stats'] LOOP
            allowed := allowed || (grain || '_' || family);
        END LOOP;
    END LOOP;

    FOREACH t IN ARRAY allowed LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format(
            'CREATE POLICY agent_ro_sdk_key ON %I FOR SELECT TO klicklab_agent_ro '
            'USING (sdk_key = current_setting(''app.sdk_key'', true))', t);
        EXECUTE format('GRANT SELECT ON %I TO klicklab_agent_ro', t);
    END LOOP;
END
$$;
