"""실행 로그(agent_runs / agent_steps) 저장. klicklab_agent 롤 연결을 쓴다.

조회는 항상 토큰의 sdk_key + user_id 로 제한한다 (이 테이블에는 RLS 가 없다).
"""

import json
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID, uuid4

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pydantic.alias_generators import to_camel

from app.agent.turn import HISTORY_TURNS, Turn
from app.sql.executor import to_json_value


@dataclass
class RunTotals:
    status: str
    difficulty: str | None
    answer: dict[str, Any] | None
    tool_calls: int
    input_tokens: int
    output_tokens: int
    latency_ms: int
    cost_usd: float | None = None
    error: str | None = None  # status=failed 일 때 사용자에게 보여 준 사유


class RunStore(Protocol):
    def resolve_conversation(
        self, *, sdk_key: str, user_id: str, conversation_id: str | None
    ) -> tuple[str, list[Turn]]: ...

    def create_run(
        self, *, sdk_key: str, user_id: str, question: str, conversation_id: str | None = None
    ) -> str: ...

    def set_difficulty(self, run_id: str, difficulty: str) -> None: ...

    def add_step(
        self,
        run_id: str,
        *,
        seq: int,
        tool: str,
        input: dict[str, Any],
        output: dict[str, Any] | None,
        error: str | None,
        duration_ms: int,
    ) -> None: ...

    def finish_run(self, run_id: str, totals: RunTotals) -> None: ...


def _json(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, default=str)


