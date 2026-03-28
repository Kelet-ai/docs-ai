FROM python:3.13-slim-bookworm AS base
RUN apt-get update -qy && apt-get install -qyy \
    -o APT::Install-Recommends=false \
    -o APT::Install-Suggests=false \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

FROM base AS builder
COPY --from=ghcr.io/astral-sh/uv:0.6.6 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /svc

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=./uv.lock,target=uv.lock \
    --mount=type=bind,source=./pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=./.python-version,target=.python-version \
    uv sync --frozen --no-dev --no-install-project

COPY . /svc

FROM base AS release
RUN groupadd -r svc && useradd -r -g svc svc
COPY --from=builder --chown=svc:svc /svc /svc

ENV PATH="/svc/.venv/bin:$PATH"
ENV PYTHONPATH="/svc/src:${PYTHONPATH:-}"

WORKDIR /svc
USER svc

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--proxy-headers"]
