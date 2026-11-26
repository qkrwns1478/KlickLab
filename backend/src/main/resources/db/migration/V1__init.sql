-- =====================================================================
-- KlickLab PostgreSQL schema (ClickHouse + PostgreSQL -> PostgreSQL 단독)
--  * 원천 데이터: events
--  * 집계 데이터: agg_* (RollupService 가 events 로부터 일 단위로 재계산)
--  * 모든 날짜/시간 버킷은 세션 타임존(Asia/Seoul) 기준
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------
-- 계정 / 설정
-- ---------------------------------------------------------------------
CREATE TABLE users (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email         VARCHAR(320) NOT NULL UNIQUE,
    password_hash VARCHAR(100) NOT NULL,
    sdk_key       VARCHAR(64)  NOT NULL UNIQUE,
    is_approved   BOOLEAN      NOT NULL DEFAULT FALSE,
    event         VARCHAR(50)  NOT NULL DEFAULT 'is_payment',
    domain        VARCHAR(255),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE event_rules (
    rule_id             UUID PRIMARY KEY,
    sdk_key             VARCHAR(64)  NOT NULL,
    new_event_name      VARCHAR(255) NOT NULL,
    source_event_name   VARCHAR(255) NOT NULL,
    condition_type      VARCHAR(50)  NOT NULL,
    condition_parameter VARCHAR(255) NOT NULL,
    condition_value     TEXT         NOT NULL,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_event_rules_sdk_key ON event_rules (sdk_key);

CREATE TABLE event_button (
    config_id    UUID PRIMARY KEY,
    sdk_key      VARCHAR(64)  NOT NULL,
    event_name   VARCHAR(255) NOT NULL,
    css_selector TEXT         NOT NULL,
    description  TEXT         NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_event_button_sdk_key ON event_button (sdk_key, created_at DESC);

-- ClickHouse 의 conversion_events_dict(Dictionary) 를 대체: 일반 테이블 + PK 조회
CREATE TABLE conversion_events (
    sdk_key     VARCHAR(64)  NOT NULL,
    event_name  VARCHAR(255) NOT NULL,
    description TEXT         NOT NULL DEFAULT '',
    is_active   SMALLINT     NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (sdk_key, event_name)
);

-- ---------------------------------------------------------------------
-- 원천 이벤트 (수집 파이프라인이 적재)
-- ---------------------------------------------------------------------
CREATE TABLE events (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sdk_key              VARCHAR(64)  NOT NULL,
    event_name           VARCHAR(255) NOT NULL,
    timestamp            TIMESTAMPTZ  NOT NULL,
    client_id            VARCHAR(255),
    user_id              VARCHAR(255),
    session_id           VARCHAR(255),
    page_path            TEXT         NOT NULL DEFAULT '',
    page_title           TEXT,
    referrer             TEXT         NOT NULL DEFAULT '',
    traffic_source       VARCHAR(255) NOT NULL DEFAULT '',
    traffic_medium       VARCHAR(255) NOT NULL DEFAULT '',
    traffic_campaign     VARCHAR(255) NOT NULL DEFAULT '',
    device_type          VARCHAR(50)  NOT NULL DEFAULT '',
    device_os            VARCHAR(100) NOT NULL DEFAULT '',
    browser              VARCHAR(100) NOT NULL DEFAULT '',
    city                 VARCHAR(100) NOT NULL DEFAULT '',
    user_gender          VARCHAR(20),
    user_age             SMALLINT,
    element              TEXT         NOT NULL DEFAULT '',
    time_on_page_seconds DOUBLE PRECISION,
    properties           JSONB
);
CREATE INDEX idx_events_sdk_ts      ON events (sdk_key, timestamp);
CREATE INDEX idx_events_sdk_name_ts ON events (sdk_key, event_name, timestamp);
CREATE INDEX idx_events_sdk_session ON events (sdk_key, session_id);
CREATE INDEX idx_events_ts_brin     ON events USING BRIN (timestamp);

-- ---------------------------------------------------------------------
-- 집계 테이블 (agg_*): RollupService 가 날짜 단위로 DELETE + INSERT
-- 세션 속성(도시/기기/유입경로 등)은 세션의 첫 이벤트 기준, 세션 날짜는 시작 시각 기준
-- ---------------------------------------------------------------------

-- 사용자/세션: 일 단위 + 성별/연령대 (일별 순 사용자 수 정확도 유지)
CREATE TABLE agg_user_session_daily (
    sdk_key              VARCHAR(64) NOT NULL,
    summary_date         DATE        NOT NULL,
    gender               VARCHAR(20) NOT NULL,
    age_group            VARCHAR(10) NOT NULL,
    users                BIGINT      NOT NULL,
    sessions             BIGINT      NOT NULL,
    session_duration_sum BIGINT      NOT NULL,
    PRIMARY KEY (sdk_key, summary_date, gender, age_group)
);

-- 사용자/세션: 시간 단위 + 상세 속성 (기존 flat_user_session_stats 대응)
CREATE TABLE agg_user_session_hourly (
    sdk_key              VARCHAR(64)  NOT NULL,
    summary_date         DATE         NOT NULL,
    summary_hour         SMALLINT     NOT NULL,
    city                 VARCHAR(100) NOT NULL,
    age_group            VARCHAR(10)  NOT NULL,
    gender               VARCHAR(20)  NOT NULL,
    device_type          VARCHAR(50)  NOT NULL,
    device_os            VARCHAR(100) NOT NULL,
    browser              VARCHAR(100) NOT NULL,
    users                BIGINT       NOT NULL,
    sessions             BIGINT       NOT NULL,
    session_duration_sum BIGINT       NOT NULL,
    PRIMARY KEY (sdk_key, summary_date, summary_hour, city, age_group, gender, device_type, device_os, browser)
);

-- 일별 활성 사용자 목록 (DAU/WAU/MAU 정확 계산용)
CREATE TABLE agg_daily_users (
    sdk_key      VARCHAR(64)  NOT NULL,
    summary_date DATE         NOT NULL,
    client_id    VARCHAR(255) NOT NULL,
    PRIMARY KEY (sdk_key, summary_date, client_id)
);

-- 페이지
CREATE TABLE agg_page_daily (
    sdk_key           VARCHAR(64)      NOT NULL,
    summary_date      DATE             NOT NULL,
    page_path         TEXT             NOT NULL,
    page_views        BIGINT           NOT NULL,
    unique_users      BIGINT           NOT NULL,
    sessions          BIGINT           NOT NULL,
    exits             BIGINT           NOT NULL,
    time_on_page_sum  DOUBLE PRECISION NOT NULL,
    last_event_at     TIMESTAMPTZ,
    PRIMARY KEY (sdk_key, summary_date, page_path)
);

-- 이벤트
CREATE TABLE agg_event_daily (
    sdk_key      VARCHAR(64)  NOT NULL,
    summary_date DATE         NOT NULL,
    event_name   VARCHAR(255) NOT NULL,
    event_count  BIGINT       NOT NULL,
    unique_users BIGINT       NOT NULL,
    PRIMARY KEY (sdk_key, summary_date, event_name)
);

CREATE TABLE agg_event_page_daily (
    sdk_key      VARCHAR(64)  NOT NULL,
    summary_date DATE         NOT NULL,
    event_name   VARCHAR(255) NOT NULL,
    page_path    TEXT         NOT NULL,
    event_count  BIGINT       NOT NULL,
    unique_users BIGINT       NOT NULL,
    PRIMARY KEY (sdk_key, summary_date, event_name, page_path)
);

-- 유입/마케팅 (기존 flat_traffic_marketing_stats 대응)
CREATE TABLE agg_traffic_hourly (
    sdk_key              VARCHAR(64)  NOT NULL,
    summary_date         DATE         NOT NULL,
    summary_hour         SMALLINT     NOT NULL,
    traffic_source       VARCHAR(255) NOT NULL,
    traffic_medium       VARCHAR(255) NOT NULL,
    traffic_campaign     VARCHAR(255) NOT NULL,
    landing_page         TEXT         NOT NULL,
    users                BIGINT       NOT NULL,
    sessions             BIGINT       NOT NULL,
    bounced_sessions     BIGINT       NOT NULL,
    conversions          BIGINT       NOT NULL,
    conversion_value_sum NUMERIC      NOT NULL,
    funnel_visits        BIGINT       NOT NULL,
    funnel_engaged       BIGINT       NOT NULL,
    funnel_converted     BIGINT       NOT NULL,
    PRIMARY KEY (sdk_key, summary_date, summary_hour, traffic_source, traffic_medium, traffic_campaign, landing_page)
);

-- 퍼널: 페이지 전이 (source -> target)
CREATE TABLE agg_funnel_links_daily (
    sdk_key      VARCHAR(64) NOT NULL,
    summary_date DATE        NOT NULL,
    source       TEXT        NOT NULL,
    target       TEXT        NOT NULL,
    sessions     BIGINT      NOT NULL,
    PRIMARY KEY (sdk_key, summary_date, source, target)
);

-- 퍼널: 세션 시작 페이지
CREATE TABLE agg_first_pages_daily (
    sdk_key      VARCHAR(64) NOT NULL,
    summary_date DATE        NOT NULL,
    page_path    TEXT        NOT NULL,
    sessions     BIGINT      NOT NULL,
    PRIMARY KEY (sdk_key, summary_date, page_path)
);

-- Sankey: 세션별 페이지/이벤트 경로
CREATE TABLE agg_sankey_paths_daily (
    sdk_key      VARCHAR(64)  NOT NULL,
    summary_date DATE         NOT NULL,
    session_id   VARCHAR(255) NOT NULL,
    url_path     TEXT[]       NOT NULL,
    event_path   TEXT[]       NOT NULL,
    PRIMARY KEY (sdk_key, summary_date, session_id)
);

-- 집계 실행 이력
CREATE TABLE rollup_runs (
    summary_date DATE PRIMARY KEY,
    refreshed_at TIMESTAMPTZ NOT NULL,
    duration_ms  BIGINT      NOT NULL
);
