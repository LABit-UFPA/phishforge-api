"""Criterio central da issue #11: os dois endpoints de geracao usam o
MESMO pipeline, entao com o mesmo `context` produzem o mesmo contexto
recuperado -- e o lote reaproveita a parte cara (normalizacao, HyDE,
retrieve, rerank, fusao) uma vez por requisicao, nao uma vez por item.

Antes desta extracao, nenhuma das duas coisas era verdade: o lote
pulava normalizacao/HyDE/rerank/fusao inteiramente e usava o chunk de
busca (child_text) em vez do bloco completo (parent_content).
"""


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

    resposta_lote = await client.post(
        "/api/v1/generate/batch",
        json={"context": contexto, "difficulties": ["facil"], "total": 1},
    )
    assert resposta_lote.status_code == 200

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
    response = await client.post(
        "/api/v1/generate/batch",
        json={
            "context": "cobranca de fatura",
            "difficulties": ["facil", "medio"],
            "total": 6,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_generated"] == 6
    assert all("error" not in item for item in body["examples"])

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
