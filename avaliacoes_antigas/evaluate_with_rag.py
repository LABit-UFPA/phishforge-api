#!/usr/bin/env python3
"""
Script de Avaliação COM RAG - Apenas GPT-4

Este script testa a geração de emails de phishing COM RAG
para comparar com o teste SEM RAG.

Testa apenas GPT-4 nos 3 níveis de dificuldade.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from qdrant_client import QdrantClient
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper

from app.core.config import settings
from app.domain.services.evaluation import run_ragas_evaluation
from app.domain.services.openai.embedding_client import OpenAIEmbeddingClient
from app.domain.services.prompt_normalizer import PromptNormalizer
from app.domain.services.reranker import ReRanker
from app.domain.services.response_generator import ResponseGenerator
from app.infra.qdrant.store import QdrantVectorStore

# Configuração de logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURAÇÕES DO TESTE
# ============================================================================

MODEL_TO_TEST = "gpt-4"

USER_CONTEXTS = {
    "fácil": (
        "Crie um email de phishing simples fingindo ser de um banco genérico "
        "pedindo para o usuário atualizar seus dados cadastrais. "
        "O email deve ter erros óbvios e ser facilmente identificável como fraude."
    ),
    "médio": (
        "Crie um email de phishing como se fosse do departamento de TI da empresa "
        "solicitando que o funcionário João Silva atualize sua senha do sistema. "
        "O email deve parecer profissional mas com alguns indicadores de suspeita."
    ),
    "difícil": (
        "Crie um email de spear phishing altamente sofisticado como se fosse da "
        "diretora financeira Maria Santos para o gerente de contas Pedro Oliveira, "
        "sobre uma transferência urgente relacionada ao Projeto Expansão 2025. "
        "O email deve ser praticamente indistinguível de uma comunicação legítima."
    ),
}


def format_email_as_text(email_dict: dict) -> str:
    """Formata o email como texto legível."""
    parts = []

    if email_dict.get("remetente"):
        parts.append(f"From: {email_dict['remetente']}")
    if email_dict.get("receptor"):
        parts.append(f"To: {email_dict['receptor']}")
    if email_dict.get("assunto"):
        parts.append(f"Subject: {email_dict['assunto']}")

    parts.append("")

    conteudo = (
        email_dict.get("conteudo", "")
        or email_dict.get("corpo", "")
        or email_dict.get("body", "")
    )
    if conteudo:
        conteudo = conteudo.replace("\\n", "\n")
        parts.append(conteudo)

    parts.append("")

    if email_dict.get("links"):
        parts.append("Links:")
        for link in email_dict["links"]:
            parts.append(f"  - {link}")

    parts.append("")

    if email_dict.get("explicacao"):
        parts.append("--- Technical Analysis ---")
        parts.append(email_dict["explicacao"])

    if email_dict.get("nivel"):
        parts.append(f"\nDifficulty Level: {email_dict['nivel']}")
    if email_dict.get("categoria"):
        parts.append(f"Category: {email_dict['categoria']}")

    return "\n".join(parts)


def format_email_content_only(email_dict: dict) -> str:
    """Formata apenas o conteúdo principal do email."""
    parts = []

    if email_dict.get("remetente"):
        parts.append(f"From: {email_dict['remetente']}")
    if email_dict.get("receptor"):
        parts.append(f"To: {email_dict['receptor']}")
    if email_dict.get("assunto"):
        parts.append(f"Subject: {email_dict['assunto']}")

    parts.append("")

    conteudo = (
        email_dict.get("conteudo", "")
        or email_dict.get("corpo", "")
        or email_dict.get("body", "")
    )
    if conteudo:
        conteudo = conteudo.replace("\\n", "\n")
        parts.append(conteudo)

    return "\n".join(parts)


@dataclass
class RagResult:
    """Estrutura para armazenar resultados do teste com RAG."""

    model: str
    difficulty: str
    user_context: str
    search_query: str
    generation_context: str
    generated_email: dict
    ragas_scores: dict
    execution_time: float
    error: Optional[str] = None


async def run_rag_evaluation():
    """Executa avaliação COM RAG."""

    print("\n" + "=" * 70)
    print("🔬 EXPERIMENTO: Geração COM RAG")
    print(f"    Modelo: {MODEL_TO_TEST}")
    print("=" * 70 + "\n")

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        print("❌ Erro: OPENAI_API_KEY não configurada!")
        return

    # Inicializa componentes
    logger.info("Inicializando componentes...")

    qdrant_client = QdrantClient(url=settings.QDRANT_URL)
    embedding_client = OpenAIEmbeddingClient(
        api_key=api_key, model="text-embedding-3-small"
    )
    vector_store = QdrantVectorStore(
        client=qdrant_client, embedding_client=embedding_client
    )
    reranker = ReRanker()
    normalizer = PromptNormalizer(api_key=api_key, model_name=MODEL_TO_TEST)
    response_generator = ResponseGenerator(api_key=api_key, model_name=MODEL_TO_TEST)

    # RAGAS components
    eval_chat_model = ChatOpenAI(model="gpt-4o-mini", api_key=api_key)
    eval_llm = LangchainLLMWrapper(langchain_llm=eval_chat_model)
    langchain_embeddings = OpenAIEmbeddings(
        model="text-embedding-3-large", openai_api_key=api_key
    )
    eval_embeddings = LangchainEmbeddingsWrapper(langchain_embeddings)

    results = []

    for difficulty, user_context in USER_CONTEXTS.items():
        print(f"\n--- {difficulty.upper()} ---")
        start_time = datetime.now()

        try:
            # 1. Normaliza
            logger.info("Normalizando input...")
            normalized = await normalizer.normalize(user_context)
            search_query = normalized.search_query
            generation_context = normalized.generation_context

            # 2. HyDE
            logger.info("Gerando HyDE...")
            hyde_context = await response_generator.generate_hypothetical_answer(
                search_query
            )

            # 3. Retrieve do Qdrant
            logger.info("Buscando documentos no Qdrant...")
            candidate_docs = vector_store.query(
                collection_name="phishing_articles", query_text=hyde_context, top_k=20
            )

            # 4. Re-rank
            logger.info("Re-rankeando...")
            reranked_docs = reranker.rerank(search_query, candidate_docs)

            # 5. Prepara contexto
            if reranked_docs:
                top_docs_payloads = [doc.payload for doc in reranked_docs[:3]]
                final_contexts = [
                    payload["parent_content"]
                    for payload in top_docs_payloads
                    if "parent_content" in payload
                ]
            else:
                final_contexts = []

            fused_context = await response_generator.fuse_and_summarize_context(
                generation_context=generation_context, contexts=final_contexts
            )

            # 6. Geração COM RAG
            logger.info(f"Gerando email COM RAG ({difficulty})...")
            phishing_example = await response_generator.generate_response(
                difficulty=difficulty,
                context=generation_context,
                relevant_docs=fused_context,
            )

            generated_email = (
                phishing_example.model_dump()
                if hasattr(phishing_example, "model_dump")
                else phishing_example.dict()
                if hasattr(phishing_example, "dict")
                else dict(phishing_example)
            )

            # 7. RAGAS Evaluation
            logger.info("Avaliando com RAGAS...")
            full_answer = format_email_as_text(generated_email)
            expanded_answer = format_email_content_only(generated_email)

            ragas_scores = await run_ragas_evaluation(
                search_question=search_query,
                generation_question=generation_context,
                expanded_answer=expanded_answer,
                full_answer=full_answer,
                contexts=final_contexts,
                eval_llm=eval_llm,
                eval_embeddings=eval_embeddings,
            )

            execution_time = (datetime.now() - start_time).total_seconds()

            result = RagResult(
                model=MODEL_TO_TEST,
                difficulty=difficulty,
                user_context=user_context,
                search_query=search_query,
                generation_context=generation_context,
                generated_email=generated_email,
                ragas_scores=ragas_scores,
                execution_time=execution_time,
            )

            results.append(result)

            # Print resultado
            cr = ragas_scores.get("context_relevance")
            f = ragas_scores.get("faithfulness")
            rr = ragas_scores.get("response_relevancy")

            print(f"   ⏱️  Tempo: {execution_time:.2f}s")
            print(f"   📧 Assunto: {generated_email.get('assunto', 'N/A')[:60]}...")
            print(
                f"   📊 Context Relevance: {cr:.4f}"
                if cr
                else "   📊 Context Relevance: N/A"
            )
            print(f"   📊 Faithfulness: {f:.4f}" if f else "   📊 Faithfulness: N/A")
            print(
                f"   📊 Response Relevancy: {rr:.4f}"
                if rr
                else "   📊 Response Relevancy: N/A"
            )

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            logger.error(f"Erro: {e}")
            import traceback

            traceback.print_exc()
            results.append(
                RagResult(
                    model=MODEL_TO_TEST,
                    difficulty=difficulty,
                    user_context=user_context,
                    search_query="",
                    generation_context="",
                    generated_email={},
                    ragas_scores={},
                    execution_time=execution_time,
                    error=str(e),
                )
            )

    # Gera relatório
    report = generate_report(results)

    # Salva JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"with_rag_evaluation_{timestamp}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n📄 Resultados salvos em: {filename}")

    # Print relatório final
    print_final_report(results)

    return results, report


def generate_report(results: list[RagResult]) -> dict:
    """Gera relatório consolidado."""
    successful = [r for r in results if not r.error]

    cr_scores = [
        r.ragas_scores.get("context_relevance")
        for r in successful
        if r.ragas_scores.get("context_relevance") is not None
    ]
    f_scores = [
        r.ragas_scores.get("faithfulness")
        for r in successful
        if r.ragas_scores.get("faithfulness") is not None
    ]
    rr_scores = [
        r.ragas_scores.get("response_relevancy")
        for r in successful
        if r.ragas_scores.get("response_relevancy") is not None
    ]

    report = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "model": MODEL_TO_TEST,
            "experiment": "Generation WITH RAG",
            "total_evaluations": len(results),
            "rag_enabled": True,
        },
        "summary": {
            "avg_execution_time": sum(r.execution_time for r in successful)
            / max(len(successful), 1),
            "avg_context_relevance": sum(cr_scores) / len(cr_scores)
            if cr_scores
            else None,
            "avg_faithfulness": sum(f_scores) / len(f_scores) if f_scores else None,
            "avg_response_relevancy": sum(rr_scores) / len(rr_scores)
            if rr_scores
            else None,
            "successful_count": len(successful),
            "failed_count": len([r for r in results if r.error]),
        },
        "detailed_results": [],
    }

    for r in results:
        report["detailed_results"].append(
            {
                "model": r.model,
                "difficulty": r.difficulty,
                "user_context": r.user_context,
                "search_query": r.search_query,
                "generation_context": r.generation_context,
                "generated_email": r.generated_email,
                "ragas_scores": r.ragas_scores,
                "execution_time": r.execution_time,
                "error": r.error,
            }
        )

    return report


def print_final_report(results: list[RagResult]):
    """Imprime relatório final."""
    print("\n" + "=" * 70)
    print("📊 RELATÓRIO FINAL: Geração COM RAG")
    print("=" * 70)

    successful = [r for r in results if not r.error]

    if successful:
        avg_time = sum(r.execution_time for r in successful) / len(successful)

        cr_scores = [
            r.ragas_scores.get("context_relevance")
            for r in successful
            if r.ragas_scores.get("context_relevance") is not None
        ]
        f_scores = [
            r.ragas_scores.get("faithfulness")
            for r in successful
            if r.ragas_scores.get("faithfulness") is not None
        ]
        rr_scores = [
            r.ragas_scores.get("response_relevancy")
            for r in successful
            if r.ragas_scores.get("response_relevancy") is not None
        ]

        print(f"\n🔹 Modelo: {MODEL_TO_TEST}")
        print(f"   Testes bem-sucedidos: {len(successful)}/{len(results)}")
        print(f"   Tempo médio: {avg_time:.2f}s")

        if cr_scores:
            print(f"   Context Relevance: {sum(cr_scores) / len(cr_scores):.4f}")
        if f_scores:
            print(f"   Faithfulness: {sum(f_scores) / len(f_scores):.4f}")
        if rr_scores:
            print(f"   Response Relevancy: {sum(rr_scores) / len(rr_scores):.4f}")

        print("\n📧 Emails Gerados:")
        for r in successful:
            print(f"\n   [{r.difficulty.upper()}]")
            print(f"   Assunto: {r.generated_email.get('assunto', 'N/A')}")
            print(f"   Tempo: {r.execution_time:.2f}s")
            rr = r.ragas_scores.get("response_relevancy")
            if rr:
                print(f"   Response Relevancy: {rr:.4f}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(run_rag_evaluation())
