from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import psycopg
import pytest

from app.config import Settings
from app.sql.executor import SQLExecutionError, build_executor, to_json_value

DEMO_KEY = "klicklab-demo-sdk-key-0001"


def test_to_json_value():
    kst = timezone(timedelta(hours=9))
    assert to_json_value(Decimal("3")) == 3
    assert to_json_value(Decimal("1.25")) == 1.25
    assert to_json_value(Decimal("NaN")) is None
    assert to_json_value(float("inf")) is None
    assert to_json_value(date(2026, 11, 10)) == "2026-11-10"
    assert to_json_value(datetime(2026, 11, 10, 9, tzinfo=kst)) == "2026-11-10T09:00:00+09:00"
    assert to_json_value(timedelta(minutes=2)) == 120.0
    assert to_json_value(UUID(int=1)) == "00000000-0000-0000-0000-000000000001"
    assert to_json_value([Decimal("1"), {"a": Decimal("2.5")}]) == [1, {"a": 2.5}]


# ---------------------------------------------------------------------------
# 로컬 DB(klicklab_agent_ro 로그인 + 데모 시드)가 있을 때만 실행하는 통합 테스트
# guard 를 거치지 않은 SQL 로 DB 계층의 방어를 직접 확인한다.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def executor():
    settings = Settings()
    dsn = settings.dsn(read_only=True)
    try:
        psycopg.connect(dsn, connect_timeout=2).close()
    except psycopg.Error:
        pytest.skip("읽기 전용 DB 연결 불가")
    ex = build_executor(dsn, token_dsn=Settings().dsn(read_only=False), statement_timeout_ms=1000)
    yield ex
    ex.close()


def _count(executor, sdk_key: str) -> int:
    sql = "SELECT count(*) FROM agg_page_daily"
    return executor.execute(sql, sdk_key).rows[0][0]


def test_rls_scopes_rows_to_sdk_key(executor):
    if _count(executor, DEMO_KEY) == 0:
        pytest.skip("데모 시드 없음")
    assert _count(executor, "other-tenant") == 0


def test_rls_ignores_sdk_key_condition_in_query(executor):
    sql = f"SELECT count(*) FROM agg_page_daily WHERE sdk_key = '{DEMO_KEY}'"
    assert executor.execute(sql, "other-tenant").rows[0][0] == 0


SWITCH_SDK_KEY = (
    "WITH s AS MATERIALIZED (SELECT set_config('app.sdk_key', '{key}', true) AS v) "
    "SELECT (SELECT v FROM s), (SELECT count(*) FROM agg_page_daily)"
)


def test_rls_cannot_be_switched_with_set_config_in_query(executor):
    # V4 정책(sdk_key = current_setting('app.sdk_key'))은 이 쿼리로 데모 테넌트 행이 보였다
    rows = executor.execute(SWITCH_SDK_KEY.format(key=DEMO_KEY), "other-tenant").rows
    assert rows[0][1] == 0


def test_rls_token_tampering_shows_nothing(executor):
    sql = (
        "WITH s AS MATERIALIZED (SELECT set_config('app.tenant_token', 'guess', true) AS v) "
        "SELECT (SELECT v FROM s), (SELECT count(*) FROM agg_page_daily)"
    )
    assert executor.execute(sql, DEMO_KEY).rows[0][1] == 0


def test_read_only_role_cannot_issue_tokens_or_read_them(executor):
    for sql in (
        "SELECT agent_issue_tenant_token('klicklab-demo-sdk-key-0001')",
        "SELECT token FROM agent_tenant_tokens",
    ):
        with pytest.raises(SQLExecutionError) as e:
            executor.execute(sql, "other-tenant")
        assert e.value.kind == "permission"


def test_multiple_statements_are_rejected(executor):
    with pytest.raises(SQLExecutionError, match="multiple commands"):
        executor.execute("SELECT 1; SELECT count(*) FROM agg_page_daily", DEMO_KEY)


def test_percent_sign_in_sql_is_literal(executor):
    sql = "SELECT count(*) FROM agg_page_daily WHERE page_path LIKE '/products%'"
    assert executor.execute(sql, DEMO_KEY).rows[0][0] >= 0


def test_write_is_blocked_even_without_guard(executor):
    with pytest.raises(SQLExecutionError):
        executor.execute(
            "WITH d AS (DELETE FROM agg_page_daily RETURNING 1) SELECT count(*) FROM d", DEMO_KEY
        )


def test_account_table_is_not_readable(executor):
    with pytest.raises(SQLExecutionError) as e:
        executor.execute("SELECT count(*) FROM users", DEMO_KEY)
    assert e.value.kind == "permission"


def test_statement_timeout(executor):
    with pytest.raises(SQLExecutionError) as e:
        executor.execute("SELECT pg_sleep(3)", DEMO_KEY)
    assert e.value.kind == "timeout"


def test_runs_in_seoul_timezone(executor):
    assert executor.execute("SELECT current_setting('TimeZone')", DEMO_KEY).rows == [["Asia/Seoul"]]


def test_result_rows_are_capped(executor):
    result = executor.execute("SELECT generate_series(1, 30)", DEMO_KEY, result_rows=10)
    assert len(result.rows) == 10
    assert result.row_count == 30
    assert result.truncated
