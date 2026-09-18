"""Prova de que a maquina de integracao funciona de ponta a ponta:
Postgres real, schema aplicado pelas migrations do flyway, INSERT e
SELECT pelo repositorio de verdade.

Este e o fixture que a futura correcao da #2 vai reaproveitar para o
proprio criterio de aceite dela ("nivel persistido igual ao pedido --
consultar o banco, nao so a resposta").
"""

import uuid

import asyncpg
import pytest

from app.domain.models.phishing_email import PhishingEmail


def _email_de_teste(**overrides) -> PhishingEmail:
    base = dict(
        receptor="alvo@example.com",
        remetente="remetente@example.com",
        assunto="Assunto de teste de integracao",
        conteudo="Conteudo de teste de integracao.",
        explicacao="Explicacao de teste.",
        nivel="medio",
        categoria="teste_integracao",
        links=[],
    )
    base.update(overrides)
    return PhishingEmail(**base)


async def test_create_e_get_by_id_fazem_roundtrip(phishing_repository):
    email = _email_de_teste()

    email_id = await phishing_repository.create(email)
    assert isinstance(email_id, uuid.UUID)

    lido = await phishing_repository.get_by_id(email_id)
    assert lido is not None
    assert lido.assunto == email.assunto
    assert lido.nivel == "medio"


async def test_nivel_fora_do_vocabulario_e_rejeitado_pelo_check(phishing_repository):
    """phishing_emails_nivel_check (migration V20260517120000) e a
    ultima linha de defesa contra nivel invalido chegando ao banco.
    Este teste falha se uma migration futura afrouxar o CHECK sem
    querer -- inclusive a propria correcao da #2, que deve manter essa
    garantia, so que fazendo o valor invalido nunca chegar ate aqui
    (422 antes do INSERT, nao um CHECK pego em cima da hora).
    """
    email = _email_de_teste(nivel="nivel_que_nao_existe")

    with pytest.raises(asyncpg.exceptions.CheckViolationError):
        await phishing_repository.create(email)
