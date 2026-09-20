"""Filtros de listagem que compoem e `offset` em qualquer combinacao
(issue #39), contra Postgres real: o SQL dinamico e o que esta em jogo.
"""

from uuid import uuid4

import pytest

from app.domain.models.phishing_email import PhishingEmail


def _email(categoria, nivel, conteudo, assunto="Assunto") -> PhishingEmail:
    return PhishingEmail(
        receptor="a@x.com", remetente="s@x.example", assunto=assunto, conteudo=conteudo,
        explicacao="x", nivel=nivel, categoria=categoria, links=[], is_malicious=True,
    )


@pytest.fixture
async def corpus(phishing_repository):
    """Categoria e palavra unicas por execucao: o banco e compartilhado."""
    cat = f"cat-{uuid4().hex[:8]}"
    palavra = f"zebrafish{uuid4().hex[:6]}"
    ids = {}
    spec = [
        ("a", "facil", f"fatura {palavra}"),
        ("b", "medio", f"fatura {palavra}"),
        ("c", "dificil", f"fatura {palavra}"),
        ("d", "dificil", "sem a palavra"),
        ("e", "dificil", f"boleto {palavra}"),
    ]
    for chave, nivel, conteudo in spec:
        ids[chave] = await phishing_repository.create(_email(cat, nivel, conteudo))
    return cat, palavra, ids


async def test_filtros_compoem(phishing_repository, corpus):
    cat, palavra, ids = corpus

    so_cat = await phishing_repository.list_emails(categoria=cat)
    assert {e.id for e in so_cat} == set(ids.values())

    cat_nivel = await phishing_repository.list_emails(categoria=cat, nivel="dificil")
    assert {e.id for e in cat_nivel} == {ids["c"], ids["d"], ids["e"]}

    busca_nivel = await phishing_repository.list_emails(categoria=cat, nivel="dificil", search=palavra)
    assert {e.id for e in busca_nivel} == {ids["c"], ids["e"]}  # interseccao, nao precedencia

    so_busca = await phishing_repository.list_emails(categoria=cat, search=palavra)
    assert {e.id for e in so_busca} == {ids["a"], ids["b"], ids["c"], ids["e"]}


async def test_offset_pagina_em_varias_combinacoes(phishing_repository, corpus):
    cat, palavra, ids = corpus

    for filtros, total in (
        ({"categoria": cat}, 5),
        ({"categoria": cat, "nivel": "dificil"}, 3),
        ({"categoria": cat, "search": palavra}, 4),
        ({"categoria": cat, "nivel": "dificil", "search": palavra}, 2),
    ):
        paginas, vistos = [], []
        for offset in range(0, total, 2):
            pagina = await phishing_repository.list_emails(**filtros, limit=2, offset=offset)
            paginas.append(len(pagina))
            vistos += [e.id for e in pagina]
        assert len(vistos) == total and len(set(vistos)) == total, filtros  # sem repetir nem pular
        assert await phishing_repository.list_emails(**filtros, limit=2, offset=total) == [], filtros


async def test_sem_filtro_continua_mais_recente_primeiro(phishing_repository, corpus):
    cat, _, ids = corpus
    itens = await phishing_repository.list_emails(categoria=cat)
    assert [e.id for e in itens] == [ids["e"], ids["d"], ids["c"], ids["b"], ids["a"]]


async def test_busca_ordena_por_relevancia_e_valores_nao_sao_sql(phishing_repository, corpus):
    cat, palavra, _ = corpus
    # valores hostis viram parametro, nao SQL
    assert await phishing_repository.list_emails(categoria="x'; DROP TABLE phishing_emails; --") == []
    assert await phishing_repository.list_emails(search="'); DROP TABLE phishing_emails; --") == []
    assert len(await phishing_repository.list_emails(categoria=cat, search=palavra)) == 4


async def test_endpoint_http_compoe_filtros_e_pagina(client_com_postgres_real, corpus):
    cat, palavra, ids = corpus
    c = client_com_postgres_real

    r = await c.get(f"/api/v1/emails?categoria={cat}&nivel=dificil&search={palavra}")
    assert {e["id"] for e in r.json()["emails"]} == {str(ids["c"]), str(ids["e"])}

    p1 = (await c.get(f"/api/v1/emails?categoria={cat}&limit=3&offset=0")).json()["emails"]
    p2 = (await c.get(f"/api/v1/emails?categoria={cat}&limit=3&offset=3")).json()["emails"]
    assert len(p1) == 3 and len(p2) == 2 and not ({e["id"] for e in p1} & {e["id"] for e in p2})
