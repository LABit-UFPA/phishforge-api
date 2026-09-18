"""Contrato de GET /api/v1/emails/statistics (issue #8): banco fora do
ar e "nenhum email cadastrado" sao estados diferentes -- antes os dois
respondiam 200 com estatistica zerada, porque a excecao era engolida
em duas camadas (repositorio E endpoint).
"""


async def test_statistics_com_banco_ok_retorna_200(client, fakes):
    response = await client.get("/api/v1/emails/statistics")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 0


async def test_statistics_com_erro_no_banco_propaga_500(client, fakes):
    """Antes desta issue, este cenario respondia 200 com
    {"total": 0, ...} -- indistinguivel de "banco vazio de verdade".
    """

    async def get_stats_quebrado():
        raise ConnectionError("banco fora do ar, simulado no teste")

    fakes["phishing_service"].repository.get_stats = get_stats_quebrado

    response = await client.get("/api/v1/emails/statistics")

    assert response.status_code == 500
