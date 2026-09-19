"""Contrato multicanal (issue #6): todos os 5 canais que usam
content_json -- website, phone_call, pix_qr, sms e whatsapp. Os dois
ultimos foram desbloqueados pela phishing-quest-api #68
(`buildDraftContent` passou a aceitar valor aninhado -- `links`/
`messages` como array de objetos -- em vez de `map[string]string`,
mesmo bloqueio registrado na #5 para o `links` de email). O canal
email continua exatamente como antes (ver test_generate_endpoint.py,
test_generate_is_malicious.py, etc. -- nenhum foi alterado por esta
issue e todos continuam passando).
"""

import pytest

from tests.unit._batch_helpers import post_batch_and_get_job

_SHAPE_POR_CANAL = {
    "website": {"url", "title", "visible_content"},
    "phone_call": {"caller", "transcript"},
    "pix_qr": {"payload", "recipient", "amount", "pix_key"},
    "sms": {"sender", "text", "links"},
    "whatsapp": {"sender", "display_name", "messages"},
}

_CANAIS_NOVOS = ["website", "phone_call", "pix_qr", "sms", "whatsapp"]


@pytest.mark.parametrize("channel", _CANAIS_NOVOS)
async def test_generate_em_canal_novo_devolve_content_json_no_shape_certo(client, channel):
    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "facil", "channel": channel},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["channel"] == channel
    assert set(body["content_json"].keys()) == _SHAPE_POR_CANAL[channel]
    # Campos de email ficam None -- nao um email disfarcado de outro canal.
    assert body["receptor"] is None
    assert body["remetente"] is None
    assert body["assunto"] is None
    assert body["conteudo"] is None
    assert body["id"]


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


async def test_generate_com_canal_invalido_da_422_do_pydantic(client):
    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "facil", "channel": "carta_pombo"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize("channel", _CANAIS_NOVOS)
async def test_lote_em_canal_novo_gera_itens_com_content_json(client, channel):
    job = await post_batch_and_get_job(
        client,
        {
            "context": "cobranca de fatura",
            "difficulties": ["facil"],
            "total": 2,
            "channel": channel,
        },
    )

    assert job["channel"] == channel
    assert job["status"] == "concluido"
    assert job["total_generated"] == 2
    for item in job["examples"]:
        assert item["channel"] == channel
        assert set(item["content_json"].keys()) == _SHAPE_POR_CANAL[channel]


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
