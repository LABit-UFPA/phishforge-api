"""Contrato de POST /api/v1/generate/batch, com o pipeline substituido
por fakes. Cobre hoje so a distribuicao entre dificuldades (que a #11
pede para preservar) e a validacao de entrada -- nao a paridade com o
/generate nem a deduplicacao, que sao objeto da propria #11.
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


async def test_lista_de_dificuldades_vazia_e_rejeitada(client):
    response = await client.post(
        "/api/v1/generate/batch",
        json={"context": "cobranca de fatura", "difficulties": [], "total": 5},
    )

    assert response.status_code == 400


async def test_total_acima_do_limite_e_rejeitado(client):
    response = await client.post(
        "/api/v1/generate/batch",
        json={
            "context": "cobranca de fatura",
            "difficulties": ["facil"],
            "total": 101,
        },
    )

    assert response.status_code == 400
