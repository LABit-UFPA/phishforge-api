"""Critério de aceite da issue #2, ao pé da letra: "valor válido -> 201/200
e nível persistido igual ao pedido (consultar o banco, não só a
resposta)".

Diferente do resto de tests/integration/ (que chama o repositório
direto), aqui sobe a app inteira via HTTP -- para exercitar a
validação do Pydantic de ponta a ponta -- mas com o LLM/reranker/
retriever substituídos por fakes (como em tests/unit): o único
componente real é o Postgres, porque é exatamente ele que este teste
audita. Nenhuma chamada paga.
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test-nao-usada-em-nenhuma-chamada-real")

import httpx
import pytest
import pytest_asyncio
from dependency_injector import providers

import main as main_module
from app.infra.database.connection import DatabaseConnection
from tests.fakes import FakePromptNormalizer, FakeReRanker, FakeResponseGenerator, FakeRetriever


@pytest_asyncio.fixture
async def client_com_postgres_real():
    """App com LLM/reranker/retriever fakes, mas phishing_service e
    db_connection REAIS -- para o INSERT ir de fato para o Postgres do
    job de integracao.
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
    container.retriever.override(providers.Object(FakeRetriever()))
    # phishing_service e phishing_repository NAO sao sobrescritos: o
    # container resolve as versoes reais, usando o db_connection real
    # acima.

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await real_db_connection.close_pool()


@pytest.mark.parametrize(
    "difficulty_enviado,nivel_esperado_no_banco",
    [
        ("facil", "facil"),
        ("medio", "medio"),
        ("dificil", "dificil"),
        ("easy", "facil"),  # sinonimo em ingles
        ("hard", "dificil"),  # sinonimo em ingles
        ("médio", "medio"),  # sinonimo em portugues acentuado
    ],
)
async def test_nivel_persistido_bate_com_o_solicitado(
    client_com_postgres_real, phishing_repository, difficulty_enviado, nivel_esperado_no_banco
):
    response = await client_com_postgres_real.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": difficulty_enviado},
    )

    assert response.status_code == 200
    body = response.json()

    # Nao basta a resposta dizer o nivel certo -- issue #2 pede
    # explicitamente para consultar o banco.
    from uuid import UUID

    persistido = await phishing_repository.get_by_id(UUID(body["id"]))
    assert persistido is not None
    assert persistido.nivel == nivel_esperado_no_banco


async def test_difficulty_invalido_da_422_e_nao_toca_o_banco(client_com_postgres_real):
    response = await client_com_postgres_real.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "nivel_inventado"},
    )

    # 422, nunca 500 -- o encadeamento que a issue #2 documenta
    # (fallback silencioso -> nivel cru sobrescrito -> CHECK do banco
    # estourando em 500) nao deve mais existir.
    assert response.status_code == 422
