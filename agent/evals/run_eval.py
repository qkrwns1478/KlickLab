"""평가 실행기 (Phase 4).

    cd agent
    .venv/Scripts/python -m evals.run_eval check               # LLM 없이: 평가셋 + 안전성(guard·DB)
    .venv/Scripts/python -m evals.run_eval golden              # Text-to-SQL 실행 정확도 (단일 턴)
    .venv/Scripts/python -m evals.run_eval golden --mode loop  # 같은 문항을 Tool Loop 로
    .venv/Scripts/python -m evals.run_eval analysis --judge    # 원인 분석: 규칙 + LLM-as-judge
    .venv/Scripts/python -m evals.run_eval safety --agent      # 안전성: 에이전트 전체까지
    .venv/Scripts/python -m evals.run_eval --ids lookup-01     # 명령 생략 = golden (Phase 1~3)

공통 옵션: --ids, --ci(PR 회귀용 축소 평가셋), --provider/--model, --knowledge prompt|rag,
--label, --min-score(점수가 이보다 낮으면 종료 코드 1).
결과는 evals/reports/ 에 Markdown 과 JSON 으로 남긴다.
"""

import argparse
import asyncio
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.agent.text_to_sql import TextToSQL, today_kst
from app.config import Settings
from app.knowledge.context import close_knowledge_context, get_knowledge_context
from app.llm import LLMError, build_llm_client
from app.sql.executor import SQLExecutionError, SQLExecutor, build_executor
from app.sql.guard import SQLRejected, guard
from evals import datasets, report
from evals.agent_runner import AgentTrace, CaptureStore, run_agent
from evals.judges import LLMJudge, rule_judge
from evals.matching import compare
from evals.report import Price, RunMetrics, cell
from evals.safety import SafetyResult, blocked_at, check_agent, check_db, check_guard

MAX_ROWS = 1000
COMMANDS = ("check", "golden", "analysis", "safety")


# ---------------------------------------------------------------------------
# 공통
# ---------------------------------------------------------------------------


def configure(args: argparse.Namespace) -> Settings:
    settings = Settings()
    if getattr(args, "provider", None):
        settings.llm_provider = args.provider
    if getattr(args, "model", None):
        setattr(settings, f"{settings.llm_provider}_model", args.model)
    if getattr(args, "knowledge", None):
        settings.knowledge_mode = args.knowledge
    if getattr(args, "quota", None):
        settings.knowledge_context_quota = args.quota
    return settings


def make_executor(settings: Settings, **kwargs: Any) -> SQLExecutor:
    return build_executor(
        settings.dsn(read_only=True),
        token_dsn=settings.dsn(read_only=False),
        statement_timeout_ms=settings.sql_statement_timeout_ms,
        **kwargs,
    )


def make_agent(settings: Settings) -> tuple[Any, CaptureStore]:
    from app.api.runs import build_agent  # FastAPI 라우터 모듈이라 필요할 때만 불러온다

    store = CaptureStore()
    return build_agent(settings, store), store


def run_gold(executor: SQLExecutor, sql: str, sdk_key: str):
    return executor.execute(guard(sql, max_rows=MAX_ROWS).sql, sdk_key, result_rows=MAX_ROWS)


def header(title: str, settings: Settings | None, started_at: str, label: str) -> list[str]:
    lines = [f"# {title}", "", f"- 실행: {started_at}" + (f" / {label}" if label else "")]
    if settings is not None:
        model = getattr(settings, f"{settings.llm_provider}_model")
        lines.append(
            f"- 모델: {settings.llm_provider} / {model}, 스키마 컨텍스트: {settings.knowledge_mode}"
            + (
                f" (할당량 {settings.knowledge_context_quota})"
                if settings.knowledge_mode == "rag"
                else ""
            )
        )
    return lines


def _pct(group: dict[str, Any]) -> str:
    accuracy = "-" if group["accuracy"] is None else f"{group['accuracy']}%"
    return f"{accuracy} ({group['n']})"


def _rate(flags: list[bool]) -> float:
    return round(sum(flags) / len(flags) * 100, 1) if flags else 0.0


# ---------------------------------------------------------------------------
# golden: Text-to-SQL 실행 정확도
# ---------------------------------------------------------------------------


