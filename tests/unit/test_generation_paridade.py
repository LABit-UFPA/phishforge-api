"""Criterio central da issue #11: os dois endpoints de geracao usam o
MESMO pipeline, entao com o mesmo `context` produzem o mesmo contexto
recuperado -- e o lote reaproveita a parte cara (normalizacao, HyDE,
retrieve, rerank, fusao) uma vez por requisicao, nao uma vez por item.

Antes desta extracao, nenhuma das duas coisas era verdade: o lote
pulava normalizacao/HyDE/rerank/fusao inteiramente e usava o chunk de
busca (child_text) em vez do bloco completo (parent_content).

Desde a issue #11b, /generate/batch responde 202 -- os testes do lote
usam post_batch_and_get_job para chegar no resultado final.
"""

from tests.unit._batch_helpers import post_batch_and_get_job


async def test_generate_e_generate_batch_recebem_o_mesmo_contexto(client, fakes):
    contexto = "cobranca de fatura de energia, identica nos dois flows"

    resposta_unica = await client.post(
        "/api/v1/generate",
        json={"context": contexto, "difficulty": "facil"},
    )
    assert resposta_unica.status_code == 200

    chamada_unica = next(
        c for c in fakes["response_generator"].calls if c["step"] == "generate_response"
    )

    fakes["response_generator"].calls.clear()

    await post_batch_and_get_job(
        client, {"context": contexto, "difficulties": ["facil"], "total": 1}
    )

    chamada_lote = next(
        c for c in fakes["response_generator"].calls if c["step"] == "generate_response"
    )

    # E exatamente o que a issue #11 pede para provar: "os dois
    # caminhos recebem o mesmo contexto recuperado".
    assert chamada_unica["context"] == chamada_lote["context"]
    assert chamada_unica["relevant_docs"] == chamada_lote["relevant_docs"]


async def test_lote_reaproveita_o_pipeline_uma_vez_por_requisicao(client, fakes):
    """3 itens faceis + 3 medios (total=6): a geracao final roda 6
    vezes (uma por item, porque depende da dificuldade), mas
    normalizacao/HyDE/retrieve/rerank/fusao rodam so 1 vez -- essa e a
    parte que a issue #11 identificou como reaproveitavel entre itens
    do mesmo lote.
    """
    job = await post_batch_and_get_job(
        client,
        {
            "context": "cobranca de fatura",
            "difficulties": ["facil", "medio"],
            "total": 6,
        },
    )

    assert job["total_generated"] == 6
    assert all("error" not in item for item in job["examples"])

    generator_calls = fakes["response_generator"].calls
    generate_response_calls = [c for c in generator_calls if c["step"] == "generate_response"]
    hyde_calls = [c for c in generator_calls if c["step"] == "generate_hypothetical_answer"]
    fusion_calls = [c for c in generator_calls if c["step"] == "fuse_and_summarize_context"]

    assert len(generate_response_calls) == 6
    assert len(hyde_calls) == 1
    assert len(fusion_calls) == 1
    assert len(fakes["prompt_normalizer"].calls) == 1
    assert len(fakes["reranker"].calls) == 1
    assert len(fakes["qdrant_store"].calls) == 1
