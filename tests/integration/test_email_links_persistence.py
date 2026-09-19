"""Persistencia de `links` como objetos {text, href} (issue #5) contra
Postgres de verdade: a coluna `links` continua JSONB (sem migration
nova -- so o shape Python muda), mas o round-trip create -> get_by_id
precisa preservar `text` e `href` de cada link.
"""

from app.domain.models.link_ref import LinkRef
from app.domain.models.phishing_email import PhishingEmail


def _email_de_teste(**overrides) -> PhishingEmail:
    base = dict(
        receptor="alvo@example.com",
        remetente="remetente@example.com",
        assunto="Assunto de teste de integracao",
        conteudo="Clique no link para regularizar.",
        explicacao="Explicacao de teste.",
        nivel="dificil",
        categoria="teste_integracao",
        links=[],
        is_malicious=True,
    )
    base.update(overrides)
    return PhishingEmail(**base)


async def test_create_persiste_e_get_by_id_recupera_links_como_objetos(phishing_repository):
    email = _email_de_teste(
        links=[
            LinkRef(text="Acessar minha conta", href="http://banc0-brasil.com/x"),
            LinkRef(text="Duvidas", href="http://banc0-brasil.com/ajuda"),
        ]
    )

    email_id = await phishing_repository.create(email)
    lido = await phishing_repository.get_by_id(email_id)

    assert lido is not None
    assert lido.links == [
        LinkRef(text="Acessar minha conta", href="http://banc0-brasil.com/x"),
        LinkRef(text="Duvidas", href="http://banc0-brasil.com/ajuda"),
    ]
    # text e href precisam sobreviver DISTINTOS -- e exatamente essa
    # separacao que habilita a pista link_text_mismatch.
    assert lido.links[0].text != lido.links[0].href


async def test_create_com_links_vazio_persiste_lista_vazia(phishing_repository):
    email = _email_de_teste(links=[])

    email_id = await phishing_repository.create(email)
    lido = await phishing_repository.get_by_id(email_id)

    assert lido.links == []
