"""Geracao concorrente do lote (item 6 do plano de producao).

O Sonnet 4.6 leva ~124 s por item; em serie, 3.000 itens levariam ~104 h.
A geracao passa a rodar em paralelo (semaforo configuravel), SEM quebrar o
dedup nem o balanceamento de ficha: a decisao de aceite roda numa secao
sincrona (atomica no asyncio), e a ficha inicial de cada slot e pre-sorteada
em ordem. Falha de um item nao derruba o lote, e 429/529 do provider entram
em backoff exponencial com falha visivel depois de N tentativas.

Mesmo padrao dos outros testes do worker: tudo com fakes, nenhuma chamada de
rede nem de LLM.
"""

import asyncio

import pytest

from app.domain.models.generated_item_draft import ValidatedItemDraft
from app.domain.models.generation_job import JobStatus
from app.domain.services.batch_generation_worker import (
    BatchGenerationWorker,
    _e_erro_de_taxa,
)
from app.domain.services.generation_pipeline import GenerationPipeline
from tests.fakes import (
    FakeEmbeddingClient,
    FakeGenerationJobRepository,
    FakePhishingService,
    FakePromptNormalizer,
    FakeReRanker,
    FakeResponseGenerator,
    FakeVectorStore,
)


def _montar(
    response_generator,
    concurrency=8,
    max_tentativas_taxa=5,
    backoff_base_seconds=0.0,
    service=None,
):
    rg = response_generator
    jobs = FakeGenerationJobRepository()
    service = service or FakePhishingService()
    pipeline = GenerationPipeline(
        normalizer=FakePromptNormalizer(),
        response_generator=rg,
        vector_store=FakeVectorStore(),
        reranker=FakeReRanker(),
        collection_name="colecao_de_teste",
    )
    worker = BatchGenerationWorker(
        job_repository=jobs,
        phishing_service=service,
        pipeline=pipeline,
        response_generator=rg,
        embedding_client=FakeEmbeddingClient(),
        dedup_threshold=0.95,
        concurrency=concurrency,
        max_tentativas_taxa=max_tentativas_taxa,
        backoff_base_seconds=backoff_base_seconds,
    )
    return worker, jobs, service


async def _rodar(worker, jobs, total, difficulties=("medio",), **kwargs):
    job_id = await jobs.create(
        context="pendencia na matricula",
        difficulties=list(difficulties),
        total=total,
        malicious_ratio=1.0,
    )
    await worker.run(
        job_id=job_id,
        context="pendencia na matricula",
        difficulties=list(difficulties),
        total=total,
        malicious_ratio=1.0,
        **kwargs,
    )
    return jobs.storage[job_id]


# ---------------------------------------------------------------------------
# Fakes de apoio
# ---------------------------------------------------------------------------


class _ErroDeTaxa(Exception):
    """Imita um 429/529 do provider (duck-typing por status_code)."""

    def __init__(self, status_code=429):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


class _GeradorComAtraso(FakeResponseGenerator):
    """Cada geracao cede o controle (await sleep) e registra quantas geracoes
    ficam em voo ao mesmo tempo -- para provar que o semaforo limita."""

    def __init__(self, atraso=0.02):
        super().__init__()
        self._atraso = atraso
        self.em_voo = 0
        self.max_em_voo = 0

    async def generate_response(
        self, difficulty, context, relevant_docs, is_malicious=True, variacao=None, **kwargs
    ):
        self.em_voo += 1
        self.max_em_voo = max(self.max_em_voo, self.em_voo)
        try:
            await asyncio.sleep(self._atraso)
            return await super().generate_response(
                difficulty, context, relevant_docs, is_malicious, variacao
            )
        finally:
            self.em_voo -= 1


class _ConteudoFixo(FakeResponseGenerator):
    """Mesmo conteudo/assunto em toda chamada -> tudo duplicata (sim. 1.0)."""

    async def generate_response(
        self, difficulty, context, relevant_docs, is_malicious=True, variacao=None, **kwargs
    ):
        draft = await super().generate_response(
            difficulty, context, relevant_docs, is_malicious, variacao
        )
        draft.conteudo = "CONTEUDO IDENTICO"
        draft.assunto = "Assunto identico"
        return draft


