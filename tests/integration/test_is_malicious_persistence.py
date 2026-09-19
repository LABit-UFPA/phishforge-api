"""Criterio de aceite da issue #3, no mesmo espirito do que a #2 exige
para nivel: consultar o banco depois do INSERT, nao so a resposta HTTP.
"""

from uuid import UUID

import pytest


@pytest.mark.parametrize(
    "is_malicious_enviado",
    [True, False],
)
async def test_is_malicious_persistido_bate_com_o_solicitado(
    client_com_postgres_real, phishing_repository, is_malicious_enviado
):
    response = await client_com_postgres_real.post(
        "/api/v1/generate",
        json={
            "context": "aviso de manutencao programada do sistema interno",
            "difficulty": "medio",
            "is_malicious": is_malicious_enviado,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_malicious"] == is_malicious_enviado

    persistido = await phishing_repository.get_by_id(UUID(body["id"]))
    assert persistido is not None
    assert persistido.is_malicious == is_malicious_enviado


async def test_lote_com_malicious_ratio_persiste_os_dois_rotulos(
    client_com_postgres_real, phishing_repository
):
    """Desde a issue #11b, /generate/batch responde 202 -- o resultado
    e lido via polling em GET /generate/batch/{job_id}.
    """
    post_response = await client_com_postgres_real.post(
        "/api/v1/generate/batch",
        json={
            "context": "cobranca de fatura",
            "difficulties": ["facil"],
            "total": 4,
            "malicious_ratio": 0.5,
        },
    )
    assert post_response.status_code == 202
    job_id = post_response.json()["job_id"]

    get_response = await client_com_postgres_real.get(f"/api/v1/generate/batch/{job_id}")
    assert get_response.status_code == 200
    job = get_response.json()
    assert job["status"] == "concluido"
    ids = [UUID(item["id"]) for item in job["examples"]]

    persistidos = [await phishing_repository.get_by_id(i) for i in ids]
    assert all(p is not None for p in persistidos)

    rotulos = [p.is_malicious for p in persistidos]
    assert rotulos.count(True) == 2
    assert rotulos.count(False) == 2
