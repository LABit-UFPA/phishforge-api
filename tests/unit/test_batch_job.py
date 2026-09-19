"""Comportamento especifico do job assincrono da issue #11b, alem do
contrato ja coberto por test_generate_batch_endpoint.py: 404 para job
inexistente, dedup por similaridade de cosseno descartando item quase-
identico (distinto de falha), falha de geracao contando como failure
(distinto de descarte), e o job inteiro falhando quando a montagem do
contexto (pipeline) da excecao antes de qualquer item ser gerado.

Os testes de dedup/falha precisam de controle fino sobre o que o
gerador fake devolve por chamada -- alem do que os fakes padrao de
`fakes` (conftest.py) oferecem -- entao usam `app_and_fakes` e
overrideam mais um provider por cima dos defaults, num Container novo
por teste (sem vazamento entre eles).
"""

from uuid import uuid4

import httpx
from dependency_injector import providers

from tests.fakes import FakeResponseGenerator
from tests.unit._batch_helpers import post_batch_and_get_job


async def test_job_inexistente_retorna_404(client):
    response = await client.get(f"/api/v1/generate/batch/{uuid4()}")

    assert response.status_code == 404


class _ConteudoFixoResponseGenerator(FakeResponseGenerator):
    """Sempre devolve o mesmo `conteudo` -- com FakeEmbeddingClient
    (embedding derivado do texto), isso forca similaridade de cosseno
    1.0 entre qualquer par de itens gerados por este fake, o gatilho
    exato que a dedup da #11b precisa detectar.
    """

    async def generate_response(self, difficulty, context, relevant_docs, is_malicious=True):
        draft = await super().generate_response(difficulty, context, relevant_docs, is_malicious)
        draft.conteudo = "CONTEUDO IDENTICO EM TODA CHAMADA, PARA FORCAR A DEDUP"
        return draft


class _FalhaNaSegundaChamadaResponseGenerator(FakeResponseGenerator):
    """A primeira chamada de generate_response funciona normalmente; a
    segunda (e so ela) levanta excecao -- simula uma falha real de LLM
    no meio do lote, categoria distinta de descarte por duplicidade.
    """

    def __init__(self):
        super().__init__()
        self._chamadas_generate_response = 0

    async def generate_response(self, difficulty, context, relevant_docs, is_malicious=True):
        self._chamadas_generate_response += 1
        if self._chamadas_generate_response == 2:
            raise RuntimeError("falha simulada de LLM")
        return await super().generate_response(difficulty, context, relevant_docs, is_malicious)


class _NormalizerQueFalha:
    async def normalize(self, user_context: str):
        raise RuntimeError("falha simulada na normalizacao")


async def _client_com_override(app_and_fakes, provider_name: str, fake):
    app, fakes = app_and_fakes
    getattr(app.container, provider_name).override(providers.Object(fake))
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test"), fakes


async def test_dedup_descarta_item_quase_identico_sem_contar_como_falha(app_and_fakes):
    client, _fakes = await _client_com_override(
        app_and_fakes, "response_generator", _ConteudoFixoResponseGenerator()
    )
    async with client:
        job = await post_batch_and_get_job(
            client, {"context": "cobranca de fatura", "difficulties": ["facil"], "total": 2}
        )

    # O primeiro item nao tem nada para colidir (accepted_embeddings
    # comeca vazio) e sempre e aceito; o segundo, com conteudo
    # identico ao primeiro, colide em toda tentativa e e descartado
    # apos MAX_DEDUP_RETRIES -- sem virar failure.
    assert job["status"] == "concluido"
    assert job["total_generated"] == 1
    assert job["total_discarded"] == 1
    assert job["total_failed"] == 0
    assert job["failures"] == []


async def test_falha_de_geracao_conta_como_failure_distinto_de_descarte(app_and_fakes):
    client, _fakes = await _client_com_override(
        app_and_fakes, "response_generator", _FalhaNaSegundaChamadaResponseGenerator()
    )
    async with client:
        job = await post_batch_and_get_job(
            client, {"context": "cobranca de fatura", "difficulties": ["facil"], "total": 2}
        )

    assert job["status"] == "concluido_com_falhas"
    assert job["total_generated"] == 1
    assert job["total_failed"] == 1
    assert job["total_discarded"] == 0
    assert len(job["failures"]) == 1
    assert job["failures"][0]["difficulty"] == "facil"
    assert "falha simulada de LLM" in job["failures"][0]["error"]


async def test_job_falha_inteiro_quando_montagem_de_contexto_da_excecao(app_and_fakes):
    client, _fakes = await _client_com_override(
        app_and_fakes, "prompt_normalizer", _NormalizerQueFalha()
    )
    async with client:
        job = await post_batch_and_get_job(
            client, {"context": "cobranca de fatura", "difficulties": ["facil"], "total": 3}
        )

    # Excecao na etapa de contexto (comum a normalizacao/HyDE/retrieve/
    # fusao) acontece ANTES de qualquer item ser gerado -- o job inteiro
    # falha, nao item a item.
    assert job["status"] == "falhou"
    assert job["total_generated"] == 0
    assert job["total_failed"] == 0
    assert job["total_discarded"] == 0
    assert job["distribution"] is None
    assert "falha simulada na normalizacao" in job["error_message"]
