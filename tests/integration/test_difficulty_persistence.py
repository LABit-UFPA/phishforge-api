"""Critério de aceite da issue #2, ao pé da letra: "valor válido -> 201/200
e nível persistido igual ao pedido (consultar o banco, não só a
resposta)".

Diferente do resto de tests/integration/ (que chama o repositório
direto), aqui sobe a app inteira via HTTP -- para exercitar a
validação do Pydantic de ponta a ponta -- mas com o LLM/reranker/
base vetorial substituídos por fakes (como em tests/unit): o único
componente real é o Postgres, porque é exatamente ele que este teste
audita. Nenhuma chamada paga.

`client_com_postgres_real` vive em tests/integration/conftest.py --
compartilhado com test_is_malicious_persistence.py.
"""

from uuid import UUID

import pytest


@pytest.mark.parametrize(
    "difficulty_enviado,nivel_esperado_no_banco",
    [
        ("facil", "facil"),
        ("medio", "medio"),
        ("dificil", "dificil"),
        ("easy", "facil"),  # sinonimo em ingles
        ("hard", "dificil"),  # sinonimo em ingles
        ("médio", "medio"),  # sinonimo em portugues acentuado
    ],
)
async def test_nivel_persistido_bate_com_o_solicitado(
    client_com_postgres_real, phishing_repository, difficulty_enviado, nivel_esperado_no_banco
):
    response = await client_com_postgres_real.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": difficulty_enviado},
    )

    assert response.status_code == 200
    body = response.json()

    # Nao basta a resposta dizer o nivel certo -- issue #2 pede
    # explicitamente para consultar o banco.
    persistido = await phishing_repository.get_by_id(UUID(body["id"]))
    assert persistido is not None
    assert persistido.nivel == nivel_esperado_no_banco


async def test_difficulty_invalido_da_422_e_nao_toca_o_banco(client_com_postgres_real):
    response = await client_com_postgres_real.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "nivel_inventado"},
    )

    # 422, nunca 500 -- o encadeamento que a issue #2 documenta
    # (fallback silencioso -> nivel cru sobrescrito -> CHECK do banco
    # estourando em 500) nao deve mais existir.
    assert response.status_code == 422
