"""Phase 4 평가 도구: 평가셋 형식, 규칙·LLM 심사, 안전성 계층 판정, 에이전트 실행 지표."""

import json
import re
from dataclasses import dataclass, field

import pytest

from app.agent.loop import AgentEvent
from app.llm import ChatResult, Usage
from app.sql.executor import QueryResult, SQLExecutionError
from app.sql.guard import ALLOWED_TABLES, SQLRejected, guard
from evals import datasets
from evals.agent_runner import AgentTrace, CaptureStore
from evals.judges import (
    LLMJudge,
    answer_text,
    fact_found,
    judge_messages,
    parse_verdict,
    rule_judge,
)
from evals.report import Price, RunMetrics, aggregate
from evals.run_eval import main
from evals.safety import (
    blocked_at,
    check_agent,
    check_db,
    check_guard,
    numbers,
    parse_db_expectation,
)

GOLDEN = datasets.load(datasets.GOLDEN)
ANALYSIS = datasets.load(datasets.ANALYSIS)
SAFETY = datasets.load(datasets.SAFETY)


# --- 평가셋 형식 --------------------------------------------------------------


def test_dataset_sizes_meet_plan():
    assert len(GOLDEN) >= 40
    assert len(ANALYSIS) >= 10
    assert len(SAFETY) >= 15


def test_golden_items_are_well_formed():
    for item in GOLDEN:
        assert item["category"] in ("lookup", "compare"), item["id"]
        assert item["id"].startswith(item["category"]), item["id"]
        guard(item["sql"])  # 정답 SQL 도 guard 를 통과해야 한다
        assert "sdk_key" not in item["sql"], item["id"]  # 테넌트 조건은 RLS 가 건다


def test_golden_knowledge_labels_exist_in_catalog():
    from app.knowledge.documents import load_catalog

    names = {f"{d.kind}/{d.name}" for d in load_catalog()}
    for item in GOLDEN:
        for label in item.get("knowledge") or []:
            assert label in names, (item["id"], label)


def test_analysis_items_are_well_formed():
    for item in ANALYSIS:
        assert item["facts"], item["id"]
        assert 1 <= int(item.get("required", 1)) <= len(item["facts"]), item["id"]
        assert any(f.get("check_sql") for f in item["facts"]), item["id"]
        for fact in item["facts"]:
            assert fact["keywords"] and all(fact["keywords"]), (item["id"], fact["id"])
            if fact.get("check_sql"):
                guard(fact["check_sql"])
        placeholders = {
            name
            for fact in item["facts"]
            for group in fact["keywords"]
            for k in group
            for name in re.findall(r"\{(\w+)\}", str(k))
        }
        assert not placeholders or item.get("values_sql"), item["id"]


def test_analysis_questions_avoid_run_date_relative_days():
    # 시드 날짜와 실행 날짜가 다르면 "N일 전" 패턴이 하루씩 밀린다
    for item in ANALYSIS:
        assert not re.search(r"\d+\s*일\s*전", item["question"]), item["id"]


def test_safety_items_are_well_formed():
    kinds = {i["kind"] for i in SAFETY}
    assert {"write", "account", "tenant", "injection"} <= kinds
    for item in SAFETY:
        assert item["guard"] in ("rejected", "allowed"), item["id"]
        parse_db_expectation(item["db"])
        for pattern in [*(item.get("forbidden_sql") or []), *(item.get("forbidden_answer") or [])]:
            re.compile(pattern)


@pytest.mark.parametrize("item", SAFETY, ids=lambda i: i["id"])
def test_safety_guard_layer_matches_expectation(item):
    assert check_guard(item).ok, check_guard(item).detail


def test_ci_subsets_cover_each_dataset():
    assert len(datasets.select(GOLDEN, ci=True)) >= 8
    assert datasets.select(ANALYSIS, ci=True)
    assert {i["kind"] for i in datasets.select(SAFETY, ci=True)} >= {"write", "tenant"}


def test_select_by_ids_and_unknown_id():
    assert [i["id"] for i in datasets.select(GOLDEN, ids=["lookup-02"])] == ["lookup-02"]
    with pytest.raises(ValueError):
        datasets.select(GOLDEN, ids=["nope"])


def test_load_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "d.yaml"
    path.write_text("- id: a\n- id: a\n", encoding="utf-8")
    with pytest.raises(ValueError, match="중복"):
        datasets.load("d", path)


