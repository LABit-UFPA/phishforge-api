"""Contrato de `is_malicious` nos dois endpoints de geracao (issue #3).

A selecao da chain (phishing vs. legitima) dentro de ResponseGenerator
tem seu proprio teste em test_response_generator_is_malicious.py, sem
HTTP. Aqui o foco e o contrato do endpoint: o campo chega, e repassado
corretamente e persiste com o valor certo. Desde a issue #11b,
/generate/batch responde 202 -- os testes do lote usam
post_batch_and_get_job para chegar no resultado final.
"""

from tests.unit._batch_helpers import post_batch_and_get_job


async def test_generate_default_e_malicious_true(client):
    """Retrocompatibilidade: quem chama /generate sem is_malicious
    continua recebendo phishing, como sempre foi.
    """
    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "medio"},
    )

    assert response.status_code == 200
    assert response.json()["is_malicious"] is True


async def test_generate_com_is_malicious_false(client, fakes):
    response = await client.post(
        "/api/v1/generate",
        json={"context": "aviso de manutencao programada", "difficulty": "facil", "is_malicious": False},
    )

    assert response.status_code == 200
    assert response.json()["is_malicious"] is False

    generate_call = next(
        c for c in fakes["response_generator"].calls if c["step"] == "generate_response"
    )
    assert generate_call["is_malicious"] is False


async def test_lote_default_malicious_ratio_gera_so_phishing(client):
    """Retrocompatibilidade: lote sem malicious_ratio continua 100%
    phishing, como antes da #3.
    """
    job = await post_batch_and_get_job(
        client, {"context": "cobranca de fatura", "difficulties": ["facil"], "total": 4}
    )

    assert all(item["is_malicious"] is True for item in job["examples"])


async def test_lote_com_malicious_ratio_compoe_com_a_distribuicao(client):
    """total=10, uma dificuldade, malicious_ratio=0.5 -> 5 maliciosos +
    5 legitimos (issue #3: a proporcao compoe com a distribuicao de
    dificuldades ja existente, sem alterar o divmod entre dificuldades).
    """
    job = await post_batch_and_get_job(
        client,
        {
            "context": "cobranca de fatura",
            "difficulties": ["facil"],
            "total": 10,
            "malicious_ratio": 0.5,
        },
    )

    assert job["total_generated"] == 10

    maliciosos = [item for item in job["examples"] if item["is_malicious"] is True]
    legitimos = [item for item in job["examples"] if item["is_malicious"] is False]
    assert len(maliciosos) == 5
    assert len(legitimos) == 5


async def test_lote_malicious_ratio_fora_do_intervalo_da_422(client):
    """422, nao mais 400 (issue #8): validado por Field(ge=0.0, le=1.0)
    em BatchGenerationRequest, no lugar do `if` manual que existia so
    para este campo.
    """
    response = await client.post(
        "/api/v1/generate/batch",
        json={
            "context": "cobranca de fatura",
            "difficulties": ["facil"],
            "total": 4,
            "malicious_ratio": 1.5,
        },
    )

    assert response.status_code == 422
