-- =====================================================================
-- 집계 전용 테이블 (klicklab-workers 의 ClickHouse 테이블 이식)
--  * aggregation 패키지의 Spring Batch Job 이 구간 단위로 DELETE + INSERT
--  * minutes_* / hourly_* : date_time = 구간 시작 시각 (10분 / 1시간)
--  * daily_* / weekly_*   : date      = 구간 시작 날짜 (1일 / 7일)
--  * 집계 원천: minutes ← events, hourly ← minutes, daily ← hourly(metrics, page_stats) / events(그 외),
--             weekly ← daily
-- =====================================================================

-- 방문 수 계산 시 "이전 방문 여부" 조회용
CREATE INDEX idx_events_sdk_client_ts ON events (sdk_key, client_id, timestamp);

-- ---------------------------------------------------------------------
-- 방문/클릭 지표
-- ---------------------------------------------------------------------
CREATE TABLE minutes_metrics (
    date_time           TIMESTAMPTZ NOT NULL,
    sdk_key             VARCHAR(64) NOT NULL,
    clicks              BIGINT      NOT NULL,
    visitors            BIGINT      NOT NULL,
    new_visitors        BIGINT      NOT NULL,
    existing_visitors   BIGINT      NOT NULL,
    avg_session_seconds INTEGER     NOT NULL,
    PRIMARY KEY (date_time, sdk_key)
);

CREATE TABLE hourly_metrics (LIKE minutes_metrics INCLUDING ALL);

CREATE TABLE daily_metrics (
    date                DATE        NOT NULL,
    sdk_key             VARCHAR(64) NOT NULL,
    clicks              BIGINT      NOT NULL,
    visitors            BIGINT      NOT NULL,
    new_visitors        BIGINT      NOT NULL,
    existing_visitors   BIGINT      NOT NULL,
    avg_session_seconds INTEGER     NOT NULL,
    PRIMARY KEY (date, sdk_key)
);

CREATE TABLE weekly_metrics (LIKE daily_metrics INCLUDING ALL);

-- ---------------------------------------------------------------------
-- 세그먼트별 클릭 요약 (segment_type: user_gender / traffic_source / device_type / user_age)
-- ---------------------------------------------------------------------
CREATE TABLE minutes_click_summary (
    date_time           TIMESTAMPTZ  NOT NULL,
    sdk_key             VARCHAR(64)  NOT NULL,
    segment_type        VARCHAR(32)  NOT NULL,
    segment_value       VARCHAR(255) NOT NULL,
    total_clicks        BIGINT       NOT NULL,
    total_users         BIGINT       NOT NULL,
    avg_clicks_per_user DOUBLE PRECISION,
    PRIMARY KEY (date_time, sdk_key, segment_type, segment_value)
);

CREATE TABLE hourly_click_summary (LIKE minutes_click_summary INCLUDING ALL);

CREATE TABLE daily_click_summary (
    date                DATE         NOT NULL,
    sdk_key             VARCHAR(64)  NOT NULL,
    segment_type        VARCHAR(32)  NOT NULL,
    segment_value       VARCHAR(255) NOT NULL,
    total_clicks        BIGINT       NOT NULL,
    total_users         BIGINT       NOT NULL,
    avg_clicks_per_user DOUBLE PRECISION,
    PRIMARY KEY (date, sdk_key, segment_type, segment_value)
);

CREATE TABLE weekly_click_summary (LIKE daily_click_summary INCLUDING ALL);

-- ---------------------------------------------------------------------
-- 세그먼트별 Top 3 클릭 요소
-- ---------------------------------------------------------------------
CREATE TABLE minutes_top_elements (
    date_time     TIMESTAMPTZ  NOT NULL,
    sdk_key       VARCHAR(64)  NOT NULL,
    segment_type  VARCHAR(32)  NOT NULL,
    segment_value VARCHAR(255) NOT NULL,
    rank          SMALLINT     NOT NULL,
    element       TEXT         NOT NULL,
    total_clicks  BIGINT       NOT NULL,
    user_count    BIGINT       NOT NULL,
    PRIMARY KEY (date_time, sdk_key, segment_type, segment_value, rank)
);

