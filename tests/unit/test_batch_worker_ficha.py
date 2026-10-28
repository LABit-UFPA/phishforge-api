"""BatchGenerationWorker direto (sem HTTP), com os fakes de tests/fakes.py:
ficha por item, semente reproduzivel, log de tentativas e dedup entre
lotes (lote-piloto de 26/10/2026).

Os testes pela API (422 para lote inexistente, campos novos no GET do
job) ficam em test_batch_job.py.
"""

from uuid import uuid4

from app.domain.models.cue import CueCode
from app.domain.models.generation_job import JobStatus
from app.domain.models.variation_spec import VariationSpec
from app.domain.services.batch_generation_worker import BatchGenerationWorker
from app.domain.services.generation_pipeline import GenerationPipeline
from app.domain.services.instituicoes_ficticias import INSTITUICOES
from tests.fakes import (
    FakeEmbeddingClient,
    FakeGenerationJobRepository,
    FakePhishingService,
    FakePromptNormalizer,
    FakeReRanker,
    FakeResponseGenerator,
    FakeVectorStore,
)


class _ConteudoFixo(FakeResponseGenerator):
    """Mesmo `conteudo` em toda chamada: similaridade 1.0 entre quaisquer
    dois itens com FakeEmbeddingClient.
    """

    async def generate_response(
        self, difficulty, context, relevant_docs, is_malicious=True, variacao=None, **kwargs
    ):
        draft = await super().generate_response(
            difficulty, context, relevant_docs, is_malicious, variacao
        )
        draft.conteudo = "CONTEUDO IDENTICO EM TODA CHAMADA"
        draft.assunto = "Assunto identico em toda chamada"
        return draft


class _FalhaSempre(FakeResponseGenerator):
    async def generate_response(self, *args, **kwargs):
        raise RuntimeError("falha simulada de LLM")


def _montar(response_generator=None, jobs=None, service=None):
    rg = response_generator or FakeResponseGenerator()
    jobs = jobs or FakeGenerationJobRepository()
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
    )
    return worker, jobs, service, rg


async def _rodar(worker, jobs, total=4, difficulties=("medio",), **kwargs):
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


def _fichas(rg) -> list:
    return [c["variacao"] for c in rg.calls if c["step"] == "generate_response"]


async def test_cada_item_recebe_a_sua_ficha_e_ela_e_persistida():
    worker, jobs, service, rg = _montar()

    job = await _rodar(worker, jobs, total=4)

    fichas = _fichas(rg)
    assert len(fichas) == 4
    assert all(isinstance(f, VariationSpec) for f in fichas)
    assert len({f.nome_destinatario for f in fichas}) == 4

    itens = [service.repository.storage[i] for i in job.item_ids]
    for item, ficha in zip(itens, fichas):
        assert item.target_cues == ficha.pistas_alvo
        assert item.variation_spec["nome_destinatario"] == ficha.nome_destinatario
        assert all(isinstance(p, CueCode) for p in item.target_cues)


async def test_mesma_semente_reproduz_as_fichas_do_lote():
    worker_a, jobs_a, _, rg_a = _montar()
    worker_b, jobs_b, _, rg_b = _montar()

    await _rodar(worker_a, jobs_a, total=6, difficulties=("facil", "medio", "dificil"), seed=42)
    await _rodar(worker_b, jobs_b, total=6, difficulties=("facil", "medio", "dificil"), seed=42)

    assert _fichas(rg_a) == _fichas(rg_b)


async def test_semente_omitida_e_sorteada_e_registrada():
    worker, jobs, _, _ = _montar()
    job = await _rodar(worker, jobs, total=1)
    assert isinstance(job.run_metadata["seed"], int)


async def test_run_metadata_registra_o_que_o_gerador_recebeu():
    worker, jobs, _, _ = _montar()

    job = await _rodar(worker, jobs, total=1, seed=3)

    meta = job.run_metadata
    assert meta["seed"] == 3
    assert meta["limiar_dedup"] == 0.95
    assert meta["ficha_por_item"] is True
    assert meta["dedup_job_ids"] == []
    assert meta["itens_de_lotes_anteriores"] == 0
    assert meta["generation_context"].startswith("generation_context fake")
    assert meta["fused_context"] == "contexto fundido fake"


