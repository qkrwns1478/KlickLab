import contextlib
import json
from pathlib import Path

import psycopg
import pytest
import yaml

from app.agent.budget import Budget
from app.agent.tools import RunState
from app.agent.tools.search_knowledge import SearchKnowledge
from app.config import Settings
from app.knowledge.context import KnowledgeContext, table_list
from app.knowledge.documents import CatalogError, load_catalog
from app.knowledge.indexer import sync_catalog
from app.knowledge.retriever import Hit, KnowledgeRetriever, parse_quota, query_terms
from app.sql.executor import build_executor
from app.sql.guard import ALLOWED_TABLES, guard

DEMO_KEY = "klicklab-demo-sdk-key-0001"
GOLDEN = Path(__file__).parents[1] / "evals" / "datasets" / "golden_sql.yaml"


@pytest.fixture(scope="module")
def docs():
    return load_catalog()


# --- 카탈로그 ----------------------------------------------------------------


def test_catalog_loads_all_kinds(docs):
    kinds = {d.kind for d in docs}
    assert kinds == {"table", "metric", "example", "glossary"}
    assert len({d.key for d in docs}) == len(docs)
    assert all(d.content and d.title for d in docs)


def test_catalog_tables_are_queryable(docs):
    for doc in docs:
        if doc.kind == "table":
            assert doc.name in ALLOWED_TABLES, doc.name


def test_metric_source_tables_exist_in_catalog(docs):
    tables = {d.name for d in docs if d.kind == "table"}
    for doc in docs:
        if doc.kind == "metric":
            for table in doc.metadata["source_table"].split(","):
                assert table.strip() in tables, (doc.name, table)


def test_examples_do_not_leak_golden_questions(docs):
    golden = {i["question"] for i in yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))}
    examples = {d.title for d in docs if d.kind == "example"}
    assert not golden & examples


def test_example_sql_passes_guard(docs):
    for doc in docs:
        if doc.kind == "example":
            guard(doc.metadata["sql"])


def test_content_hash_changes_with_content(docs):
    doc = docs[0]
    changed = type(doc)(doc.kind, doc.name, doc.title, doc.content + "!", doc.metadata)
    assert changed.content_hash != doc.content_hash


def test_duplicate_names_are_rejected(tmp_path):
    for name in ("tables", "metrics", "examples", "glossary"):
        (tmp_path / f"{name}.yaml").write_text("[]", encoding="utf-8")
    entry = {"name": "a", "title": "A", "content": "x"}
    (tmp_path / "glossary.yaml").write_text(yaml.safe_dump([entry, entry]), encoding="utf-8")
    with pytest.raises(CatalogError, match="중복"):
        load_catalog(tmp_path)


def test_missing_field_is_rejected(tmp_path):
    for name in ("tables", "metrics", "examples", "glossary"):
        (tmp_path / f"{name}.yaml").write_text("[]", encoding="utf-8")
    (tmp_path / "metrics.yaml").write_text(yaml.safe_dump([{"name": "x"}]), encoding="utf-8")
    with pytest.raises(CatalogError, match="필수 항목"):
        load_catalog(tmp_path)


# --- 검색 보조 함수 ------------------------------------------------------------


def test_query_terms_strip_particles_and_stopwords():
    terms = query_terms("지난주 유입 소스별 이탈률은 얼마야?")
    assert terms == ["지난주", "유입", "소스", "이탈률"]
    assert query_terms("/checkout/success 페이지를 본 세션") == [
        "checkout/success",
        "페이지",
        "세션",
    ]
    assert query_terms("보여줘") == []


def test_parse_quota():
    assert parse_quota("table:2, metric:1,") == {"table": 2, "metric": 1}
    with pytest.raises(ValueError):
        parse_quota("tables:2")
    with pytest.raises(ValueError):
        parse_quota("table:x")


def test_rrf_fusion_prefers_documents_found_by_several_signals():
    retriever = KnowledgeRetriever(pool=None, embedder=None)  # type: ignore[arg-type]

    def row(name):
        return {"kind": "metric", "name": name, "title": name, "content": name}

    hits = retriever._fuse(
        [row("a"), row("b"), row("c")],  # 벡터
        [row("c"), row("b")],  # 키워드
        [row("c")],  # 별칭
    )
    assert [h.name for h in hits] == ["c", "b", "a"]
    assert (hits[0].vector_rank, hits[0].keyword_rank, hits[0].alias_rank) == (3, 1, 1)


# --- 컨텍스트와 search_knowledge 도구 -------------------------------------------


class FakeRetriever:
    def __init__(self, hits=None, error=None):
        self.hits = hits or []
        self.error = error
        self.calls = []

    def search(self, query, *, kinds=None, k=5, mode="hybrid"):
        self.calls.append((query, kinds, k))
        if self.error:
            raise self.error
        return self.hits[:k]

    def context(self, query, quota, *, mode="hybrid"):
        self.calls.append((query, quota))
        return self.hits


def hit(kind, name, content="본문"):
    return Hit(kind, name, name, content, 0.1)


def test_schema_context_has_table_list_and_documents(docs):
    retriever = FakeRetriever([hit("metric", "bounce_rate", "이탈률 정의")])
    context = KnowledgeContext(retriever, {"metric": 1}, docs=tuple(docs))
    schema = context.schema_for("이탈률")
    assert "- agg_traffic_hourly:" in schema.text
    assert "### [metric] bounce_rate\n이탈률 정의" in schema.text
    assert schema.doc_ids == ["metric/bounce_rate"]
    assert table_list(docs).count("\n") == sum(d.kind == "table" for d in docs) - 1


