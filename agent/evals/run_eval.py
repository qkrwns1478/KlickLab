"""golden SQL 평가: 질문마다 SQL 을 1회 생성해 정답 SQL 과 실행 결과를 비교한다.

    cd agent
    .venv/Scripts/python -m evals.run_eval                      # 전체
    .venv/Scripts/python -m evals.run_eval --ids lookup-01 compare-02
    .venv/Scripts/python -m evals.run_eval --reasoning-effort low --label low
    .venv/Scripts/python -m evals.run_eval --knowledge rag      # 스키마 요약 대신 지식 베이스 검색

답변 생성 단계는 채점 대상이 아니므로 호출하지 않는다 (문항당 LLM 호출 1회).
결과는 evals/reports/ 에 Markdown 과 JSON 으로 남긴다.
"""

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from app.agent.text_to_sql import KST, TextToSQL, today_kst
from app.config import Settings
from app.knowledge.context import close_knowledge_context, get_knowledge_context
from app.llm import LLMError, build_llm_client
from app.sql.executor import SQLExecutionError, build_executor
from app.sql.guard import SQLRejected, guard
from evals.matching import compare

ROOT = Path(__file__).parent
DEMO_SDK_KEY = "klicklab-demo-sdk-key-0001"
MAX_ROWS = 1000


@dataclass
class ItemResult:
    id: str
    category: str
    question: str
    status: str  # match / mismatch / rejected / exec_error / no_sql / llm_error
    reason: str = ""
    sql: str | None = None
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    gold_rows: int = 0
    pred_rows: int | None = None
    knowledge: list[str] = field(default_factory=list)  # rag 모드에서 프롬프트에 넣은 문서
    retrieval_ms: int = 0


@dataclass
class Report:
    model: str
    reasoning_effort: str
    label: str
    started_at: str
    knowledge_mode: str = "prompt"
    knowledge_quota: str | None = None
    items: list[ItemResult] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        def rate(items: list[ItemResult]) -> float:
            return (
                round(sum(i.status == "match" for i in items) / len(items) * 100, 1)
                if items
                else 0.0
            )

        latencies = [i.latency_ms for i in self.items if i.status != "llm_error"]
        by_cat: dict[str, list[ItemResult]] = {}
        for i in self.items:
            by_cat.setdefault(i.category, []).append(i)
        statuses: dict[str, int] = {}
        for i in self.items:
            statuses[i.status] = statuses.get(i.status, 0) + 1
        n = len(self.items) or 1
        return {
            "total": len(self.items),
            "execution_accuracy": rate(self.items),
            "by_category": {
                c: {"n": len(v), "accuracy": rate(v)} for c, v in sorted(by_cat.items())
            },
            "statuses": statuses,
            "latency_ms_avg": round(statistics.mean(latencies)) if latencies else 0,
            "latency_ms_p50": round(statistics.median(latencies)) if latencies else 0,
            "latency_ms_max": max(latencies) if latencies else 0,
            "prompt_tokens_avg": round(sum(i.prompt_tokens for i in self.items) / n),
            "completion_tokens_avg": round(sum(i.completion_tokens for i in self.items) / n),
            "reasoning_tokens_avg": round(sum(i.reasoning_tokens for i in self.items) / n),
            "retrieval_ms_avg": round(sum(i.retrieval_ms for i in self.items) / n),
        }


async def evaluate(
    items: list[dict], settings: Settings, *, sdk_key: str, reasoning_effort: str, label: str
) -> Report:
    llm = build_llm_client(settings)
    executor = build_executor(
        settings.dsn(read_only=True), statement_timeout_ms=settings.sql_statement_timeout_ms
    )
    pipeline = TextToSQL(
        llm,
        executor,
        sql_params={
            "max_tokens": settings.llm_sql_max_tokens,
            "reasoning_effort": reasoning_effort,
        },
        knowledge=get_knowledge_context(settings),
    )
    rag = settings.knowledge_mode == "rag"
    report = Report(
        model=llm.model,
        reasoning_effort=reasoning_effort,
        label=label,
        started_at=datetime.now(KST).isoformat(timespec="seconds"),
        knowledge_mode=settings.knowledge_mode,
        knowledge_quota=settings.knowledge_context_quota if rag else None,
    )
    today = today_kst()
    try:
        for item in items:
            result = await _evaluate_one(item, pipeline, executor, sdk_key, today)
            report.items.append(result)
            print(
                f"[{result.status:>10}] {result.id:<11} {result.latency_ms:>6}ms  {result.reason}"
            )
    finally:
        await pipeline.aclose()
        close_knowledge_context()
    return report


