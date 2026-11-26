import asyncio
import logging
import re
from typing import Any

from app.agent.tools import RunState, ToolOutcome, function_schema
from app.knowledge.documents import KINDS
from app.knowledge.retriever import KnowledgeRetriever

log = logging.getLogger(__name__)

NAME = "search_knowledge"

SCHEMA = function_schema(
    NAME,
    "지식 베이스에서 테이블 설명, 지표 정의·계산식, 용어·기간 표현, 예시 SQL 을 검색한다.",
    {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "찾을 내용 (예: 재방문율 계산, 결제 금액 컬럼)",
            },
            "kind": {
                "type": "string",
                "enum": list(KINDS),
                "description": "문서 종류를 좁힐 때만 (table / metric / example / glossary)",
            },
        },
        "required": ["query"],
    },
)


class SearchKnowledge:
    def __init__(self, retriever: KnowledgeRetriever, *, k: int = 4):
        self._retriever = retriever
        self._k = k

    async def __call__(self, state: RunState, args: dict[str, Any], seq: int) -> ToolOutcome:
        query = str(args.get("query") or "").strip()
        if not query:
            return ToolOutcome.fail("query 가 비어 있습니다.")
        kind = args.get("kind") or None
        if kind is not None and kind not in KINDS:
            return ToolOutcome.fail(f"kind 는 {', '.join(KINDS)} 중 하나입니다.")

        key = f"{kind or '*'}:{re.sub(r'\s+', ' ', query.lower())}"
        if key in state.search_cache:  # 같은 검색은 예산을 차감하지 않는다
            return ToolOutcome.fail(
                f"같은 검색을 이미 했다 (step {state.search_cache[key]}). 다른 표현으로 검색하라.",
                charged=False,
            )
        try:
            hits = await asyncio.to_thread(
                self._retriever.search, query, kinds=[kind] if kind else None, k=self._k
            )
        except Exception:
            log.exception("지식 베이스 검색 실패")
            return ToolOutcome.fail("지식 베이스 검색에 실패했다. 지금 가진 정보로 진행하라.")
        state.search_cache[key] = seq

        documents: list[dict[str, Any]] = []
        for hit in hits:
            doc_id = f"{hit.kind}/{hit.name}"
            if doc_id in state.knowledge_seen:  # 이미 보여 준 문서는 이름만 (토큰 절약)
                documents.append({"kind": hit.kind, "name": hit.name, "note": "앞에서 제공함"})
            else:
                documents.append(hit.for_model())
                state.knowledge_seen.add(doc_id)
        found = [f"{h.kind}/{h.name}" for h in hits]
        return ToolOutcome(
            for_model={"ok": True, "documents": documents},
            output={"query": query, "kind": kind, "documents": found},
        )