async def test_log_registra_cada_tentativa_inclusive_as_descartadas():
    worker, jobs, _, rg = _montar(response_generator=_ConteudoFixo())

    job = await _rodar(worker, jobs, total=2)

    assert job.total_generated == 1
    assert job.total_discarded == 1
    resultados = [(t["item"], t["tentativa"], t["resultado"]) for t in job.attempt_log]
    assert resultados == [
        (1, 1, "aceito"),
        (2, 1, "repetido"),
        (2, 2, "repetido"),
        (2, 3, "descartado"),
    ]
    assert job.attempt_log[0]["similaridade_max"] == 0.0
    assert job.attempt_log[-1]["similaridade_max"] == 1.0
    assert all(t["nivel"] == "medio" and len(t["pistas_alvo"]) == 2 for t in job.attempt_log)
    # Cada nova tentativa sorteia uma ficha nova.
    fichas_do_item_2 = _fichas(rg)[1:]
    assert len({f.nome_destinatario for f in fichas_do_item_2}) == 3


async def test_falha_de_geracao_aparece_no_log():
    worker, jobs, _, _ = _montar(response_generator=_FalhaSempre())

    job = await _rodar(worker, jobs, total=1)

    assert job.total_failed == 1
    assert job.attempt_log == [
        {"item": 1, "nivel": "medio", "tentativa": 1, "similaridade_max": None, "resultado": "falha"}
    ]


async def test_dedup_compara_com_itens_de_lotes_anteriores_indicados():
    jobs = FakeGenerationJobRepository()
    service = FakePhishingService()

    worker_a, _, _, _ = _montar(response_generator=_ConteudoFixo(), jobs=jobs, service=service)
    lote_a = await _rodar(worker_a, jobs, total=1)
    assert lote_a.total_generated == 1

    # Sem indicar o lote A, o lote B nao ve o item repetido: era a lacuna.
    worker_b, _, _, _ = _montar(response_generator=_ConteudoFixo(), jobs=jobs, service=service)
    lote_b = await _rodar(worker_b, jobs, total=1)
    assert lote_b.total_generated == 1

    worker_c, _, _, _ = _montar(response_generator=_ConteudoFixo(), jobs=jobs, service=service)
    lote_c = await _rodar(worker_c, jobs, total=1, dedup_job_ids=[lote_a.id])
    assert lote_c.total_generated == 0
    assert lote_c.total_discarded == 1
    assert lote_c.run_metadata["itens_de_lotes_anteriores"] == 1
    assert lote_c.run_metadata["dedup_job_ids"] == [str(lote_a.id)]


async def test_lote_anterior_inexistente_falha_o_job_antes_de_gerar():
    worker, jobs, _, rg = _montar()

    job = await _rodar(worker, jobs, total=2, dedup_job_ids=[uuid4()])

    assert job.status == JobStatus.FALHOU
    assert "lotes anteriores" in job.error_message
    assert _fichas(rg) == []


class _MesmoCorpoAssuntoDiferente(FakeResponseGenerator):
    """Corpo identico, assunto diferente a cada chamada."""

    async def generate_response(
        self, difficulty, context, relevant_docs, is_malicious=True, variacao=None, **kwargs
    ):
        draft = await super().generate_response(
            difficulty, context, relevant_docs, is_malicious, variacao
        )
        draft.conteudo = "CORPO IDENTICO"
        draft.assunto = f"Assunto {self._contador}"
        return draft


async def test_dedup_considera_o_assunto():
    """Piloto 2: a dedup so via o corpo, e dois pares de itens tinham o
    mesmo assunto. Agora o texto comparado e assunto + corpo.
    """
    worker, jobs, _, _ = _montar(response_generator=_MesmoCorpoAssuntoDiferente())
    job = await _rodar(worker, jobs, total=2)
    assert job.total_generated == 2
    assert job.total_discarded == 0


