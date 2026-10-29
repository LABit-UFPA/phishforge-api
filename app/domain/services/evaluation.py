import logging
from typing import Any, Optional

from pydantic import BaseModel, Field
from ragas.metrics.collections import (
    AnswerRelevancy,
    ContextRelevance,
    Faithfulness,
)

logging.basicConfig(level=logging.INFO)
evaluation_logger = logging.getLogger("ragas_evaluation")


class NotaQualidade(BaseModel):
    """Saida estruturada do juiz para a rubrica de qualidade do item."""

    nota: int = Field(description="Nota inteira de 1 a 5")
    justificativa: str = Field(description="Uma frase curta justificando a nota")


# Rubrica holistica, reference-free e CIENTE DO NIVEL (piloto de
# comparacao de modelos): mede quao bem o e-mail cumpre o item pedido,
# sem penalizar o nivel facil por ser amador de proposito. O juiz e o
# MESMO fixo da comparacao (llm_factory), para a nota ser comparavel
# entre modelos. Criterios aprovados com o pesquisador -- registrar no
# metodo do artigo junto da versao do RAGAS e do juiz.
_RUBRICA_QUALIDADE = (
    "Você avalia um e-mail gerado para um experimento academico de deteccao de "
    "phishing. O e-mail foi PEDIDO para:\n"
    "- CENÁRIO: {cenario}\n"
    "- NÍVEL DE DIFICULDADE: {nivel} (fácil = DEVE ser obviamente suspeito/amador; "
    "médio = plausível, com alguns sinais de suspeita; difícil = quase indistinguível "
    "de uma comunicação legítima).\n\n"
    "Dê uma nota INTEIRA de 1 a 5 para o quão bem o e-mail cumpre esse pedido, "
    "considerando: aderência ao cenário, adequação ao nível pedido, português correto "
    "e coeso, estrutura de e-mail plausível e ausência de artefatos (marcadores de "
    "template não preenchidos, texto quebrado).\n"
    "- 5: cumpre plenamente o cenário e o nível; texto impecável; sem artefatos.\n"
    "- 4: cumpre bem; no máximo um deslize pequeno.\n"
    "- 3: aceitável, com elementos genéricos ou leve desajuste de nível/cenário.\n"
    "- 2: cumpre mal: foge do cenário/nível, tom artificial, ou falhas de forma.\n"
    "- 1: não cumpre: fora do cenário, nível errado, artefatos evidentes ou incoerente.\n\n"
    "E-MAIL:\n{email}\n"
)


async def avaliar_qualidade_rubrica(
    eval_llm: Any, cenario: str, nivel: str, email: str
) -> dict:
    """Nota 1-5 de qualidade do e-mail pela rubrica, dada pelo juiz fixo
    (`eval_llm` do `llm_factory`, que expoe `.agenerate(prompt, modelo)`
    -- o mesmo mecanismo das metricas de `collections`). Devolve
    {'qualidade': float|None, 'qualidade_justificativa': str|None}.
    """
    prompt = _RUBRICA_QUALIDADE.format(cenario=cenario, nivel=nivel, email=email)
    try:
        res = await eval_llm.agenerate(prompt, NotaQualidade)
        nota = max(1, min(5, int(res.nota)))  # clamp defensivo
        return {
            "qualidade": float(nota),
            "qualidade_justificativa": getattr(res, "justificativa", "") or "",
        }
    except Exception as e:
        evaluation_logger.error(f"Erro na rubrica de qualidade: {e}", exc_info=True)
        return {"qualidade": None, "qualidade_justificativa": None, "error": str(e)}


def _valor(resultado: Any) -> Optional[float]:
    """Le a nota das metricas do RAGAS 0.4: `ascore` devolve um
    MetricResult com `.value` (antes era um float direto). Tolera um
    float cru por seguranca.
    """
    if resultado is None:
        return None
    valor = getattr(resultado, "value", resultado)
    return float(valor) if valor is not None else None


