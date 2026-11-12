"""LLM 이 생성한 SQL 의 정적 검증.

DB 권한(klicklab_agent_ro)과 RLS 가 최종 방어선이고, 여기서는 그 전에 의도가 분명히 잘못된 쿼리를
이유와 함께 돌려보내 모델이 고칠 수 있게 한다. 검증을 통과한 SQL 은 sqlglot 으로 다시 만들지 않고
원문 그대로 실행한다(재생성 과정의 의미 변화를 피하기 위함). LIMIT 이 없거나 상한을 넘으면 원문을
서브쿼리로 감싸 제한한다.
"""

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

GRAINS = ("minutes", "hourly", "daily", "weekly")
FAMILIES = ("metrics", "click_summary", "top_elements", "user_distribution", "page_stats")

ALLOWED_TABLES: frozenset[str] = frozenset(
    {
        "events",
        "conversion_events",
        "agg_user_session_daily",
        "agg_user_session_hourly",
        "agg_daily_users",
        "agg_page_daily",
        "agg_event_daily",
        "agg_event_page_daily",
        "agg_traffic_hourly",
        "agg_funnel_links_daily",
        "agg_first_pages_daily",
        "agg_sankey_paths_daily",
        *(f"{g}_{f}" for g in GRAINS for f in FAMILIES),
    }
)

# 서버 상태 조회·변경, 파일/네트워크 접근, 지연, 임의 쿼리 실행이 가능한 함수
_BLOCKED_FUNCTION_PREFIXES = ("pg_", "lo_", "dblink", "txid_")
_BLOCKED_FUNCTIONS = frozenset(
    {
        "set_config",
        "current_setting",
        "query_to_xml",
        "query_to_xml_and_xmlschema",
        "query_to_xmlschema",
        "table_to_xml",
        "table_to_xml_and_xmlschema",
        "cursor_to_xml",
        "database_to_xml",
        "schema_to_xml",
        "inet_server_addr",
        "inet_server_port",
        "version",
    }
)

_FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Command,
    exp.Copy,
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)

_TIME_PREDICATES = (exp.GT, exp.GTE, exp.LT, exp.LTE, exp.EQ, exp.Between)