# --- 규칙 심사 ----------------------------------------------------------------

ANSWER = {
    "summary": "이번 주 참여도 하락은 nov_mega_sale 캠페인 종료 때문으로 보입니다.",
    "findings": [
        {"claim": "모바일에서 10월 26일 /checkout/success 도달이 0건이었다", "evidence": [2]},
        {"claim": "Instagram 이탈률이 71% 로 가장 높다", "evidence": [3]},
    ],
}


def test_answer_text_joins_summary_and_claims():
    text = answer_text(ANSWER)
    assert "nov_mega_sale" in text and "Instagram" in text
    assert answer_text(None) == ""


def test_fact_found_needs_one_keyword_from_every_group():
    text = answer_text(ANSWER)
    assert fact_found(text, {"keywords": [["instagram", "인스타그램"]]})  # 대소문자 무시
    assert fact_found(text, {"keywords": [["모바일"], ["checkout/success"]]})
    assert not fact_found(text, {"keywords": [["모바일"], ["youtube"]]})


def test_fact_found_ignores_spacing_and_fills_values():
    text = "결제 완료 단계에서 끊겼고 날짜는 10월 26일"
    assert fact_found(text, {"keywords": [["결제완료"]]})
    fact = {"keywords": [["{iso}", "{kr}"]]}
    assert fact_found(text, fact, {"iso": "2026-10-26", "kr": "10월 26일"})
    assert not fact_found(text, fact, {"iso": "2026-10-27", "kr": "10월 27일"})


def test_rule_judge_counts_required_facts():
    item = {
        "required": 2,
        "facts": [
            {"id": "campaign", "keywords": [["캠페인"]]},
            {"id": "youtube", "keywords": [["youtube"]]},
        ],
    }
    verdict = rule_judge(ANSWER, item)
    assert verdict.found == ["campaign"] and verdict.missing == ["youtube"]
    assert not verdict.passed
    assert verdict.coverage == 0.5
    item["required"] = 1
    assert rule_judge(ANSWER, item).passed


# --- LLM 심사 -----------------------------------------------------------------


@dataclass
class FakeLLM:
    content: str
    model: str = "judge"
    requests: list = field(default_factory=list)

    async def chat(self, messages, **params):
        self.requests.append((messages, params))
        return ChatResult(content=self.content, usage=Usage(100, 20, 0))

    async def aclose(self):
        pass


def test_judge_messages_include_claims_evidence_rows_and_facts():
    evidence = {
        2: {"output": {"sql": "SELECT 1", "columns": ["a"], "rows": [[i] for i in range(40)]}}
    }
    facts = [{"id": "outage", "description": "모바일 결제 장애"}]
    user = judge_messages("질문", ANSWER, evidence, facts)[1]["content"]
    assert "1. 모바일에서 10월 26일" in user and "(근거 step: [2])" in user
    assert "### step 2" in user and "SQL: SELECT 1" in user
    assert "[[0], [1]" in user and "[15]" not in user  # 근거 행은 앞 15행만
    assert "- outage: 모바일 결제 장애" in user


def test_parse_verdict_scores_and_ignores_unknown_facts():
    content = "결과:\n" + json.dumps(
        {
            "claims": [{"index": 1, "supported": True}, {"index": 2, "supported": False}],
            "facts": [{"id": "outage", "covered": True}, {"id": "other", "covered": True}],
            "comment": "대체로 맞다",
        }
    )
    verdict = parse_verdict(content, ["outage", "campaign"])
    assert verdict.grounded == 0.5
    assert verdict.facts == {"outage": True}
    assert verdict.fact_coverage == 1.0
    assert verdict.comment == "대체로 맞다"


def test_parse_verdict_errors():
    assert parse_verdict("판정 불가", []).error
    assert parse_verdict("{not json}", []).error
    assert parse_verdict('{"claims": []}', []).grounded is None


async def test_llm_judge_calls_model_once_and_skips_empty_answers():
    llm = FakeLLM('{"claims": [{"index": 1, "supported": true}], "facts": []}')
    judge = LLMJudge(llm, reasoning_effort="low")
    verdict = await judge.judge("q", ANSWER, {}, [])
    assert verdict.grounded == 1.0 and verdict.usage.prompt_tokens == 100
    assert llm.requests[0][1] == {"reasoning_effort": "low"}
    assert (await judge.judge("q", {"summary": "s", "findings": []}, {}, [])).error
    assert len(llm.requests) == 1


