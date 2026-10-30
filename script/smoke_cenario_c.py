"""Smoke do item 2 (plano de producao): roda o Sonnet 4.6 nos 15 contextos de
CENARIO C (5 eixos x 3 niveis) e mede a taxa de falha por MARCADOR antes/depois
do conserto da assinatura de sistema, mais a contagem de artefatos visiveis.

Base (comparacao de 29/10/2026): o Sonnet teve 5 falhas por marcador em 45
itens, 4 delas no cenario C ([UCRV], [SISTEMA ANR], [RMP], [ESM],
[AVISO AUTOMATICO] -- a assinatura de 'notificacao automatica' escrita como
rotulo entre colchetes). Alvo depois: 0 falha de marcador nos 15.

Reaproveita a construcao de gerador do eval (mesmo caminho de geracao), mas NAO
chama os juizes RAGAS -- o criterio aqui e marcador/artefato, nao a nota.

Uso (dentro do Docker):
  docker run --rm --network phishforge_network \
    -e QDRANT_URL=http://phishforge-qdrant:6333 \
    -e GIT_COMMIT=$(git rev-parse --short HEAD) \
    -v "$PWD":/app -w /app phishforge-api-phishforge-api:latest \
    sh -c "poetry install ... --with evaluation; poetry run python -m script.smoke_cenario_c"
"""

import asyncio
from collections import Counter

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


async def main() -> int:
    sonnet = next(m for m in MODELOS_A_TESTAR if m.model == "claude-sonnet-4-6")
    openai_key = settings.OPENAI_API_KEY
    anthropic_key = settings.ANTHROPIC_API_KEY
    if not (openai_key and anthropic_key):
        raise SystemExit("OPENAI_API_KEY e ANTHROPIC_API_KEY sao necessarias (.env).")

    contextos = [c for c in _ler_aba_lotes(XLSX_PADRAO) if c.cenario == "C"]
    print(f"Cenario C: {len(contextos)} contextos (esperado 15 = 5 eixos x 3 niveis).")

    qdrant = QdrantClient(url=settings.QDRANT_URL)
    embedding = OpenAIEmbeddingClient(api_key=openai_key, model=EMBEDDING_DA_BASE)
    vector_store = QdrantVectorStore(client=qdrant, embedding_client=embedding)
    reranker = ReRanker()
    rg, norm = construir_gerador(sonnet, openai_key, anthropic_key, SEED)

    sucessos = 0
    falhas_por_motivo: Counter = Counter()
    regen_marcador = 0
    regen_link = 0
    assinaturas_desembrulhadas = 0
    itens_com_artefato = 0

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
            motivo = _classificar_erro(e)
            falhas_por_motivo[motivo] += 1
            print(f"[FALHA ] {rotulo}: {motivo} -- {e}")
            continue
        except Exception as e:  # noqa: BLE001
            motivo = _classificar_erro(e)
            falhas_por_motivo[motivo] += 1
            print(f"[ERRO  ] {rotulo}: {motivo} -- {type(e).__name__}: {e}")
            continue

        sucessos += 1
        v = draft.validacao or {}
        regen_marcador += v.get("regeneracoes_por_marcador", 0) or 0
        regen_link += v.get("regeneracoes_por_link", 0) or 0
        assinaturas_desembrulhadas += v.get("assinaturas_de_sistema_desembrulhadas", 0) or 0

        # Artefato VISIVEL no item final (deve ser 0 -- o gerador ja limpa/regenera).
        textos_link = [l.text for l in draft.links]
        artefatos = (
            encontrar_marcadores(
                draft.remetente, draft.assunto, draft.conteudo, textos_de_link=textos_link
            )
            + encontrar_disclaimer_de_simulacao(
                draft.remetente, draft.assunto, draft.conteudo, *textos_link
            )
            + [h for h, _ in encontrar_links_invalidos(draft.links)]
        )
        if artefatos:
            itens_com_artefato += 1
            print(f"[ARTEF ] {rotulo}: {artefatos}")
        else:
            print(
                f"[ OK   ] {rotulo}: assunto={draft.assunto!r} | "
                f"regen_marcador={v.get('regeneracoes_por_marcador')} | "
                f"desembrulhadas={v.get('assinaturas_de_sistema_desembrulhadas')}"
            )

    falhas_marcador = falhas_por_motivo.get("validacao", 0)  # marcador cai em "validacao"
    print("\n==================== RESUMO CENARIO C ====================")
    print(f"contextos                         : {len(contextos)}")
    print(f"itens gerados com sucesso          : {sucessos}")
    print(f"falhas finais (por motivo)         : {dict(falhas_por_motivo) or '{}'}")
    print(f"itens com artefato visivel         : {itens_com_artefato}  (alvo: 0)")
    print(f"regeneracoes por marcador (soma)   : {regen_marcador}")
    print(f"regeneracoes por link (soma)       : {regen_link}")
    print(f"assinaturas de sistema desembrulhadas: {assinaturas_desembrulhadas}")
    print("---------------------------------------------------------")
    print("BASE (comparacao): 4 falhas de marcador em cenario C (de 15 itens C).")
    print(f"DEPOIS           : {falhas_marcador} falha(s) de validacao/marcador; "
          f"{itens_com_artefato} item(ns) com artefato.")
    print("=========================================================")
    return 0 if (itens_com_artefato == 0) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
