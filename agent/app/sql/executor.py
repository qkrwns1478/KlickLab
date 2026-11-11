"""검증된 SQL 을 읽기 전용 롤(klicklab_agent_ro)로 실행한다.

트랜잭션마다 READ ONLY, statement_timeout, 테넌트 토큰(RLS), 타임존을 지정하고 끝나면 롤백한다.
psycopg 의 async 연결은 Windows 기본 이벤트 루프(Proactor)에서 동작하지 않으므로 동기 풀을 쓰고
호출 측에서 스레드로 실행한다.

DB 계층 방어는 guard 를 우회한 SQL 이 들어와도 버텨야 한다.
* RLS 는 sdk_key 가 아니라 추측할 수 없는 테넌트 토큰(app.tenant_token)으로 건다 (V5). 쿼리 안에서
  설정을 바꿔도 다른 테넌트의 토큰을 모르므로 다른 테넌트 행이 보이지 않는다.
* 사용자 SQL 은 prepared statement(확장 프로토콜)로 실행해 한 번에 한 문장만 실행되게 한다.
"""

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg import errors
from psycopg_pool import ConnectionPool

TIMEZONE = "Asia/Seoul"


class SQLExecutionError(Exception):
    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind  # timeout / permission / too_expensive / error
        self.message = message


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    elapsed_ms: int


class TenantTokens:
    """sdk_key → RLS 테넌트 토큰.

    토큰은 실행 로그 롤(klicklab_agent) 연결로 agent_issue_tenant_token() 을 불러 받는다.
    읽기 전용 롤은 토큰 테이블과 발급 함수에 접근할 수 없다. 토큰은 바뀌지 않으므로 캐시한다.
    """

    def __init__(self, dsn: str):
        self._dsn = dsn
        self._cache: dict[str, str] = {}
        self._lock = threading.Lock()

    def __call__(self, sdk_key: str) -> str:
        token = self._cache.get(sdk_key)
        if token is not None:
            return token
        with self._lock:
            token = self._cache.get(sdk_key)
            if token is None:
                with psycopg.connect(self._dsn, autocommit=True, connect_timeout=5) as conn:
                    row = conn.execute("SELECT agent_issue_tenant_token(%s)", (sdk_key,)).fetchone()
                token = self._cache[sdk_key] = row[0]
        return token


class SQLExecutor:
    def __init__(
        self,
        pool: ConnectionPool,
        *,
        tenant_token: Callable[[str], str],
        statement_timeout_ms: int = 5000,
        result_rows: int = 200,
        max_plan_cost: float | None = None,
    ):
        self._pool = pool
        self._tenant_token = tenant_token
        self._timeout = statement_timeout_ms
        self._result_rows = result_rows
        self._max_plan_cost = max_plan_cost

    def execute(self, sql: str, sdk_key: str, *, result_rows: int | None = None) -> QueryResult:
        keep = result_rows or self._result_rows
        started = time.monotonic()
        try:
            token = self._tenant_token(sdk_key)
        except psycopg.Error as e:
            raise SQLExecutionError(
                "error", f"테넌트 토큰을 발급받지 못했습니다: {_message(e)}"
            ) from None
        try:
            with self._pool.connection() as conn, conn.transaction(force_rollback=True):
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute(
                        "SELECT set_config('app.tenant_token', %s, true),"
                        " set_config('statement_timeout', %s, true),"
                        " set_config('TimeZone', %s, true)",
                        (token, str(self._timeout), TIMEZONE),
                    )
                    if self._max_plan_cost is not None:
                        self._check_cost(cur, sql)
                    cur.execute(sql, prepare=True)  # 여러 문장이 들어오면 구문 오류
                    if cur.description is None:
                        raise SQLExecutionError("error", "결과 집합이 없는 문장입니다.")
                    columns = [d.name for d in cur.description]
                    fetched = cur.fetchall()  # guard 가 LIMIT 상한을 보장한다
                    row_count = len(fetched)
        except SQLExecutionError:
            raise
        except errors.QueryCanceled:
            raise SQLExecutionError(
                "timeout",
                f"실행 시간이 {self._timeout}ms 를 넘었습니다. "
                "기간을 줄이거나 집계 테이블을 사용하세요.",
            ) from None
        except errors.InsufficientPrivilege as e:
            raise SQLExecutionError("permission", _message(e)) from None
        except psycopg.Error as e:
            raise SQLExecutionError("error", _message(e)) from None

        rows = [[to_json_value(v) for v in row] for row in fetched[:keep]]
        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=row_count,
            truncated=row_count > keep,
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )

    def _check_cost(self, cur: psycopg.Cursor, sql: str) -> None:
        cur.execute("EXPLAIN (FORMAT JSON) " + sql, prepare=True)
        plan = cur.fetchone()[0][0]["Plan"]
        cost = float(plan["Total Cost"])
        if cost > self._max_plan_cost:
            raise SQLExecutionError(
                "too_expensive",
                f"예상 실행 비용({cost:,.0f})이 상한({self._max_plan_cost:,.0f})을 넘습니다. "
                "기간을 줄이거나 agg_* 집계 테이블을 사용하세요.",
            )

    def close(self) -> None:
        self._pool.close()


def _message(e: psycopg.Error) -> str:
    diag = getattr(e, "diag", None)
    primary = diag.message_primary if diag else None
    hint = diag.message_hint if diag else None
    text = primary or str(e).splitlines()[0]
    return f"{text} (힌트: {hint})" if hint else text


def to_json_value(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            return None
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime, date, dtime)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [to_json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_json_value(v) for k, v in value.items()}
    if isinstance(value, (bytes, memoryview)):
        return bytes(value).hex()
    return str(value)


def build_executor(dsn: str, *, token_dsn: str, **kwargs: Any) -> SQLExecutor:
    """dsn: 읽기 전용 롤 연결, token_dsn: 테넌트 토큰을 발급받을 klicklab_agent 연결."""
    pool = ConnectionPool(dsn, min_size=1, max_size=4, open=False, kwargs={"autocommit": False})
    pool.open(wait=False)
    return SQLExecutor(pool, tenant_token=TenantTokens(token_dsn), **kwargs)