class _FalhaNoNivel(FakeResponseGenerator):
    """Levanta so quando o nivel e o indicado -- falha deterministica de um
    slot, independentemente da ordem de conclusao."""

    def __init__(self, nivel_que_falha):
        super().__init__()
        self._nivel = nivel_que_falha

    async def generate_response(
        self, difficulty, context, relevant_docs, is_malicious=True, variacao=None, **kwargs
    ):
        if difficulty == self._nivel:
            raise RuntimeError("falha proposital de LLM")
        return await super().generate_response(
            difficulty, context, relevant_docs, is_malicious, variacao
        )


class _RateLimitNasPrimeiras(FakeResponseGenerator):
    """Levanta 429 nas primeiras `falhas` chamadas, depois gera normal."""

    def __init__(self, falhas=1):
        super().__init__()
        self._restantes = falhas

    async def generate_response(
        self, difficulty, context, relevant_docs, is_malicious=True, variacao=None, **kwargs
    ):
        if self._restantes > 0:
            self._restantes -= 1
            raise _ErroDeTaxa(429)
        return await super().generate_response(
            difficulty, context, relevant_docs, is_malicious, variacao
        )


class _RateLimitSempre(FakeResponseGenerator):
    async def generate_response(self, *args, **kwargs):
        raise _ErroDeTaxa(529)


class _ServicoFalhaNaPrimeira(FakePhishingService):
    """Levanta na 1a gravacao, grava normal depois -- para testar que a reserva
    de dedup e DESFEITA quando o create_email falha."""

    def __init__(self):
        super().__init__()
        self._primeira = True

    async def create_email(self, email):
        if self._primeira:
            self._primeira = False
            raise RuntimeError("falha de gravacao no banco")
        return await super().create_email(email)


# ---------------------------------------------------------------------------
# _e_erro_de_taxa
# ---------------------------------------------------------------------------


def test_e_erro_de_taxa_por_status_code():
    assert _e_erro_de_taxa(_ErroDeTaxa(429))
    assert _e_erro_de_taxa(_ErroDeTaxa(529))
    assert not _e_erro_de_taxa(RuntimeError("erro comum"))


def test_e_erro_de_taxa_por_nome_de_classe():
    class RateLimitError(Exception):
        pass

    class OverloadedError(Exception):
        pass

    assert _e_erro_de_taxa(RateLimitError())
    assert _e_erro_de_taxa(OverloadedError())


def test_e_erro_de_taxa_em_excecao_aninhada():
    try:
        try:
            raise _ErroDeTaxa(429)
        except _ErroDeTaxa as e:
            raise RuntimeError("embrulhado") from e
    except RuntimeError as topo:
        assert _e_erro_de_taxa(topo)


# ---------------------------------------------------------------------------
# Concorrencia
# ---------------------------------------------------------------------------


async def test_semaforo_limita_geracoes_simultaneas():
    rg = _GeradorComAtraso(atraso=0.02)
    worker, jobs, _ = _montar(rg, concurrency=4)
    job = await _rodar(worker, jobs, total=10)
    assert job.total_generated == 10
    # Nunca mais de 4 geracoes em voo; e de fato chegou a paralelizar.
    assert rg.max_em_voo == 4


async def test_concorrencia_maior_que_total_nao_passa_do_total():
    rg = _GeradorComAtraso(atraso=0.02)
    worker, jobs, _ = _montar(rg, concurrency=8)
    job = await _rodar(worker, jobs, total=3)
    assert job.total_generated == 3
    assert rg.max_em_voo == 3  # so ha 3 itens para gerar


async def test_dedup_correto_sob_concorrencia():
    """Varios itens identicos gerando em paralelo: a decisao de aceite e
    atomica, entao exatamente UM e aceito e o resto descartado -- sem a
    secao atomica, dois itens em voo se aceitariam como nao-duplicatas."""
    worker, jobs, _ = _montar(_ConteudoFixo(), concurrency=8)
    job = await _rodar(worker, jobs, total=5)
    assert job.total_generated == 1
    assert job.total_discarded == 4


async def test_falha_de_um_item_nao_derruba_o_lote():
    worker, jobs, _ = _montar(_FalhaNoNivel("medio"), concurrency=4)
    job = await _rodar(worker, jobs, total=3, difficulties=("facil", "medio", "dificil"))
    assert job.total_generated == 2  # facil e dificil
    assert len(job.failures) == 1
    assert job.failures[0].difficulty == "medio"
    assert job.status == JobStatus.CONCLUIDO_COM_FALHAS


