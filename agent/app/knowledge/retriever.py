"""지식 베이스 하이브리드 검색.

세 신호의 순위를 Reciprocal Rank Fusion(Σ 1 / (k + rank))으로 합친다. 척도가 달라 순위만 쓴다.
  vector : pgvector 코사인 거리 (bge-m3)
  keyword: pg_trgm word_similarity × idf
  alias  : 지표·용어 문서의 별칭이 질문에 그대로 들어 있는지
문서가 수십 개라 모두 전체를 훑어도 비용이 작다.
"""

import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.knowledge.documents import KINDS, Kind
from app.llm.embedding import EmbeddingClient, EmbeddingError

log = logging.getLogger(__name__)

SearchMode = Literal["hybrid", "vector", "keyword"]

RRF_K = 60
CANDIDATES = 20  # 검색 방식별로 가져올 후보 수
MIN_TERM_SIMILARITY = 0.3  # 키워드 하나가 문서에 이 정도 이상 맞아야 점수에 넣는다

# 질문에 흔한 서술어·의문사. 키워드 점수에서 뺀다
_STOPWORDS = {
    "보여줘", "보여주세요", "알려줘", "알려주세요", "해줘", "해주세요", "비교해줘",
    "분석해줘", "찾아줘", "계산해줘", "얼마", "얼마야", "얼마나", "무엇", "뭐야",
    "어떻게", "어떤", "있어", "있나", "대한", "관련", "그리고", "중", "및", "몇",
    "기준", "수는", "수를",
}  # fmt: skip
# 단어 끝 조사. 3글자 이상 단어에서만 떼어 낸다 ("소스별은" → "소스")
_PARTICLES = re.compile(
    r"(별로|별|에서|으로|부터|까지|에게|이나|은|는|이|가|을|를|의|에|로|와|과|도)+$"
)
_TOKEN = re.compile(r"[0-9A-Za-z_가-힣/.%+-]+")


@dataclass
class Hit:
    kind: Kind
    name: str
    title: str
    content: str
    score: float
    vector_rank: int | None = None
    keyword_rank: int | None = None
    alias_rank: int | None = None

    def for_model(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "content": self.content}


def query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for token in _TOKEN.findall(query.lower()):
        token = token.strip("./%+-")
        if len(token) >= 3 and re.search(r"[가-힣]$", token):
            stripped = _PARTICLES.sub("", token)
            token = stripped if len(stripped) >= 2 else token
        if len(token) < 2 or token in _STOPWORDS:
            continue
        if token not in terms:
            terms.append(token)
    return terms


def parse_quota(spec: str) -> dict[Kind, int]:
    """'table:3,metric:2' → {'table': 3, 'metric': 2}"""
    quota: dict[Kind, int] = {}
    for part in spec.split(","):
        if not part.strip():
            continue
        kind, _, count = part.partition(":")
        kind = kind.strip()
        if kind not in KINDS or not count.strip().isdigit():
            raise ValueError(f"잘못된 지식 베이스 할당량입니다: {part!r}")
        quota[kind] = int(count)  # type: ignore[index]
    return quota


_VECTOR_SQL = """
SELECT kind, name, content, metadata->>'title' AS title,
       embedding <=> %(vector)s::vector AS distance
FROM agent_knowledge
WHERE embedding IS NOT NULL AND kind = ANY(%(kinds)s)
ORDER BY distance
LIMIT %(limit)s
"""

# 키워드 점수 = Σ word_similarity(단어, 문서) × idf(단어). '세션', '페이지'처럼 대부분의 문서에 있는
# 단어보다 '지난주', '이탈률'처럼 드문 단어가 순위를 정하게 한다. idf 는 전체 문서 기준으로 계산한다
_KEYWORD_SQL = """
WITH m AS (
    SELECT k.id, t.term, word_similarity(t.term, k.name || ' ' || k.content) AS ws
    FROM agent_knowledge k CROSS JOIN unnest(%(terms)s::text[]) AS t(term)
),
hit AS (SELECT * FROM m WHERE ws >= %(min_similarity)s),
idf AS (
    SELECT term, ln((SELECT count(*) FROM agent_knowledge)::float / count(*) + 1) AS w
    FROM hit GROUP BY term
),
scored AS (
    SELECT hit.id, sum(hit.ws * idf.w) AS score FROM hit JOIN idf USING (term) GROUP BY hit.id
)
SELECT k.kind, k.name, k.content, k.metadata->>'title' AS title, s.score
FROM scored s JOIN agent_knowledge k USING (id)
WHERE k.kind = ANY(%(kinds)s)
ORDER BY s.score DESC, k.name
LIMIT %(limit)s
"""

