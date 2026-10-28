# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# `git` e necessario para a dependencia `tracing-lib` (vem de um repo
# git); `build-essential` cobre eventuais pacotes sem wheel pronto.
# Cache mounts do apt: os indices e .deb ficam num cache do BuildKit, em
# vez de re-baixados a cada build. Por isso o `rm -rf .../lists` sai --
# as listas vivem no cache, nao na camada da imagem.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git

# Install Poetry
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install poetry==2.1.1

# Copy dependency files first for better caching
COPY pyproject.toml poetry.lock* ./

# Configure Poetry to not create virtualenv inside container
RUN poetry config virtualenvs.create false

# Instala so as dependencias de producao (sem dev e sem o grupo
# opcional `evaluation`/RAGAS -- ver pyproject.toml). O cache do Poetry
# (wheels ja baixadas) persiste entre builds pelo mount do BuildKit:
# mesmo quando o lock muda, so o que mudou e re-baixado.
RUN --mount=type=cache,target=/root/.cache/pypoetry \
    --mount=type=cache,target=/root/.cache/pip \
    poetry install --no-interaction --no-ansi --no-root --only main

# Copy application code
COPY app/ ./app/
COPY main.py ./
COPY data/ ./data/

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