async def test_backoff_recupera_de_429(monkeypatch):
    import app.domain.services.batch_generation_worker as bw

    esperas = []

    async def _sleep_falso(segundos):
        esperas.append(segundos)

    monkeypatch.setattr(bw.asyncio, "sleep", _sleep_falso)

    worker, jobs, _ = _montar(
        _RateLimitNasPrimeiras(falhas=2), concurrency=4, backoff_base_seconds=1.0
    )
    job = await _rodar(worker, jobs, total=1)
    assert job.total_generated == 1  # recuperou apos 2 backoffs
    assert esperas == [1.0, 2.0]  # exponencial: BASE, 2*BASE


async def test_backoff_desiste_e_erro_fica_visivel(monkeypatch):
    import app.domain.services.batch_generation_worker as bw

    esperas = []

    async def _sleep_falso(segundos):
        esperas.append(segundos)

    monkeypatch.setattr(bw.asyncio, "sleep", _sleep_falso)

    worker, jobs, _ = _montar(
        _RateLimitSempre(), concurrency=2, max_tentativas_taxa=3, backoff_base_seconds=1.0
    )
    job = await _rodar(worker, jobs, total=1)
    # Esgotou as 3 tentativas -> o item FALHA (visivel), nao fica preso.
    assert job.total_generated == 0
    assert len(job.failures) == 1
    assert job.status == JobStatus.FALHOU
    assert len(esperas) == 2  # espera entre as 3 tentativas (nao depois da ultima)


async def test_mesma_semente_fichas_balanceadas_com_concorrencia():
    """Com concorrencia, a ficha inicial de cada slot e pre-sorteada em ordem:
    a mesma semente reproduz o mesmo conjunto de fichas (balanceamento de
    instituicao preservado)."""
    rg_a = FakeResponseGenerator()
    rg_b = FakeResponseGenerator()
    worker_a, jobs_a, _ = _montar(rg_a, concurrency=4)
    worker_b, jobs_b, _ = _montar(rg_b, concurrency=4)

    await _rodar(worker_a, jobs_a, total=6, difficulties=("facil", "medio", "dificil"), seed=7)
    await _rodar(worker_b, jobs_b, total=6, difficulties=("facil", "medio", "dificil"), seed=7)

    # A geracao termina fora de ordem, entao comparamos o CONJUNTO de fichas
    # (serializadas), nao a sequencia de chamadas: a mesma semente produz o
    # mesmo multiconjunto de fichas, com o balanceamento preservado.
    fichas_a = sorted(
        c["variacao"].model_dump_json()
        for c in rg_a.calls
        if c["step"] == "generate_response"
    )
    fichas_b = sorted(
        c["variacao"].model_dump_json()
        for c in rg_b.calls
        if c["step"] == "generate_response"
    )
    assert fichas_a and fichas_a == fichas_b


async def test_reserva_de_dedup_e_desfeita_quando_gravacao_falha():
    """Dois itens identicos; a 1a gravacao falha. Sem desfazer a reserva, o
    embedding fantasma do item 1 faria o item 2 (identico) ser descartado como
    duplicata de algo que nao existe. Com o undo, o item 2 e aceito."""
    worker, jobs, _ = _montar(
        _ConteudoFixo(), concurrency=2, service=_ServicoFalhaNaPrimeira()
    )
    job = await _rodar(worker, jobs, total=2)
    assert job.total_generated == 1  # o 2o item entra (fantasma foi removido)
    assert len(job.failures) == 1  # o 1o falhou na gravacao
    assert job.total_discarded == 0  # ninguem foi descartado por duplicidade


async def test_attempt_log_fica_ordenado_por_item():
    """A geracao termina fora de ordem, mas o log sai estavel (item, tentativa)."""
    rg = _GeradorComAtraso(atraso=0.01)
    worker, jobs, _ = _montar(rg, concurrency=8)
    job = await _rodar(worker, jobs, total=5)
    itens = [t["item"] for t in job.attempt_log]
    assert itens == sorted(itens)
    assert {t["item"] for t in job.attempt_log} == {1, 2, 3, 4, 5}