async def run_ragas_evaluation(
    search_question: str,
    generation_question: str,
    expanded_answer: str,
    full_answer: str,
    contexts: list[str],
    eval_llm: Any,
    eval_embeddings: Any,
    incluir_faithfulness: bool = True,
    incluir_response_relevancy: bool = True,
) -> dict:
    """
    Executa avaliação RAGAS - TUDO EM INGLÊS.
    Usa apenas métricas reference-free (sem necessidade de ground truth).

    API do RAGAS 0.4 (migracao da 0.3.5): metricas em
    `ragas.metrics.collections`, chamadas por `ascore(**kwargs)` com
    argumentos nomeados (nao mais um `SingleTurnSample`), e a nota lida
    de `MetricResult.value`. `eval_llm` e o LLM moderno do
    `ragas.llms.llm_factory` (as metricas chamam `.agenerate`);
    `eval_embeddings`, o do `ragas.embeddings.embedding_factory`.

    Métricas:
    - Context Relevance: os contextos recuperados sao relevantes para a
      consulta de busca. Precisa de contexto -> None se nao houver.
    - Answer/Response Relevancy: a resposta responde ao cenario pedido.
      Nao usa contexto (so user_input + response), mas usa embeddings.
    - Faithfulness (OPCIONAL, default ligado por compatibilidade): mede
      quantas afirmacoes da resposta se sustentam no contexto. Faz
      sentido em RAG-QA, NAO numa geracao criativa: o e-mail de phishing
      e um cenario ficticio que nao deve repetir os artigos academicos
      recuperados, entao faithfulness fica baixo por desenho e nao mede
      qualidade do gerador. A comparacao de modelos passa
      `incluir_faithfulness=False` (ver script/avaliar_modelos_llm.py);
      a propria Tabela 2 do artigo ja usava so rel. contexto + rel.
      resposta. Mantido como opcao para quem avalia um fluxo RAG-QA de
      verdade.
    """
    resultado = {
        "context_relevance": None,
        "faithfulness": None,
        "response_relevancy": None,
    }
    try:
        tem_contexto = bool(contexts)

        if tem_contexto:
            context_scorer = ContextRelevance(llm=eval_llm)
            resultado["context_relevance"] = _valor(
                await context_scorer.ascore(
                    user_input=search_question, retrieved_contexts=contexts
                )
            )
            if incluir_faithfulness:
                faithfulness_scorer = Faithfulness(llm=eval_llm)
                resultado["faithfulness"] = _valor(
                    await faithfulness_scorer.ascore(
                        user_input=search_question,
                        response=full_answer,
                        retrieved_contexts=contexts,
                    )
                )

        if incluir_response_relevancy:
            relevancy_scorer = AnswerRelevancy(llm=eval_llm, embeddings=eval_embeddings)
            resultado["response_relevancy"] = _valor(
                await relevancy_scorer.ascore(
                    user_input=generation_question, response=expanded_answer
                )
            )

        evaluation_logger.info(f"\n{'=' * 60}")
        evaluation_logger.info("RAGAS EVALUATION (0.4, ALL IN ENGLISH)")
        evaluation_logger.info(f"{'=' * 60}")
        evaluation_logger.info(f"Context Relevance:    {resultado['context_relevance']}")
        evaluation_logger.info(f"Faithfulness:         {resultado['faithfulness']}")
        evaluation_logger.info(f"Response Relevancy:   {resultado['response_relevancy']}")
        evaluation_logger.info(f"{'=' * 60}\n")

        return resultado

    except Exception as e:
        evaluation_logger.error(f"Erro RAGAS: {str(e)}", exc_info=True)
        resultado["error"] = str(e)
        return resultado


async def run_and_log_ragas_evaluation(
    search_question: str,
    generation_question: str,
    expanded_answer: str,
    full_answer: str,
    contexts: list[str],
    eval_llm: Any,
    eval_embeddings: Any,
):
    """
    Wrapper que executa a avaliação RAGAS e exibe resultados formatados.
    """
    ragas_result = await run_ragas_evaluation(
        search_question=search_question,
        generation_question=generation_question,
        expanded_answer=expanded_answer,
        full_answer=full_answer,
        contexts=contexts,
        eval_llm=eval_llm,
        eval_embeddings=eval_embeddings,
    )

    print("\n" + "=" * 70)
    print("📊 RAGAS EVALUATION RESULTS")
    print("=" * 70)
    print(f"Search Question: {search_question[:100]}...")
    print(f"Generation Question: {generation_question[:100]}...")
    print("-" * 70)

    if ragas_result.get("error"):
        print(f"❌ ERROR: {ragas_result['error']}")
    else:
        context_rel = ragas_result.get("context_relevance")
        faithfulness_score = ragas_result.get("faithfulness")
        response_rel = ragas_result.get("response_relevancy")

        print(
            f"Context Relevance:    {context_rel:.4f}"
            if context_rel is not None
            else "Context Relevance:    N/A"
        )
        print(
            f"Faithfulness:         {faithfulness_score:.4f}"
            if faithfulness_score is not None
            else "Faithfulness:         N/A"
        )
        print(
            f"Response Relevancy:   {response_rel:.4f}"
            if response_rel is not None
            else "Response Relevancy:   N/A"
        )

        if context_rel is not None:
            if context_rel >= 0.8:
                print("✅ Context Relevance: EXCELENTE - Contexto altamente relevante")
            elif context_rel >= 0.6:
                print("⚠️  Context Relevance: BOM - Contexto parcialmente relevante")
            else:
                print("❌ Context Relevance: BAIXO - Contexto pouco relevante")

        if faithfulness_score is not None:
            if faithfulness_score >= 0.8:
                print("✅ Faithfulness: EXCELENTE - A resposta é fiel ao contexto")
            elif faithfulness_score >= 0.6:
                print(
                    "⚠️  Faithfulness: BOM - A resposta contém algumas informações não suportadas"
                )
            else:
                print(
                    "❌ Faithfulness: BAIXO - A resposta parece estar alucinando/inventando fatos"
                )

        if response_rel is not None:
            if response_rel >= 0.8:
                print("✅ Response Relevancy: EXCELENTE - Resposta altamente alinhada")
            elif response_rel >= 0.6:
                print(
                    "⚠️  Response Relevancy: BOM - Resposta adequada com espaço para melhoria"
                )
            else:
                print("❌ Response Relevancy: BAIXO - Resposta precisa de ajustes")

    print("=" * 70 + "\n")
