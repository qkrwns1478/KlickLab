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
