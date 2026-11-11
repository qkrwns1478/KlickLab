import asyncio
from typing import Any

from app.agent.tools import RunState, ToolOutcome, function_schema
from app.sql.executor import SQLExecutionError, SQLExecutor
from app.sql.guard import ALLOWED_TABLES

NAME = "describe_table"

SCHEMA = function_schema(
    NAME,
    "조회 가능한 테이블의 컬럼, 타입, 설명과 최근 샘플 3행을 돌려준다.",
    {
        "type": "object",
        "properties": {"table_name": {"type": "string", "description": "테이블 이름"}},
        "required": ["table_name"],
    },
)

NOTES = {
    "events": "원천 이벤트. 조회 시 WHERE 에 timestamp 기간 조건이 필요하다.",
    "agg_daily_users": "날짜별 활동 방문자(client_id) 목록",
    "agg_user_session_daily": "날짜 × 성별 × 연령대별 방문자·세션·세션 시간(초)",
    "agg_user_session_hourly": "날짜 × 시간대 × 지역·연령·성별·기기·OS·브라우저별 방문자·세션",
    "agg_page_daily": "날짜 × 페이지별 페이지뷰, 순 방문자, 세션, 종료 수, 체류 시간 합(초)",
    "agg_event_daily": "날짜 × 이벤트별 발생 수, 순 방문자",
    "agg_event_page_daily": "날짜 × 이벤트 × 페이지별 발생 수, 순 방문자",
    "agg_traffic_hourly": "날짜 × 시간대 × 유입 경로·캠페인·랜딩 페이지별 세션, 이탈, 전환, 퍼널",
    "agg_funnel_links_daily": "날짜별 페이지 이동(source → target) 세션 수",
    "agg_first_pages_daily": "날짜별 랜딩 페이지 세션 수",
    "agg_sankey_paths_daily": "날짜 × 세션별 페이지·이벤트 경로 배열",
    "conversion_events": "전환으로 집계하는 이벤트 정의",
}
_BATCH_NOTE = "대시보드 위젯용 배치 집계. 최근 날짜가 늦게 반영된다."

# 테이블 이름은 화이트리스트를 통과한 값만 들어간다
_COLUMNS_SQL = (
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_schema = 'public' AND table_name = '{table}' ORDER BY ordinal_position"
)
_DATE_COLUMNS = ("summary_date", "date", "timestamp")


class DescribeTable:
    def __init__(self, executor: SQLExecutor):
        self._executor = executor
        self._columns: dict[str, list[dict[str, str]]] = {}  # 스키마는 실행 중 바뀌지 않는다

    async def __call__(self, state: RunState, args: dict[str, Any], seq: int) -> ToolOutcome:
        table = str(args.get("table_name") or "").strip().lower().removeprefix("public.")
        if table not in ALLOWED_TABLES:
            return ToolOutcome.fail(f"조회할 수 없는 테이블입니다: {table or '(없음)'}")
        try:
            columns = await self._load_columns(table, state.sdk_key)
            sample = await asyncio.to_thread(
                self._executor.execute, sample_sql(table, columns), state.sdk_key
            )
        except SQLExecutionError as e:
            return ToolOutcome.fail(e.message)

        description: dict[str, Any] = {
            "ok": True,
            "table": table,
            "description": NOTES.get(table, _BATCH_NOTE),
            "columns": columns,
            "sample": {"columns": sample.columns, "rows": sample.rows[:3]},
        }
        return ToolOutcome(for_model=description, output=description)

    async def _load_columns(self, table: str, sdk_key: str) -> list[dict[str, str]]:
        if table not in self._columns:
            result = await asyncio.to_thread(
                self._executor.execute, _COLUMNS_SQL.format(table=table), sdk_key
            )
            self._columns[table] = [{"name": r[0], "type": r[1]} for r in result.rows]
        return self._columns[table]


def sample_sql(table: str, columns: list[dict[str, str]]) -> str:
    """최근 데이터 3행. events 는 기간 조건 없이 읽지 않는다."""
    if table == "events":
        return (
            "SELECT * FROM events WHERE timestamp >= current_date - 1 "
            "ORDER BY timestamp DESC LIMIT 3"
        )
    names = {c["name"] for c in columns}
    for column in _DATE_COLUMNS:
        if column in names:
            return f'SELECT * FROM {table} ORDER BY "{column}" DESC LIMIT 3'
    return f"SELECT * FROM {table} LIMIT 3"
