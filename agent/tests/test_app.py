import time

import jwt
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app

SECRET = "test-secret-test-secret-test-secret-0123"


@pytest.fixture
def client():
    app.dependency_overrides[get_settings] = lambda: Settings(jwt_secret=SECRET)
    yield TestClient(app)
    app.dependency_overrides.clear()


def _token(**claims) -> str:
    payload = {"userId": "u1", "email": "a@b.c", "sdk_key": "key-1", "exp": time.time() + 60}
    payload.update(claims)
    return jwt.encode(payload, SECRET, algorithm="HS256")


def test_health(client):
    assert client.get("/agent/health").json() == {"status": "ok"}


def test_me_requires_token(client):
    assert client.get("/agent/me").status_code == 401


def test_me_returns_sdk_key_from_token(client):
    r = client.get("/agent/me", headers={"Authorization": f"Bearer {_token()}"})
    assert r.status_code == 200
    assert r.json() == {"email": "a@b.c", "sdkKey": "key-1"}


def test_rejects_wrong_signature(client):
    bad = jwt.encode({"sdk_key": "k"}, "x" * 40, algorithm="HS256")
    assert client.get("/agent/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_rejects_token_without_sdk_key(client):
    token = _token(sdk_key="")
    assert client.get("/agent/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


class _FakePipeline:
    def __init__(self):
        self.calls = []

    async def ask(self, question, sdk_key):
        from app.agent.text_to_sql import AskResult
        from app.llm import Usage
        from app.sql.executor import QueryResult

        self.calls.append((question, sdk_key))
        return AskResult(
            status="succeeded",
            question=question,
            sql="SELECT 1 AS one",
            result=QueryResult(["one"], [[1]], 1, False, 2),
            answer="1입니다.",
            usage=Usage(10, 5, 2),
            timings={"generate_ms": 1},
        )


@pytest.fixture
def pipeline():
    from app.api.ask import get_text_to_sql

    fake = _FakePipeline()
    app.dependency_overrides[get_text_to_sql] = lambda: fake
    yield fake


def test_ask_requires_token(client, pipeline):
    assert client.post("/agent/ask", json={"question": "q"}).status_code == 401


def test_ask_uses_sdk_key_from_token(client, pipeline):
    r = client.post(
        "/agent/ask",
        json={"question": "  어제 방문자 수는?  "},
        headers={"Authorization": f"Bearer {_token()}"},
    )
    assert r.status_code == 200
    assert pipeline.calls == [("어제 방문자 수는?", "key-1")]
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["result"] == {"columns": ["one"], "rows": [[1]], "rowCount": 1, "truncated": False}
    assert body["usage"] == {"promptTokens": 10, "completionTokens": 5, "reasoningTokens": 2}


def test_ask_validates_question(client, pipeline):
    headers = {"Authorization": f"Bearer {_token()}"}
    assert client.post("/agent/ask", json={"question": ""}, headers=headers).status_code == 422
    long = {"question": "x" * 501}
    assert client.post("/agent/ask", json=long, headers=headers).status_code == 422


def test_dsn_quotes_special_characters_in_values():
    from app.config import Settings

    dsn = Settings(db_ro_password=r"a b'c\d").dsn(read_only=True)
    assert r"password='a b\'c\\d'" in dsn
