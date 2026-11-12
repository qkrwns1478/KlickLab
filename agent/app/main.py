from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ask, runs
from app.auth import AuthUser, current_user
from app.config import get_settings
from app.knowledge.context import close_knowledge_context
from app.llm.health import log_local_server_status


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.text_to_sql = None
    app.state.agent = None
    app.state.run_store = None
    await log_local_server_status(get_settings())
    yield
    for name in ("text_to_sql", "agent"):
        component = getattr(app.state, name)
        if component is not None:
            await component.aclose()
    if app.state.run_store is not None:
        app.state.run_store.close()
    close_knowledge_context()


app = FastAPI(title="KlickLab Agent", lifespan=lifespan)

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


@app.get("/agent/me")
def me(user: AuthUser = Depends(current_user)) -> dict[str, str]:
    return {"email": user.email, "sdkKey": user.sdk_key}