class PostgresRunStore:
    def __init__(self, pool: ConnectionPool):
        self._pool = pool

    def resolve_conversation(
        self, *, sdk_key: str, user_id: str, conversation_id: str | None
    ) -> tuple[str, list[Turn]]:
        """내 대화면 (id, 최근 턴), 아니면 (새 id, [])."""
        if not conversation_id or not _is_uuid(conversation_id):
            return str(uuid4()), []
        with self._pool.connection() as conn:
            owned = conn.execute(
                "SELECT 1 FROM agent_runs WHERE conversation_id = %s AND sdk_key = %s"
                " AND user_id = %s LIMIT 1",
                (conversation_id, sdk_key, user_id),
            ).fetchone()
            if owned is None:
                return str(uuid4()), []
            rows = conn.execute(
                "SELECT question, answer ->> 'summary' FROM agent_runs"
                " WHERE conversation_id = %s AND sdk_key = %s AND user_id = %s"
                " AND status IN ('succeeded', 'budget_exhausted') AND answer ? 'summary'"
                " ORDER BY created_at DESC LIMIT %s",
                (conversation_id, sdk_key, user_id, HISTORY_TURNS),
            ).fetchall()
        return str(UUID(conversation_id)), [Turn(q, s or "") for q, s in reversed(rows)]

    def create_run(
        self, *, sdk_key: str, user_id: str, question: str, conversation_id: str | None = None
    ) -> str:
        with self._pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO agent_runs (sdk_key, user_id, question, status, conversation_id)"
                " VALUES (%s, %s, %s, 'running', COALESCE(%s::uuid, gen_random_uuid()))"
                " RETURNING id",
                (sdk_key, user_id, question, conversation_id),
            ).fetchone()
        return str(row[0])

    def set_difficulty(self, run_id: str, difficulty: str) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE agent_runs SET difficulty = %s WHERE id = %s", (difficulty, run_id)
            )

    def add_step(self, run_id, *, seq, tool, input, output, error, duration_ms) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "INSERT INTO agent_steps (run_id, seq, tool, input, output, error, duration_ms)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (run_id, seq, tool, _json(input), _json(output), error, duration_ms),
            )

    def finish_run(self, run_id: str, totals: RunTotals) -> None:
        with self._pool.connection() as conn:
            conn.execute(
                "UPDATE agent_runs SET status = %s, difficulty = %s, answer = %s, tool_calls = %s,"
                " input_tokens = %s, output_tokens = %s, latency_ms = %s, cost_usd = %s,"
                " error_message = %s WHERE id = %s",
                (
                    totals.status,
                    totals.difficulty,
                    _json(totals.answer),
                    totals.tool_calls,
                    totals.input_tokens,
                    totals.output_tokens,
                    totals.latency_ms,
                    totals.cost_usd,
                    totals.error,
                    run_id,
                ),
            )

    # --- 조회 (API) ---------------------------------------------------

    def list_runs(self, *, sdk_key: str, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, question, difficulty, status, tool_calls, input_tokens, output_tokens,"
                " cost_usd, latency_ms, feedback, created_at FROM agent_runs"
                " WHERE sdk_key = %s AND user_id = %s ORDER BY created_at DESC LIMIT %s",
                (sdk_key, user_id, limit),
            )
            return [_row(r) for r in cur.fetchall()]

    def list_conversations(
        self, *, sdk_key: str, user_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT g.id, COALESCE(t.title, g.title) AS title, g.run_count, g.updated_at,"
                " g.status FROM ("
                "  SELECT conversation_id AS id,"
                "  (array_agg(question ORDER BY created_at))[1] AS title,"
                "  count(*) AS run_count, max(created_at) AS updated_at,"
                "  (array_agg(status ORDER BY created_at DESC))[1] AS status"
                "  FROM agent_runs WHERE sdk_key = %s AND user_id = %s"
                "  GROUP BY conversation_id) g"
                " LEFT JOIN agent_conversation_titles t ON t.conversation_id = g.id"
                " AND t.sdk_key = %s AND t.user_id = %s"
                " ORDER BY g.updated_at DESC LIMIT %s",
                (sdk_key, user_id, sdk_key, user_id, limit),
            )
            return [_row(r) for r in cur.fetchall()]

    def rename_conversation(
        self, conversation_id: str, *, sdk_key: str, user_id: str, title: str
    ) -> bool:
        """내 대화의 제목을 바꾼다. 내 대화가 아니면 False."""
        if not _is_uuid(conversation_id):
            return False
        with self._pool.connection() as conn:
            return (
                conn.execute(
                    "INSERT INTO agent_conversation_titles"
                    " (conversation_id, sdk_key, user_id, title)"
                    " SELECT %s::uuid, %s, %s, %s WHERE EXISTS ("
                    "  SELECT 1 FROM agent_runs WHERE conversation_id = %s::uuid"
                    "  AND sdk_key = %s AND user_id = %s)"
                    " ON CONFLICT (conversation_id) DO UPDATE"
                    " SET title = EXCLUDED.title, updated_at = now()",
                    (conversation_id, sdk_key, user_id, title, conversation_id, sdk_key, user_id),
                ).rowcount
                > 0
            )

    def delete_conversation(self, conversation_id: str, *, sdk_key: str, user_id: str) -> bool:
        """내 대화의 실행·단계(CASCADE)·제목을 지운다. 내 대화가 아니면 False."""
        if not _is_uuid(conversation_id):
            return False
        with self._pool.connection() as conn, conn.transaction():
            deleted = conn.execute(
                "DELETE FROM agent_runs WHERE conversation_id = %s AND sdk_key = %s"
                " AND user_id = %s",
                (conversation_id, sdk_key, user_id),
            ).rowcount
            conn.execute(
                "DELETE FROM agent_conversation_titles WHERE conversation_id = %s"
                " AND sdk_key = %s AND user_id = %s",
                (conversation_id, sdk_key, user_id),
            )
        return deleted > 0

    def get_conversation(
        self, conversation_id: str, *, sdk_key: str, user_id: str
    ) -> dict[str, Any] | None:
        """대화에 속한 실행들을 오래된 순서로, 단계와 함께 돌려준다."""
        if not _is_uuid(conversation_id):
            return None
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, question, difficulty, status, answer, error_message, tool_calls,"
                " input_tokens, output_tokens, cost_usd, latency_ms, feedback, feedback_note,"
                " created_at FROM agent_runs"
                " WHERE conversation_id = %s AND sdk_key = %s AND user_id = %s"
                " ORDER BY created_at",
                (conversation_id, sdk_key, user_id),
            )
            runs = [_row(r) for r in cur.fetchall()]
            if not runs:
                return None
            cur.execute(
                "SELECT run_id, seq, tool, input, output, error, duration_ms, created_at"
                " FROM agent_steps WHERE run_id = ANY(%s::uuid[]) ORDER BY run_id, seq",
                ([r["id"] for r in runs],),
            )
            steps: dict[str, list[dict[str, Any]]] = {r["id"]: [] for r in runs}
            for step in cur.fetchall():
                run_id = str(step.pop("run_id"))
                steps[run_id].append(_row(step))
        for run in runs:
            run["steps"] = steps[run["id"]]
        return {"id": conversation_id, "runs": runs}

    def get_run(self, run_id: str, *, sdk_key: str, user_id: str) -> dict[str, Any] | None:
        if not _is_uuid(run_id):
            return None
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                "SELECT id, question, difficulty, status, answer, error_message, tool_calls,"
                " input_tokens, output_tokens, cost_usd, latency_ms, feedback, feedback_note,"
                " created_at FROM agent_runs WHERE id = %s AND sdk_key = %s AND user_id = %s",
                (run_id, sdk_key, user_id),
            )
            run = cur.fetchone()
            if run is None:
                return None
            cur.execute(
                "SELECT seq, tool, input, output, error, duration_ms, created_at FROM agent_steps"
                " WHERE run_id = %s ORDER BY seq",
                (run_id,),
            )
            detail = _row(run)
            detail["steps"] = [_row(s) for s in cur.fetchall()]
            return detail

    def set_feedback(
        self, run_id: str, *, sdk_key: str, user_id: str, feedback: int, note: str | None
    ) -> bool:
        if not _is_uuid(run_id):
            return False
        with self._pool.connection() as conn:
            updated = conn.execute(
                "UPDATE agent_runs SET feedback = %s, feedback_note = %s"
                " WHERE id = %s AND sdk_key = %s AND user_id = %s",
                (feedback, note, run_id, sdk_key, user_id),
            ).rowcount
        return updated > 0

    def close(self) -> None:
        self._pool.close()


def _row(row: dict[str, Any]) -> dict[str, Any]:
    return {to_camel(k): to_json_value(v) for k, v in row.items()}


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def build_run_store(dsn: str) -> PostgresRunStore:
    pool = ConnectionPool(dsn, min_size=1, max_size=4, open=False, kwargs={"autocommit": True})
    pool.open(wait=False)
    return PostgresRunStore(pool)
