"""지식 베이스 검색 평가 (LLM 호출 없음).

golden 문항마다 "풀이에 필요한 문서"가 질문 컨텍스트(종류별 할당량)에 들어오는지 본다.
    필요한 문서 = 정답 SQL 이 쓰는 테이블 + 문항의 knowledge 라벨(지표·용어)

    cd agent
    .venv/Scripts/python -m evals.run_retrieval_eval      # hybrid / vector / keyword 비교
    .venv/Scripts/python -m evals.run_retrieval_eval --quota table:2,metric:2,glossary:3,example:1
"""

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

import sqlglot
import yaml
from psycopg_pool import ConnectionPool
from sqlglot import exp

from app.agent.text_to_sql import KST
from app.config import Settings
from app.knowledge.retriever import KnowledgeRetriever, SearchMode, format_hits, parse_quota
from app.llm.embedding import build_embedding_client

ROOT = Path(__file__).parent
MODES: tuple[SearchMode, ...] = ("hybrid", "vector", "keyword")


def gold_tables(sql: str) -> set[str]:
    tree = sqlglot.parse_one(sql, dialect="postgres")
    ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}
    return {t.name for t in tree.find_all(exp.Table) if t.name not in ctes}


def expected_docs(item: dict) -> set[str]:
    docs = {f"table/{t}" for t in gold_tables(item["sql"])}
    return docs | set(item.get("knowledge") or [])


@dataclass
class ItemResult:
    id: str
    expected: list[str]
    retrieved: list[str]
    missing: list[str]
    recall: float
    context_chars: int


@dataclass
class ModeResult:
    mode: str
    items: list[ItemResult] = field(default_factory=list)
    latency_ms_avg: int = 0

    def summary(self) -> dict:
        n = len(self.items) or 1
        by_kind: dict[str, list[int]] = {}
        for i in self.items:
            for doc in i.expected:
                kind = doc.split("/")[0]
                by_kind.setdefault(kind, []).append(int(doc not in i.missing))
        return {
            "recall": round(sum(i.recall for i in self.items) / n * 100, 1),
            "all_found": sum(not i.missing for i in self.items),
            "by_kind": {k: round(sum(v) / len(v) * 100, 1) for k, v in sorted(by_kind.items())},
            "context_chars_avg": round(sum(i.context_chars for i in self.items) / n),
            "latency_ms_avg": self.latency_ms_avg,
        }


def evaluate(retriever: KnowledgeRetriever, items: list[dict], quota, mode: SearchMode):
    result = ModeResult(mode)
    elapsed = 0.0
    for item in items:
        expected = expected_docs(item)
        started = time.monotonic()
        hits = retriever.context(item["question"], quota, mode=mode)
        elapsed += time.monotonic() - started
        retrieved = [f"{h.kind}/{h.name}" for h in hits]
        missing = sorted(expected - set(retrieved))
        result.items.append(
            ItemResult(
                item["id"],
                sorted(expected),
                retrieved,
                missing,
                (len(expected) - len(missing)) / len(expected),
                len(format_hits(hits)),
            )
        )
    result.latency_ms_avg = round(elapsed / max(len(items), 1) * 1000)
    return result


def write_report(results: list[ModeResult], quota_spec: str, out_dir: Path, label: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(KST)
    base = out_dir / (f"{now:%Y%m%d-%H%M}-retrieval" + (f"-{label}" if label else ""))
    payload = {
        "started_at": now.isoformat(timespec="seconds"),
        "quota": quota_spec,
        "modes": [{"mode": r.mode, "summary": r.summary(), "items": [asdict(i) for i in r.items]}
                  for r in results],
    }  # fmt: skip
    base.with_name(base.name + ".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        f"# 지식 베이스 검색 평가 — 할당량 {quota_spec}",
        "",
        f"- 실행: {payload['started_at']}",
        "- 필요한 문서 = 정답 SQL 의 테이블 + 문항 knowledge 라벨(지표·용어)",
        "",
        "| 방식 | 재현율 | 전부 찾은 문항 | table | metric | glossary "
        "| 컨텍스트 평균(자) | 지연 평균(ms) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        s = r.summary()
        k = s["by_kind"]
        lines.append(
            f"| {r.mode} | {s['recall']}% | {s['all_found']}/{len(r.items)} | "
            f"{k.get('table', '-')}% | {k.get('metric', '-')}% | {k.get('glossary', '-')}% | "
            f"{s['context_chars_avg']} | {s['latency_ms_avg']} |"
        )
    for r in results:
        missed = [i for i in r.items if i.missing]
        if missed:
            lines += ["", f"## 놓친 문서 — {r.mode}", ""]
            lines += [f"- {i.id}: {', '.join(i.missing)}" for i in missed]
    md = base.with_name(base.name + ".md")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=ROOT / "datasets" / "golden_sql.yaml")
    parser.add_argument("--quota", help="기본값: KNOWLEDGE_CONTEXT_QUOTA")
    parser.add_argument("--modes", nargs="*", default=list(MODES), choices=MODES)
    parser.add_argument("--label", default="")
    parser.add_argument(
        "--min-recall", type=float, help="어느 방식이든 재현율(%%)이 이보다 낮으면 종료 코드 1"
    )
    parser.add_argument("--out-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args(argv)

    settings = Settings()
    quota_spec = args.quota or settings.knowledge_context_quota
    quota = parse_quota(quota_spec)
    items = yaml.safe_load(args.dataset.read_text(encoding="utf-8"))
    embedder = build_embedding_client(settings)
    with ConnectionPool(settings.dsn(read_only=False), min_size=1, max_size=1) as pool:
        retriever = KnowledgeRetriever(pool, embedder)
        retriever.search("warmup", k=1)  # 모델 로드 시간을 지연에서 뺀다
        results = [evaluate(retriever, items, quota, mode) for mode in args.modes]

    for r in results:
        s = r.summary()
        print(f"{r.mode:<8} 재현율 {s['recall']}%  전부 찾음 {s['all_found']}/{len(r.items)}  {s}")
    print(write_report(results, quota_spec, args.out_dir, args.label))
    low = [r.mode for r in results if args.min_recall and r.summary()["recall"] < args.min_recall]
    if low:
        print(f"재현율 기준 {args.min_recall}% 미달: {', '.join(low)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
