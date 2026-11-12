import time
from uuid import uuid4

import jwt
import psycopg
import pytest
from fastapi.testclient import TestClient

from app.agent.loop import AgentEvent
from app.agent.store import RunTotals, build_run_store
from app.api.runs import get_agent, get_run_store
from app.config import Settings, get_settings
from app.main import app

SECRET = "test-secret-test-secret-test-secret-0123"
USER = "86867428-e167-4c55-a0c2-0c611ecf54a6"


def _headers(**claims) -> dict[str, str]:
    payload = {"userId": USER, "email": "a@b.c", "sdk_key": "key-1", "exp": time.time() + 60}
    payload.update(claims)
    return {"Authorization": f"Bearer {jwt.encode(payload, SECRET, algorithm='HS256')}"}


class FakeAgent:
    def __init__(self):
        self.calls = []

    async def run(self, question, *, sdk_key, user_id, conversation_id=None):
        self.calls.append((question, sdk_key, user_id, conversation_id))
        yield AgentEvent("started", {"runId": "r1"})
        yield AgentEvent("answer", {"summary": "575명입니다.", "findings": []})
        yield AgentEvent("done", {"runId": "r1", "status": "succeeded"})


class FakeStore:
    def __init__(self):
        self.feedback = None

    def list_runs(self, *, sdk_key, user_id, limit):
        return [{"id": "r1", "question": "q", "sdkKey": sdk_key, "limit": limit}]

    def get_run(self, run_id, *, sdk_key, user_id):
        return {"id": run_id, "steps": []} if run_id == "r1" else None

    def set_feedback(self, run_id, *, sdk_key, user_id, feedback, note):
        self.feedback = (run_id, feedback, note)
        return run_id == "r1"

    def list_conversations(self, *, sdk_key, user_id, limit):
        return [{"id": "c1", "title": "q", "runCount": 2, "sdkKey": sdk_key, "limit": limit}]

    def rename_conversation(self, conversation_id, *, sdk_key, user_id, title):
        self.renamed = (conversation_id, title)
        return conversation_id == "c1"

    def delete_conversation(self, conversation_id, *, sdk_key, user_id):
        self.deleted = conversation_id
        return conversation_id == "c1"

    def get_conversation(self, conversation_id, *, sdk_key, user_id):
        return {"id": conversation_id, "runs": []} if conversation_id == "c1" else None


@pytest.fixture
def client():
    agent, store = FakeAgent(), FakeStore()
    app.dependency_overrides[get_settings] = lambda: Settings(jwt_secret=SECRET)
    app.dependency_overrides[get_agent] = lambda: agent
    app.dependency_overrides[get_run_store] = lambda: store
    yield TestClient(app), agent, store
    app.dependency_overrides.clear()


def test_create_run_streams_sse_events(client):
    http, agent, _ = client
    with http.stream(
        "POST", "/agent/runs", json={"question": " 어제 방문자 수는? "}, headers=_headers()
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())

    assert agent.calls == [("어제 방문자 수는?", "key-1", USER, None)]
    assert body.split("\n\n")[:3] == [
        'event: started\ndata: {"runId": "r1"}',
        'event: answer\ndata: {"summary": "575명입니다.", "findings": []}',
        'event: done\ndata: {"runId": "r1", "status": "succeeded"}',
    ]


def test_create_run_passes_conversation_id(client):
    http, agent, _ = client
    with http.stream(
        "POST",
        "/agent/runs",
        json={"question": "그럼 지난주는?", "conversationId": "c1"},
        headers=_headers(),
    ) as r:
        "".join(r.iter_text())
    assert agent.calls[0][3] == "c1"


def test_conversations_are_scoped_to_token(client):
    http, *_ = client
    listed = http.get("/agent/conversations?limit=5", headers=_headers()).json()
    assert listed == [{"id": "c1", "title": "q", "runCount": 2, "sdkKey": "key-1", "limit": 5}]
    assert http.get("/agent/conversations/c1", headers=_headers()).json() == {
        "id": "c1",
        "runs": [],
    }
    assert http.get("/agent/conversations/other", headers=_headers()).status_code == 404
    assert http.get("/agent/conversations").status_code == 401


def test_rename_and_delete_conversation(client):
    http, _, store = client
    ok = http.patch(
        "/agent/conversations/c1", json={"title": "  방문자   추이 "}, headers=_headers()
    )
    assert ok.status_code == 204 and store.renamed == ("c1", "방문자 추이")
    for bad in ({"title": ""}, {"title": "   "}, {"title": "x" * 101}):
        r = http.patch("/agent/conversations/c1", json=bad, headers=_headers())
        assert r.status_code == 422
    missing = http.patch("/agent/conversations/x", json={"title": "t"}, headers=_headers())
    assert missing.status_code == 404

    assert http.delete("/agent/conversations/c1", headers=_headers()).status_code == 204
    assert store.deleted == "c1"
    assert http.delete("/agent/conversations/x", headers=_headers()).status_code == 404
    assert http.delete("/agent/conversations/c1").status_code == 401


def test_runs_require_token(client):
    http, *_ = client
    assert http.post("/agent/runs", json={"question": "q"}).status_code == 401
    assert http.get("/agent/runs").status_code == 401


def test_create_run_validates_question(client):
    http, *_ = client
    assert http.post("/agent/runs", json={"question": ""}, headers=_headers()).status_code == 422