class SQLRejected(Exception):
    """정적 검증 실패. reason 은 모델에게 그대로 돌려줄 수 있는 문장이다."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class GuardedSQL:
    sql: str
    tables: frozenset[str]
    limit_applied: bool


def guard(sql: str, *, max_rows: int = 1000) -> GuardedSQL:
    text = _strip(sql)
    if not text:
        raise SQLRejected("빈 SQL 입니다.")

    try:
        statements = [s for s in sqlglot.parse(text, read="postgres") if s is not None]
    except ParseError as e:
        raise SQLRejected(f"SQL 구문을 해석할 수 없습니다: {_first_line(str(e))}") from None
    if len(statements) != 1:
        raise SQLRejected("SQL 문은 하나만 허용됩니다.")
    tree = statements[0]

    if not isinstance(tree, exp.Query):
        raise SQLRejected("SELECT 조회만 허용됩니다.")
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SQLRejected("데이터·스키마 변경이나 세션 설정 문은 허용되지 않습니다.")
        if isinstance(node, exp.Select) and node.args.get("into"):
            raise SQLRejected("SELECT INTO 는 허용되지 않습니다.")
        if isinstance(node, exp.Lock):
            raise SQLRejected("FOR UPDATE / FOR SHARE 잠금은 허용되지 않습니다.")
        if isinstance(node, exp.Func):
            name = _function_name(node)
            if name in _BLOCKED_FUNCTIONS or name.startswith(_BLOCKED_FUNCTION_PREFIXES):
                raise SQLRejected(f"허용되지 않는 함수입니다: {name}")

    tables = _check_tables(tree)
    _check_events_time_filter(tree)
    limited, applied = _apply_limit(tree, text, max_rows)
    return GuardedSQL(sql=limited, tables=tables, limit_applied=applied)


def _strip(sql: str) -> str:
    return re.sub(r"[\s;]+$", "", sql.strip())


def _first_line(message: str) -> str:
    return message.splitlines()[0][:200] if message else ""


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return node.sql_name().lower()


def _check_tables(tree: exp.Expression) -> frozenset[str]:
    cte_names = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    used: set[str] = set()
    for table in tree.find_all(exp.Table):
        name = table.name.lower()
        if not name:  # generate_series(...) 같은 테이블 함수: 함수 검사에서 걸러진다
            continue
        schema = (table.db or "").lower()
        if schema and schema != "public":
            raise SQLRejected(f"허용되지 않는 스키마입니다: {schema}")
        if table.catalog:
            raise SQLRejected("다른 데이터베이스는 조회할 수 없습니다.")
        if not schema and name in cte_names:
            continue
        if name not in ALLOWED_TABLES:
            raise SQLRejected(f"조회할 수 없는 테이블입니다: {name}")
        used.add(name)
    return frozenset(used)


def _check_events_time_filter(tree: exp.Expression) -> None:
    """원천 events 테이블은 WHERE/ON 조건에 timestamp 범위 조건이 있어야 한다 (풀스캔 방지)."""
    for table in tree.find_all(exp.Table):
        if table.name.lower() != "events" or (table.db and table.db.lower() != "public"):
            continue
        select = table.find_ancestor(exp.Select)
        names = {"events", (table.alias or "").lower()} - {""}
        if select is None or not _has_time_predicate(_filter_clauses(select), names):
            raise SQLRejected(
                "events 테이블을 조회할 때는 WHERE 절에 timestamp 기간 조건이 필요합니다. "
                "일 단위 이상 집계는 agg_* 테이블을 우선 사용하세요."
            )


def _filter_clauses(select: exp.Select) -> list[exp.Expression]:
    """WHERE 절과 JOIN ... ON 조건 (조인 조건에 기간을 넣는 것도 정상적인 작성법이다)."""
    clauses = [select.args.get("where")]
    clauses += [join.args.get("on") for join in select.args.get("joins") or []]
    return [c for c in clauses if c is not None]


def _has_time_predicate(clauses: list[exp.Expression], names: set[str]) -> bool:
    return any(_clause_has_time_predicate(c, names) for c in clauses)


def _conjuncts(node: exp.Expression) -> list[exp.Expression]:
    """최상위 AND 로 묶인 조건들. OR 안의 조건은 항상 참일 수 있어 세지 않는다."""
    while isinstance(node, (exp.Paren, exp.Where)):
        node = node.this
    if isinstance(node, exp.And):
        return _conjuncts(node.this) + _conjuncts(node.expression)
    return [node]


def _is_time_column(column: exp.Column, names: set[str]) -> bool:
    return column.name.lower() == "timestamp" and (
        not column.table or column.table.lower() in names
    )


def _has_column(node: exp.Expression | None) -> bool:
    return node is not None and node.find(exp.Column) is not None


def _compares_time_to_value(predicate: exp.Expression, names: set[str]) -> bool:
    if isinstance(predicate, exp.Between):
        subject, others = predicate.this, [predicate.args.get("low"), predicate.args.get("high")]
        return _mentions_time(subject, names) and not any(_has_column(o) for o in others)
    left, right = predicate.this, predicate.expression
    return (_mentions_time(left, names) and not _has_column(right)) or (
        _mentions_time(right, names) and not _has_column(left)
    )


def _mentions_time(node: exp.Expression | None, names: set[str]) -> bool:
    return node is not None and any(_is_time_column(c, names) for c in node.find_all(exp.Column))


def _clause_has_time_predicate(where: exp.Expression, names: set[str]) -> bool:
    """events.timestamp 를 컬럼이 아닌 값(상수·now() 등)과 비교하는 조건이 AND 로 걸려 있는가."""
    return any(
        isinstance(p, _TIME_PREDICATES) and _compares_time_to_value(p, names)
        for p in _conjuncts(where)
    )


def _apply_limit(tree: exp.Expression, text: str, max_rows: int) -> tuple[str, bool]:
    limit = tree.args.get("limit")
    if limit is not None:
        count = _limit_count(limit)
        if count is None:
            if not _is_limit_all(limit):
                raise SQLRejected("LIMIT 에는 정수 상수만 사용할 수 있습니다.")
        elif count <= max_rows:
            return text, False
    return f"SELECT * FROM (\n{text}\n) AS limited_result LIMIT {max_rows}", True


def _limit_count(limit: exp.Expression) -> int | None:
    value = limit.expression if isinstance(limit, exp.Limit) else limit.args.get("count")
    if isinstance(value, exp.Literal) and not value.is_string:
        try:
            return int(value.this)
        except ValueError:
            return None
    return None


def _is_limit_all(limit: exp.Expression) -> bool:
    value = limit.expression if isinstance(limit, exp.Limit) else limit.args.get("count")
    return isinstance(value, exp.Var) and str(value.this).upper() == "ALL"
