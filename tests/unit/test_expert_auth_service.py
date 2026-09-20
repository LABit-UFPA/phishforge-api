"""ExpertAuthService (issue #36): codigo de acesso e JWT de sessao."""

import re
from uuid import uuid4

import pytest

from app.domain.services.expert_auth_service import ExpertAuthError, ExpertAuthService

_AMBIGUOS = set("01ILOU") - set("U")  # 0/1/I/L/O nunca aparecem (U e valido)


def test_codigo_tem_o_formato_e_nao_usa_caracteres_ambiguos():
    for _ in range(200):
        codigo = ExpertAuthService.gerar_codigo()
        assert re.fullmatch(r"[A-Z2-9]{4}(-[A-Z2-9]{4}){3}", codigo)
        assert not (set(codigo.replace("-", "")) & _AMBIGUOS)


def test_codigos_gerados_nao_se_repetem():
    assert len({ExpertAuthService.gerar_codigo() for _ in range(500)}) == 500


def test_hash_ignora_caixa_espacos_e_tracos():
    codigo = "ABCD-EFGH-JKMN-PQRS"
    esperado = ExpertAuthService.hash_codigo(codigo)

    assert ExpertAuthService.hash_codigo("abcd-efgh-jkmn-pqrs") == esperado
    assert ExpertAuthService.hash_codigo("  ABCDEFGHJKMNPQRS ") == esperado
    assert len(esperado) == 64
    assert ExpertAuthService.hash_codigo("ABCD-EFGH-JKMN-PQRT") != esperado


def test_token_ida_e_volta():
    svc = ExpertAuthService("segredo", expires_hours=12)
    especialista_id = uuid4()

    token, expira = svc.emitir_token(especialista_id)

    assert svc.validar_token(token) == especialista_id
    assert expira.tzinfo is not None


def test_token_de_outro_segredo_e_recusado():
    token, _ = ExpertAuthService("segredo-a").emitir_token(uuid4())
    with pytest.raises(ExpertAuthError):
        ExpertAuthService("segredo-b").validar_token(token)


def test_token_expirado_e_recusado():
    svc = ExpertAuthService("segredo", expires_hours=-1)
    token, _ = svc.emitir_token(uuid4())
    with pytest.raises(ExpertAuthError):
        svc.validar_token(token)


@pytest.mark.parametrize("lixo", ["", "nao-e-jwt", "a.b.c"])
def test_token_malformado_e_recusado(lixo):
    with pytest.raises(ExpertAuthError):
        ExpertAuthService("segredo").validar_token(lixo)


def test_sem_segredo_nao_esta_configurado():
    assert ExpertAuthService("").configurado is False
    assert ExpertAuthService("x").configurado is True