def test_list_and_detail_are_scoped_to_token(client):
    http, *_ = client
    listed = http.get("/agent/runs?limit=5", headers=_headers()).json()
    assert listed == [{"id": "r1", "question": "q", "sdkKey": "key-1", "limit": 5}]
    assert http.get("/agent/runs/r1", headers=_headers()).json() == {"id": "r1", "steps": []}
    assert http.get("/agent/runs/other", headers=_headers()).status_code == 404


def test_feedback(client):
    http, _, store = client
    r = http.post(
        "/agent/runs/r1/feedback", json={"feedback": -1, "note": "틀림"}, headers=_headers()
    )
    assert r.status_code == 204
    assert store.feedback == ("r1", -1, "틀림")
    bad = http.post("/agent/runs/r1/feedback", json={"feedback": 2}, headers=_headers())
    assert bad.status_code == 422
    missing = http.post("/agent/runs/x/feedback", json={"feedback": 1}, headers=_headers())
    assert missing.status_code == 404


# ---------------------------------------------------------------------------
# 로컬 DB(klicklab_agent 로그인 + V4)가 있을 때만 실행하는 실행 로그 저장 통합 테스트
# ---------------------------------------------------------------------------


@pytest.fixture
def store():
    dsn = Settings().dsn(read_only=False)
    try:
        psycopg.connect(dsn, connect_timeout=2).close()
    except psycopg.Error:
        pytest.skip("실행 로그 DB 연결 불가")
    s = build_run_store(dsn)
    yield s
    s.close()


def test_store_round_trip_and_scoping(store):
    # klicklab_agent 롤에는 DELETE 권한이 없어 테스트 행(sdk_key=test-store-key)이 남는다
    run_id = store.create_run(sdk_key="test-store-key", user_id=USER, question="테스트 질문")
    store.set_difficulty(run_id, "lookup")
    store.add_step(
        run_id,
        seq=1,
        tool="run_sql",
        input={"sql": "SELECT 1"},
        output={"rows": [[1]]},
        error=None,
        duration_ms=3,
    )
    store.finish_run(
        run_id,
        RunTotals("succeeded", "lookup", {"summary": "s"}, 1, 100, 20, 1500),
    )
    detail = store.get_run(run_id, sdk_key="test-store-key", user_id=USER)
    assert detail["status"] == "succeeded"
    assert detail["answer"] == {"summary": "s"}
    assert detail["inputTokens"] == 100
    assert detail["steps"][0]["output"] == {"rows": [[1]]}
    assert store.get_run(run_id, sdk_key="other-key", user_id=USER) is None
    assert store.get_run("not-a-uuid", sdk_key="test-store-key", user_id=USER) is None

    listed = store.list_runs(sdk_key="test-store-key", user_id=USER, limit=5)
    assert listed[0]["id"] == run_id
    assert store.set_feedback(run_id, sdk_key="test-store-key", user_id=USER, feedback=1, note=None)
    assert not store.set_feedback(run_id, sdk_key="other-key", user_id=USER, feedback=1, note=None)


def test_store_conversations(store):
    key = "test-store-key-conv"
    conv, history = store.resolve_conversation(sdk_key=key, user_id=USER, conversation_id=None)
    assert history == []

    def run(question, status=None, summary=None):
        run_id = store.create_run(
            sdk_key=key, user_id=USER, question=question, conversation_id=conv
        )
        if status:
            totals = RunTotals(status, "lookup", {"summary": summary}, 1, 1, 1, 1)
            store.finish_run(run_id, totals)
        return run_id

    first = run("어제 방문자 수는?", "succeeded", "575명")
    rejected = run("날씨?", "rejected", "범위 밖")
    second = run("그럼 그제는?")

    same, history = store.resolve_conversation(sdk_key=key, user_id=USER, conversation_id=conv)
    assert same == conv
    assert [(t.question, t.summary) for t in history] == [("어제 방문자 수는?", "575명")]

    # 남의 대화 id 나 잘못된 id 는 새 대화로 시작한다 (이력이 새지 않는다)
    other, leaked = store.resolve_conversation(
        sdk_key="other-key", user_id=USER, conversation_id=conv
    )
    assert other != conv and leaked == []
    assert store.resolve_conversation(sdk_key=key, user_id=USER, conversation_id="nope")[1] == []

    detail = store.get_conversation(conv, sdk_key=key, user_id=USER)
    assert [r["id"] for r in detail["runs"]] == [first, rejected, second]
    assert store.get_conversation(conv, sdk_key="other-key", user_id=USER) is None
    listed = [c for c in store.list_conversations(sdk_key=key, user_id=USER) if c["id"] == conv]
    assert listed[0]["title"] == "어제 방문자 수는?" and listed[0]["runCount"] == 3

    # 이름 변경은 내 대화에만 된다
    assert store.rename_conversation(conv, sdk_key=key, user_id=USER, title="방문자 추이")
    assert not store.rename_conversation(conv, sdk_key="other-key", user_id=USER, title="x")
    assert not store.rename_conversation(str(uuid4()), sdk_key=key, user_id=USER, title="x")
    listed = [c for c in store.list_conversations(sdk_key=key, user_id=USER) if c["id"] == conv]
    assert listed[0]["title"] == "방문자 추이"

    # 삭제는 내 대화만, 실행과 단계가 함께 사라진다
    assert not store.delete_conversation(conv, sdk_key="other-key", user_id=USER)
    assert store.delete_conversation(conv, sdk_key=key, user_id=USER)
    assert store.get_conversation(conv, sdk_key=key, user_id=USER) is None
    assert store.get_run(first, sdk_key=key, user_id=USER) is None
    assert not store.delete_conversation(conv, sdk_key=key, user_id=USER)
