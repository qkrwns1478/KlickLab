from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ask
from app.auth import AuthUser, current_user
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.text_to_sql = None
    yield
    pipeline = app.state.text_to_sql
    if pipeline is not None:
        await pipeline.aclose()


app = FastAPI(title="KlickLab Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ask.router)


@app.get("/agent/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/agent/me")
def me(user: AuthUser = Depends(current_user)) -> dict[str, str]:
    return {"email": user.email, "sdkKey": user.sdk_key}
