"""Contrato de POST /api/v1/generate, com todo o pipeline (normalizacao,
HyDE, retrieve, rerank, fusao, geracao, persistencia) substituido por
fakes -- nenhuma chamada de rede, nenhum modelo de ML carregado.

Cobre o contrato de dificuldade (#2) na parte rapida, sem banco: 422
para valor invalido e sinonimo aceito na borda. A parte que exige
"consultar o banco, nao so a resposta" (criterio de aceite da #2) esta
em tests/integration/test_difficulty_persistence.py, com Postgres
real. `is_malicious` (#3) tem seu proprio arquivo,
test_generate_is_malicious.py. A regressao de #4 (avaliador) ainda nao
tem teste aqui -- entra junto com a propria issue.
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


async def test_difficulty_invalido_da_422_nao_500(client):
    """O encadeamento que a issue #2 documenta -- fallback silencioso
    -> nivel cru sobrescrito -> CHECK do banco estourando em 500 -- nao
    deve mais existir. Um valor fora do vocabulario (canonico ou
    sinonimo) e rejeitado pelo Pydantic antes de tocar em qualquer
    pipeline.
    """
    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "nivel_inventado"},
    )

    assert response.status_code == 422


async def test_sinonimo_em_ingles_e_aceito_e_normalizado(client, fakes):
    """Retrocompatibilidade com quem ja chama a API em ingles (issue
    #2): 'easy' funciona e o valor que chega ao gerador e o canonico
    'facil', nao o sinonimo cru.
    """
    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "easy"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["nivel"] == "facil"

    generate_call = next(
        c for c in fakes["response_generator"].calls if c["step"] == "generate_response"
    )
    assert generate_call["difficulty"] == "facil"
