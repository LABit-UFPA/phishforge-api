"""Smoke dos eixos E2-E5 (passo pos-PRs do plano de producao): gera com o
Sonnet 4.6 alguns itens de cada eixo x nivel ainda nao exercitados (a
comparacao e os smokes anteriores focaram E1 e cenario C), confirma que saem
validos (sem marcador/artefato/link invalido) e serve de MEDIDOR do custo real
por item antes de comprometer o lote grande.

Geracao-only (sem juizes RAGAS) -- o criterio aqui e "gera item valido" e o
custo, nao a nota. Reaproveita o caminho de geracao do eval (construir_gerador).

Como MEDIR o US$/item de verdade (a API nao expoe o custo aqui):
  1. Anote o saldo da Anthropic ANTES de rodar.
  2. Rode este smoke.
  3. Anote o saldo DEPOIS. custo/item = (antes - depois) / itens_gerados.
Este caminho (por-contexto) NAO amortiza normalizacao/HyDE/fusao como o lote de
producao (batch worker) faz sobre 50 itens, entao o US$/item do LOTE tende a
ser MENOR que o medido aqui -- util como teto.

Uso (dentro do Docker):
  docker run --rm --network phishforge_network \
    -e QDRANT_URL=http://phishforge-qdrant:6333 \
    -e GIT_COMMIT=$(git rev-parse --short HEAD) \
    -v "$PWD":/app -w /app phishforge-api-phishforge-api:latest \
    sh -c "poetry install ... --with evaluation; \
           poetry run python -m script.smoke_eixos --por-celula 1"
"""

import argparse
import asyncio
from collections import Counter, defaultdict

from qdrant_client import QdrantClient

from app.core.config import settings
from app.domain.models.difficulty import Difficulty
from app.domain.services.item_validation import (
    encontrar_disclaimer_de_simulacao,
    encontrar_links_invalidos,
    encontrar_marcadores,
)
from app.domain.services.openai.embedding_client import OpenAIEmbeddingClient
from app.domain.services.reranker import ReRanker
from app.domain.services.response_generator import ItemInvalidoError
from app.infra.qdrant.store import QdrantVectorStore
from script.avaliar_modelos_llm import (
    COLLECTION_NAME,
    EMBEDDING_DA_BASE,
    MODELOS_A_TESTAR,
    TOP_K_RETRIEVE,
    TOP_N_PARA_FUSAO,
    XLSX_PADRAO,
    _classificar_erro,
    _ficha_do_contexto,
    _ler_aba_lotes,
    construir_gerador,
)

SEED = 42
EIXOS_PADRAO = ("E2", "E3", "E4", "E5")


