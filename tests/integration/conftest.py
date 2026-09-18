"""Fixtures dos testes de integracao: usam Postgres de verdade, com o
schema aplicado pelas migrations do flyway (migrate/changelogs) --
nao um schema recriado a mao pelo teste. E a mesma logica do CI do
`phishing-quest-api` (issue #31 la, espelhada aqui pela #8): se uma
migration quebrar, e aqui que aparece, nao so em producao.

No CI (job `integration-tests`), o Postgres e um servico efemero e as
variaveis DB_* apontam para ele. Fora do CI, suba
`docker compose up -d phishforge-postgresql phishforge-flyway` antes
de rodar `pytest tests/integration`.

Estes testes NAO usam os fakes de tests/fakes.py -- a persistencia real
e exatamente o que estao testando.
"""

import os

import pytest_asyncio

from app.infra.database.connection import DatabaseConnection
from app.infra.database.repositories.phishing_repository import PhishingEmailRepository


@pytest_asyncio.fixture
async def db_connection():
    connection = DatabaseConnection(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        user=os.environ.get("DB_USER", "phishforge"),
        password=os.environ.get("DB_PASSWORD", "phishforge"),
        database=os.environ.get("DB_NAME", "phishforge"),
    )
    await connection.create_pool()
    yield connection
    await connection.close_pool()


@pytest_asyncio.fixture
async def phishing_repository(db_connection):
    return PhishingEmailRepository(db=db_connection)
