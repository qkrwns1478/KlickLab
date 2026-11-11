"""평가 리포트 공통: 에이전트 실행 지표 집계, 파일 저장."""

import json
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.agent.text_to_sql import KST
from evals.agent_runner import AgentTrace

REPORTS = Path(__file__).parent / "reports"


@dataclass(frozen=True)
class Price:
    """USD / 100만 토큰. 무료 등급 공급자는 0 으로 두고 토큰 수만 본다."""

    input: float = 0.0
    output: float = 0.0

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens * self.input + completion_tokens * self.output) / 1_000_000


@dataclass
class RunMetrics:
    """에이전트 실행 한 번의 비용·과정 지표."""

    status: str = ""
    difficulty: str | None = None  # 승격 후 최종 난이도
    initial_difficulty: str | None = None  # 분류기 결과
    tool_calls: int = 0
    sql_attempts: int = 0
    sql_failures: int = 0
    first_sql_ok: bool | None = None
    corrections: int = 0
    llm_calls: int = 0
    format_errors: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    wait_ms: int = 0
    error: str | None = None

    @classmethod
    def of(cls, trace: AgentTrace) -> "RunMetrics":
        summary = trace.summary
        usage = summary.get("usage") or {}
        sql = trace.sql_stats()
        return cls(
            status=trace.status,
            difficulty=summary.get("difficulty"),
            initial_difficulty=trace.classified.get("difficulty"),
            tool_calls=summary.get("toolCalls", 0),
            sql_attempts=int(sql["attempts"] or 0),
            sql_failures=int(sql["failures"] or 0),
            first_sql_ok=sql["first_ok"],  # type: ignore[arg-type]
            corrections=int(sql["corrections"] or 0),
            llm_calls=summary.get("llmCalls", 0),
            format_errors=summary.get("formatErrors", 0),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            latency_ms=summary.get("latencyMs", 0),
            wait_ms=summary.get("rateLimitWaitMs", 0),
            error=trace.error,
        )


def _avg(values: list[float]) -> float:
    return round(statistics.mean(values), 1) if values else 0.0


FREE = Price()


def aggregate(metrics: list[RunMetrics], price: Price = FREE) -> dict[str, Any]:
    """전체 + 난이도별 평균 비용·지연·툴 호출, 예산 소진 비율, SQL 1회 성공률."""

    def summarize(ms: list[RunMetrics]) -> dict[str, Any]:
        first = [m.first_sql_ok for m in ms if m.first_sql_ok is not None]
        latencies = [m.latency_ms for m in ms]
        return {
            "n": len(ms),
            "tool_calls_avg": _avg([m.tool_calls for m in ms]),
            "llm_calls_avg": _avg([m.llm_calls for m in ms]),
            "prompt_tokens_avg": round(_avg([m.prompt_tokens for m in ms])),
            "completion_tokens_avg": round(_avg([m.completion_tokens for m in ms])),
            "cost_usd_avg": round(
                statistics.mean([price.cost(m.prompt_tokens, m.completion_tokens) for m in ms]), 6
            )
            if ms
            else 0.0,
            "latency_ms_avg": round(_avg(latencies)),
            "latency_ms_p50": round(statistics.median(latencies)) if latencies else 0,
            "wait_ms_avg": round(_avg([m.wait_ms for m in ms])),
            "budget_exhausted_rate": _rate([m.status == "budget_exhausted" for m in ms]),
            "failed_rate": _rate([m.status == "failed" for m in ms]),
            "first_sql_ok_rate": _rate(first) if first else None,
            "corrections_avg": _avg([m.corrections for m in ms]),
            "promoted": sum(
                1 for m in ms if m.initial_difficulty and m.difficulty != m.initial_difficulty
            ),
        }

    by_difficulty: dict[str, list[RunMetrics]] = {}
    for m in metrics:
        by_difficulty.setdefault(m.difficulty or "unknown", []).append(m)
    return {
        "overall": summarize(metrics),
        "by_difficulty": {d: summarize(ms) for d, ms in sorted(by_difficulty.items())},
    }


def _rate(flags: list[bool]) -> float:
    return round(sum(flags) / len(flags) * 100, 1) if flags else 0.0


def metrics_table(agg: dict[str, Any]) -> list[str]:
    """난이도별 비용·지연 Markdown 표."""
    lines = [
        "| 난이도 | n | 툴 호출 | LLM 호출 | 입력 토큰 | 출력 토큰 | 비용(USD) "
        "| 지연 평균/중앙값(ms) | 예산 소진 | SQL 1회 성공 | 자가 수정 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    rows = [*agg["by_difficulty"].items(), ("전체", agg["overall"])]
    for name, s in rows:
        first = "-" if s["first_sql_ok_rate"] is None else f"{s['first_sql_ok_rate']}%"
        lines.append(
            f"| {name} | {s['n']} | {s['tool_calls_avg']} | {s['llm_calls_avg']} "
            f"| {s['prompt_tokens_avg']:,} | {s['completion_tokens_avg']:,} | {s['cost_usd_avg']} "
            f"| {s['latency_ms_avg']:,} / {s['latency_ms_p50']:,} | {s['budget_exhausted_rate']}% "
            f"| {first} | {s['corrections_avg']} |"
        )
    return lines


def now_kst() -> datetime:
    return datetime.now(KST)


def write(
    name: str, payload: dict[str, Any], lines: list[str], out_dir: Path | None = None
) -> Path:
    """<stamp>-<name>.json / .md 로 저장하고 md 경로를 돌려준다. out_dir 기본값은 REPORTS."""
    out_dir = out_dir or REPORTS
    out_dir.mkdir(parents=True, exist_ok=True)
    started = payload.get("started_at")
    stamp = (datetime.fromisoformat(started) if started else now_kst()).strftime("%Y%m%d-%H%M")
    base = out_dir / f"{stamp}-{name}"
    base.with_name(base.name + ".json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8"
    )
    md = base.with_name(base.name + ".md")
    md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md


def _json_default(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return str(value)


def cell(text: Any) -> str:
    """Markdown 표 칸."""
    return str(text).replace("|", "\\|").replace("\n", " ")


def file_safe(model: str) -> str:
    return model.replace(".", "_").replace("/", "_")
