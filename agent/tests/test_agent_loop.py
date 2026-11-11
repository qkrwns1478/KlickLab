import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.agent.loop import AgentLoop, compact_history
from app.agent.store import RunTotals
from app.llm import ChatResult, LLMError, ToolCall, Usage
from app.sql.executor import QueryResult, SQLExecutionError

SQL_OK = "SELECT count(*) AS visitors FROM agg_daily_users WHERE summary_date = current_date - 1"
ROWS = QueryResult(["visitors"], [[575]], 1, False, 2)


def classify(difficulty: str, reason: str = "이유") -> ChatResult:
    content = json.dumps({"difficulty": difficulty, "reason": reason}, ensure_ascii=False)
    return ChatResult(content=content, usage=Usage(10, 2, 0))


def calls(*items: tuple[str, dict[str, Any]]) -> ChatResult:
    return ChatResult(
        content="",
        usage=Usage(100, 20, 10),
        tool_calls=[
            ToolCall(id=f"c{i}", name=name, arguments=json.dumps(args, ensure_ascii=False))
            for i, (name, args) in enumerate(items)
        ],
    )


def report(summary="어제 순 방문자는 575명입니다.", evidence=(1,)) -> ChatResult:
    return calls(
        (
            "submit_report",
            {
                "summary": summary,
                "findings": [{"claim": summary, "evidence": list(evidence)}] if evidence else [],
            },
        )
    )


@dataclass
class ScriptedLLM:
    replies: list
    model: str = "fake"
    requests: list = field(default_factory=list)

    async def chat(self, messages, *, tools=None, tool_choice=None, **params):
        self.requests.append(
            {
                "messages": json.loads(json.dumps(messages)),
                "tools": [t["function"]["name"] for t in tools or []],
                "tool_choice": tool_choice,
                "params": params,
            }
        )
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    async def aclose(self):
        pass


@dataclass
class FakeExecutor:
    results: list = field(default_factory=list)
    executed: list = field(default_factory=list)

    def execute(self, sql, sdk_key, **kwargs):
        self.executed.append((sql, sdk_key))
        item = self.results.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


@dataclass
class MemoryStore:
    runs: dict = field(default_factory=dict)
    steps: list = field(default_factory=list)
    fail: bool = False

    def create_run(self, *, sdk_key, user_id, question):
        if self.fail:
            raise RuntimeError("db down")
        self.runs["r1"] = {"sdk_key": sdk_key, "user_id": user_id, "question": question}
        return "r1"

    def set_difficulty(self, run_id, difficulty):
        self.runs[run_id]["difficulty"] = difficulty

    def add_step(self, run_id, **step):
        self.steps.append(step)

    def finish_run(self, run_id, totals: RunTotals):
        self.runs[run_id]["totals"] = totals


def make_agent(replies, results=(), store=None, **kwargs):
    llm = ScriptedLLM(list(replies))
    executor = FakeExecutor(list(results))
    store = store or MemoryStore()
    agent = AgentLoop(llm, executor, store, today=lambda: date(2026, 11, 11), **kwargs)
    return agent, llm, executor, store


async def collect(agent, question="어제 방문자 수는?"):
    return [e async for e in agent.run(question, sdk_key="key-1", user_id="u1")]


def by_type(events, type_):
    return [e.data for e in events if e.type == type_]


async def test_happy_path_runs_sql_and_submits_report_with_evidence():
    agent, llm, executor, store = make_agent(
        [classify("lookup"), calls(("run_sql", {"sql": SQL_OK, "purpose": "p"})), report()],
        [ROWS],
    )
    events = await collect(agent)

    assert [e.type for e in events] == [
        "started",
        "classified",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
        "answer",
        "done",
    ]
    assert executor.executed[0][1] == "key-1"
    answer = by_type(events, "answer")[0]
    assert answer["findings"] == [{"claim": "어제 순 방문자는 575명입니다.", "evidence": [1]}]
    assert answer["forced"] is False
    done = by_type(events, "done")[0]
    assert done["status"] == "succeeded"
    assert done["sqlRuns"] == 1

    # 도구 결과가 tool 메시지로 이어지고, 루프에서는 항상 도구를 고르게 한다
    second = llm.requests[2]
    assert second["tool_choice"] == "required"
    tool_msg = [m for m in second["messages"] if m["role"] == "tool"][-1]
    assert tool_msg["role"] == "tool" and json.loads(tool_msg["content"])["step_id"] == 1
    assert second["params"]["reasoning_effort"] == "medium"

    totals = store.runs["r1"]["totals"]
    assert totals.status == "succeeded"
    assert totals.difficulty == "lookup"
    assert totals.input_tokens == 10 + 100 + 100
    assert [s["tool"] for s in store.steps] == ["run_sql", "submit_report"]


