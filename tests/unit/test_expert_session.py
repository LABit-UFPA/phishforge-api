"""Sessao, TCLE, consentimento, perfil e revogacao do especialista (issue #36).

Todos os testes usam `expert_client` (SEM X-API-Key): as rotas do
especialista ficam fora do `require_api_key` do backend Go.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.api.v1.endpoints import deps
from app.domain.services.expert_auth_service import ExpertAuthService
from tests.conftest import TEST_EXPERT_JWT_SECRET


async def _cenario(fakes, status="aberta", com_rodada=True, tcle_versao="v1", itens=3):
    """Rodada + especialista + codigo em claro."""
    rounds, experts = fakes["evaluation_round_repository"], fakes["expert_repository"]
    rodada = await rounds.create(
        nome="Rodada piloto", tcle_versao=tcle_versao, tcle_texto_md="# TCLE\n\nTexto.", status=status
    )
    for ordem in range(1, itens + 1):
        await rounds.adicionar_item(rodada.id, object(), ordem)
    codigo = ExpertAuthService.gerar_codigo()
    esp = experts.adicionar(
        ExpertAuthService.hash_codigo(codigo),
        rodada_id=rodada.id if com_rodada else None,
        codigo_prefixo=codigo[:4],
    )
    return rodada, esp, codigo


async def _sessao(expert_client, codigo):
    r = await expert_client.post("/api/v1/expert/session", json={"codigo_acesso": codigo})
    assert r.status_code == 200, r.text
    return r.json()


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------- sessao

async def test_sessao_ok_sem_api_key_do_backend_go(expert_client, fakes):
    rodada, esp, codigo = await _cenario(fakes, itens=30)

    body = await _sessao(expert_client, codigo)

    assert body["token"]
    expira = datetime.fromisoformat(body["expires_at"])
    assert timedelta(hours=11, minutes=55) < expira - datetime.now(timezone.utc) <= timedelta(hours=12)
    assert body["especialista"]["id"] == str(esp.id)
    assert body["rodada"]["tcle_versao"] == "v1"
    assert body["consentimento"] == {"necessario": True, "versao": "v1"}
    assert body["perfil"] == {"necessario": True}
    assert body["progresso"] == {"total": 30, "concluidas": 0, "proxima_ordem": 1}
    assert esp.ultimo_acesso_em is not None


async def test_codigo_aceita_minusculas_e_sem_tracos(expert_client, fakes):
    _, _, codigo = await _cenario(fakes)

    await _sessao(expert_client, codigo.lower().replace("-", ""))


async def test_codigo_invalido_e_revogado_tem_a_mesma_resposta(expert_client, fakes):
    _, esp, codigo = await _cenario(fakes)
    invalido = await expert_client.post("/api/v1/expert/session", json={"codigo_acesso": "AAAA-BBBB-CCCC-DDDD"})
    esp.revogado_em = datetime.now(timezone.utc)
    revogado = await expert_client.post("/api/v1/expert/session", json={"codigo_acesso": codigo})

    assert invalido.status_code == revogado.status_code == 401
    assert invalido.json() == revogado.json()


@pytest.mark.parametrize("cenario", [{"com_rodada": False}, {"status": "rascunho"}, {"status": "encerrada"}])
async def test_sem_rodada_aberta_da_409(expert_client, fakes, cenario):
    _, _, codigo = await _cenario(fakes, **cenario)

    r = await expert_client.post("/api/v1/expert/session", json={"codigo_acesso": codigo})

    assert r.status_code == 409


async def test_sem_segredo_jwt_o_modulo_inteiro_responde_503(expert_client, app_and_fakes, fakes):
    from dependency_injector import providers

    app, _ = app_and_fakes
    _, _, codigo = await _cenario(fakes)
    app.container.expert_auth_service.override(providers.Object(ExpertAuthService("")))

    sessao = await expert_client.post("/api/v1/expert/session", json={"codigo_acesso": codigo})
    me = await expert_client.get("/api/v1/expert/me", headers=_bearer("qualquer"))

    assert sessao.status_code == 503
    assert me.status_code == 503


# ------------------------------------------------------------------ auth

@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer"}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer lixo"}])
async def test_sem_token_valido_da_401(expert_client, fakes, headers):
    await _cenario(fakes)

    assert (await expert_client.get("/api/v1/expert/me", headers=headers)).status_code == 401


async def test_token_de_outro_segredo_da_401(expert_client, fakes):
    _, esp, _ = await _cenario(fakes)
    token, _ = ExpertAuthService("outro-segredo").emitir_token(esp.id)

    assert (await expert_client.get("/api/v1/expert/me", headers=_bearer(token))).status_code == 401


async def test_token_expirado_da_401(expert_client, fakes):
    _, esp, _ = await _cenario(fakes)
    token, _ = ExpertAuthService(TEST_EXPERT_JWT_SECRET, expires_hours=-1).emitir_token(esp.id)

    assert (await expert_client.get("/api/v1/expert/me", headers=_bearer(token))).status_code == 401


async def test_revogacao_vale_na_hora_mesmo_com_token_ainda_valido(expert_client, fakes):
    _, esp, codigo = await _cenario(fakes)
    token = (await _sessao(expert_client, codigo))["token"]
    assert (await expert_client.get("/api/v1/expert/me", headers=_bearer(token))).status_code == 200

    esp.revogado_em = datetime.now(timezone.utc)

    assert (await expert_client.get("/api/v1/expert/me", headers=_bearer(token))).status_code == 401


async def test_rotas_de_geracao_continuam_exigindo_a_api_key_do_go(expert_client):
    assert (await expert_client.get("/api/v1/emails")).status_code == 401


async def test_hash_e_codigo_nunca_aparecem_em_nenhuma_resposta(expert_client, fakes):
    _, esp, codigo = await _cenario(fakes)
    hash_ = ExpertAuthService.hash_codigo(codigo)
    respostas = []

    sessao = await expert_client.post("/api/v1/expert/session", json={"codigo_acesso": codigo})
    token = sessao.json()["token"]
    respostas.append(sessao.text)
    respostas.append((await expert_client.post("/api/v1/expert/session", json={"codigo_acesso": "ERRO-ERRO-ERRO-ERRO"})).text)
    respostas.append((await expert_client.get("/api/v1/expert/me", headers=_bearer(token))).text)
    respostas.append((await expert_client.get("/api/v1/expert/tcle", headers=_bearer(token))).text)
    respostas.append((await expert_client.get("/api/v1/expert/me")).text)

    for texto in respostas:
        assert hash_ not in texto
        assert codigo not in texto
        assert "codigo_hash" not in texto
        assert "codigo_prefixo" not in texto


# ------------------------------------------------------ TCLE e consentimento

async def test_tcle_devolve_versao_e_texto(expert_client, fakes):
    _, _, codigo = await _cenario(fakes)
    token = (await _sessao(expert_client, codigo))["token"]

    r = await expert_client.get("/api/v1/expert/tcle", headers=_bearer(token))

    assert r.json() == {"versao": "v1", "texto_md": "# TCLE\n\nTexto."}


async def test_consentimento_aceito_libera_e_nova_versao_do_tcle_exige_reconsentir(expert_client, fakes):
    rodada, _, codigo = await _cenario(fakes)
    token = (await _sessao(expert_client, codigo))["token"]

    r = await expert_client.post("/api/v1/expert/consentimento", headers=_bearer(token), json={"versao": "v1", "aceito": True})
    assert r.status_code == 200
    assert r.json()["consentimento"]["necessario"] is False

    rodada.tcle_versao = "v2"  # o CEP pediu alteracao no meio da coleta
    me = await expert_client.get("/api/v1/expert/me", headers=_bearer(token))
    assert me.json()["consentimento"] == {"necessario": True, "versao": "v2"}


async def test_consentimento_recusado_da_422(expert_client, fakes):
    _, esp, codigo = await _cenario(fakes)
    token = (await _sessao(expert_client, codigo))["token"]

    r = await expert_client.post("/api/v1/expert/consentimento", headers=_bearer(token), json={"versao": "v1", "aceito": False})

    assert r.status_code == 422
    assert esp.consentimento_versao is None


async def test_consentimento_de_versao_desatualizada_da_409(expert_client, fakes):
    _, esp, codigo = await _cenario(fakes, tcle_versao="v2")
    token = (await _sessao(expert_client, codigo))["token"]

    r = await expert_client.post("/api/v1/expert/consentimento", headers=_bearer(token), json={"versao": "v1", "aceito": True})

    assert r.status_code == 409
    assert esp.consentimento_versao is None


# ------------------------------------------------------------------ perfil

async def test_perfil_e_registrado(expert_client, fakes):
    _, esp, codigo = await _cenario(fakes)
    token = (await _sessao(expert_client, codigo))["token"]
    perfil = {"anos_experiencia": 7, "area_atuacao": "Resposta a incidentes", "formacao": "CISSP"}

    r = await expert_client.post("/api/v1/expert/perfil", headers=_bearer(token), json=perfil)

    assert r.status_code == 200
    assert r.json()["perfil"] == {"necessario": False}
    assert esp.perfil_json == perfil


@pytest.mark.parametrize("perfil", [
    {"anos_experiencia": -1, "area_atuacao": "x", "formacao": "y"},
    {"anos_experiencia": 3, "area_atuacao": "", "formacao": "y"},
    {"anos_experiencia": 3, "area_atuacao": "x"},
])
async def test_perfil_invalido_da_422(expert_client, fakes, perfil):
    _, _, codigo = await _cenario(fakes)
    token = (await _sessao(expert_client, codigo))["token"]

    assert (await expert_client.post("/api/v1/expert/perfil", headers=_bearer(token), json=perfil)).status_code == 422


# --------------------------------------------------------------- revogacao

async def test_revogacao_e_idempotente_e_bloqueia_o_acesso(expert_client, fakes):
    _, esp, codigo = await _cenario(fakes)
    token = (await _sessao(expert_client, codigo))["token"]

    primeira = await expert_client.post("/api/v1/expert/revogacao", headers=_bearer(token))

    assert primeira.status_code == 200
    assert esp.revogado_em is not None
    assert (await expert_client.get("/api/v1/expert/me", headers=_bearer(token))).status_code == 401
    assert (await expert_client.post("/api/v1/expert/session", json={"codigo_acesso": codigo})).status_code == 401


async def test_revogar_funciona_com_a_rodada_encerrada(expert_client, fakes):
    rodada, _, codigo = await _cenario(fakes)
    token = (await _sessao(expert_client, codigo))["token"]
    rodada.status = "encerrada"

    assert (await expert_client.post("/api/v1/expert/revogacao", headers=_bearer(token))).status_code == 200


# -------------------------------------------------------- require_researcher

async def test_require_researcher_falha_fechado_e_compara_em_tempo_constante(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(deps.settings, "RESEARCHER_API_KEY", "")
    with pytest.raises(HTTPException) as vazio:
        await deps.require_researcher("qualquer")
    assert vazio.value.status_code == 503

    monkeypatch.setattr(deps.settings, "RESEARCHER_API_KEY", "chave-do-pesquisador")
    with pytest.raises(HTTPException) as errada:
        await deps.require_researcher("outra")
    assert errada.value.status_code == 401
    with pytest.raises(HTTPException) as ausente:
        await deps.require_researcher(None)
    assert ausente.value.status_code == 401

    assert await deps.require_researcher("chave-do-pesquisador") is None


async def test_chave_do_pesquisador_nao_e_a_do_backend_go(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(deps.settings, "API_KEY", "chave-do-go")
    monkeypatch.setattr(deps.settings, "RESEARCHER_API_KEY", "chave-do-pesquisador")

    with pytest.raises(HTTPException):
        await deps.require_researcher("chave-do-go")
