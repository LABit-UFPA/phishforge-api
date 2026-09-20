"""Fundacao do modulo de especialistas (issue #36) contra Postgres real:
constraints da migration e o fluxo completo pela API, inclusive a
checagem de `revogado_em` no banco a cada request.
"""

from uuid import uuid4

import asyncpg
import pytest

from app.domain.models.phishing_email import PhishingEmail
from app.domain.services.expert_auth_service import ExpertAuthService


def _email() -> PhishingEmail:
    return PhishingEmail(
        receptor="a@b.com", remetente="c@d.com", assunto="assunto", conteudo="conteudo",
        explicacao="explicacao", nivel="facil", categoria="teste", is_malicious=True,
    )


async def _rodada_com_especialista(rounds, experts, phishing_repository, status="aberta", itens=2):
    rodada = await rounds.create(
        nome="Rodada de integracao", tcle_versao="v1", tcle_texto_md="# TCLE", status=status
    )
    for ordem in range(1, itens + 1):
        await rounds.adicionar_item(rodada.id, await phishing_repository.create(_email()), ordem)
    codigo = ExpertAuthService.gerar_codigo()
    esp = await experts.create(
        nome="Ana", sobrenome="Souza", email=f"{uuid4()}@example.com",
        codigo_hash=ExpertAuthService.hash_codigo(codigo),
        codigo_prefixo=ExpertAuthService.prefixo_codigo(codigo), rodada_id=rodada.id,
    )
    return rodada, esp, codigo


async def test_roundtrip_de_especialista_sem_expor_o_hash(evaluation_round_repository, expert_repository, phishing_repository):
    _, esp, codigo = await _rodada_com_especialista(evaluation_round_repository, expert_repository, phishing_repository)

    achado = await expert_repository.get_by_codigo_hash(ExpertAuthService.hash_codigo(codigo))

    assert achado.id == esp.id
    assert achado.codigo_prefixo == codigo[:4]
    assert "codigo_hash" not in achado.model_dump()
    assert await expert_repository.get_by_codigo_hash("0" * 64) is None


async def test_consentimento_perfil_e_revogacao_persistem(evaluation_round_repository, expert_repository, phishing_repository):
    _, esp, _ = await _rodada_com_especialista(evaluation_round_repository, expert_repository, phishing_repository)
    perfil = {"anos_experiencia": 5, "area_atuacao": "SOC", "formacao": "Mestrado"}

    await expert_repository.registrar_consentimento(esp.id, "v1")
    await expert_repository.registrar_perfil(esp.id, perfil)
    primeira = await expert_repository.revogar(esp.id)
    segunda = await expert_repository.revogar(esp.id)

    lido = await expert_repository.get_by_id(esp.id)
    assert lido.consentimento_versao == "v1" and lido.consentimento_em is not None
    assert lido.perfil_json == perfil and lido.perfil_em is not None
    assert primeira == segunda == lido.revogado_em  # idempotente: preserva a data original


async def test_rodada_rejeita_item_e_ordem_duplicados(evaluation_round_repository, phishing_repository):
    rodada = await evaluation_round_repository.create(nome="r", tcle_versao="v1", tcle_texto_md="t")
    email_a = await phishing_repository.create(_email())
    email_b = await phishing_repository.create(_email())
    await evaluation_round_repository.adicionar_item(rodada.id, email_a, 1)

    with pytest.raises(asyncpg.UniqueViolationError):
        await evaluation_round_repository.adicionar_item(rodada.id, email_a, 2)  # mesmo item
    with pytest.raises(asyncpg.UniqueViolationError):
        await evaluation_round_repository.adicionar_item(rodada.id, email_b, 1)  # mesma ordem
    assert await evaluation_round_repository.contar_itens(rodada.id) == 1


async def test_item_de_uma_rodada_nao_pode_ser_apagado(evaluation_round_repository, phishing_repository):
    rodada = await evaluation_round_repository.create(nome="r", tcle_versao="v1", tcle_texto_md="t")
    email_id = await phishing_repository.create(_email())
    await evaluation_round_repository.adicionar_item(rodada.id, email_id, 1)

    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await phishing_repository.delete(email_id)  # ON DELETE RESTRICT


async def test_rodada_com_status_invalido_e_rejeitada(evaluation_round_repository):
    with pytest.raises(asyncpg.CheckViolationError):
        await evaluation_round_repository.create(nome="r", tcle_versao="v1", tcle_texto_md="t", status="inventado")


async def test_email_de_especialista_e_unico(expert_repository):
    email = f"{uuid4()}@example.com"
    # hashes unicos por execucao: o banco pode ser reaproveitado entre rodadas
    await expert_repository.create("A", "B", email, uuid4().hex * 2, "AAAA")

    with pytest.raises(asyncpg.UniqueViolationError):
        await expert_repository.create("C", "D", email, uuid4().hex * 2, "BBBB")


async def test_fluxo_completo_pela_api_e_revogacao_imediata(
    expert_client_real, evaluation_round_repository, expert_repository, phishing_repository, db_connection
):
    _, esp, codigo = await _rodada_com_especialista(
        evaluation_round_repository, expert_repository, phishing_repository, itens=2
    )
    h = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731

    sessao = await expert_client_real.post("/api/v1/expert/session", json={"codigo_acesso": codigo})
    assert sessao.status_code == 200, sessao.text
    token = sessao.json()["token"]
    assert sessao.json()["progresso"]["total"] == 2

    assert (await expert_client_real.get("/api/v1/expert/tcle", headers=h(token))).json()["versao"] == "v1"
    consent = await expert_client_real.post("/api/v1/expert/consentimento", headers=h(token), json={"versao": "v1", "aceito": True})
    assert consent.json()["consentimento"]["necessario"] is False
    perfil = await expert_client_real.post(
        "/api/v1/expert/perfil", headers=h(token),
        json={"anos_experiencia": 4, "area_atuacao": "Pentest", "formacao": "OSCP"},
    )
    assert perfil.json()["perfil"]["necessario"] is False

    async with db_connection.get_connection() as conn:
        linha = await conn.fetchrow("SELECT codigo_hash, ultimo_acesso_em FROM especialistas WHERE id = $1", esp.id)
    assert linha["codigo_hash"] == ExpertAuthService.hash_codigo(codigo) != codigo
    assert linha["ultimo_acesso_em"] is not None

    # Revogacao pelo proprio especialista: o MESMO token deixa de valer na hora.
    assert (await expert_client_real.post("/api/v1/expert/revogacao", headers=h(token))).status_code == 200
    assert (await expert_client_real.get("/api/v1/expert/me", headers=h(token))).status_code == 401
    assert (await expert_client_real.post("/api/v1/expert/session", json={"codigo_acesso": codigo})).status_code == 401