CREATE TABLE hourly_top_elements (LIKE minutes_top_elements INCLUDING ALL);

CREATE TABLE daily_top_elements (
    date          DATE         NOT NULL,
    sdk_key       VARCHAR(64)  NOT NULL,
    segment_type  VARCHAR(32)  NOT NULL,
    segment_value VARCHAR(255) NOT NULL,
    rank          SMALLINT     NOT NULL,
    element       TEXT         NOT NULL,
    total_clicks  BIGINT       NOT NULL,
    user_count    BIGINT       NOT NULL,
    PRIMARY KEY (date, sdk_key, segment_type, segment_value, rank)
);

CREATE TABLE weekly_top_elements (LIKE daily_top_elements INCLUDING ALL);

-- ---------------------------------------------------------------------
-- 세그먼트별 사용자 분포 (dist_type: ageGroup / device)
-- ---------------------------------------------------------------------
CREATE TABLE minutes_user_distribution (
    date_time     TIMESTAMPTZ  NOT NULL,
    sdk_key       VARCHAR(64)  NOT NULL,
    segment_type  VARCHAR(32)  NOT NULL,
    segment_value VARCHAR(255) NOT NULL,
    dist_type     VARCHAR(16)  NOT NULL,
    dist_value    VARCHAR(100) NOT NULL,
    user_count    BIGINT       NOT NULL,
    PRIMARY KEY (date_time, sdk_key, segment_type, segment_value, dist_type, dist_value)
);

CREATE TABLE hourly_user_distribution (LIKE minutes_user_distribution INCLUDING ALL);

CREATE TABLE daily_user_distribution (
    date          DATE         NOT NULL,
    sdk_key       VARCHAR(64)  NOT NULL,
    segment_type  VARCHAR(32)  NOT NULL,
    segment_value VARCHAR(255) NOT NULL,
    dist_type     VARCHAR(16)  NOT NULL,
    dist_value    VARCHAR(100) NOT NULL,
    user_count    BIGINT       NOT NULL,
    PRIMARY KEY (date, sdk_key, segment_type, segment_value, dist_type, dist_value)
);

CREATE TABLE weekly_user_distribution (LIKE daily_user_distribution INCLUDING ALL);

-- ---------------------------------------------------------------------
-- 페이지 통계 (next_pages: [{"to": "/path", "count": 3}, ...], count 내림차순)
-- ---------------------------------------------------------------------
CREATE TABLE minutes_page_stats (
    date_time                TIMESTAMPTZ      NOT NULL,
    sdk_key                  VARCHAR(64)      NOT NULL,
    page_path                TEXT             NOT NULL,
    page_views               BIGINT           NOT NULL,
    page_exits               BIGINT           NOT NULL,
    drop_rate                DOUBLE PRECISION NOT NULL,
    next_pages               JSONB            NOT NULL,
    avg_time_on_page_seconds DOUBLE PRECISION,
    PRIMARY KEY (date_time, sdk_key, page_path)
);

CREATE TABLE hourly_page_stats (LIKE minutes_page_stats INCLUDING ALL);

CREATE TABLE daily_page_stats (
    date                     DATE             NOT NULL,
    sdk_key                  VARCHAR(64)      NOT NULL,
    page_path                TEXT             NOT NULL,
    page_views               BIGINT           NOT NULL,
    page_exits               BIGINT           NOT NULL,
    drop_rate                DOUBLE PRECISION NOT NULL,
    next_pages               JSONB            NOT NULL,
    avg_time_on_page_seconds DOUBLE PRECISION,
    PRIMARY KEY (date, sdk_key, page_path)
);

CREATE TABLE weekly_page_stats (LIKE daily_page_stats INCLUDING ALL);
