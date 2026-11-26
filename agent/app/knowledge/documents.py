"""시맨틱 레이어 YAML(knowledge/catalog/*.yaml) → 검색·프롬프트용 문서.

문서 하나는 (kind, name) 으로 식별한다. content 는 임베딩·키워드 검색 대상이자
모델에게 보여 줄 본문이다.
"""

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

CATALOG_DIR = Path(__file__).parent / "catalog"

Kind = Literal["table", "metric", "example", "glossary"]
KINDS: tuple[Kind, ...] = ("table", "metric", "example", "glossary")
_FILES: dict[Kind, str] = {
    "table": "tables.yaml",
    "metric": "metrics.yaml",
    "example": "examples.yaml",
    "glossary": "glossary.yaml",
}


@dataclass(frozen=True)
class KnowledgeDoc:
    kind: Kind
    name: str
    title: str  # 한 줄 제목 (검색 결과 목록, 프롬프트의 테이블 목록)
    content: str
    metadata: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)

    @property
    def key(self) -> tuple[str, str]:
        return self.kind, self.name

    @property
    def content_hash(self) -> str:
        """본문이 바뀌었을 때만 다시 임베딩하기 위한 해시."""
        payload = json.dumps([self.title, self.content], ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


class CatalogError(ValueError):
    pass


def _lines(items: Any) -> list[str]:
    if not items:
        return []
    if isinstance(items, str):
        return [items.strip()]
    return [str(i).strip() for i in items]


def render_table(entry: dict[str, Any]) -> KnowledgeDoc:
    name = entry["name"]
    lines = [f"테이블 {name} — {entry['summary']}", f"grain: {entry['grain']}", "컬럼:"]
    columns = entry.get("columns") or {}
    lines += [f"- {col}: {desc}" for col, desc in columns.items()]
    notes = _lines(entry.get("notes"))
    if notes:
        lines += ["참고:"] + [f"- {n}" for n in notes]
    use_for = _lines(entry.get("use_for"))
    if use_for:
        lines.append("이런 질문에 쓴다: " + ", ".join(use_for))
    return KnowledgeDoc(
        "table",
        name,
        entry["summary"],
        "\n".join(lines),
        {"columns": [c.split()[0] for c in columns], "use_for": use_for},
    )


def render_metric(entry: dict[str, Any]) -> KnowledgeDoc:
    aliases = _lines(entry.get("aliases"))
    title = entry["title"]
    lines = [f"지표 {title}" + (f" (다른 이름: {', '.join(aliases)})" if aliases else "")]
    lines.append(f"정의: {entry['definition']}")
    lines.append(f"계산식: {str(entry['sql']).strip()}")
    lines.append(f"테이블: {entry['source_table']}")
    lines += [f"- {n}" for n in _lines(entry.get("notes"))]
    return KnowledgeDoc(
        "metric",
        entry["name"],
        title,
        "\n".join(lines),
        {"aliases": aliases, "source_table": entry["source_table"]},
    )


def render_glossary(entry: dict[str, Any]) -> KnowledgeDoc:
    aliases = _lines(entry.get("aliases"))
    title = entry["title"]
    lines = [f"용어 {title}" + (f" (관련 표현: {', '.join(aliases)})" if aliases else "")]
    lines.append(str(entry["content"]).strip())
    return KnowledgeDoc("glossary", entry["name"], title, "\n".join(lines), {"aliases": aliases})


def render_example(entry: dict[str, Any]) -> KnowledgeDoc:
    question = entry["question"]
    sql = str(entry["sql"]).strip()
    content = f"예시 질문: {question}\n```sql\n{sql}\n```"
    return KnowledgeDoc("example", entry["name"], question, content, {"sql": sql})


_RENDER = {
    "table": render_table,
    "metric": render_metric,
    "example": render_example,
    "glossary": render_glossary,
}


def load_catalog(directory: Path = CATALOG_DIR) -> list[KnowledgeDoc]:
    docs: list[KnowledgeDoc] = []
    seen: set[tuple[str, str]] = set()
    for kind in KINDS:
        path = directory / _FILES[kind]
        entries = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        if not isinstance(entries, list):
            raise CatalogError(f"{path.name}: 문서 목록이어야 합니다.")
        for entry in entries:
            try:
                doc = _RENDER[kind](entry)
            except (KeyError, TypeError) as e:
                raise CatalogError(f"{path.name}: 필수 항목 누락 {e} — {entry!r:.80}") from None
            if doc.key in seen:
                raise CatalogError(f"{path.name}: 이름이 중복됩니다 — {doc.name}")
            seen.add(doc.key)
            docs.append(doc)
    return docs


@lru_cache
def default_catalog() -> tuple[KnowledgeDoc, ...]:
    return tuple(load_catalog())
