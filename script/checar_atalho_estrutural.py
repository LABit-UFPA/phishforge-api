"""Checagem anti-atalho da issue #3.

Antes de considerar o corpus misto (malicioso/legitimo) pronto, a
issue pede para rodar um lote de 20+ itens e confirmar que NENHUMA
variavel estrutural (presenca de link, numero de links, tamanho do
conteudo, saudacao, prazo) separa 100% as classes -- e o mesmo vicio
ja presente nos exemplos manuais do app (links.isEmpty prediz o rotulo
em 8 de 8 itens la).

Este script NAO foi executado contra geracao real neste PR: exige
OPENAI_API_KEY paga para gerar o lote de teste, indisponivel neste
ambiente. Ele fica pronto para rodar assim que houver orcamento --
ver nota na descricao do PR.

Uso:
    poetry run python script/checar_atalho_estrutural.py [--limit N]

Le os ultimos N itens (default 60) direto do Postgres configurado em
.env e imprime, para cada variavel candidata, a tabela cruzada contra
`is_malicious`. Termina com exit code 1 se alguma variavel separar as
duas classes perfeitamente (uma combinacao com 100% de um lado e 0%
do outro), e 0 caso contrario.

`tem_saudacao` e `tem_prazo` sao heuristicas de regex, nao NLP -- uma
aproximacao para triagem rapida, nao um classificador validado. Um
alerta destas duas colunas pede confirmacao manual antes de agir; um
alerta de `tem_link`/`n_links`/`tam_conteudo_bucket` e mais confiavel,
porque sao contagens exatas.
"""

import argparse
import asyncio
import re
import sys
from collections import defaultdict

from app.core.config import settings
from app.infra.database.connection import DatabaseConnection
from app.infra.database.repositories.phishing_repository import PhishingEmailRepository

# Heuristica, nao classificador: saudacao GENERICA reconhecida quando o
# nome logo apos "Prezado(a)"/"Olá"/"Caro(a)" e um destes termos
# (client, usuario, etc.) em vez de um nome proprio.
_SAUDACAO_GENERICA_RE = re.compile(
    r"\b(prezad[oa]s?|ol[áa]|car[oa]s?)\b[,:\s]+(cliente|usu[áa]rio|senhor|senhora|colaborador[a]?)\b",
    re.IGNORECASE,
)
_SAUDACAO_QUALQUER_RE = re.compile(r"\b(prezad[oa]s?|ol[áa]|car[oa]s?)\b", re.IGNORECASE)

_PRAZO_RE = re.compile(
    # \d+ (nao \d): um so digito quebraria o \b de fechamento no meio
    # de um numero com mais de um digito (ex.: "até 24" -- o \b entre
    # '2' e '4' nao existe, os dois sao caracteres de palavra).
    r"\b(prazo|até\s+\d+|em\s+\d+\s*(hora|dia|minuto)s?|vence|expira|urgente|imediatamente)\b",
    re.IGNORECASE,
)


def _tem_saudacao_personalizada(conteudo: str) -> bool:
    """True se ha saudacao (Prezado/Olá/Caro) que NAO seja generica.
    Ausencia total de saudacao tambem conta como False.
    """
    return bool(_SAUDACAO_QUALQUER_RE.search(conteudo)) and not _SAUDACAO_GENERICA_RE.search(
        conteudo
    )


def _tem_prazo(conteudo: str) -> bool:
    return bool(_PRAZO_RE.search(conteudo))


def _bucket_tamanho(conteudo: str) -> str:
    tamanho = len(conteudo)
    if tamanho < 500:
        return "curto(<500)"
    if tamanho < 1500:
        return "medio(500-1500)"
    return "longo(>1500)"


def _crosstab(items, variavel_fn, nome_variavel: str) -> dict:
    tabela = defaultdict(lambda: {"malicioso": 0, "legitimo": 0})
    for item in items:
        chave = variavel_fn(item)
        tabela[chave]["malicioso" if item.is_malicious else "legitimo"] += 1
    return dict(tabela)


def _tem_separacao_perfeita(tabela: dict) -> bool:
    """True se alguma combinacao (variavel=valor) tiver so maliciosos ou
    so legitimos, E os dois rotulos aparecerem no lote inteiro (senao a
    checagem nao faz sentido -- um lote 100% malicioso "separa
    perfeitamente" qualquer variavel trivialmente).
    """
    total_malicioso = sum(v["malicioso"] for v in tabela.values())
    total_legitimo = sum(v["legitimo"] for v in tabela.values())
    if total_malicioso == 0 or total_legitimo == 0:
        return False

    for contagem in tabela.values():
        so_malicioso = contagem["malicioso"] > 0 and contagem["legitimo"] == 0
        so_legitimo = contagem["legitimo"] > 0 and contagem["malicioso"] == 0
        if so_malicioso or so_legitimo:
            return True
    return False


async def main(limit: int) -> int:
    db = DatabaseConnection(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
    )
    await db.create_pool()
    repo = PhishingEmailRepository(db=db)

    try:
        items = await repo.list_emails(limit=limit, offset=0)
    finally:
        await db.close_pool()

    if len(items) < 20:
        print(
            f"AVISO: apenas {len(items)} itens encontrados. A issue #3 pede pelo menos "
            "20 para esta checagem ter sentido estatistico -- resultado abaixo e so "
            "indicativo."
        )

    variaveis = {
        "tem_link": lambda item: len(item.links) > 0,
        "n_links": lambda item: len(item.links),
        "tam_conteudo_bucket": lambda item: _bucket_tamanho(item.conteudo),
        "tem_saudacao_personalizada": lambda item: _tem_saudacao_personalizada(item.conteudo),
        "tem_prazo": lambda item: _tem_prazo(item.conteudo),
    }

    algum_atalho_encontrado = False
    for nome_variavel, fn in variaveis.items():
        tabela = _crosstab(items, fn, nome_variavel)
        print(f"\n=== {nome_variavel} ===")
        for valor, contagem in sorted(tabela.items(), key=str):
            print(f"  {valor!r}: malicioso={contagem['malicioso']} legitimo={contagem['legitimo']}")

        if _tem_separacao_perfeita(tabela):
            print(f"  !! ATALHO ESTRUTURAL: '{nome_variavel}' separa as classes perfeitamente.")
            algum_atalho_encontrado = True

    print()
    if algum_atalho_encontrado:
        print("RESULTADO: pelo menos um atalho estrutural encontrado -- revisar o prompt antes de aceitar o lote.")
        return 1

    print("RESULTADO: nenhuma variavel candidata separou as classes perfeitamente.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=60, help="Quantos itens recentes analisar (default: 60)")
    args = parser.parse_args()

    sys.exit(asyncio.run(main(args.limit)))