async def test_gerador_recebe_o_sorteador_para_regenerar_com_ficha_nova():
    worker, jobs, _, rg = _montar()
    await _rodar(worker, jobs, total=1)
    # O fake nao regenera; o que importa e o worker ter passado o sorteador.
    chamada = next(c for c in rg.calls if c["step"] == "generate_response")
    assert callable(chamada["sortear_variacao"])
    assert isinstance(chamada["sortear_variacao"](), VariationSpec)


async def test_run_metadata_registra_versao_do_gerador():
    from app.domain.services.response_generator import VERSAO_GERADOR

    worker, jobs, _, _ = _montar()
    job = await _rodar(worker, jobs, total=1)
    assert job.run_metadata["versao_gerador"] == VERSAO_GERADOR
    assert "anotacao_cega" in job.run_metadata


class _AssuntoFixo(FakeResponseGenerator):
    """Corpo diferente a cada chamada (similaridade baixa), mas sempre o
    mesmo assunto -- o caso que passava pela dedup no piloto 3.
    """

    async def generate_response(
        self, difficulty, context, relevant_docs, is_malicious=True, variacao=None, **kwargs
    ):
        draft = await super().generate_response(
            difficulty, context, relevant_docs, is_malicious, variacao
        )
        draft.assunto = "Pendência na Matrícula!"
        return draft


async def test_assunto_identico_conta_como_repeticao_mesmo_com_corpo_diferente():
    worker, jobs, _, _ = _montar(response_generator=_AssuntoFixo())

    job = await _rodar(worker, jobs, total=2)

    assert job.total_generated == 1
    assert job.total_discarded == 1
    segundo = [t for t in job.attempt_log if t["item"] == 2]
    assert [t["resultado"] for t in segundo] == ["repetido", "repetido", "descartado"]
    assert all(t["assunto_repetido"] for t in segundo)
    assert all(t["similaridade_max"] < 0.95 for t in segundo)


async def test_assunto_de_lote_anterior_indicado_tambem_conta():
    jobs = FakeGenerationJobRepository()
    service = FakePhishingService()

    worker_a, _, _, _ = _montar(response_generator=_AssuntoFixo(), jobs=jobs, service=service)
    lote_a = await _rodar(worker_a, jobs, total=1)

    worker_b, _, _, _ = _montar(response_generator=_AssuntoFixo(), jobs=jobs, service=service)
    lote_b = await _rodar(worker_b, jobs, total=1, dedup_job_ids=[lote_a.id])

    assert lote_b.total_generated == 0
    assert lote_b.total_discarded == 1


# ---------------------------------------------------------------------------
# Lote-piloto 5 (correcoes de qualidade, item 2.1)
# ---------------------------------------------------------------------------


async def test_instituicao_override_vale_para_todo_o_lote():
    """A requisicao do lote pode fixar uma instituicao para a celula
    inteira (BatchGenerationRequest.instituicao) -- todo item do lote
    usa a mesma, em vez de sortear da lista.
    """
    worker, jobs, _, rg = _montar()
    fixa = INSTITUICOES[5]

    await _rodar(worker, jobs, total=4, difficulties=("facil", "medio"), instituicao=fixa)

    fichas = _fichas(rg)
    assert len(fichas) == 4
    assert all(f.instituicao == fixa for f in fichas)


async def test_sem_override_cada_item_do_lote_sorteia_uma_instituicao():
    worker, jobs, _, rg = _montar()

    await _rodar(worker, jobs, total=len(INSTITUICOES))

    fichas = _fichas(rg)
    assert {f.instituicao for f in fichas} == set(INSTITUICOES)


async def test_run_metadata_registra_o_override_de_instituicao():
    worker, jobs, _, _ = _montar()
    fixa = INSTITUICOES[2]

    job = await _rodar(worker, jobs, total=1, instituicao=fixa)

    assert job.run_metadata["instituicao_override"] == fixa.model_dump(mode="json")


async def test_run_metadata_sem_override_registra_none():
    worker, jobs, _, _ = _montar()

    job = await _rodar(worker, jobs, total=1)

    assert job.run_metadata["instituicao_override"] is None
