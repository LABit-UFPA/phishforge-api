"""Contrato de POST /api/v1/generate, com todo o pipeline (normalizacao,
HyDE, retrieve, rerank, fusao, geracao, persistencia) substituido por
fakes -- nenhuma chamada de rede, nenhum modelo de ML carregado.

Isto e o esqueleto que a issue #8 pede; nao cobre ainda as regressoes
especificas de #2 (contrato de dificuldade), #4 (avaliador) ou #11
(paridade dos dois fluxos de geracao) -- essas entram junto com a
implementacao de cada issue, para o teste nascer com a correcao que ele
cobre em vez de ser escrito contra um comportamento que ainda vai
mudar.
"""


async def test_generate_retorna_o_email_persistido(client, fakes):
    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura de energia", "difficulty": "medio"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"]
    assert body["assunto"] == "Assunto de teste"
    assert body["conteudo"]

    # Prova de que o pipeline realmente passou pelas etapas: o fake
    # recebeu o contexto ja fundido (nao o generation_context cru),
    # que e a etapa 5 do pipeline descrito na #11.
    generate_call = next(
        c for c in fakes["response_generator"].calls if c["step"] == "generate_response"
    )
    assert generate_call["relevant_docs"] == "contexto fundido fake"


async def test_generate_com_contexto_vazio_ainda_gera(client):
    """Regressao de sanidade: contexto vazio nao deveria quebrar o
    pipeline antes mesmo de chegar ao gerador.
    """
    response = await client.post(
        "/api/v1/generate",
        json={"context": "", "difficulty": "medio"},
    )

    assert response.status_code == 200