@dataclass
class GoldenResult:
    id: str
    category: str
    question: str
    status: str  # match / mismatch / rejected / exec_error / no_sql / llm_error
    reason: str = ""
    sql: str | None = None
    beyond_summary: bool = False
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    gold_rows: int = 0
    pred_rows: int | None = None
    knowledge: list[str] = field(default_factory=list)  # rag 모드에서 프롬프트에 넣은 문서
    retrieval_ms: int = 0
    transposed: bool = False  # 정답의 열을 행으로 돌려줘서 통과 (evals/matching.py)
    any_step_match: bool | None = None  # loop: 실행한 SQL 중 하나라도 정답과 같았는가
    metrics: RunMetrics | None = None  # loop


def golden_summary(items: list[GoldenResult], mode: str, price: Price) -> dict[str, Any]:
    def rate(rs: list[GoldenResult]) -> float:
        # 공급자 오류(한도 초과 등)로 답을 받지 못한 문항은 정확도에서 빼고 따로 센다
        return _rate([r.status == "match" for r in rs if r.status != "llm_error"])

    def group(rs: list[GoldenResult]) -> dict[str, Any]:
        """n = 평가된 문항 수. 하나도 없으면 accuracy 는 None."""
        evaluated = [r for r in rs if r.status != "llm_error"]
        return {"n": len(evaluated), "accuracy": rate(evaluated) if evaluated else None}

    by_cat: dict[str, list[GoldenResult]] = {}
    statuses: dict[str, int] = {}
    for r in items:
        by_cat.setdefault(r.category, []).append(r)
        statuses[r.status] = statuses.get(r.status, 0) + 1
    latencies = [r.latency_ms for r in items if r.status != "llm_error"]
    n = len(items) or 1
    beyond = [r for r in items if r.beyond_summary]
    summary: dict[str, Any] = {
        "total": len(items),
        "execution_accuracy": rate(items),
        "evaluated": sum(r.status != "llm_error" for r in items),
        "transposed": sum(r.transposed for r in items),
        "llm_errors": sum(r.status == "llm_error" for r in items),
        "by_category": {c: group(v) for c, v in sorted(by_cat.items())},
        "beyond_summary": group(beyond),
        "statuses": statuses,
        "latency_ms_avg": round(statistics.mean(latencies)) if latencies else 0,
        "latency_ms_p50": round(statistics.median(latencies)) if latencies else 0,
        "latency_ms_max": max(latencies) if latencies else 0,
        "prompt_tokens_avg": round(sum(r.prompt_tokens for r in items) / n),
        "completion_tokens_avg": round(sum(r.completion_tokens for r in items) / n),
        "reasoning_tokens_avg": round(sum(r.reasoning_tokens for r in items) / n),
        "retrieval_ms_avg": round(sum(r.retrieval_ms for r in items) / n),
    }
    if mode == "loop":
        summary["any_step_accuracy"] = _rate([bool(r.any_step_match) for r in items])
        summary["agent"] = report.aggregate([r.metrics for r in items if r.metrics], price)
    return summary


async def evaluate_golden(
    items: list[dict], settings: Settings, *, mode: str, reasoning_effort: str
) -> list[GoldenResult]:
    executor = make_executor(settings)
    today = today_kst()
    results: list[GoldenResult] = []
    if mode == "single":
        pipeline = TextToSQL(
            build_llm_client(settings),
            executor,
            sql_params={
                "max_tokens": settings.llm_sql_max_tokens,
                "reasoning_effort": reasoning_effort,
            },
            knowledge=get_knowledge_context(settings),
        )
        run_one = lambda item: _golden_single(item, pipeline, executor, today)  # noqa: E731
        closer = pipeline.aclose
    else:
        agent, store = make_agent(settings)
        run_one = lambda item: _golden_loop(item, agent, store, executor)  # noqa: E731

        async def closer() -> None:
            await agent.aclose()
            executor.close()

    try:
        for item in items:
            result = await run_one(item)
            results.append(result)
            print(
                f"[{result.status:>10}] {result.id:<11} {result.latency_ms:>7}ms  {result.reason}"
            )
    finally:
        await closer()
        close_knowledge_context()
    return results


def _golden_base(item: dict) -> GoldenResult:
    return GoldenResult(
        item["id"],
        item["category"],
        item["question"],
        status="mismatch",
        beyond_summary=bool(item.get("beyond_summary")),
    )


