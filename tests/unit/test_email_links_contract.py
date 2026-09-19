"""Contrato de `links` na resposta HTTP (issue #5): o campo passa de
`List[str]` para `List[LinkRef]` (objeto com `text`/`href`), para
habilitar a pista `link_text_mismatch` (texto do link diferente do
destino real). Mudanca quebra-contrato deliberada -- ver docstring de
`app.domain.models.link_ref.LinkRef`.

Mesmo padrao de test_email_cues_contract.py: o foco aqui e o transporte
do gerador ate o cliente HTTP, nao a geracao em si.
"""

import pytest
from pydantic import ValidationError

from app.domain.models.link_ref import LinkRef
from app.domain.models.phishing_email import PhishingEmail


async def test_generate_propaga_links_como_objetos_ate_a_resposta(client, fakes):
    fakes["response_generator"].links_a_devolver = [
        LinkRef(text="Acessar minha conta", href="http://banc0-brasil.com/x"),
    ]

    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "facil"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["links"] == [
        {"text": "Acessar minha conta", "href": "http://banc0-brasil.com/x"}
    ]


async def test_generate_sem_links_devolve_lista_vazia(client):
    response = await client.post(
        "/api/v1/generate",
        json={"context": "cobranca de fatura", "difficulty": "facil"},
    )

    assert response.status_code == 200
    assert response.json()["links"] == []


def test_phishing_email_aceita_links_como_dicts_texto_href():
    """PhishingEmail deve validar dicts crus {"text","href"} em LinkRef
    -- e o que `_row_to_model` (repositorio) depende para reconstruir
    o email a partir do JSON persistido, sem conversao manual.
    """
    email = PhishingEmail(
        receptor="a@b.com",
        remetente="c@d.com",
        assunto="assunto",
        conteudo="conteudo",
        explicacao="explicacao",
        nivel="facil",
        categoria="teste",
        links=[{"text": "Ver fatura", "href": "https://exemplo.invalid/fatura"}],
    )

    assert email.links == [LinkRef(text="Ver fatura", href="https://exemplo.invalid/fatura")]


def test_phishing_email_rejeita_links_como_string_solta():
    """Regressao central da issue #5: o shape antigo (List[str], so o
    destino, sem texto exibido) nao pode mais passar -- e exatamente o
    que tornava link_text_mismatch inexpressavel.
    """
    with pytest.raises(ValidationError):
        PhishingEmail(
            receptor="a@b.com",
            remetente="c@d.com",
            assunto="assunto",
            conteudo="conteudo",
            explicacao="explicacao",
            nivel="facil",
            categoria="teste",
            links=["http://exemplo.invalid/so-destino"],
        )
