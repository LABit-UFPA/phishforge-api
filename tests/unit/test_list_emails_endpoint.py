"""Contrato de GET /api/v1/emails (issue #8): EmailSearchRequest passa
a ser usado via Depends(), tratando cada campo do DTO como query param
independente -- mesmo contrato de URL que os parametros soltos que
existiam antes (confirmado experimentalmente antes de trocar, ver
comentario no endpoint).
"""

from uuid import uuid4

from app.domain.models.phishing_email import PhishingEmail


def _seed(fakes, **overrides):
    """Insere um email diretamente no storage do fake, sem passar por
    create_email -- essa validacao ja tem seus proprios testes; aqui o
    foco e filtro/busca sobre o que ja esta persistido.
    """
    base = dict(
        receptor="a@b.com",
        remetente="c@d.com",
        assunto="assunto de teste",
        conteudo="conteudo de teste sobre cobranca",
        explicacao="explicacao de teste",
        nivel="facil",
        categoria="financeiro",
        links=[],
        is_malicious=True,
    )
    base.update(overrides)
    email_id = uuid4()
    email = PhishingEmail(id=email_id, **base)
    fakes["phishing_service"].repository.storage[email_id] = email
    return email


async def test_lista_todos_sem_filtro(client, fakes):
    _seed(fakes)
    _seed(fakes)

    response = await client.get("/api/v1/emails")

    assert response.status_code == 200
    assert response.json()["count"] == 2


async def test_filtra_por_categoria(client, fakes):
    _seed(fakes, categoria="financeiro")
    _seed(fakes, categoria="rh")

    response = await client.get("/api/v1/emails?categoria=rh")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["emails"][0]["categoria"] == "rh"


async def test_filtra_por_nivel(client, fakes):
    _seed(fakes, nivel="facil")
    _seed(fakes, nivel="dificil")

    response = await client.get("/api/v1/emails?nivel=dificil")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["emails"][0]["nivel"] == "dificil"


async def test_busca_textual(client, fakes):
    _seed(fakes, conteudo="mensagem sobre fatura de energia")
    _seed(fakes, conteudo="mensagem sobre folha de pagamento")

    response = await client.get("/api/v1/emails?search=energia")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert "energia" in body["emails"][0]["conteudo"]


async def test_limit_zero_e_rejeitado(client):
    """Mudanca real desta issue: o parametro solto so tinha `le=100`,
    entao limit=0 antes era aceito e virava `LIMIT 0` silencioso na
    query. EmailSearchRequest tem `ge=1`, entao agora e 422.
    """
    response = await client.get("/api/v1/emails?limit=0")

    assert response.status_code == 422


async def test_limit_acima_do_maximo_e_rejeitado(client):
    response = await client.get("/api/v1/emails?limit=101")

    assert response.status_code == 422
