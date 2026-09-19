"""Validador `PhishingEmail._conteudo_bate_com_o_canal` (issue #6):
espelha o CHECK `ck_conteudo_por_canal` do banco no nivel do modelo --
falha na construcao do objeto Python, antes de qualquer tentativa de
INSERT.
"""

import pytest

from app.domain.models.phishing_email import PhishingEmail


def _campos_email():
    return dict(
        receptor="a@b.com",
        remetente="c@d.com",
        assunto="assunto",
        conteudo="conteudo",
        explicacao="explicacao",
        nivel="facil",
        categoria="teste",
    )


def test_email_com_os_quatro_campos_e_sem_content_json_e_valido():
    email = PhishingEmail(**_campos_email())
    assert email.channel.value == "email"
    assert email.content_json is None


def test_email_sem_conteudo_e_invalido():
    campos = _campos_email()
    campos["conteudo"] = None
    with pytest.raises(ValueError, match="channel=email exige"):
        PhishingEmail(**campos)


def test_email_com_content_json_preenchido_e_invalido():
    campos = _campos_email()
    campos["content_json"] = {"url": "http://x"}
    with pytest.raises(ValueError, match="nao deve ter content_json"):
        PhishingEmail(**campos)


def test_canal_novo_com_content_json_e_sem_campos_de_email_e_valido():
    email = PhishingEmail(
        channel="website",
        content_json={"url": "http://x", "title": "t", "visible_content": "c"},
        explicacao="explicacao",
        nivel="facil",
        categoria="teste",
    )
    assert email.receptor is None
    assert email.conteudo is None


def test_canal_novo_sem_content_json_e_invalido():
    with pytest.raises(ValueError, match="exige content_json"):
        PhishingEmail(
            channel="website",
            explicacao="explicacao",
            nivel="facil",
            categoria="teste",
        )


def test_canal_novo_com_campo_de_email_preenchido_e_invalido():
    with pytest.raises(ValueError, match="nao deve ter receptor"):
        PhishingEmail(
            channel="pix_qr",
            content_json={"payload": "p", "recipient": "r", "amount": "1.00", "pix_key": "k"},
            receptor="a@b.com",
            explicacao="explicacao",
            nivel="facil",
            categoria="teste",
        )