async def _golden_single(item, pipeline: TextToSQL, executor, today) -> GoldenResult:
    out = _golden_base(item)
    gold = await asyncio.to_thread(run_gold, executor, item["sql"], datasets.DEMO_SDK_KEY)
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
        pred = await asyncio.to_thread(
            executor.execute, guarded.sql, datasets.DEMO_SDK_KEY, result_rows=MAX_ROWS
        )
    except SQLExecutionError as e:
        out.status, out.reason = "exec_error", e.message
        return out
    out.pred_rows = pred.row_count
    match = compare(gold.rows, pred.rows, order_matters=bool(item.get("order_matters")))
    out.status = "match" if match.ok else "mismatch"
    out.reason = match.reason
    out.transposed = match.transposed
    return out


async def _golden_loop(item, agent, store: CaptureStore, executor) -> GoldenResult:
    """답변이 근거로 인용한 SQL 결과(없으면 마지막 성공 SQL)를 정답과 비교한다."""
    out = _golden_base(item)
    gold = await asyncio.to_thread(run_gold, executor, item["sql"], datasets.DEMO_SDK_KEY)
    out.gold_rows = gold.row_count
    trace = await run_agent(agent, store, item["question"], sdk_key=datasets.DEMO_SDK_KEY)
    metrics = out.metrics = RunMetrics.of(trace)
    out.latency_ms = metrics.latency_ms
    out.prompt_tokens = metrics.prompt_tokens
    out.completion_tokens = metrics.completion_tokens
    out.knowledge = trace.summary.get("knowledge") or []

    ordered = bool(item.get("order_matters"))
    ok_steps = trace.sql_steps(ok=True)
    if not ok_steps:
        out.status = "llm_error" if trace.error else "no_sql"
        out.reason = trace.error or f"성공한 SQL 없음 ({trace.status})"
        return out
    candidates = trace.evidence_steps() or ok_steps[-1:]
    matches = [compare(gold.rows, s["output"]["rows"], order_matters=ordered) for s in candidates]
    best = next((i for i, m in enumerate(matches) if m.ok), 0)
    out.sql = str(candidates[best]["input"].get("sql"))
    out.pred_rows = candidates[best]["output"]["rowCount"]
    out.status = "match" if matches[best].ok else "mismatch"
    out.reason = matches[best].reason
    out.transposed = matches[best].transposed
    out.any_step_match = any(
        compare(gold.rows, s["output"]["rows"], order_matters=ordered).ok for s in ok_steps
    )
    return out


def golden_report(
    results: list[GoldenResult],
    settings: Settings,
    *,
    mode: str,
    effort: str,
    label: str,
    started_at: str,
    price: Price,
) -> tuple[Path, dict[str, Any]]:
    summary = golden_summary(results, mode, price)
    title = f"golden SQL 평가 ({'Tool Loop' if mode == 'loop' else f'단일 턴, effort={effort}'})"
    lines = header(title, settings, started_at, label)
    lines += [
        f"- 실행 정확도: **{summary['execution_accuracy']}%** "
        f"({summary['statuses'].get('match', 0)}/{summary['evaluated']})"
        + (
            f" — 공급자 오류로 평가 못 한 문항 {summary['llm_errors']}/{summary['total']}"
            if summary["llm_errors"]
            else ""
        ),
        "- 난이도별: "
        + ", ".join(f"{c} {_pct(v)}" for c, v in summary["by_category"].items())
        + f" / 스키마 요약 밖 지식 {_pct(summary['beyond_summary'])}",
        "- 상태: " + ", ".join(f"{k} {v}" for k, v in sorted(summary["statuses"].items())),
        *(
            [f"- 정답 중 전치 허용(두 기간을 행으로 반환)으로 통과: {summary['transposed']}문항"]
            if summary["transposed"]
            else []
        ),
        f"- 지연(ms): 평균 {summary['latency_ms_avg']}, 중앙값 {summary['latency_ms_p50']}, "
        f"최대 {summary['latency_ms_max']}",
        f"- 평균 토큰: 입력 {summary['prompt_tokens_avg']}, 출력 {summary['completion_tokens_avg']}"
        f" (추론 {summary['reasoning_tokens_avg']})",
    ]
    if mode == "loop":
        lines += [
            f"- 실행한 SQL 중 하나라도 정답: {summary['any_step_accuracy']}%",
            "",
            *report.metrics_table(summary["agent"]),
        ]
    lines += ["", "| id | 결과 | 지연(ms) | 출력 토큰 | 사유 |", "| --- | --- | --- | --- | --- |"]
    for r in results:
        lines.append(
            f"| {r.id} | {r.status} | {r.latency_ms} | {r.completion_tokens} | {cell(r.reason)} |"
        )
    failures = [r for r in results if r.status != "match"]
    if failures:
        lines += ["", "## 실패 문항", ""]
        for r in failures:
            lines += [f"### {r.id} — {r.status}", "", f"질문: {r.question}", ""]
            if r.reason:
                lines += [f"사유: {r.reason}", ""]
            if r.knowledge:
                lines += [f"넣은 문서: {', '.join(r.knowledge)}", ""]
            if r.sql:
                lines += ["```sql", r.sql, "```", ""]

    model = getattr(settings, f"{settings.llm_provider}_model")
    name = f"golden_sql-{report.file_safe(model)}-" + ("loop" if mode == "loop" else effort)
    name += ("-rag" if settings.knowledge_mode == "rag" else "") + (f"-{label}" if label else "")
    payload = {
        "kind": "golden",
        "mode": mode,
        "model": model,
        "reasoning_effort": effort,
        "label": label,
        "started_at": started_at,
        "knowledge_mode": settings.knowledge_mode,
        "knowledge_quota": settings.knowledge_context_quota
        if settings.knowledge_mode == "rag"
        else None,
        "summary": summary,
        "items": [asdict(r) for r in results],
    }
    return report.write(name, payload, lines), summary


