import pytest

from app.sql.guard import SQLRejected, guard


@pytest.mark.parametrize(
    ("sql", "reason"),
    [
        ("", "빈 SQL"),
        ("SELECT 1; SELECT 2", "하나만"),
        ("SELECT 1; DROP TABLE users", "하나만"),
        ("DROP TABLE events", "SELECT 조회만"),
        ("DELETE FROM agg_page_daily", "SELECT 조회만"),
        ("UPDATE events SET page_path = ''", "SELECT 조회만"),
        ("INSERT INTO agg_page_daily SELECT * FROM agg_page_daily", "SELECT 조회만"),
        ("SET app.sdk_key = 'other'", "SELECT 조회만"),
        ("COPY events TO '/tmp/x'", "SELECT 조회만"),
        ("WITH d AS (DELETE FROM agg_page_daily RETURNING *) SELECT * FROM d", "변경"),
        ("SELECT * INTO backup FROM agg_page_daily", "SELECT INTO"),
        ("SELECT * FROM agg_page_daily FOR UPDATE", "잠금"),
        ("SELECT * FROM users", "users"),
        ("SELECT * FROM event_rules", "event_rules"),
        ("SELECT * FROM agg_page_daily p JOIN users u ON true", "users"),
        ("SELECT * FROM agg_page_daily WHERE page_path IN (SELECT email FROM users)", "users"),
        ("SELECT * FROM pg_catalog.pg_roles", "스키마"),
        ("SELECT * FROM information_schema.tables", "스키마"),
        ("SELECT * FROM pg_user", "pg_user"),
        ("SELECT pg_sleep(10)", "pg_sleep"),
        ("SELECT pg_read_file('/etc/passwd')", "pg_read_file"),
        ("SELECT set_config('app.sdk_key', 'other', false)", "set_config"),
        ("SELECT current_setting('app.sdk_key')", "current_setting"),
        ("SELECT dblink('host=x', 'select 1')", "dblink"),
        ("SELECT lo_import('/etc/passwd')", "lo_import"),
        ("SELECT query_to_xml('select * from users', true, true, '')", "query_to_xml"),
        ("SELECT count(*) FROM events", "timestamp"),
        ("SELECT count(*) FROM events WHERE event_name = 'page_view'", "timestamp"),
        ("SELECT * FROM (SELECT * FROM events) e WHERE e.timestamp > now()", "timestamp"),
        (
            "SELECT count(*) FROM agg_daily_users u JOIN events e ON e.client_id = u.client_id",
            "timestamp",
        ),
        ("SELECT * FROM agg_page_daily LIMIT (SELECT 1)", "LIMIT"),
        ("SELEC * FROM agg_page_daily", ""),
    ],
)
def test_rejects(sql, reason):
    with pytest.raises(SQLRejected) as e:
        guard(sql)
    assert reason in e.value.reason


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT count(*) FROM agg_daily_users WHERE summary_date = current_date - 1",
        "SELECT count(*) FROM events WHERE timestamp >= current_date - 7",
        "SELECT count(*) FROM events e WHERE e.timestamp::date = current_date - 1",
        "SELECT count(*) FROM events WHERE timestamp BETWEEN now() - interval '1 day' AND now()",
        "SELECT * FROM public.agg_page_daily",
        "WITH w AS (SELECT summary_date, sum(page_views) pv FROM agg_page_daily GROUP BY 1) "
        "SELECT * FROM w ORDER BY summary_date",
        "SELECT d::date FROM generate_series(current_date - 7, current_date, interval '1 day') d",
        "SELECT page_path FROM agg_page_daily UNION SELECT page_path FROM agg_first_pages_daily",
        "SELECT * FROM daily_top_elements WHERE segment_type = 'device_type'",
        "SELECT count(*) FROM agg_daily_users u JOIN events e ON e.client_id = u.client_id "
        "AND e.timestamp >= current_date - 7",
    ],
)
def test_allows(sql):
    guard(sql)


def test_keeps_original_text_when_limit_is_within_bound():
    sql = "SELECT page_path FROM agg_page_daily ORDER BY page_views DESC LIMIT 5"
    result = guard(sql + ";\n")
    assert result.sql == sql
    assert not result.limit_applied
    assert result.tables == {"agg_page_daily"}


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM agg_page_daily",
        "SELECT * FROM agg_page_daily LIMIT 5000",
        "SELECT * FROM agg_page_daily LIMIT ALL",
        "SELECT page_path FROM agg_page_daily UNION SELECT page_path FROM agg_first_pages_daily",
    ],
)
def test_wraps_with_limit(sql):
    result = guard(sql, max_rows=1000)
    assert result.limit_applied
    assert result.sql.endswith("LIMIT 1000")
    guard(result.sql)  # 감싼 결과도 다시 통과해야 한다


def test_wrap_survives_trailing_comment():
    result = guard("SELECT * FROM agg_page_daily -- 전체")
    assert result.sql.endswith("\n) AS limited_result LIMIT 1000")


def test_cte_name_is_not_treated_as_table():
    result = guard("WITH recent AS (SELECT * FROM agg_page_daily) SELECT * FROM recent LIMIT 1")
    assert result.tables == {"agg_page_daily"}