# --- 안전성 계층 --------------------------------------------------------------


@dataclass
class FakeExecutor:
    outcome: object
    calls: list = field(default_factory=list)

    def execute(self, sql, sdk_key, **kwargs):
        self.calls.append((sql, sdk_key))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _rows(*rows):
    return QueryResult(
        ["c"] * len(rows[0]) if rows else [], [list(r) for r in rows], len(rows), False, 1
    )


def test_parse_db_expectation():
    assert parse_db_expectation("error") == ("error", None)
    assert parse_db_expectation("skip") == ("skip", None)
    assert parse_db_expectation("max:2") == ("max", 2)
    with pytest.raises(ValueError):
        parse_db_expectation("maybe")


def test_numbers_ignores_text_and_bools():
    assert numbers([["a", 1, True, 2.5, None]]) == [1, 2.5]


def test_check_guard():
    item = {"attack_sql": "DELETE FROM events", "guard": "rejected"}
    assert check_guard(item).ok
    assert not check_guard({**item, "guard": "allowed"}).ok
    allowed = {"attack_sql": "SELECT count(*) FROM agg_daily_users", "guard": "allowed"}
    assert check_guard(allowed).ok


def test_check_db_error_expectation():
    item = {"attack_sql": "DELETE FROM x", "db": "error"}
    assert check_db(item, FakeExecutor(SQLExecutionError("permission", "denied"))).ok
    assert check_db(item, FakeExecutor(_rows((1,)))).ok is False


def test_check_db_max_expectation_runs_as_canary():
    item = {"attack_sql": "SELECT count(*) FROM t", "db": "max:2", "run_as": "canary"}
    executor = FakeExecutor(_rows(("klicklab-demo", 2)))
    assert check_db(item, executor).ok
    assert executor.calls[0][1] == datasets.CANARY_SDK_KEY
    assert check_db(item, FakeExecutor(_rows(("x", 33714)))).ok is False
    assert check_db(item, FakeExecutor(SQLExecutionError("error", "x"))).ok  # 실패도 유출 없음


def test_check_db_skip():
    assert check_db({"attack_sql": "x", "db": "skip", "reason": "r"}, FakeExecutor(None)).ok is None


def _event(type_, **data):
    return AgentEvent(type_, data)


def _sql_step(seq, sql, *, rows=None, error=None, db_error=False, cached=None):
    if cached is not None:
        output = {"cachedFrom": cached}
    elif error is None:
        output = {
            "sql": sql,
            "columns": ["v"],
            "rows": rows or [[1]],
            "rowCount": len(rows or [[1]]),
        }
    else:
        output = {"sql": sql} if db_error else None
    return {
        "seq": seq,
        "tool": "run_sql",
        "input": {"sql": sql},
        "output": output,
        "error": error,
        "duration_ms": 1,
    }


def _trace(steps, *, answer=None, difficulty="lookup", status="succeeded", error=None):
    events = [_event("started", runId="r"), _event("classified", difficulty=difficulty)]
    if error:
        events.append(_event("error", message=error))
    if answer is not None:
        events.append(_event("answer", **answer))
    events.append(
        _event(
            "done",
            status=status,
            difficulty=difficulty,
            toolCalls=len(steps),
            llmCalls=3,
            usage={"prompt_tokens": 1000, "completion_tokens": 200},
            latencyMs=1500,
        )
    )
    return AgentTrace("q", datasets.DEMO_SDK_KEY, events, steps)


def test_check_agent_flags_forbidden_sql_only_when_it_succeeded():
    item = {"db": "error", "forbidden_sql": [r"\busers\b"]}
    blocked = _trace(
        [_sql_step(1, "SELECT * FROM users", error="조회할 수 없는 테이블")], answer={}
    )
    assert check_agent(item, blocked).ok
    leaked = _trace([_sql_step(1, "SELECT * FROM users")], answer={})
    assert check_agent(item, leaked).ok is False


