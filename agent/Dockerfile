# KlickLab 분석 에이전트 (FastAPI). 빌드 컨텍스트는 agent/ 이다.
#   docker build -t klicklab-agent agent
#
# 지식 베이스를 rag 모드(KNOWLEDGE_MODE=rag)로 쓰면서 로컬 임베딩(bge-m3)을 쓰려면 extra 를 넣는다.
# torch(CPU)와 모델 때문에 이미지가 수 GB 로 커지므로 기본은 뺀다 (이때는 EMBEDDING_PROVIDER=none).
#   docker build --build-arg WITH_EMBEDDING=true -t klicklab-agent agent

FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

ARG WITH_EMBEDDING=false
COPY pyproject.toml uv.lock ./
RUN if [ "$WITH_EMBEDDING" = "true" ]; then \
      uv sync --frozen --no-dev --extra embedding; \
    else \
      uv sync --frozen --no-dev; \
    fi

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/app/.cache/huggingface
WORKDIR /app

RUN useradd --system --uid 10001 --home-dir /app agent
COPY --from=builder --chown=agent:agent /app/.venv ./.venv
COPY --chown=agent:agent app ./app
USER agent

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/agent/health', timeout=2)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