# ---------------------------------------------------------------------------
# analysis: 원인 분석 (diagnose)
# ---------------------------------------------------------------------------


@dataclass
class AnalysisResult:
    id: str
    question: str
    passed: bool = False
    found: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    required: int = 1
    values: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    findings: int = 0
    dropped_findings: int = 0
    forced: bool = False
    judge_grounded: float | None = None
    judge_fact_coverage: float | None = None
    judge_comment: str = ""
    judge_error: str | None = None
    unsupported_claims: list[str] = field(default_factory=list)
    metrics: RunMetrics | None = None


def fact_values(item: dict, executor: SQLExecutor) -> dict[str, Any]:
    """values_sql 결과 한 행 → {컬럼: 값}. 없거나 행이 하나가 아니면 빈 dict."""
    if not item.get("values_sql"):
        return {}
    result = run_gold(executor, item["values_sql"], datasets.DEMO_SDK_KEY)
    if result.row_count != 1:
        return {}
    return dict(zip(result.columns, result.rows[0], strict=True))


async def evaluate_analysis(
    items: list[dict], settings: Settings, *, judge: LLMJudge | None
) -> list[AnalysisResult]:
    executor = make_executor(settings)
    agent, store = make_agent(settings)
    results: list[AnalysisResult] = []
    try:
        for item in items:
            out = AnalysisResult(item["id"], item["question"])
            out.values = await asyncio.to_thread(fact_values, item, executor)
            trace = await run_agent(agent, store, item["question"], sdk_key=datasets.DEMO_SDK_KEY)
            out.metrics = RunMetrics.of(trace)
            answer = trace.answer or {}
            out.summary = answer.get("summary", "")
            out.findings = len(answer.get("findings") or [])
            out.dropped_findings = answer.get("droppedFindings", 0)
            out.forced = bool(answer.get("forced"))
            verdict = rule_judge(answer, item, out.values)
            out.found, out.missing, out.required = verdict.found, verdict.missing, verdict.required
            out.passed = verdict.passed
            if judge is not None:
                await _judge(out, judge, item, trace)
            results.append(out)
            print(
                f"[{'pass' if out.passed else 'fail':>4}] {out.id:<8} {out.metrics.status:<16} "
                f"facts {len(out.found)}/{len(item['facts'])}  grounded {out.judge_grounded}"
            )
    finally:
        await agent.aclose()
        executor.close()
        close_knowledge_context()
        if judge is not None:
            await judge.aclose()
    return results


async def _judge(out: AnalysisResult, judge: LLMJudge, item: dict, trace: AgentTrace) -> None:
    evidence = {s["seq"]: s for s in trace.evidence_steps()}
    try:
        verdict = await judge.judge(item["question"], trace.answer, evidence, item["facts"])
    except LLMError as e:
        out.judge_error = str(e)[:200]
        return
    out.judge_grounded = verdict.grounded
    out.judge_fact_coverage = verdict.fact_coverage
    out.judge_comment = verdict.comment
    out.judge_error = verdict.error
    out.unsupported_claims = [
        f"{c.get('index')}: {c.get('reason', '')}" for c in verdict.claims if not c.get("supported")
    ]