async def _evaluate_one(item, pipeline: TextToSQL, executor, sdk_key, today) -> ItemResult:
    out = ItemResult(item["id"], item["category"], item["question"], status="mismatch")
    gold = await asyncio.to_thread(
        executor.execute, guard(item["sql"], max_rows=MAX_ROWS).sql, sdk_key, result_rows=MAX_ROWS
    )
    out.gold_rows = gold.row_count

    try:
        draft = await pipeline.generate_sql(item["question"], today=today)
    except LLMError as e:
        out.status, out.reason = "llm_error", str(e)[:200]
        return out
    out.sql = draft.sql
    out.latency_ms = draft.latency_ms
    out.prompt_tokens = draft.usage.prompt_tokens
    out.completion_tokens = draft.usage.completion_tokens
    out.reasoning_tokens = draft.usage.reasoning_tokens
    out.knowledge = draft.knowledge
    out.retrieval_ms = draft.retrieval_ms
    if draft.sql is None:
        out.status = "no_sql"
        out.reason = draft.no_sql_reason or ("출력 잘림" if draft.truncated else "SQL 없음")
        return out

    try:
        guarded = guard(draft.sql, max_rows=MAX_ROWS)
    except SQLRejected as e:
        out.status, out.reason = "rejected", e.reason
        return out
    try:
        pred = await asyncio.to_thread(executor.execute, guarded.sql, sdk_key, result_rows=MAX_ROWS)
    except SQLExecutionError as e:
        out.status, out.reason = "exec_error", e.message
        return out
    out.pred_rows = pred.row_count

    match = compare(gold.rows, pred.rows, order_matters=bool(item.get("order_matters")))
    out.status = "match" if match.ok else "mismatch"
    out.reason = match.reason
    return out


def write_report(report: Report, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromisoformat(report.started_at).strftime("%Y%m%d-%H%M")
    suffix = f"-{report.label}" if report.label else ""
    model = report.model.replace(".", "_").replace("/", "_")  # 파일명에 점이 여러 개 생기지 않도록
    mode = "-rag" if report.knowledge_mode == "rag" else ""
    base = out_dir / f"{stamp}-golden_sql-{model}-{report.reasoning_effort}{mode}{suffix}"

    summary = report.summary()
    payload = {**{k: v for k, v in asdict(report).items() if k != "items"}, "summary": summary}
    payload["items"] = [asdict(i) for i in report.items]
    base.with_name(base.name + ".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        f"# golden SQL 평가 — {report.model} (reasoning_effort={report.reasoning_effort})",
        "",
        f"- 실행: {report.started_at}" + (f" / {report.label}" if report.label else ""),
        f"- 스키마 컨텍스트: {report.knowledge_mode}"
        + (f" (할당량 {report.knowledge_quota})" if report.knowledge_quota else ""),
        f"- 실행 정확도: **{summary['execution_accuracy']}%** "
        f"({summary['statuses'].get('match', 0)}/{summary['total']})",
        "- 난이도별: "
        + ", ".join(f"{c} {v['accuracy']}% ({v['n']})" for c, v in summary["by_category"].items()),
        "- 상태: " + ", ".join(f"{k} {v}" for k, v in sorted(summary["statuses"].items())),
        f"- 생성 지연(ms): 평균 {summary['latency_ms_avg']}, 중앙값 {summary['latency_ms_p50']}, "
        f"최대 {summary['latency_ms_max']}",
        f"- 평균 토큰: 입력 {summary['prompt_tokens_avg']}, 출력 {summary['completion_tokens_avg']}"
        f" (추론 {summary['reasoning_tokens_avg']})",
        "",
        "| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for i in report.items:
        reason = i.reason.replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {i.id} | {i.status} | {i.latency_ms} | {i.completion_tokens} | {reason} |")
    failures = [i for i in report.items if i.status != "match"]
    if failures:
        lines += ["", "## 실패 문항", ""]
        for i in failures:
            lines += [f"### {i.id} — {i.status}", "", f"질문: {i.question}", ""]
            if i.reason:
                lines += [f"사유: {i.reason}", ""]
            if i.knowledge:
                lines += [f"넣은 문서: {', '.join(i.knowledge)}", ""]
            if i.sql:
                lines += ["```sql", i.sql, "```", ""]
    md = base.with_name(base.name + ".md")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dataset", type=Path, default=ROOT / "datasets" / "golden_sql.yaml")
    parser.add_argument("--ids", nargs="*", help="평가할 문항 id")
    parser.add_argument("--sdk-key", default=DEMO_SDK_KEY)
    parser.add_argument("--reasoning-effort", help="기본값: LLM_SQL_REASONING_EFFORT")
    parser.add_argument("--label", default="")
    parser.add_argument("--provider", help="LLM_PROVIDER 덮어쓰기 (exaone / groq)")
    parser.add_argument("--model", help="공급자 모델 id 덮어쓰기")
    parser.add_argument("--knowledge", choices=["prompt", "rag"], help="KNOWLEDGE_MODE 덮어쓰기")
    parser.add_argument("--quota", help="KNOWLEDGE_CONTEXT_QUOTA 덮어쓰기")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "reports")
    args = parser.parse_args(argv)

    settings = Settings()
    if args.provider:
        settings.llm_provider = args.provider
    if args.model:
        setattr(settings, f"{settings.llm_provider}_model", args.model)
    if args.knowledge:
        settings.knowledge_mode = args.knowledge
    if args.quota:
        settings.knowledge_context_quota = args.quota
    items = yaml.safe_load(args.dataset.read_text(encoding="utf-8"))
    if args.ids:
        items = [i for i in items if i["id"] in set(args.ids)]
    if not items:
        print("평가할 문항이 없습니다.", file=sys.stderr)
        return 1

    effort = args.reasoning_effort or settings.llm_sql_reasoning_effort
    report = asyncio.run(
        evaluate(items, settings, sdk_key=args.sdk_key, reasoning_effort=effort, label=args.label)
    )
    path = write_report(report, args.out_dir)
    summary = report.summary()
    print(f"\n실행 정확도 {summary['execution_accuracy']}% — {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
