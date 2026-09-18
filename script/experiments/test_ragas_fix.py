#!/usr/bin/env python3
"""
Script de Teste para Validar Correções nas Métricas RAGAS

Este script testa a hipótese de que as métricas Response Relevancy e Faithfulness
estão zeradas porque:
1. O campo "corpo" não existe (o correto é "conteudo")
2. O email precisa ser formatado como texto legível, não JSON

Testa apenas GPT-4o-mini nos 3 níveis de dificuldade.
"""

import asyncio
import json
import logging
from datetime import datetime

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from openai import OpenAI
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

# User contexts para cada nível
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
    """
    Formata o email gerado como texto legível para avaliação RAGAS.

    Esta é a CORREÇÃO PRINCIPAL: ao invés de passar JSON bruto,
    formatamos o email de forma estruturada e legível.
    """
    parts = []

    # Cabeçalho do email
    if email_dict.get("remetente"):
        parts.append(f"De: {email_dict['remetente']}")
    if email_dict.get("receptor"):
        parts.append(f"Para: {email_dict['receptor']}")
    if email_dict.get("assunto"):
        parts.append(f"Assunto: {email_dict['assunto']}")

    parts.append("")  # Linha em branco

    # Corpo do email - CORREÇÃO: usar "conteudo" ao invés de "corpo"
    conteudo = (
        email_dict.get("conteudo", "")
        or email_dict.get("corpo", "")
        or email_dict.get("body", "")
    )
    if conteudo:
        # Remove escapes de newline duplos
        conteudo = conteudo.replace("\\n", "\n")
        parts.append(conteudo)

    parts.append("")  # Linha em branco

    # Links
    if email_dict.get("links"):
        parts.append("Links incluídos:")
        for link in email_dict["links"]:
            parts.append(f"  - {link}")

    parts.append("")  # Linha em branco

    # Explicação técnica
    if email_dict.get("explicacao"):
        parts.append("--- Análise Técnica ---")
        parts.append(email_dict["explicacao"])

    # Metadados
    if email_dict.get("nivel"):
        parts.append(f"\nNível de Dificuldade: {email_dict['nivel']}")
    if email_dict.get("categoria"):
        parts.append(f"Categoria: {email_dict['categoria']}")

    return "\n".join(parts)


def format_email_as_text_v2(email_dict: dict) -> str:
    """
    Versão alternativa: apenas o conteúdo principal sem metadados.
    Pode ser mais apropriado para Response Relevancy.
    """
    parts = []

    if email_dict.get("remetente"):
        parts.append(f"De: {email_dict['remetente']}")
    if email_dict.get("receptor"):
        parts.append(f"Para: {email_dict['receptor']}")
    if email_dict.get("assunto"):
        parts.append(f"Assunto: {email_dict['assunto']}")

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


