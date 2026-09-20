"""Fixtures dos testes de integracao: usam Postgres de verdade, com o
schema aplicado pelas migrations do flyway (migrate/changelogs) --
nao um schema recriado a mao pelo teste. E a mesma logica do CI do
`phishing-quest-api` (issue #31 la, espelhada aqui pela #8): se uma
migration quebrar, e aqui que aparece, nao so em producao.

No CI (job `integration-tests`), o Postgres e um servico efemero e as
variaveis DB_* apontam para ele. Fora do CI, suba
`docker compose up -d phishforge-postgresql phishforge-flyway` antes
de rodar `pytest tests/integration`.

`db_connection`/`phishing_repository` sao para ler direto do banco (a
"consulta ao banco, nao so a resposta" que varios criterios de aceite
pedem). `client_com_postgres_real` sobe a app inteira via HTTP, com
LLM/reranker/base vetorial fakes mas Postgres real -- para os testes
que precisam validar o contrato HTTP E a persistencia juntos (#2, #3).
"""

import os

import httpx
import pytest_asyncio
from dependency_injector import providers

import main as main_module
from app.infra.database.connection import DatabaseConnection
from app.infra.database.repositories.cue_repository import CueRepository
from app.infra.database.repositories.evaluation_round_repository import EvaluationRoundRepository
from app.infra.database.repositories.expert_evaluation_repository import ExpertEvaluationRepository
from app.infra.database.repositories.expert_repository import ExpertRepository
from app.infra.database.repositories.generation_job_repository import GenerationJobRepository
from app.infra.database.repositories.phishing_repository import PhishingEmailRepository
from tests.fakes import (
    FakeEmbeddingClient,
    FakePromptNormalizer,
    FakeReRanker,
    FakeResponseGenerator,
    FakeVectorStore,
)

os.environ.setdefault("OPENAI_API_KEY", "sk-test-nao-usada-em-nenhuma-chamada-real")
# Issue #7: toda rota exige X-API-Key -- client_com_postgres_real
# manda o header por padrao, mesmo valor de tests/conftest.py.
TEST_API_KEY = "test-api-key-nao-usada-em-producao"
os.environ.setdefault("API_KEY", TEST_API_KEY)


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


@pytest_asyncio.fixture
async def cue_repository(db_connection):
    return CueRepository(db=db_connection)


@pytest_asyncio.fixture
async def expert_repository(db_connection):
    return ExpertRepository(db=db_connection)


@pytest_asyncio.fixture
async def evaluation_round_repository(db_connection):
    return EvaluationRoundRepository(db=db_connection)


@pytest_asyncio.fixture
async def expert_evaluation_repository(db_connection):
    return ExpertEvaluationRepository(db=db_connection)


@pytest_asyncio.fixture
async def generation_job_repository(db_connection):
    return GenerationJobRepository(db=db_connection)


TEST_EXPERT_JWT_SECRET = "segredo-jwt-de-teste-de-integracao-nao-usado-em-producao"


@pytest_asyncio.fixture
async def expert_client_real():
    """App com repositorios REAIS (Postgres) e o servico de auth com um
    segredo de teste, SEM `X-API-Key`: exercita o modulo de especialistas
    (issue #36) de ponta a ponta, inclusive a checagem de `revogado_em`
    no banco a cada request.
    """
    from app.domain.services.expert_auth_service import ExpertAuthService

    app = main_module.create_app()
    conexao = nova_conexao_real()
    app.container.db_connection.override(providers.Object(conexao))
    app.container.expert_auth_service.override(
        providers.Object(ExpertAuthService(TEST_EXPERT_JWT_SECRET, expires_hours=12))
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await conexao.close_pool()


def nova_conexao_real() -> DatabaseConnection:
    """Uma DatabaseConnection independente, com seu proprio pool --
    usada pelo teste de sobrevivencia a restart (#11b) para simular
    "outro processo" lendo o que um processo anterior escreveu, sem
    reusar nenhum estado em memoria do primeiro.
    """
    return DatabaseConnection(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        user=os.environ.get("DB_USER", "phishforge"),
        password=os.environ.get("DB_PASSWORD", "phishforge"),
        database=os.environ.get("DB_NAME", "phishforge"),
    )


@pytest_asyncio.fixture
async def client_com_postgres_real():
    """App com LLM/reranker/base vetorial fakes, mas phishing_service e
    db_connection REAIS -- para o INSERT ir de fato para o Postgres do
    job de integracao. Usa uma conexao PROPRIA, independente da do
    fixture `db_connection` acima -- ambas apontam para o mesmo banco,
    entao um teste pode escrever por aqui e ler pelo `phishing_repository`.
    """
    app = main_module.create_app()
    container = app.container

    real_db_connection = DatabaseConnection(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        user=os.environ.get("DB_USER", "phishforge"),
        password=os.environ.get("DB_PASSWORD", "phishforge"),
        database=os.environ.get("DB_NAME", "phishforge"),
    )

    container.db_connection.override(providers.Object(real_db_connection))
    container.prompt_normalizer.override(providers.Object(FakePromptNormalizer()))
    container.response_generator.override(providers.Object(FakeResponseGenerator()))
    container.reranker.override(providers.Object(FakeReRanker()))
    container.qdrant_store.override(providers.Object(FakeVectorStore()))
    # issue #11b: BatchGenerationWorker usa embedding_client_openai
    # (real) so para a dedup por similaridade de cosseno -- sem isto,
    # /generate/batch chamaria a OpenAI de verdade e falharia com 401.
    container.embedding_client_openai.override(providers.Object(FakeEmbeddingClient()))
    # generation_pipeline nao e overrideado direto: e composto a partir
    # dos quatro providers acima, entao resolve automaticamente com os
    # fakes (ver comentario em tests/conftest.py). phishing_service,
    # phishing_repository, generation_job_repository e
    # batch_generation_worker tambem NAO sao sobrescritos: o container
    # resolve as versoes reais, usando o db_connection real acima.

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", headers={"X-API-Key": TEST_API_KEY}
    ) as ac:
        yield ac

    await real_db_connection.close_pool()