def test_check_agent_flags_canary_leak_and_forbidden_answer():
    item = {"db": "max:2", "run_as": "canary", "forbidden_answer": [r"\$2[aby]\$"]}
    ok = _trace([_sql_step(1, "SELECT count(*) FROM agg_daily_users", rows=[[2]])], answer={})
    assert check_agent(item, ok).ok
    leak = _trace([_sql_step(1, "SELECT count(*) FROM agg_daily_users", rows=[[33714]])], answer={})
    assert "상한 2 초과" in check_agent(item, leak).detail
    hashed = _trace([], answer={"summary": "해시는 $2a$10$abc", "findings": []})
    assert check_agent(item, hashed).ok is False


def test_check_agent_not_evaluated_on_llm_failure():
    assert check_agent({"db": "error"}, _trace([], error="LLM 호출 실패: 429")).ok is None


def test_blocked_at():
    assert blocked_at(_trace([], difficulty="out_of_scope")) == "router"
    rejected = _trace([_sql_step(1, "DELETE FROM events", error="SELECT 조회만")])
    assert blocked_at(rejected) == "guard"
    denied = _trace([_sql_step(1, "SELECT pg_sleep(9)", error="timeout", db_error=True)])
    assert blocked_at(denied) == "db"
    assert blocked_at(_trace([_sql_step(1, "SELECT 1")])) == "model"


# --- 에이전트 실행 지표 ---------------------------------------------------------


def test_trace_sql_stats_counts_self_corrections():
    steps = [
        _sql_step(1, "SELECT bad", error="컬럼 없음", db_error=True),
        _sql_step(2, "SELECT good"),
        _sql_step(3, "SELECT good", cached=2),
        _sql_step(4, "SELECT bad2", error="rejected"),
        _sql_step(5, "SELECT good2"),
    ]
    trace = _trace(
        steps, answer={"summary": "s", "findings": [{"claim": "c", "evidence": [5, 2, 9]}]}
    )
    assert trace.sql_stats() == {"attempts": 4, "failures": 2, "first_ok": False, "corrections": 2}
    assert [s["seq"] for s in trace.sql_steps(ok=True)] == [2, 5]
    assert [s["seq"] for s in trace.evidence_steps()] == [5, 2]  # 없는 step 9 는 무시


def test_run_metrics_and_aggregate_by_difficulty():
    lookup = RunMetrics.of(_trace([_sql_step(1, "SELECT 1")]))
    assert lookup.first_sql_ok and lookup.prompt_tokens == 1000 and lookup.latency_ms == 1500
    diagnose = RunMetrics(
        status="budget_exhausted",
        difficulty="diagnose",
        initial_difficulty="compare",
        prompt_tokens=9000,
        completion_tokens=1000,
        latency_ms=10_000,
    )
    agg = aggregate([lookup, diagnose], Price(input=1.0, output=5.0))
    assert agg["overall"]["n"] == 2
    assert agg["overall"]["budget_exhausted_rate"] == 50.0
    assert agg["overall"]["promoted"] == 1
    assert agg["by_difficulty"]["diagnose"]["cost_usd_avg"] == pytest.approx(0.014)
    assert agg["by_difficulty"]["lookup"]["first_sql_ok_rate"] == 100.0


def test_capture_store_keeps_steps_per_run():
    store = CaptureStore()
    run_id = store.create_run(sdk_key="k", user_id="u", question="q")
    store.add_step(run_id, seq=1, tool="run_sql", input={}, output=None, error="e", duration_ms=1)
    store.set_difficulty(run_id, "lookup")
    assert store.runs[run_id].steps[0]["error"] == "e"
    assert store.runs[run_id].difficulty == "lookup"


# --- CLI ----------------------------------------------------------------------


def test_cli_rejects_empty_selection(capsys):
    with pytest.raises(ValueError):
        main(["golden", "--ids", "nope"])


def test_cli_without_command_defaults_to_golden(monkeypatch):
    seen = {}

    async def fake_evaluate(items, settings, *, mode, reasoning_effort):
        seen.update(ids=[i["id"] for i in items], mode=mode)
        return []

    monkeypatch.setattr("evals.run_eval.evaluate_golden", fake_evaluate)
    monkeypatch.setattr(
        "evals.run_eval.golden_report",
        lambda *a, **k: ("p", {"execution_accuracy": 0, "llm_errors": 0}),
    )
    assert main(["--ids", "lookup-01"]) == 0
    assert seen == {"ids": ["lookup-01"], "mode": "single"}
    assert main(["golden", "--ids", "lookup-01", "--min-score", "50"]) == 1


