"""Criterio de aceite da issue #24: GET /api/v1/emails e
GET /api/v1/emails/{id} devolvem `id` preenchido e batendo com o que
esta de fato no Postgres -- nao um objeto onde o Pydantic descartou o
campo em silencio por ele nao estar declarado no modelo.

Mesmo padrao de test_difficulty_persistence.py: sobe a app via HTTP com
LLM/reranker/base vetorial fakes, mas Postgres real.
"""

from uuid import UUID


async def test_generate_e_listagem_tem_o_mesmo_id_do_banco(
    client_com_postgres_real, phishing_repository
):
    response = await client_com_postgres_real.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "facil"},
    )
    assert response.status_code == 200
    email_id = UUID(response.json()["id"])

    persistido = await phishing_repository.get_by_id(email_id)
    assert persistido is not None
    assert persistido.id == email_id
    assert persistido.created_at is not None
    assert persistido.updated_at is not None

    lista = await client_com_postgres_real.get("/api/v1/emails")
    assert lista.status_code == 200
    ids_na_listagem = {item["id"] for item in lista.json()["emails"]}
    assert str(email_id) in ids_na_listagem

    detalhe = await client_com_postgres_real.get(f"/api/v1/emails/{email_id}")
    assert detalhe.status_code == 200
    assert detalhe.json()["id"] == str(email_id)
    assert detalhe.json()["created_at"] is not None
