"""Fixtures compartilhadas por tests/unit.

Nenhum teste aqui abre conexao real com Postgres, Qdrant ou a OpenAI:
os providers pesados do container (reranker, response_generator,
prompt_normalizer, qdrant_store, phishing_service, db_connection) sao
substituidos por fakes (tests/fakes.py) via `container.<provider>.
override(...)`. E o que garante que o CI passe sem OPENAI_API_KEY
configurada e sem baixar nenhum modelo de ML -- ver issues #8 e #12.

`generation_pipeline` (issue #11) nao e overrideado diretamente: ele e
composto, na definicao do container, a partir de prompt_normalizer,
response_generator, qdrant_store e reranker -- overrideando esses
quatro, a pipeline resolvida automaticamente usa os fakes tambem, sem
precisar de um FakeGenerationPipeline. Isso deixa a orquestracao real
(extracao de parent_content, ordem das etapas) exercitada de verdade
nos testes, nao substituida por atalho.

tests/integration/conftest.py e separado e usa Postgres de verdade.
"""

import os

# Hoje todo campo de Settings tem default (OPENAI_API_KEY="" inclusive),
# entao a suite roda sem isto. Fica como cinto de seguranca: se o
# campo virar obrigatorio (#7 fala em falhar no start sem a chave em
# producao), a suite continua nao precisando de .env nem de rede --
# nenhum provider que realmente usa a chave e resolvido, ver overrides
# abaixo.
os.environ.setdefault("OPENAI_API_KEY", "sk-test-nao-usada-em-nenhuma-chamada-real")

import httpx
import pytest
import pytest_asyncio
from dependency_injector import providers

import main as main_module
from tests.fakes import (
    FakeDbConnection,
    FakeEmbeddingClient,
    FakeGenerationJobRepository,
    FakePhishingService,
    FakePromptNormalizer,
    FakeReRanker,
    FakeResponseGenerator,
    FakeUserAnswerEvaluator,
    FakeVectorStore,
)


def _build_app_with_fakes():
    """Cria uma app + Container novos e aplica os overrides padrao.

    Um Container novo por teste (em vez de reusar main.app) evita
    vazamento de override entre testes -- nao ha estado compartilhado
    para "resetar" porque nao ha instancia compartilhada.
    """
    app = main_module.create_app()
    container = app.container

    fakes = {
        "db_connection": FakeDbConnection(),
        "prompt_normalizer": FakePromptNormalizer(),
        "response_generator": FakeResponseGenerator(),
        "reranker": FakeReRanker(),
        "qdrant_store": FakeVectorStore(),
        "phishing_service": FakePhishingService(),
        "user_answer_evaluator": FakeUserAnswerEvaluator(),
        # issue #11b: repositorio do job de lote fala SQL direto via
        # db.get_connection(), que FakeDbConnection nao implementa --
        # overrideado direto (nao via db_connection) para nao exigir
        # Postgres real em tests/unit. batch_generation_worker e
        # composto a partir deste mesmo provider, entao ganha o fake
        # automaticamente.
        "generation_job_repository": FakeGenerationJobRepository(),
        # issue #11b: BatchGenerationWorker usa embedding_client_openai
        # (real, chamaria a OpenAI de verdade) so para a dedup por
        # similaridade de cosseno -- sem este override, todo item do
        # lote falha com 401 antes mesmo de chegar na dedup.
        "embedding_client_openai": FakeEmbeddingClient(),
    }
    for name, fake in fakes.items():
        getattr(container, name).override(providers.Object(fake))

    return app, fakes


@pytest.fixture
def app_and_fakes():
    """App com os providers pesados substituidos, mais o dicionario de
    fakes usado -- para o teste inspecionar `.calls` quando precisar
    conferir o que o endpoint passou ao gerador (ex.: qual `difficulty`
    chegou de fato em generate_response).
    """
    return _build_app_with_fakes()


@pytest.fixture
def fakes(app_and_fakes):
    _app, fakes = app_and_fakes
    return fakes


@pytest_asyncio.fixture
async def client(app_and_fakes):
    app, _fakes = app_and_fakes
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