def test_guard_whitelist_covers_tables_used_by_evals():
    for item in GOLDEN:
        assert guard(item["sql"]).tables <= ALLOWED_TABLES


def test_safety_attacks_marked_rejected_are_really_rejected():
    for item in SAFETY:
        if item["guard"] == "rejected":
            with pytest.raises(SQLRejected):
                guard(item["attack_sql"])


# --- golden loop 채점 ---------------------------------------------------------


@dataclass
class ScriptedAgent:
    """CaptureStore 에 step 을 남기고 정해진 이벤트를 내는 가짜 AgentLoop."""

    store: CaptureStore
    steps: list
    answer: dict

    async def run(self, question, *, sdk_key, user_id):
        run_id = self.store.create_run(sdk_key=sdk_key, user_id=user_id, question=question)
        yield AgentEvent("started", {"runId": run_id})
        yield AgentEvent("classified", {"difficulty": "lookup"})
        for step in self.steps:
            self.store.add_step(run_id, **step)
        yield AgentEvent("answer", self.answer)
        yield AgentEvent("done", {"status": "succeeded", "difficulty": "lookup", "usage": {}})


GOLD_ITEM = {"id": "lookup-x", "category": "lookup", "question": "q", "sql": "SELECT 1"}


async def _score(steps, answer, gold_rows):
    from evals.run_eval import _golden_loop

    store = CaptureStore()
    agent = ScriptedAgent(store, steps, answer)
    return await _golden_loop(GOLD_ITEM, agent, store, FakeExecutor(_rows(*gold_rows)))


async def test_golden_loop_scores_the_cited_step():
    steps = [_sql_step(1, "SELECT 575", rows=[[575]]), _sql_step(2, "SELECT 9", rows=[[9]])]
    answer = {"summary": "s", "findings": [{"claim": "c", "evidence": [1]}]}
    result = await _score(steps, answer, [(575,)])
    assert result.status == "match" and result.sql == "SELECT 575"
    assert result.any_step_match and result.metrics.sql_attempts == 2


async def test_golden_loop_uses_last_sql_without_evidence_and_reports_any_match():
    steps = [_sql_step(1, "SELECT 575", rows=[[575]]), _sql_step(2, "SELECT 9", rows=[[9]])]
    result = await _score(steps, {"summary": "s", "findings": []}, [(575,)])
    assert result.status == "mismatch" and result.sql == "SELECT 9"
    assert result.any_step_match is True


async def test_golden_loop_without_successful_sql():
    steps = [_sql_step(1, "DELETE FROM x", error="SELECT 조회만")]
    result = await _score(steps, {"summary": "s", "findings": []}, [(1,)])
    assert result.status == "no_sql"


def test_golden_accuracy_excludes_provider_errors():
    from evals.run_eval import GoldenResult, golden_summary

    rows = [
        GoldenResult("a", "lookup", "q", "match"),
        GoldenResult("b", "lookup", "q", "mismatch"),
        GoldenResult("c", "compare", "q", "llm_error"),
    ]
    summary = golden_summary(rows, "single", Price())
    assert summary["execution_accuracy"] == 50.0
    assert summary["evaluated"] == 2 and summary["llm_errors"] == 1
    assert summary["by_category"]["compare"] == {"n": 0, "accuracy": None}


# --- 재채점 -------------------------------------------------------------------


@dataclass
class QueueExecutor:
    results: list

    def execute(self, sql, sdk_key, **kwargs):
        return self.results.pop(0)


def test_rescore_item_flips_transposed_mismatch_and_skips_unrescorable():
    from evals.rescore import rescore_item

    item = {"id": "compare-08", "sql": "SELECT 1"}
    saved = {"status": "mismatch", "sql": "SELECT 1"}
    gold = QueryResult(["a", "b"], [[2775, 951]], 1, False, 1)
    pred = QueryResult(["p", "n"], [["recent", 2775], ["previous", 951]], 2, False, 1)
    update = rescore_item(item, saved, QueueExecutor([gold, pred]))
    assert update["status"] == "match" and update["transposed"]
    for status in ("llm_error", "rejected", "no_sql"):
        assert rescore_item(item, {"status": status, "sql": "SELECT 1"}, None) == {}
    assert rescore_item(item, {"status": "mismatch", "sql": None}, None) == {}
