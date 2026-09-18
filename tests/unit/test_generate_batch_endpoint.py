"""Contrato de POST /api/v1/generate/batch, com o pipeline substituido
por fakes. Cobre a distribuicao entre dificuldades (que a #11 pede
para preservar), a validacao de entrada e, agora, o contrato de
dificuldade (#2) tambem no lote -- nao a paridade com o /generate nem
a deduplicacao, que sao objeto da propria #11.
"""


async def test_distribui_dificuldades_com_resto_nas_primeiras(client):
    """De divmod(10, 3) = (3, 1): a primeira dificuldade da lista leva
    o resto. E o comportamento que a issue #11 explicitamente pede
    para nao mexer.
    """
    response = await client.post(
        "/api/v1/generate/batch",
        json={
            "context": "cobranca de fatura",
            "difficulties": ["facil", "medio", "dificil"],
            "total": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["distribution"] == {"facil": 4, "medio": 3, "dificil": 3}
    assert body["total_requested"] == 10
    # Criterio da #2: nenhum item com erro para dificuldades validas.
    assert body["total_generated"] == 10
    assert all("error" not in item for item in body["examples"])


async def test_sinonimo_em_ingles_no_lote_e_normalizado(client):
    """Mesmo sinonimo aceito no /generate funciona no lote, e a chave
    de `distribution` na resposta vem no canonico -- nao no sinonimo
    cru que foi enviado (issue #2).
    """
    response = await client.post(
        "/api/v1/generate/batch",
        json={
            "context": "cobranca de fatura",
            "difficulties": ["easy", "hard"],
            "total": 4,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["distribution"] == {"facil": 2, "dificil": 2}


async def test_dificuldade_invalida_no_lote_da_422(client):
    """Um valor invalido em QUALQUER posicao da lista rejeita a
    request inteira -- Pydantic valida antes do handler rodar, entao
    nao gera os itens validos parcialmente para so falhar nos
    invalidos.
    """
    response = await client.post(
        "/api/v1/generate/batch",
        json={
            "context": "cobranca de fatura",
            "difficulties": ["facil", "nivel_inventado"],
            "total": 4,
        },
    )

    assert response.status_code == 422


async def test_lista_de_dificuldades_vazia_e_rejeitada(client):
    """422, nao mais 400 (issue #8): a checagem virou Field(min_length=1)
    em BatchGenerationRequest, em vez de um `if` manual no endpoint --
    era esse `if` duplicado que tinha divergido do limite do DTO sem
    ninguem notar.
    """
    response = await client.post(
        "/api/v1/generate/batch",
        json={"context": "cobranca de fatura", "difficulties": [], "total": 5},
    )

    assert response.status_code == 422


async def test_total_acima_do_limite_e_rejeitado(client):
    """422, nao mais 400 (issue #8): validado por Field(le=100) no DTO.
    100 e o limite canonico agora -- antes havia tres valores
    diferentes no projeto (DTO dizia 10, endpoint validava >100, doc
    dizia "max: 10").
    """
    response = await client.post(
        "/api/v1/generate/batch",
        json={
            "context": "cobranca de fatura",
            "difficulties": ["facil"],
            "total": 101,
        },
    )

    assert response.status_code == 422
