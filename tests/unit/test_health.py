"""Testes de fumaca: a app sobe, a documentacao existe, rota
desconhecida da 404. Baratos e ainda assim pegam quebra grosseira --
ex.: um import circular ou um erro de wiring que derrubaria a app
inteira antes de qualquer endpoint especifico ser exercitado.
"""


async def test_docs_endpoint_responde(client):
    response = await client.get("/docs")
    assert response.status_code == 200


async def test_rota_desconhecida_da_404(client):
    response = await client.get("/rota/que/nao/existe")
    assert response.status_code == 404
