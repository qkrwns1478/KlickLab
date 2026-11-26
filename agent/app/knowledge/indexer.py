"""시맨틱 레이어 YAML → 임베딩 → agent_knowledge 동기화 (klicklab_agent 롤).

    cd agent
    .venv/Scripts/python -m app.knowledge.indexer            # 바뀐 문서만 다시 임베딩
    .venv/Scripts/python -m app.knowledge.indexer --force    # 전부 다시 임베딩
    .venv/Scripts/python -m app.knowledge.indexer --no-embedding   # 키워드 검색용 본문만

본문 해시(metadata.hash)와 임베딩 모델(metadata.embedding_model)이 같으면 다시 임베딩하지 않는다.
카탈로그에 없는 문서는 지운다.
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field

from psycopg_pool import ConnectionPool

from app.config import Settings
from app.knowledge.documents import KnowledgeDoc, load_catalog
from app.knowledge.retriever import vector_literal
from app.llm.embedding import EmbeddingClient, build_embedding_client


@dataclass
class SyncReport:
    inserted: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: int = 0
    deleted: list[str] = field(default_factory=list)
    embedded: int = 0
    embed_ms: int = 0


_UPSERT = """
INSERT INTO agent_knowledge (kind, name, content, metadata, embedding)
VALUES (%(kind)s, %(name)s, %(content)s, %(metadata)s::jsonb, %(embedding)s::vector)
ON CONFLICT (kind, name) DO UPDATE
SET content = EXCLUDED.content, metadata = EXCLUDED.metadata, embedding = EXCLUDED.embedding
"""


def sync_catalog(
    pool: ConnectionPool,
    embedder: EmbeddingClient | None,
    docs: list[KnowledgeDoc],
    *,
    force: bool = False,
) -> SyncReport:
    report = SyncReport()
    model = embedder.model if embedder else None
    with pool.connection() as conn:
        rows = conn.execute(
            "SELECT kind, name, metadata->>'hash', metadata->>'embedding_model', "
            "embedding IS NOT NULL FROM agent_knowledge"
        ).fetchall()
        existing = {(r[0], r[1]): (r[2], r[3], r[4]) for r in rows}

        pending: list[KnowledgeDoc] = []
        for doc in docs:
            current = existing.get(doc.key)
            if current is None or force:
                pending.append(doc)
                continue
            content_hash, embedded_with, has_vector = current
            if content_hash != doc.content_hash:
                pending.append(doc)
            elif embedder is not None and (not has_vector or embedded_with != model):
                pending.append(doc)
            else:
                report.unchanged += 1

        vectors: list[list[float] | None] = [None] * len(pending)
        if embedder is not None and pending:
            started = time.monotonic()
            vectors = list(embedder.embed([d.content for d in pending]))
            report.embed_ms = int((time.monotonic() - started) * 1000)
            report.embedded = len(pending)

        with conn.transaction():
            for doc, vector in zip(pending, vectors, strict=True):
                metadata = {
                    **doc.metadata,
                    "title": doc.title,
                    "hash": doc.content_hash,
                    "embedding_model": model if vector is not None else None,
                }
                conn.execute(
                    _UPSERT,
                    {
                        "kind": doc.kind,
                        "name": doc.name,
                        "content": doc.content,
                        "metadata": json.dumps(metadata, ensure_ascii=False),
                        "embedding": vector_literal(vector) if vector is not None else None,
                    },
                )
                label = f"{doc.kind}/{doc.name}"
                (report.updated if doc.key in existing else report.inserted).append(label)

            stale = set(existing) - {d.key for d in docs}
            for kind, name in sorted(stale):
                conn.execute(
                    "DELETE FROM agent_knowledge WHERE kind = %s AND name = %s", (kind, name)
                )
                report.deleted.append(f"{kind}/{name}")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="전부 다시 임베딩")
    parser.add_argument("--no-embedding", action="store_true", help="임베딩 없이 본문만 적재")
    args = parser.parse_args(argv)

    settings = Settings()
    if args.no_embedding:
        settings.embedding_provider = "none"
    docs = load_catalog()
    embedder = build_embedding_client(settings)
    with ConnectionPool(settings.dsn(read_only=False), min_size=1, max_size=1) as pool:
        report = sync_catalog(pool, embedder, docs, force=args.force)

    by_kind: dict[str, int] = {}
    for d in docs:
        by_kind[d.kind] = by_kind.get(d.kind, 0) + 1
    print(f"카탈로그 {len(docs)}건 " + ", ".join(f"{k} {v}" for k, v in by_kind.items()))
    print(
        f"추가 {len(report.inserted)} / 갱신 {len(report.updated)} / 유지 {report.unchanged} / "
        f"삭제 {len(report.deleted)} / 임베딩 {report.embedded}건 ({report.embed_ms}ms, "
        f"{embedder.model if embedder else '없음'})"
    )
    for label in report.deleted:
        print(f"  - 삭제 {label}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