# 별칭 일치: 지표·용어 문서의 aliases 와 제목(괄호 앞)이 질문에 그대로 들어 있으면 후보로 올린다.
# 공백을 무시하고 비교하며, 더 긴 별칭이 맞은 문서가 앞선다 ('전환율' > '전환')
_ALIAS_SQL = """
SELECT kind, name, content, metadata->>'title' AS title, a.matched
FROM agent_knowledge,
LATERAL (
    SELECT max(length(alias)) AS matched
    FROM (
        SELECT jsonb_array_elements_text(coalesce(metadata->'aliases', '[]'::jsonb)) AS alias
        UNION ALL
        SELECT split_part(metadata->>'title', ' (', 1)
    ) x
    WHERE length(alias) >= 2 AND position(replace(lower(alias), ' ', '') IN %(query)s) > 0
) a
WHERE kind = ANY(%(kinds)s) AND a.matched IS NOT NULL
ORDER BY a.matched DESC, name
LIMIT %(limit)s
"""


class KnowledgeRetriever:
    def __init__(
        self,
        pool: ConnectionPool,
        embedder: EmbeddingClient | None,
        *,
        candidates: int = CANDIDATES,
        rrf_k: int = RRF_K,
    ):
        self._pool = pool
        self._embedder = embedder
        self._candidates = candidates
        self._rrf_k = rrf_k

    @property
    def has_vectors(self) -> bool:
        return self._embedder is not None

    def search(
        self,
        query: str,
        *,
        kinds: list[Kind] | tuple[Kind, ...] | None = None,
        k: int = 5,
        mode: SearchMode = "hybrid",
    ) -> list[Hit]:
        vector = self._query_vector(query, mode)
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            return self._search(cur, query, vector, list(kinds or KINDS), k, mode)

    def context(
        self, query: str, quota: dict[Kind, int], *, mode: SearchMode = "hybrid"
    ) -> list[Hit]:
        """질문 하나에 대해 종류별 할당량만큼 문서를 고른다 (시스템 프롬프트에 미리 넣을 문서).

        종류마다 따로 검색한다. 한 번에 검색해 나누면 문서가 많은 종류(테이블·지표)가 후보를 차지해
        기간 표현 같은 용어 문서가 밀려난다.
        """
        vector = self._query_vector(query, mode)
        picked: list[Hit] = []
        with self._pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            for kind, n in quota.items():
                if n > 0:
                    picked += self._search(cur, query, vector, [kind], n, mode)
        return picked

    def _query_vector(self, query: str, mode: SearchMode) -> list[float] | None:
        if mode == "keyword" or self._embedder is None:
            return None
        try:
            return self._embedder.embed([query])[0]
        except EmbeddingError:
            # 모델을 쓸 수 없으면(선택 의존성 미설치 등) 이후로는 키워드 검색만 한다
            log.exception("질의 임베딩 실패. 키워드 검색으로 전환한다.")
            self._embedder = None
            return None

    def _search(
        self,
        cur: Any,
        query: str,
        vector: list[float] | None,
        kinds: list[Kind],
        k: int,
        mode: SearchMode,
    ) -> list[Hit]:
        vector_rows: list[dict[str, Any]] = []
        keyword_rows: list[dict[str, Any]] = []
        if vector is not None:
            cur.execute(
                _VECTOR_SQL,
                {"vector": vector_literal(vector), "kinds": kinds, "limit": self._candidates},
            )
            vector_rows = cur.fetchall()
        terms = query_terms(query) if mode != "vector" else []
        if terms:
            cur.execute(
                _KEYWORD_SQL,
                {
                    "terms": terms,
                    "kinds": kinds,
                    "min_similarity": MIN_TERM_SIMILARITY,
                    "limit": self._candidates,
                },
            )
            keyword_rows = cur.fetchall()
        alias_rows: list[dict[str, Any]] = []
        if mode == "hybrid":
            cur.execute(
                _ALIAS_SQL,
                {
                    "query": re.sub(r"\s+", "", query.lower()),
                    "kinds": kinds,
                    "limit": self._candidates,
                },
            )
            alias_rows = cur.fetchall()
        return self._fuse(vector_rows, keyword_rows, alias_rows)[:k]

    def _fuse(
        self,
        vector_rows: list[dict[str, Any]],
        keyword_rows: list[dict[str, Any]],
        alias_rows: list[dict[str, Any]] | None = None,
    ) -> list[Hit]:
        hits: dict[tuple[str, str], Hit] = {}

        def add(rows: list[dict[str, Any]], attr: str) -> None:
            for rank, row in enumerate(rows, start=1):
                key = (row["kind"], row["name"])
                hit = hits.get(key)
                if hit is None:
                    hit = hits[key] = Hit(
                        row["kind"], row["name"], row["title"] or row["name"], row["content"], 0.0
                    )
                setattr(hit, attr, rank)
                hit.score += 1 / (self._rrf_k + rank)

        add(vector_rows, "vector_rank")
        add(keyword_rows, "keyword_rank")
        add(alias_rows or [], "alias_rank")
        return sorted(hits.values(), key=lambda h: (-h.score, h.kind, h.name))


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vector) + "]"


def format_hits(hits: list[Hit]) -> str:
    """시스템 프롬프트에 넣을 문서 묶음."""
    return "\n\n".join(f"### [{h.kind}] {h.name}\n{h.content}" for h in hits)