def _selecionar(contextos, eixos, por_celula):
    """`por_celula` contextos por (eixo x nivel), deterministico (ordena por
    cenario). So os eixos pedidos."""
    por_grade = defaultdict(list)
    for c in contextos:
        if c.eixo in eixos:
            por_grade[(c.eixo, c.nivel)].append(c)
    escolhidos = []
    for chave in sorted(por_grade):
        escolhidos.extend(sorted(por_grade[chave], key=lambda c: c.cenario)[:por_celula])
    return escolhidos


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--por-celula", type=int, default=1, help="contextos por eixo x nivel")
    ap.add_argument("--eixos", default=",".join(EIXOS_PADRAO), help="eixos (virgula)")
    args = ap.parse_args()
    eixos = tuple(e.strip() for e in args.eixos.split(",") if e.strip())

    sonnet = next(m for m in MODELOS_A_TESTAR if m.model == "claude-sonnet-4-6")
    openai_key = settings.OPENAI_API_KEY
    anthropic_key = settings.ANTHROPIC_API_KEY
    if not (openai_key and anthropic_key):
        raise SystemExit("OPENAI_API_KEY e ANTHROPIC_API_KEY sao necessarias (.env).")

    contextos = _selecionar(_ler_aba_lotes(XLSX_PADRAO), eixos, args.por_celula)
    print(f"Eixos {eixos} x niveis, {args.por_celula}/celula -> {len(contextos)} contextos.")

    qdrant = QdrantClient(url=settings.QDRANT_URL)
    embedding = OpenAIEmbeddingClient(api_key=openai_key, model=EMBEDDING_DA_BASE)
    vector_store = QdrantVectorStore(client=qdrant, embedding_client=embedding)
    reranker = ReRanker()
    rg, norm = construir_gerador(sonnet, openai_key, anthropic_key, SEED)

    sucessos = 0
    falhas_por_motivo: Counter = Counter()
    itens_com_artefato = 0
    regen_total = Counter()

    for ctx in contextos:
        rotulo = f"{ctx.eixo}-{ctx.nivel[:1]}-{ctx.cenario} ({ctx.lote_id})"
        try:
            difficulty = Difficulty(ctx.nivel).value
            normalized = await norm.normalize(ctx.texto)
            try:
                hyde = await rg.generate_hypothetical_answer(normalized.search_query)
            except Exception:
                hyde = normalized.search_query
            candidatos = vector_store.query(
                collection_name=COLLECTION_NAME, query_text=hyde, top_k=TOP_K_RETRIEVE
            )
            reranked = reranker.rerank(normalized.search_query, candidatos)
            contexts = [
                doc.payload["parent_content"]
                for doc in reranked[:TOP_N_PARA_FUSAO]
                if "parent_content" in doc.payload
            ]
            fused = await rg.fuse_and_summarize_context(
                generation_context=normalized.generation_context, contexts=contexts
            )
            ficha = _ficha_do_contexto(ctx, difficulty, SEED)
            draft = await rg.generate_response(
                difficulty=difficulty,
                context=normalized.generation_context,
                relevant_docs=fused,
                is_malicious=True,
                variacao=ficha,
            )
        except ItemInvalidoError as e:
            falhas_por_motivo[_classificar_erro(e)] += 1
            print(f"[FALHA ] {rotulo}: {e}")
            continue
        except Exception as e:  # noqa: BLE001
            falhas_por_motivo[_classificar_erro(e)] += 1
            print(f"[ERRO  ] {rotulo}: {type(e).__name__}: {e}")
            continue

        sucessos += 1
        v = draft.validacao or {}
        for chave in ("regeneracoes_por_marcador", "regeneracoes_por_link",
                      "regeneracoes_por_remetente", "regeneracoes_por_disclaimer"):
            regen_total[chave] += v.get(chave, 0) or 0
        textos_link = [l.text for l in draft.links]
        artefatos = (
            encontrar_marcadores(draft.remetente, draft.assunto, draft.conteudo,
                                 textos_de_link=textos_link)
            + encontrar_disclaimer_de_simulacao(draft.remetente, draft.assunto,
                                                draft.conteudo, *textos_link)
            + [h for h, _ in encontrar_links_invalidos(draft.links)]
        )
        if artefatos:
            itens_com_artefato += 1
            print(f"[ARTEF ] {rotulo}: {artefatos}")
        else:
            print(f"[ OK   ] {rotulo}: assunto={draft.assunto!r}")

    print("\n==================== RESUMO EIXOS ====================")
    print(f"contextos                 : {len(contextos)}")
    print(f"itens gerados com sucesso : {sucessos}")
    print(f"falhas (por motivo)       : {dict(falhas_por_motivo) or '{}'}")
    print(f"itens com artefato        : {itens_com_artefato}  (alvo: 0)")
    print(f"regeneracoes              : {dict(regen_total)}")
    print("-----------------------------------------------------")
    print("CUSTO: a API nao expoe o valor aqui. Pegue o US$/item assim:")
    print("  (saldo Anthropic ANTES - saldo DEPOIS) / itens gerados.")
    print("  Este caminho por-contexto NAO amortiza normalizacao/HyDE/fusao")
    print("  (o lote de producao amortiza sobre 50), entao e um TETO do custo.")
    print("=====================================================")
    return 0 if itens_com_artefato == 0 and sucessos > 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
