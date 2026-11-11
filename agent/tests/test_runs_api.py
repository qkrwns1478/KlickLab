import time

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

    async def run(self, question, *, sdk_key, user_id):
        self.calls.append((question, sdk_key, user_id))
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

    assert agent.calls == [("어제 방문자 수는?", "key-1", USER)]
    assert body.split("\n\n")[:3] == [
        'event: started\ndata: {"runId": "r1"}',
        'event: answer\ndata: {"summary": "575명입니다.", "findings": []}',
        'event: done\ndata: {"runId": "r1", "status": "succeeded"}',
    ]


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