def _state():
    return RunState(sdk_key="k", budget=Budget("compare"))


async def test_search_knowledge_returns_documents_and_hides_seen_content():
    retriever = FakeRetriever([hit("metric", "bounce_rate"), hit("glossary", "period_week")])
    tool = SearchKnowledge(retriever, k=4)  # type: ignore[arg-type]
    state = _state()
    state.knowledge_seen.add("glossary/period_week")  # 시스템 프롬프트에 이미 있음

    out = await tool(state, {"query": "이탈률", "kind": "metric"}, seq=1)
    assert out.error is None and out.charged
    assert out.for_model["documents"] == [
        {"kind": "metric", "name": "bounce_rate", "content": "본문"},
        {"kind": "glossary", "name": "period_week", "note": "앞에서 제공함"},
    ]
    assert out.output["documents"] == ["metric/bounce_rate", "glossary/period_week"]
    assert retriever.calls == [("이탈률", ["metric"], 4)]
    assert "metric/bounce_rate" in state.knowledge_seen


async def test_search_knowledge_repeated_query_is_free():
    tool = SearchKnowledge(FakeRetriever([hit("metric", "a")]))  # type: ignore[arg-type]
    state = _state()
    await tool(state, {"query": "전환율"}, seq=1)
    again = await tool(state, {"query": "  전환율 "}, seq=2)
    assert again.error and not again.charged and "step 1" in again.error


async def test_search_knowledge_validates_input_and_reports_failure():
    tool = SearchKnowledge(FakeRetriever(error=RuntimeError("db")))  # type: ignore[arg-type]
    state = _state()
    assert (await tool(state, {"query": ""}, seq=1)).error
    assert "kind" in (await tool(state, {"query": "x", "kind": "tables"}, seq=1)).error
    failed = await tool(state, {"query": "x"}, seq=1)
    assert failed.error and "검색에 실패" in failed.error


# ---------------------------------------------------------------------------
# 로컬 DB 가 있을 때만 실행하는 통합 테스트
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def executor():
    dsn = Settings().dsn(read_only=True)
    try:
        psycopg.connect(dsn, connect_timeout=2).close()
    except psycopg.Error:
        pytest.skip("읽기 전용 DB 연결 불가")
    ex = build_executor(dsn, token_dsn=Settings().dsn(read_only=False), statement_timeout_ms=5000)
    yield ex
    ex.close()


def test_catalog_columns_match_database(docs, executor):
    for doc in docs:
        if doc.kind != "table":
            continue
        result = executor.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' "
            f"AND table_name = '{doc.name}' AND column_name <> 'sdk_key'",
            DEMO_KEY,
        )
        actual = {r[0] for r in result.rows}
        assert set(doc.metadata["columns"]) == actual, doc.name


def test_example_sql_runs_on_demo_data(docs, executor):
    for doc in docs:
        if doc.kind == "example":
            result = executor.execute(guard(doc.metadata["sql"]).sql, DEMO_KEY)
            assert result.row_count > 0, doc.name


class _TxPool:
    """sync_catalog 를 실제 테이블에 돌리되 끝나면 롤백한다."""

    def __init__(self, conn):
        self.conn = conn

    @contextlib.contextmanager
    def connection(self):
        yield self.conn


class _FakeEmbedder:
    model = "fake"
    dimension = 1024

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += len(texts)
        return [[1.0] + [0.0] * 1023 for _ in texts]


@pytest.fixture
def rw_conn():
    try:
        conn = psycopg.connect(Settings().dsn(read_only=False), connect_timeout=2)
    except psycopg.Error:
        pytest.skip("지식 베이스 DB 연결 불가")
    conn.execute("DELETE FROM agent_knowledge")  # 트랜잭션 안: 끝나면 롤백된다
    yield conn
    conn.rollback()
    conn.close()


def test_sync_catalog_embeds_only_changed_documents(docs, rw_conn):
    pool = _TxPool(rw_conn)
    embedder = _FakeEmbedder()
    first = sync_catalog(pool, embedder, docs[:3])
    assert len(first.inserted) == 3 and embedder.calls == 3

    second = sync_catalog(pool, embedder, docs[:3])
    assert second.unchanged == 3 and embedder.calls == 3

    edited = type(docs[0])(docs[0].kind, docs[0].name, docs[0].title, "바뀐 본문", {})
    third = sync_catalog(pool, embedder, [edited, docs[1]])
    assert third.updated == [f"{edited.kind}/{edited.name}"]
    assert third.deleted == [f"{docs[2].kind}/{docs[2].name}"]
    assert embedder.calls == 4

    row = rw_conn.execute(
        "SELECT content, metadata FROM agent_knowledge WHERE kind = %s AND name = %s",
        edited.key,
    ).fetchone()
    assert row[0] == "바뀐 본문" and row[1]["embedding_model"] == "fake"


def test_keyword_and_alias_search_on_real_catalog(docs, rw_conn):
    sync_catalog(_TxPool(rw_conn), None, docs)
    retriever = KnowledgeRetriever(_TxPool(rw_conn), None)  # type: ignore[arg-type]
    hits = retriever.context(
        "지난주 유입 소스별 이탈률은?", {"table": 1, "metric": 1, "glossary": 3}
    )
    found = {f"{h.kind}/{h.name}" for h in hits}
    assert {"table/agg_traffic_hourly", "metric/bounce_rate", "glossary/period_week"} <= found
    assert json.dumps([h.for_model() for h in hits], ensure_ascii=False)
