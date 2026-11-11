"""검증된 SQL 을 읽기 전용 롤(klicklab_agent_ro)로 실행한다.

트랜잭션마다 READ ONLY, statement_timeout, app.sdk_key(RLS), 타임존을 지정하고 끝나면 롤백한다.
psycopg 의 async 연결은 Windows 기본 이벤트 루프(Proactor)에서 동작하지 않으므로 동기 풀을 쓰고
호출 측에서 스레드로 실행한다.
"""

import math
import time
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


class SQLExecutor:
    def __init__(
        self,
        pool: ConnectionPool,
        *,
        statement_timeout_ms: int = 5000,
        result_rows: int = 200,
        max_plan_cost: float | None = None,
    ):
        self._pool = pool
        self._timeout = statement_timeout_ms
        self._result_rows = result_rows
        self._max_plan_cost = max_plan_cost

    def execute(self, sql: str, sdk_key: str, *, result_rows: int | None = None) -> QueryResult:
        keep = result_rows or self._result_rows
        started = time.monotonic()
        try:
            with self._pool.connection() as conn, conn.transaction(force_rollback=True):
                with conn.cursor() as cur:
                    cur.execute("SET TRANSACTION READ ONLY")
                    cur.execute(
                        "SELECT set_config('app.sdk_key', %s, true),"
                        " set_config('statement_timeout', %s, true),"
                        " set_config('TimeZone', %s, true)",
                        (sdk_key, str(self._timeout), TIMEZONE),
                    )
                    if self._max_plan_cost is not None:
                        self._check_cost(cur, sql)
                    cur.execute(sql)
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
        cur.execute("EXPLAIN (FORMAT JSON) " + sql)
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


def build_executor(dsn: str, **kwargs: Any) -> SQLExecutor:
    pool = ConnectionPool(dsn, min_size=1, max_size=4, open=False, kwargs={"autocommit": False})
    pool.open(wait=False)
    return SQLExecutor(pool, **kwargs)
