"""Contrato de POST /api/v1/evaluate/user-answer (issue #4), com o
LLM substituido por fake -- a qualidade do julgamento do LLM em si
(que caso ele reconhece, que nota da) so e testavel com chamada real;
aqui o foco e o CONTRATO: os campos novos chegam, sao repassados
corretamente ao evaluator, e a resposta inclui `acerto_por_sorte`.

As instrucoes especificas de cada um dos 4 casos, dentro do prompt,
tem seu proprio teste sem HTTP em test_user_answer_evaluator.py.
"""


async def test_campos_novos_chegam_ao_evaluator(client, fakes):
    response = await client.post(
        "/api/v1/evaluate/user-answer",
        json={
            "item_content": "conteudo do item",
            "is_malicious": False,
            "user_verdict": False,
            "user_justification": "dominio oficial, sem pedido de credencial",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "acerto_por_sorte" in body

    call = fakes["user_answer_evaluator"].calls[0]
    assert call["item_content"] == "conteudo do item"
    assert call["is_malicious"] is False
    assert call["user_verdict"] is False
    assert call["user_justification"] == "dominio oficial, sem pedido de credencial"


async def test_as_quatro_combinacoes_rotulo_x_veredito_respondem_200(client, fakes):
    """Nenhuma das quatro combinacoes deve quebrar o endpoint -- a
    logica de qual caso se aplica vive dentro do evaluator (testada
    isoladamente em test_user_answer_evaluator.py), o endpoint so
    precisa repassar os campos sem se importar com qual combinacao e.
    """
    combinacoes = [
        (True, True),
        (True, False),
        (False, False),
        (False, True),
    ]

    for is_malicious, user_verdict in combinacoes:
        response = await client.post(
            "/api/v1/evaluate/user-answer",
            json={
                "item_content": "conteudo do item",
                "is_malicious": is_malicious,
                "user_verdict": user_verdict,
                "user_justification": "justificativa de teste",
            },
        )
        assert response.status_code == 200, f"falhou para is_malicious={is_malicious}, user_verdict={user_verdict}"

    assert len(fakes["user_answer_evaluator"].calls) == 4
