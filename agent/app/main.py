import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api import ask, runs
from app.auth import AuthUser, current_user
from app.config import get_settings
from app.knowledge.context import close_knowledge_context
from app.llm.health import log_local_server_status
from app.metrics import HttpMetricsMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.text_to_sql = None
    app.state.agent = None
    app.state.llm = None  # text_to_sql 과 agent 가 함께 쓴다
    app.state.executor = None
    app.state.run_store = None
    app.state.tracer = None
    await log_local_server_status(get_settings())
    yield
    # LLM 클라이언트와 Executor 는 두 파이프라인이 공유하므로 여기서 한 번만 닫는다
    if app.state.llm is not None:
        await app.state.llm.aclose()
    if app.state.executor is not None:
        await asyncio.to_thread(app.state.executor.close)
    if app.state.tracer is not None:
        await app.state.tracer.aclose()  # 큐에 남은 트레이스를 보낸다
    if app.state.run_store is not None:
        app.state.run_store.close()
    close_knowledge_context()


app = FastAPI(title="KlickLab Agent", lifespan=lifespan)

app.add_middleware(HttpMetricsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ask.router)
app.include_router(runs.router)
app.include_router(runs.conversations_router)


@app.get("/agent/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if get_settings().metrics_enabled:

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/agent/me")
def me(user: AuthUser = Depends(current_user)) -> dict[str, str]:
    return {"email": user.email, "sdkKey": user.sdk_key}