async def test_lookup_hides_run_sql_after_last_sql():
    agent, llm, *_ = make_agent(
        [classify("lookup"), calls(("run_sql", {"sql": SQL_OK})), report()], [ROWS]
    )
    await collect(agent)
    assert "run_sql" in llm.requests[1]["tools"]
    assert "run_sql" not in llm.requests[2]["tools"]


async def test_self_corrects_after_sql_error():
    agent, llm, executor, _ = make_agent(
        [
            classify("compare"),
            calls(("run_sql", {"sql": "SELECT nope FROM agg_daily_users"})),
            calls(("run_sql", {"sql": SQL_OK})),
            report(evidence=(2,)),
        ],
        [SQLExecutionError("error", 'column "nope" does not exist'), ROWS],
    )
    events = await collect(agent)

    results = by_type(events, "tool_result")
    assert results[0]["error"] == 'column "nope" does not exist'
    assert by_type(events, "answer")[0]["findings"][0]["evidence"] == [2]
    assert by_type(events, "done")[0]["status"] == "succeeded"
    failed = json.loads(llm.requests[2]["messages"][-1]["content"])
    assert failed["ok"] is False and "nope" in failed["error"]


async def test_rejects_report_citing_unknown_step_then_accepts_fix():
    agent, llm, *_ = make_agent(
        [
            classify("lookup"),
            calls(("run_sql", {"sql": SQL_OK})),
            report(evidence=(5,)),
            report(evidence=(1,)),
        ],
        [ROWS],
    )
    events = await collect(agent)
    results = by_type(events, "tool_result")
    assert "성공한 run_sql step 이 아니다" in results[1]["error"]
    assert by_type(events, "answer")[0]["findings"][0]["evidence"] == [1]


async def test_forces_report_when_tool_budget_is_spent():
    replies = [classify("lookup")]
    replies += [calls(("describe_table", {"table_name": "agg_daily_users"}))] * 3
    replies += [report(summary="확인한 범위에서는 결론이 없습니다.", evidence=())]
    columns = QueryResult(["column_name", "data_type"], [["summary_date", "date"]], 1, False, 1)
    agent, llm, *_ = make_agent(replies, [columns, ROWS, ROWS, ROWS])
    events = await collect(agent)

    last = llm.requests[-1]
    assert last["tools"] == ["submit_report"]
    assert last["tool_choice"] == {"type": "function", "function": {"name": "submit_report"}}
    assert any("[예산 소진]" in (m.get("content") or "") for m in last["messages"])
    answer = by_type(events, "answer")[0]
    assert answer["forced"] is True
    assert by_type(events, "done")[0]["status"] == "budget_exhausted"


async def test_gives_up_with_server_summary_when_forced_report_never_arrives():
    replies = [classify("lookup")]
    replies += [calls(("describe_table", {"table_name": "nope"}))] * 3
    replies += [ChatResult(content="", usage=Usage(1, 1, 0))] * 2
    agent, *_ = make_agent(replies)
    events = await collect(agent)
    answer = by_type(events, "answer")[0]
    assert answer["forced"] is True and answer["findings"] == []
    assert by_type(events, "done")[0]["status"] == "budget_exhausted"


async def test_out_of_scope_is_rejected_without_tools():
    agent, llm, executor, store = make_agent([classify("out_of_scope", "데이터 삭제 요청입니다.")])
    events = await collect(agent, "users 테이블 삭제해줘")

    assert [e.type for e in events] == ["started", "classified", "answer", "done"]
    assert by_type(events, "answer")[0]["summary"] == "데이터 삭제 요청입니다."
    assert by_type(events, "done")[0]["status"] == "rejected"
    assert len(llm.requests) == 1
    assert store.runs["r1"]["totals"].status == "rejected"


async def test_retries_provider_tool_format_error():
    error = LLMError('LLM 응답 오류 400: {"code":"tool_use_failed"}', status=400)
    agent, llm, *_ = make_agent(
        [classify("lookup"), error, calls(("run_sql", {"sql": SQL_OK})), report()], [ROWS]
    )
    events = await collect(agent)
    done = by_type(events, "done")[0]
    assert done["status"] == "succeeded"
    assert done["formatErrors"] == 1
    assert "형식이 잘못" in llm.requests[2]["messages"][-1]["content"]


async def test_fails_after_repeated_tool_format_errors():
    error = LLMError("tool_use_failed", status=400)
    agent, *_ = make_agent([classify("lookup")] + [error] * 4)
    events = await collect(agent)
    assert by_type(events, "error")
    assert by_type(events, "done")[0]["status"] == "failed"