async def run_test():
    """Executa o teste com as correções."""

    print("\n" + "=" * 70)
    print("🔬 TESTE DE CORREÇÃO DAS MÉTRICAS RAGAS")
    print("=" * 70)
    print("\nHipótese: As métricas estão zeradas porque:")
    print("  1. O campo 'corpo' não existe (o correto é 'conteudo')")
    print("  2. O email precisa ser formatado como texto, não JSON")
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

    # RAGAS evaluation components
    eval_chat_model = ChatOpenAI(model="gpt-4o-mini", api_key=api_key)
    eval_llm = LangchainLLMWrapper(langchain_llm=eval_chat_model)
    langchain_embeddings = OpenAIEmbeddings(
        model="text-embedding-3-large", openai_api_key=api_key
    )
    eval_embeddings = LangchainEmbeddingsWrapper(langchain_embeddings)

    # Model to test
    model_name = "gpt-4o-mini"
    response_generator = ResponseGenerator(api_key=api_key, model_name=model_name)
    normalizer = PromptNormalizer(api_key=api_key, model_name=model_name)

    results = []

    for difficulty, user_context in USER_CONTEXTS.items():
        print(f"\n{'=' * 70}")
        print(f"🔄 Testando: {model_name} | Dificuldade: {difficulty}")
        print(f"{'=' * 70}")

        start_time = datetime.now()

        try:
            # 1. Normaliza input
            logger.info("📝 Normalizando input...")
            normalized_data = await normalizer.normalize(user_context)
            search_query = normalized_data.search_query
            generation_context = normalized_data.generation_context

            # 2. HyDE
            logger.info("🔍 Gerando resposta hipotética (HyDE)...")
            try:
                hyde_context = await response_generator.generate_hypothetical_answer(
                    search_query
                )
            except Exception:
                hyde_context = search_query

            # 3. Retrieve
            logger.info("📚 Buscando documentos...")
            candidate_docs = vector_store.query(
                collection_name="phishing_articles", query_text=hyde_context, top_k=20
            )

            # 4. Re-rank
            logger.info("🎯 Re-rankeando...")
            reranked_docs = reranker.rerank(search_query, candidate_docs)

            # 5. Extração de contexto
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

            # 6. Geração
            logger.info("✨ Gerando email...")
            phishing_example = await response_generator.generate_response(
                difficulty=difficulty,
                context=generation_context,
                relevant_docs=fused_context,
            )

            generated_email = (
                phishing_example.dict()
                if hasattr(phishing_example, "dict")
                else dict(phishing_example)
            )

            # ============================================================
            # CORREÇÃO: Formatar email como texto legível
            # ============================================================

            # Versão ANTIGA (problemática):
            old_full_answer = json.dumps(generated_email, ensure_ascii=False, indent=2)
            old_expanded_answer = generated_email.get(
                "corpo", ""
            ) or generated_email.get("body", "")

            # Versão NOVA (corrigida):
            new_full_answer = format_email_as_text(generated_email)
            new_expanded_answer = format_email_as_text_v2(generated_email)

            print("\n" + "-" * 50)
            print("📧 EMAIL GERADO:")
            print("-" * 50)
            print(
                new_expanded_answer[:500] + "..."
                if len(new_expanded_answer) > 500
                else new_expanded_answer
            )
            print("-" * 50)

            # ============================================================
            # Teste com método ANTIGO
            # ============================================================
            print("\n🔴 MÉTODO ANTIGO (JSON bruto):")
            print(f"   full_answer length: {len(old_full_answer)}")
            print(f"   expanded_answer length: {len(old_expanded_answer)}")
            print(f"   expanded_answer vazio? {old_expanded_answer == ''}")

            old_scores = await run_ragas_evaluation(
                search_question=search_query,
                generation_question=generation_context,
                expanded_answer=old_expanded_answer
                if old_expanded_answer
                else old_full_answer,
                full_answer=old_full_answer,
                contexts=final_contexts,
                eval_llm=eval_llm,
                eval_embeddings=eval_embeddings,
            )

            print("\n   Resultados ANTIGO:")
            print(f"   - Context Relevance:  {old_scores.get('context_relevance')}")
            print(f"   - Faithfulness:       {old_scores.get('faithfulness')}")
            print(f"   - Response Relevancy: {old_scores.get('response_relevancy')}")

            # ============================================================
            # Teste com método NOVO
            # ============================================================
            print("\n🟢 MÉTODO NOVO (texto formatado):")
            print(f"   full_answer length: {len(new_full_answer)}")
            print(f"   expanded_answer length: {len(new_expanded_answer)}")

            new_scores = await run_ragas_evaluation(
                search_question=search_query,
                generation_question=generation_context,
                expanded_answer=new_expanded_answer,
                full_answer=new_full_answer,
                contexts=final_contexts,
                eval_llm=eval_llm,
                eval_embeddings=eval_embeddings,
            )

            print("\n   Resultados NOVO:")
            print(f"   - Context Relevance:  {new_scores.get('context_relevance')}")
            print(f"   - Faithfulness:       {new_scores.get('faithfulness')}")
            print(f"   - Response Relevancy: {new_scores.get('response_relevancy')}")

            # ============================================================
            # Comparação
            # ============================================================
            print("\n📊 COMPARAÇÃO:")

            def safe_diff(new, old):
                if new is None or old is None:
                    return "N/A"
                diff = new - old
                return f"+{diff:.4f}" if diff > 0 else f"{diff:.4f}"

            print(
                f"   Context Relevance:  {safe_diff(new_scores.get('context_relevance'), old_scores.get('context_relevance'))}"
            )
            print(
                f"   Faithfulness:       {safe_diff(new_scores.get('faithfulness'), old_scores.get('faithfulness'))}"
            )
            print(
                f"   Response Relevancy: {safe_diff(new_scores.get('response_relevancy'), old_scores.get('response_relevancy'))}"
            )

            execution_time = (datetime.now() - start_time).total_seconds()

            results.append(
                {
                    "difficulty": difficulty,
                    "old_scores": old_scores,
                    "new_scores": new_scores,
                    "execution_time": execution_time,
                    "email_preview": new_expanded_answer[:200],
                }
            )

        except Exception as e:
            logger.error(f"❌ Erro: {e}")
            results.append({"difficulty": difficulty, "error": str(e)})

    # ============================================================
    # Relatório Final
    # ============================================================
    print("\n" + "=" * 70)
    print("📊 RELATÓRIO FINAL - COMPARAÇÃO ANTIGO vs NOVO")
    print("=" * 70)

    print("\n| Dificuldade | Métrica            | Antigo | Novo   | Diferença |")
    print("|-------------|--------------------|--------|--------|-----------|")

    for r in results:
        if "error" in r:
            print(f"| {r['difficulty']:<11} | ERRO: {r['error'][:30]}...")
            continue

        diff = r["difficulty"]
        for metric in ["context_relevance", "faithfulness", "response_relevancy"]:
            old = r["old_scores"].get(metric)
            new = r["new_scores"].get(metric)

            old_str = f"{old:.4f}" if old is not None else "N/A"
            new_str = f"{new:.4f}" if new is not None else "N/A"

            if old is not None and new is not None:
                diff_val = new - old
                diff_str = f"+{diff_val:.4f}" if diff_val > 0 else f"{diff_val:.4f}"
            else:
                diff_str = "N/A"

            metric_name = metric.replace("_", " ").title()
            print(
                f"| {diff:<11} | {metric_name:<18} | {old_str:<6} | {new_str:<6} | {diff_str:<9} |"
            )

    print("\n" + "=" * 70)

    # Salva resultados
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ragas_fix_test_{timestamp}.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n📄 Resultados salvos em: {filename}")
    print("\n✅ Teste concluído!")


if __name__ == "__main__":
    asyncio.run(run_test())
