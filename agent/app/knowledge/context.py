"""KNOWLEDGE_MODE=rag 일 때 시스템 프롬프트에 넣을 스키마 컨텍스트.

스키마 요약 전체 대신 (1) 조회 가능한 테이블 목록 한 줄씩과
(2) 질문으로 검색한 문서(종류별 할당량)를 넣는다. 테이블 목록은 검색이 테이블 문서를 놓쳐도
모델이 테이블 이름을 알고 search_knowledge / describe_table 로 더 찾을 수 있게 항상 넣는다.
"""

import asyncio
import threading
import time
from dataclasses import dataclass, field

from psycopg_pool import ConnectionPool

from app.config import Settings
from app.knowledge.documents import Kind, KnowledgeDoc, default_catalog
from app.knowledge.retriever import Hit, KnowledgeRetriever, format_hits, parse_quota
from app.llm.embedding import build_embedding_client

RAG_SCHEMA = """\
## 데이터 개요
KlickLab 은 웹사이트 클릭스트림 분석 서비스다. 모든 테이블은 사이트(sdk_key) 단위이며 DB 가 현재 사이트의 데이터만
보이도록 자동으로 거른다. sdk_key 조건은 쓰지 않는다. 날짜·시간은 모두 Asia/Seoul 기준이다.
날짜는 상수 대신 current_date 기준 상대 표현으로 쓴다.

## 조회 가능한 테이블
{tables}

## 참고 문서
질문으로 검색한 테이블·지표 정의·용어·예시다. 지표 계산식과 기간 표현은 이 문서를 따른다.

{documents}
"""


def table_list(docs: tuple[KnowledgeDoc, ...] | list[KnowledgeDoc]) -> str:
    return "\n".join(f"- {d.name}: {d.title}" for d in docs if d.kind == "table")


@dataclass
class SchemaContext:
    text: str
    hits: list[Hit] = field(default_factory=list)
    elapsed_ms: int = 0

    @property
    def doc_ids(self) -> list[str]:
        return [f"{h.kind}/{h.name}" for h in self.hits]


class KnowledgeContext:
    def __init__(
        self,
        retriever: KnowledgeRetriever,
        quota: dict[Kind, int],
        *,
        search_k: int = 4,
        expand_sources: int = 0,
        docs: tuple[KnowledgeDoc, ...] | None = None,
        pool: ConnectionPool | None = None,
    ):
        self.retriever = retriever
        self.quota = quota
        self.search_k = search_k
        self.expand_sources = expand_sources
        self._tables = table_list(docs if docs is not None else default_catalog())
        self._pool = pool

    def schema_for(self, question: str) -> SchemaContext:
        started = time.monotonic()
        hits = self.retriever.context(question, self.quota, expand_sources=self.expand_sources)
        text = RAG_SCHEMA.format(tables=self._tables, documents=format_hits(hits))
        return SchemaContext(text, hits, int((time.monotonic() - started) * 1000))

    async def aschema_for(self, question: str) -> SchemaContext:
        return await asyncio.to_thread(self.schema_for, question)

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close()


# 임베딩 모델(bge-m3 약 2GB)을 /agent/ask 와 /agent/runs 가 함께 쓰도록 프로세스에 하나만 둔다
_shared: KnowledgeContext | None = None
_lock = threading.Lock()


def get_knowledge_context(settings: Settings) -> KnowledgeContext | None:
    """KNOWLEDGE_MODE=rag 가 아니면 None."""
    global _shared
    if settings.knowledge_mode != "rag":
        return None
    with _lock:
        if _shared is None:
            pool = ConnectionPool(settings.dsn(read_only=False), min_size=1, max_size=4, open=False)
            pool.open(wait=False)
            retriever = KnowledgeRetriever(pool, build_embedding_client(settings))
            _shared = KnowledgeContext(
                retriever,
                parse_quota(settings.knowledge_context_quota),
                search_k=settings.knowledge_search_k,
                expand_sources=settings.knowledge_expand_sources,
                pool=pool,
            )
        return _shared


def close_knowledge_context() -> None:
    global _shared
    with _lock:
        if _shared is not None:
            _shared.close()
            _shared = None
