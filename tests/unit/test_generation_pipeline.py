"""Testes diretos de GenerationPipeline (issue #11a), com todas as
dependencias substituidas por fakes -- normalizador, gerador (so para
HyDE/fusao), reranker e base vetorial. Prova a extracao em si: a mesma
sequencia de etapas que estava escrita a mao dentro do handler do
/generate agora vive aqui, testavel sem HTTP nem FastAPI.

A paridade entre os dois endpoints e o reaproveitamento por lote tem
seus proprios testes em tests/unit/test_generation_paridade.py -- esses
sim vao pela app inteira, porque e o que a issue #11 pede para provar
("os dois caminhos recebem o mesmo contexto recuperado").
"""

import pytest

from app.domain.services.generation_pipeline import TOP_K_RETRIEVE, GenerationPipeline
from tests.fakes import FakePromptNormalizer, FakeReRanker, FakeResponseGenerator, FakeVectorStore


def _build_pipeline(vector_store=None, response_generator=None):
    return GenerationPipeline(
        normalizer=FakePromptNormalizer(),
        response_generator=response_generator or FakeResponseGenerator(),
        vector_store=vector_store or FakeVectorStore(),
        reranker=FakeReRanker(),
        collection_name="colecao_de_teste",
    )


async def test_usa_parent_content_nao_o_chunk_filho():
    """O bug central da #11: o /generate/batch antigo usava `doc.text`
    (chunk filho, otimizado so para busca) em vez de `parent_content`
    (bloco completo, para geracao). FakeVectorStore devolve os dois
    visivelmente diferentes -- ver tests/fakes.py.

    FakeResponseGenerator.fuse_and_summarize_context ignora o proprio
    input e devolve sempre "contexto fundido fake" (e um fake, nao
    reimplementa fusao de verdade) -- entao a asserção é sobre o que a
    pipeline PASSOU para ele (`contexts`), não sobre o retorno do fake.
    """
    response_generator = FakeResponseGenerator()
    pipeline = _build_pipeline(response_generator=response_generator)

    await pipeline.build_context("contexto de teste")

    fusion_call = next(
        c for c in response_generator.calls if c["step"] == "fuse_and_summarize_context"
    )
    contexts_recebidos = "\n".join(fusion_call["contexts"])
    assert "BLOCO_PAI_completo_usado_na_geracao" in contexts_recebidos
    assert "CHUNK_FILHO_pequeno_otimizado_para_busca" not in contexts_recebidos


async def test_top_k_alinhado_entre_os_fluxos():
    """Antes da #11, /generate usava top_k=20 e /generate/batch usava
    80, sem uso real dos 77 documentos extras -- so os 3 primeiros
    pos-rerank chegam a fusao, de qualquer forma. Os dois fluxos agora
    passam pelo mesmo pipeline, com um unico valor.
    """
    vector_store = FakeVectorStore()
    pipeline = _build_pipeline(vector_store=vector_store)

    await pipeline.build_context("contexto de teste")

    assert len(vector_store.calls) == 1
    assert vector_store.calls[0]["top_k"] == TOP_K_RETRIEVE


async def test_falha_no_retrieve_propaga_para_o_chamador():
    """A pipeline nao decide codigo HTTP -- so deixa a excecao subir,
    para cada endpoint decidir sozinho (ver docstring da classe). Isso
    e o que permite os dois endpoints reportarem o erro do jeito que
    ja reportavam antes desta extracao.
    """

    class VectorStoreQuebrado:
        def query(self, collection_name, query_text, top_k):
            raise ConnectionError("Qdrant fora do ar, simulado no teste")

    pipeline = _build_pipeline(vector_store=VectorStoreQuebrado())

    with pytest.raises(ConnectionError):
        await pipeline.build_context("contexto de teste")


async def test_falha_no_hyde_tem_fallback_para_search_query():
    """HyDE e melhoria de recall, nao etapa obrigatoria -- falha aqui
    NAO propaga, diferente do retrieve. O fallback e usar a
    search_query crua do normalizador como query de busca.
    """

    class ResponseGeneratorComHydeQuebrado(FakeResponseGenerator):
        async def generate_hypothetical_answer(self, query):
            raise TimeoutError("timeout simulado no HyDE")

    vector_store = FakeVectorStore()
    pipeline = _build_pipeline(
        vector_store=vector_store, response_generator=ResponseGeneratorComHydeQuebrado()
    )

    built = await pipeline.build_context("contexto de teste")

    esperado = "search_query fake para: contexto de teste"
    assert built.search_query == esperado
    assert vector_store.calls[0]["query_text"] == esperado
