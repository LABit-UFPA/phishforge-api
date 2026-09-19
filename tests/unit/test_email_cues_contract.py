"""Contrato de `cues` na resposta HTTP (issue #5): o campo chega do
gerador ate a resposta de /generate sem remapeamento, com o codigo da
taxonomia serializado como string (nao como membro cru do Enum).

A validacao de span/coerencia em si (ResponseGenerator._validar_cues)
tem seus proprios testes em test_response_generator_cues.py, sem HTTP
-- aqui o foco e so o transporte ate o cliente.
"""

from app.domain.models.cue import Cue, CueCode


async def test_generate_propaga_cues_ate_a_resposta(client, fakes):
    fakes["response_generator"].cues_a_devolver = [
        Cue(
            code=CueCode.TYPOSQUAT,
            evidencia="empres4.net",
            span_start=10,
            span_end=21,
        )
    ]

    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "facil"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["cues"] == [
        {
            "code": "typosquat",
            "evidencia": "empres4.net",
            "span_start": 10,
            "span_end": 21,
        }
    ]


async def test_generate_sem_cues_devolve_lista_vazia(client):
    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "facil"},
    )

    assert response.status_code == 200
    assert response.json()["cues"] == []