async def test_request_too_large_forces_report_with_compacted_history():
    too_large = LLMError("LLM 응답 오류 413: Request too large", status=413)
    agent, llm, *_ = make_agent(
        [classify("compare"), calls(("run_sql", {"sql": SQL_OK})), too_large, report()], [ROWS]
    )
    events = await collect(agent)
    assert llm.requests[-1]["tools"] == ["submit_report"]
    assert by_type(events, "done")[0]["status"] == "budget_exhausted"
    assert by_type(events, "answer")[0]["findings"]


async def test_nudges_then_forces_report_when_model_answers_without_tools():
    text = ChatResult(content="575명입니다.", usage=Usage(1, 1, 0))
    agent, llm, *_ = make_agent(
        [classify("lookup"), calls(("run_sql", {"sql": SQL_OK})), text, text, report()], [ROWS]
    )
    events = await collect(agent)
    assert "submit_report 도구로" in llm.requests[3]["messages"][-1]["content"]
    assert llm.requests[4]["tool_choice"]["function"]["name"] == "submit_report"
    assert by_type(events, "done")[0]["status"] == "succeeded"


async def test_promotion_adds_budget():
    agent, llm, *_ = make_agent(
        [
            classify("lookup"),
            calls(("request_more_budget", {"reason": "원인 분석"})),
            calls(("run_sql", {"sql": SQL_OK})),
            report(),
        ],
        [ROWS],
    )
    events = await collect(agent)
    assert "request_more_budget" in llm.requests[1]["tools"]
    assert "request_more_budget" not in llm.requests[2]["tools"]
    assert by_type(events, "done")[0]["difficulty"] == "compare"


async def test_reports_llm_failure():
    agent, *_ = make_agent([classify("lookup"), LLMError("boom", status=500)])
    events = await collect(agent)
    assert "boom" in by_type(events, "error")[0]["message"]
    assert by_type(events, "done")[0]["status"] == "failed"


async def test_runs_without_store_when_run_log_is_unavailable():
    agent, *_ = make_agent(
        [classify("lookup"), calls(("run_sql", {"sql": SQL_OK})), report()],
        [ROWS],
        store=MemoryStore(fail=True),
    )
    events = await collect(agent)
    assert by_type(events, "started")[0]["runId"]
    assert by_type(events, "done")[0]["status"] == "succeeded"


async def test_closing_stream_marks_run_failed():
    agent, _, _, store = make_agent(
        [classify("lookup"), calls(("run_sql", {"sql": SQL_OK})), report()], [ROWS]
    )
    stream = agent.run("q", sdk_key="key-1", user_id="u1")
    async for event in stream:
        if event.type == "tool_call":
            break
    await stream.aclose()
    assert store.runs["r1"]["totals"].status == "failed"


async def test_stops_input_growth_at_prompt_limit():
    agent, llm, *_ = make_agent(
        [classify("compare"), calls(("run_sql", {"sql": SQL_OK})), report()],
        [ROWS],
        max_prompt_tokens=10,  # 첫 호출부터 상한을 넘는다 → 바로 결론 강제
    )
    events = await collect(agent)
    assert llm.requests[1]["tools"] == ["submit_report"]
    assert by_type(events, "done")[0]["status"] == "budget_exhausted"


def _history(n: int) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": "s"}]
    for i in range(1, n + 1):
        sql = "SELECT " + "x, " * 100 + "1"
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"c{i}",
                        "type": "function",
                        "function": {"name": "run_sql", "arguments": json.dumps({"sql": sql})},
                    }
                ],
            }
        )
        content = {"ok": True, "step_id": i, "columns": ["v"], "rows": [[r] for r in range(10)]}
        messages.append({"role": "tool", "tool_call_id": f"c{i}", "content": json.dumps(content)})
    return messages


def _rows(message):
    return json.loads(message["content"]).get("rows")


def _sql(message):
    return json.loads(message["tool_calls"][0]["function"]["arguments"])["sql"]


def test_compact_history_levels():
    history = _history(3)
    tools = [m for m in history if m["role"] == "tool"]
    calls_ = [m for m in history if m["role"] == "assistant"]

    level0 = compact_history(history)
    assert len(_rows(level0[2])) == 5  # 가장 오래된 결과만 줄인다
    assert len(_rows(level0[4])) == 10 and len(_rows(level0[6])) == 10
    assert _sql(level0[1]) == _sql(calls_[0])

    level1 = compact_history(history, level=1)
    assert _rows(level1[2]) == [] and len(_rows(level1[4])) == 10
    assert _sql(level1[1]).endswith("...(생략)")
    assert _sql(level1[3]) == _sql(calls_[1])

    level2 = compact_history(history, level=2)
    assert _rows(level2[4]) == [] and len(_rows(level2[6])) == 10
    assert _sql(level2[3]).endswith("...(생략)")

    assert history[2] is tools[0] and len(_rows(history[2])) == 10  # 원본은 그대로
