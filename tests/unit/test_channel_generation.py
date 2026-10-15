"""Contrato de canal na geracao (issue #6).

Por ora /generate e /generate/batch so geram `email`
(GENERATION_SUPORTADOS em app/domain/models/channel.py). Os outros 5
canais do vocabulario -- website, phone_call, pix_qr, sms e whatsapp --
continuam validos no enum `Channel` (alinhado com o Go), mas pedir
qualquer um deles na geracao da 422 antes de gastar LLM ou criar job.
O gerador desses canais continua coberto em
test_response_generator_channel_dispatch.py, para reabilita-los sem
surpresa.
"""

import pytest

from tests.unit._batch_helpers import post_batch_and_get_job

_CANAIS_DESABILITADOS = ["website", "phone_call", "pix_qr", "sms", "whatsapp"]


@pytest.mark.parametrize("channel", _CANAIS_DESABILITADOS)
async def test_generate_em_canal_desabilitado_da_422_sem_chamar_o_llm(client, fakes, channel):
    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "facil", "channel": channel},
    )

    assert response.status_code == 422
    assert "desabilitado" in response.json()["detail"]
    # Recusado antes da pipeline: nem normalizacao, nem geracao.
    assert fakes["prompt_normalizer"].calls == []
    assert fakes["response_generator"].calls == []


async def test_generate_sem_channel_continua_email_por_padrao(client):
    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "facil"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["channel"] == "email"
    assert body["content_json"] is None
    assert body["conteudo"] is not None


async def test_generate_com_channel_email_explicito_gera_email(client):
    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "facil", "channel": "email"},
    )

    assert response.status_code == 200
    assert response.json()["channel"] == "email"


async def test_generate_com_canal_invalido_da_422_do_pydantic(client):
    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "facil", "channel": "carta_pombo"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("channel", _CANAIS_DESABILITADOS)
async def test_lote_em_canal_desabilitado_da_422_antes_de_criar_job(client, fakes, channel):
    response = await client.post(
        "/api/v1/generate/batch",
        json={
            "context": "cobranca de fatura",
            "difficulties": ["facil"],
            "total": 2,
            "channel": channel,
        },
    )

    assert response.status_code == 422
    assert "desabilitado" in response.json()["detail"]
    assert fakes["generation_job_repository"].storage == {}
    assert fakes["response_generator"].calls == []


async def test_lote_com_canal_invalido_da_422_antes_de_criar_job(client):
    response = await client.post(
        "/api/v1/generate/batch",
        json={
            "context": "cobranca de fatura",
            "difficulties": ["facil"],
            "channel": "carta_pombo",
        },
    )

    assert response.status_code == 422


async def test_lote_sem_channel_continua_email_por_padrao(client):
    job = await post_batch_and_get_job(
        client, {"context": "cobranca de fatura", "difficulties": ["facil"], "total": 1}
    )

    assert job["channel"] == "email"
    assert job["examples"][0]["content_json"] is None