def analysis_summary(results: list[AnalysisResult], price: Price) -> dict[str, Any]:
    n = len(results) or 1
    grounded = [r.judge_grounded for r in results if r.judge_grounded is not None]
    coverage = [r.judge_fact_coverage for r in results if r.judge_fact_coverage is not None]
    findings = sum(r.findings for r in results)
    return {
        "total": len(results),
        "pass_rate": _rate([r.passed for r in results]),
        "fact_coverage": round(
            sum(len(r.found) / max(len(r.found) + len(r.missing), 1) for r in results) / n * 100, 1
        ),
        "judge_grounded": round(statistics.mean(grounded) * 100, 1) if grounded else None,
        "judge_fact_coverage": round(statistics.mean(coverage) * 100, 1) if coverage else None,
        "judged": len(grounded),
        "findings_avg": round(findings / n, 1),
        "dropped_findings": sum(r.dropped_findings for r in results),
        "forced_answers": sum(r.forced for r in results),
        "agent": report.aggregate([r.metrics for r in results if r.metrics], price),
    }


def analysis_report(
    results: list[AnalysisResult],
    settings: Settings,
    *,
    judge_model: str | None,
    label: str,
    started_at: str,
    price: Price,
) -> tuple[Path, dict[str, Any]]:
    s = analysis_summary(results, price)
    lines = header("원인 분석 평가 (diagnose)", settings, started_at, label)
    lines += [
        f"- 통과(필요한 정답 사실 수 이상 언급): **{s['pass_rate']}%** "
        f"({sum(r.passed for r in results)}/{s['total']})",
        f"- 정답 사실 언급률(규칙): {s['fact_coverage']}%",
    ]
    if judge_model:
        lines += [
            f"- LLM-as-judge ({judge_model}): 근거 충실성 {s['judge_grounded']}%, "
            f"정답 사실 {s['judge_fact_coverage']}% (채점 {s['judged']}/{s['total']})",
        ]
    lines += [
        f"- 평균 주장 수 {s['findings_avg']}, 근거 검증에서 뺀 주장 {s['dropped_findings']}개, "
        f"예산 소진 후 강제 결론 {s['forced_answers']}건",
        "",
        *report.metrics_table(s["agent"]),
        "",
        "| id | 통과 | 상태 | 찾은 사실 | 놓친 사실 | 근거 충실성 | 지연(ms) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        grounded = "-" if r.judge_grounded is None else f"{r.judge_grounded * 100:.0f}%"
        lines.append(
            f"| {r.id} | {'O' if r.passed else 'X'} | {r.metrics.status if r.metrics else '-'} "
            f"| {', '.join(r.found) or '-'} | {', '.join(r.missing) or '-'} | {grounded} "
            f"| {r.metrics.latency_ms if r.metrics else 0:,} |"
        )
    lines += ["", "## 답변", ""]
    for r in results:
        lines += [
            f"### {r.id}",
            "",
            f"질문: {r.question}",
            "",
            f"> {cell(r.summary) or '(답변 없음)'}",
            "",
        ]
        if r.judge_comment:
            lines += [f"심사: {r.judge_comment}", ""]
        if r.unsupported_claims:
            lines += ["근거와 맞지 않는 주장:", *[f"- {c}" for c in r.unsupported_claims], ""]
    model = getattr(settings, f"{settings.llm_provider}_model")
    name = f"analysis-{report.file_safe(model)}" + (
        "-rag" if settings.knowledge_mode == "rag" else ""
    )
    name += f"-{label}" if label else ""
    payload = {
        "kind": "analysis",
        "model": model,
        "judge_model": judge_model,
        "label": label,
        "started_at": started_at,
        "knowledge_mode": settings.knowledge_mode,
        "summary": s,
        "items": [asdict(r) for r in results],
    }
    return report.write(name, payload, lines), s


# ---------------------------------------------------------------------------
# safety
# ---------------------------------------------------------------------------


def canary_rows(executor: SQLExecutor) -> int:
    return executor.execute("SELECT count(*) FROM agg_daily_users", datasets.CANARY_SDK_KEY).rows[
        0
    ][0]


async def evaluate_safety(
    items: list[dict], settings: Settings, *, with_agent: bool
) -> tuple[list[SafetyResult], int]:
    executor = make_executor(settings, max_plan_cost=settings.sql_max_plan_cost)
    agent = store = None
    if with_agent:
        agent, store = make_agent(settings)
    results: list[SafetyResult] = []
    try:
        canary = await asyncio.to_thread(canary_rows, executor)
        for item in items:
            result = SafetyResult(
                item["id"],
                item["kind"],
                guard=check_guard(item),
                db=await asyncio.to_thread(check_db, item, executor),
            )
            if agent is not None:
                trace = await run_agent(
                    agent, store, item["question"], sdk_key=datasets.sdk_key_for(item)
                )
                result.agent = check_agent(item, trace)
                result.blocked_at = blocked_at(trace)
                result.metrics = RunMetrics.of(trace)
                result.steps = [
                    {
                        "seq": s["seq"],
                        "tool": s["tool"],
                        "sql": (s["input"] or {}).get("sql"),
                        "error": s["error"],
                    }
                    for s in trace.sql_steps()
                ]
            results.append(result)
            agent_ok = result.agent.ok if result.agent else "-"
            print(
                f"[{'pass' if result.passed else 'FAIL':>4}] {result.id:<12} "
                f"guard={result.guard.ok} db={result.db.ok} agent={agent_ok} "
                f"{result.blocked_at or ''}"
            )
    finally:
        if agent is not None:
            await agent.aclose()
        executor.close()
        close_knowledge_context()
    return results, canary


def safety_summary(results: list[SafetyResult]) -> dict[str, Any]:
    def layer(name: str) -> dict[str, Any]:
        evaluated = [
            getattr(r, name)
            for r in results
            if getattr(r, name) and getattr(r, name).ok is not None
        ]
        return {"evaluated": len(evaluated), "pass_rate": _rate([lr.ok for lr in evaluated])}

    blocked: dict[str, int] = {}
    for r in results:
        if r.blocked_at:
            blocked[r.blocked_at] = blocked.get(r.blocked_at, 0) + 1
    return {
        "total": len(results),
        "pass_rate": _rate([r.passed for r in results]),
        "guard": layer("guard"),
        "db": layer("db"),
        "agent": layer("agent"),
        "blocked_at": blocked,
    }


def safety_report(
    results: list[SafetyResult],
    settings: Settings,
    *,
    canary: int,
    with_agent: bool,
    label: str,
    started_at: str,
) -> tuple[Path, dict[str, Any]]:
    s = safety_summary(results)
    lines = header("안전성 평가", settings if with_agent else None, started_at, label)
    lines += [
        f"- 통과: **{s['pass_rate']}%** ({sum(r.passed for r in results)}/{s['total']})",
        f"- 계층별: guard {s['guard']['pass_rate']}% ({s['guard']['evaluated']}), "
        f"DB(guard 우회 가정) {s['db']['pass_rate']}% ({s['db']['evaluated']})"
        + (
            f", 에이전트 {s['agent']['pass_rate']}% ({s['agent']['evaluated']})"
            if with_agent
            else ""
        ),
        f"- 공격 테넌트 자기 행: {canary}개"
        + (" (없음: 행 단위 우회 확인이 약해진다)" if canary == 0 else ""),
    ]
    if with_agent:
        lines.append(
            "- 에이전트에서 처음 막은 곳: "
            + ", ".join(f"{k} {v}" for k, v in sorted(s["blocked_at"].items()))
        )
    lines += [
        "",
        "| id | 종류 | 결과 | guard | DB | 에이전트 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        agent = (
            "-" if r.agent is None else f"{_mark(r.agent.ok)} {r.blocked_at} {cell(r.agent.detail)}"
        )
        lines.append(
            f"| {r.id} | {r.kind} | {'O' if r.passed else 'X'} "
            f"| {_mark(r.guard.ok)} {cell(r.guard.detail)} "
            f"| {_mark(r.db.ok)} {cell(r.db.detail)} | {agent} |"
        )
    name = "safety" + ("-agent" if with_agent else "") + (f"-{label}" if label else "")
    payload = {
        "kind": "safety",
        "with_agent": with_agent,
        "label": label,
        "started_at": started_at,
        "canary_rows": canary,
        "summary": s,
        "items": [asdict(r) for r in results],
    }
    return report.write(name, payload, lines), s


def _mark(ok: bool | None) -> str:
    return {True: "O", False: "X", None: "-"}[ok]


# ---------------------------------------------------------------------------
# check: LLM 없이 평가셋 자체를 확인한다 (CI 매 PR)
# ---------------------------------------------------------------------------


def run_check(settings: Settings) -> tuple[list[str], list[SafetyResult], int]:
    """(문제 목록, 안전성 결과, 공격 테넌트 행 수)."""
    problems: list[str] = []
    executor = make_executor(settings, max_plan_cost=settings.sql_max_plan_cost)
    try:
        for item in datasets.load(datasets.GOLDEN):
            try:
                result = run_gold(executor, item["sql"], datasets.DEMO_SDK_KEY)
            except (SQLRejected, SQLExecutionError) as e:
                problems.append(f"golden {item['id']}: 정답 SQL 실행 실패 — {e}")
                continue
            if result.row_count == 0:
                problems.append(
                    f"golden {item['id']}: 정답 결과가 비어 있다 (시드를 다시 만들어야 할 수 있다)"
                )

        for item in datasets.load(datasets.ANALYSIS):
            problems += _check_analysis_item(item, executor)

        safety, canary = [], canary_rows(executor)
        if canary == 0:
            problems.append("safety: 공격 테넌트 행이 없다 (agent/scripts/prepare_eval_db.sh)")
        for item in datasets.load(datasets.SAFETY):
            result = SafetyResult(
                item["id"], item["kind"], check_guard(item), check_db(item, executor)
            )
            safety.append(result)
            if not result.passed:
                problems.append(
                    f"safety {item['id']}: guard={result.guard.detail} / db={result.db.detail}"
                )
    finally:
        executor.close()
    return problems, safety, canary


def _check_analysis_item(item: dict, executor: SQLExecutor) -> list[str]:
    problems = []
    values: dict[str, Any] = {}
    if item.get("values_sql"):
        result = run_gold(executor, item["values_sql"], datasets.DEMO_SDK_KEY)
        if result.row_count != 1:
            problems.append(
                f"analysis {item['id']}: values_sql 결과가 1행이 아니다 ({result.row_count}행)"
            )
        else:
            values = dict(zip(result.columns, result.rows[0], strict=True))
    for fact in item["facts"]:
        for group in fact.get("keywords") or []:
            for keyword in group:
                for name in _placeholders(str(keyword)):
                    if name not in values:
                        problems.append(
                            f"analysis {item['id']}/{fact['id']}: 값이 없는 자리표시자 {{{name}}}"
                        )
        if fact.get("check_sql"):
            try:
                result = run_gold(executor, fact["check_sql"], datasets.DEMO_SDK_KEY)
            except (SQLRejected, SQLExecutionError) as e:
                problems.append(f"analysis {item['id']}/{fact['id']}: check_sql 실패 — {e}")
                continue
            if not (result.rows and result.rows[0] and result.rows[0][0] is True):
                problems.append(
                    f"analysis {item['id']}/{fact['id']}: "
                    "시드 패턴이 지금 데이터에서 성립하지 않는다"
                )
    if int(item.get("required", 1)) > len(item["facts"]):
        problems.append(f"analysis {item['id']}: required 가 사실 수보다 크다")
    return problems


def _placeholders(text: str) -> list[str]:
    import re

    return re.findall(r"\{(\w+)\}", text)


def check_report(
    problems: list[str], safety: list[SafetyResult], canary: int, started_at: str
) -> Path:
    s = safety_summary(safety)
    lines = [
        "# 평가셋 점검 (LLM 없음)",
        "",
        f"- 실행: {started_at}",
        f"- 결과: {'**통과**' if not problems else f'**문제 {len(problems)}건**'}",
        f"- 안전성(guard·DB 계층): {s['pass_rate']}% "
        f"({sum(r.passed for r in safety)}/{s['total']}), 공격 테넌트 자기 행 {canary}개",
    ]
    if problems:
        lines += ["", "## 문제", "", *[f"- {p}" for p in problems]]
    lines += ["", "| id | guard | DB |", "| --- | --- | --- |"]
    lines += [
        f"| {r.id} | {_mark(r.guard.ok)} {cell(r.guard.detail)} "
        f"| {_mark(r.db.ok)} {cell(r.db.detail)} |"
        for r in safety
    ]
    payload = {
        "kind": "check",
        "started_at": started_at,
        "problems": problems,
        "canary_rows": canary,
        "safety": [asdict(r) for r in safety],
    }
    return report.write("check", payload, lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--ids", nargs="*", help="평가할 문항 id")
    common.add_argument("--ci", action="store_true", help="PR 회귀용 축소 평가셋 (ci: true 문항)")
    common.add_argument("--label", default="")
    common.add_argument("--provider", help="LLM_PROVIDER 덮어쓰기 (exaone / groq)")
    common.add_argument("--model", help="공급자 모델 id 덮어쓰기")
    common.add_argument("--knowledge", choices=["prompt", "rag"], help="KNOWLEDGE_MODE 덮어쓰기")
    common.add_argument("--quota", help="KNOWLEDGE_CONTEXT_QUOTA 덮어쓰기")
    common.add_argument("--min-score", type=float, help="점수(%%)가 이보다 낮으면 종료 코드 1")
    common.add_argument(
        "--price", nargs=2, type=float, metavar=("IN", "OUT"), help="USD / 100만 토큰 (비용 계산)"
    )
    common.add_argument("--out-dir", type=Path, default=report.REPORTS)

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="LLM 없이 평가셋·안전성(guard·DB) 확인", parents=[common])
    golden = sub.add_parser("golden", help="Text-to-SQL 실행 정확도", parents=[common])
    golden.add_argument("--mode", choices=["single", "loop"], default="single")
    golden.add_argument("--reasoning-effort", help="single 모드. 기본값: LLM_SQL_REASONING_EFFORT")
    analysis = sub.add_parser("analysis", help="원인 분석 (diagnose)", parents=[common])
    analysis.add_argument("--judge", action="store_true", help="LLM-as-judge 채점")
    analysis.add_argument("--judge-provider", help="심사 모델 공급자 (기본: 에이전트와 같음)")
    analysis.add_argument("--judge-model")
    analysis.add_argument("--judge-effort", default="low")
    safety = sub.add_parser("safety", help="안전성", parents=[common])
    safety.add_argument("--agent", action="store_true", help="에이전트 전체로도 실행 (LLM 필요)")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] not in (*COMMANDS, "-h", "--help"):
        argv.insert(0, "golden")  # Phase 1~3 사용법 (명령 없이 golden)
    args = build_parser().parse_args(argv)
    settings = configure(args)
    report.REPORTS = args.out_dir
    started_at = report.now_kst().isoformat(timespec="seconds")
    price = Price(*args.price) if args.price else Price()

    if args.command == "check":
        problems, safety, canary = run_check(settings)
        path = check_report(problems, safety, canary, started_at)
        for p in problems:
            print(f"- {p}")
        print(f"\n평가셋 점검: {'통과' if not problems else f'문제 {len(problems)}건'} — {path}")
        return 1 if problems else 0

    name = {"golden": datasets.GOLDEN, "analysis": datasets.ANALYSIS, "safety": datasets.SAFETY}
    items = datasets.select(datasets.load(name[args.command]), ids=args.ids, ci=args.ci)
    if not items:
        print("평가할 문항이 없습니다.", file=sys.stderr)
        return 1

    if args.command == "golden":
        effort = args.reasoning_effort or settings.llm_sql_reasoning_effort
        results = asyncio.run(
            evaluate_golden(items, settings, mode=args.mode, reasoning_effort=effort)
        )
        path, summary = golden_report(
            results, settings, mode=args.mode, effort=effort, label=args.label,
            started_at=started_at, price=price,
        )  # fmt: skip
        score, title = summary["execution_accuracy"], "실행 정확도"
        if summary["llm_errors"]:
            print(f"공급자 오류로 평가 못 한 문항 {summary['llm_errors']}개", file=sys.stderr)
            if args.min_score is not None:
                print(f"{title} {score}% — {path}")
                return 1  # 회귀 판정을 할 수 없다
    elif args.command == "analysis":
        judge = None
        if args.judge:
            judge_settings = settings.model_copy()
            if args.judge_provider:
                judge_settings.llm_provider = args.judge_provider
            if args.judge_model:
                setattr(judge_settings, f"{judge_settings.llm_provider}_model", args.judge_model)
            judge = LLMJudge(
                build_llm_client(judge_settings),
                max_tokens=settings.llm_sql_max_tokens,
                reasoning_effort=args.judge_effort,
            )
        judge_model = judge.model if judge else None
        results = asyncio.run(evaluate_analysis(items, settings, judge=judge))
        path, summary = analysis_report(
            results, settings, judge_model=judge_model, label=args.label,
            started_at=started_at, price=price,
        )  # fmt: skip
        score, title = summary["pass_rate"], "통과율"
    else:
        results, canary = asyncio.run(evaluate_safety(items, settings, with_agent=args.agent))
        path, summary = safety_report(
            results, settings, canary=canary, with_agent=args.agent, label=args.label,
            started_at=started_at,
        )  # fmt: skip
        score, title = summary["pass_rate"], "통과율"

    print(f"\n{title} {score}% — {path}")
    if args.min_score is not None and score < args.min_score:
        print(f"기준 {args.min_score}% 미달", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
