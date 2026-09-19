"""Contrato de `id` nos endpoints que devolvem PhishingEmail (issue
#24): antes desta correcao, `PhishingEmail` nao declarava `id` /
`created_at` / `updated_at`, entao GET /api/v1/emails e
GET /api/v1/emails/{id} devolviam o objeto sem id -- so /generate e
/generate/batch/{job_id} escapavam do bug porque injetavam
`result["id"]` manualmente no dict de resposta.
"""

from uuid import uuid4

from app.domain.models.phishing_email import PhishingEmail


def _seed(fakes, **overrides):
    base = dict(
        receptor="a@b.com",
        remetente="c@d.com",
        assunto="assunto de teste",
        conteudo="conteudo de teste",
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
    return email_id


async def test_generate_devolve_id(client):
    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "facil"},
    )

    assert response.status_code == 200
    assert response.json()["id"]


async def test_listagem_devolve_id_de_cada_item(client, fakes):
    id_a = _seed(fakes)
    id_b = _seed(fakes)

    response = await client.get("/api/v1/emails")

    assert response.status_code == 200
    ids_na_resposta = {item["id"] for item in response.json()["emails"]}
    assert ids_na_resposta == {str(id_a), str(id_b)}


async def test_get_por_id_devolve_o_proprio_id(client, fakes):
    email_id = _seed(fakes)

    response = await client.get(f"/api/v1/emails/{email_id}")

    assert response.status_code == 200
    assert response.json()["id"] == str(email_id)
