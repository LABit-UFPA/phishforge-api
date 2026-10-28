import logging
from typing import Any, Optional

from ragas.metrics.collections import (
    AnswerRelevancy,
    ContextRelevance,
    Faithfulness,
)

logging.basicConfig(level=logging.INFO)
evaluation_logger = logging.getLogger("ragas_evaluation")


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
    - Faithfulness: a resposta se sustenta nos contextos. Precisa de
      contexto -> None se nao houver.
    - Answer/Response Relevancy: a resposta responde ao cenario pedido.
      Nao usa contexto (so user_input + response), mas usa embeddings.
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
            faithfulness_scorer = Faithfulness(llm=eval_llm)
            resultado["context_relevance"] = _valor(
                await context_scorer.ascore(
                    user_input=search_question, retrieved_contexts=contexts
                )
            )
            resultado["faithfulness"] = _valor(
                await faithfulness_scorer.ascore(
                    user_input=search_question,
                    response=full_answer,
                    retrieved_contexts=contexts,
                )
            )

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
