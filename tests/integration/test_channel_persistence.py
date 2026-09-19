"""Persistencia multicanal (issue #6) contra Postgres de verdade:
`channel`/`content_json` (migration V20260919130000) e o CHECK
`ck_conteudo_por_canal` -- email com as 4 colunas antigas E sem
content_json, ou canal novo com content_json E sem as 4 colunas
antigas, nunca uma mistura dos dois.
"""

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
        nivel="facil",
        categoria="teste_integracao",
        is_malicious=True,
    )
    base.update(overrides)
    return PhishingEmail(**base)


async def test_email_continua_persistindo_como_antes(phishing_repository):
    """Prova de nao-regressao: email (default) persiste exatamente
    como antes da issue #6 -- mesmas colunas, sem content_json.
    """
    email = _email_de_teste()
    email_id = await phishing_repository.create(email)
    lido = await phishing_repository.get_by_id(email_id)

    assert lido.channel.value == "email"
    assert lido.content_json is None
    assert lido.conteudo == "Conteudo de teste de integracao."


@pytest.mark.parametrize(
    "channel,content_json",
    [
        ("website", {"url": "http://x.test", "title": "t", "visible_content": "c"}),
        ("phone_call", {"caller": "+5500000000000", "transcript": "roteiro"}),
        (
            "pix_qr",
            {"payload": "abc", "recipient": "Fulano", "amount": "10.00", "pix_key": "chave"},
        ),
    ],
)
async def test_canal_novo_persiste_e_recupera_content_json(
    phishing_repository, channel, content_json
):
    email = _email_de_teste(
        receptor=None,
        remetente=None,
        assunto=None,
        conteudo=None,
        channel=channel,
        content_json=content_json,
    )

    email_id = await phishing_repository.create(email)
    lido = await phishing_repository.get_by_id(email_id)

    assert lido.channel.value == channel
    assert lido.content_json == content_json
    assert lido.receptor is None
    assert lido.conteudo is None


async def test_check_rejeita_email_com_content_json_preenchido(db_connection):
    async with db_connection.get_connection() as conn:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO phishing_emails
                (receptor, remetente, assunto, conteudo, explicacao, nivel, categoria,
                 is_malicious, channel, content_json)
                VALUES ('a@b.com', 'c@d.com', 'assunto', 'conteudo', 'explicacao', 'facil',
                        'teste', true, 'email', '{"url": "x"}'::jsonb)
                """
            )


async def test_check_rejeita_canal_novo_sem_content_json(db_connection):
    async with db_connection.get_connection() as conn:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO phishing_emails
                (explicacao, nivel, categoria, is_malicious, channel)
                VALUES ('explicacao', 'facil', 'teste', true, 'website')
                """
            )


async def test_check_rejeita_channel_fora_do_vocabulario(db_connection):
    async with db_connection.get_connection() as conn:
        with pytest.raises(asyncpg.exceptions.CheckViolationError):
            await conn.execute(
                """
                INSERT INTO phishing_emails
                (explicacao, nivel, categoria, is_malicious, channel, content_json)
                VALUES ('explicacao', 'facil', 'teste', true, 'fax', '{}'::jsonb)
                """
            )
