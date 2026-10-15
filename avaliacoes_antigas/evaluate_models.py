#!/usr/bin/env python3
"""
Script de Avaliação de Modelos LLM para Geração de Phishing Educacional

Este script simula o fluxo do endpoint /api/v1/generate para avaliar diferentes
modelos LLM (GPT-3.5 Turbo, GPT-4, o4-mini) usando métricas RAGAS.

Testa cada modelo nos 3 níveis de dificuldade: fácil, médio e difícil.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

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


# ============================================================================
# CONFIGURAÇÕES DO TESTE
# ============================================================================

# Modelos a serem testados
# Nota: o4-mini é modelo de reasoning e não suporta temperature != 1
# Usamos gpt-4o-mini como alternativa ao invés de o4-mini
MODELS_TO_TEST = [
    "gpt-3.5-turbo",
    "gpt-4",
    "gpt-4o-mini",
    "gpt-5.2",
]

# Modelos de reasoning que não suportam temperature
REASONING_MODELS = ["o1", "o1-mini", "o1-preview", "o3", "o3-mini", "o4-mini"]

# User contexts para cada nível de dificuldade
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

    CORREÇÃO: ao invés de passar JSON bruto, formatamos o email
    de forma estruturada e legível para melhor avaliação.
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


def format_email_content_only(email_dict: dict) -> str:
    """
    Formata apenas o conteúdo principal do email (sem metadados).
    Mais apropriado para Response Relevancy.
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


@dataclass
class EvaluationResult:
    """Estrutura para armazenar resultados de avaliação."""

    model: str
    difficulty: str
    user_context: str
    search_query: str
    generation_context: str
    contexts_retrieved: list[str]
    generated_email: dict
    ragas_scores: dict
    execution_time: float
    error: Optional[str] = None


class ModelEvaluator:
    """Classe principal para avaliação de modelos."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.results: list[EvaluationResult] = []

        # Inicializa componentes compartilhados
        self._init_shared_components()

    def _init_shared_components(self):
        """Inicializa componentes que são compartilhados entre os testes."""
        logger.info("Inicializando componentes compartilhados...")

        # Cliente Qdrant
        self.qdrant_client = QdrantClient(url=settings.QDRANT_URL)

        # Cliente de embedding (OpenAI)
        self.embedding_client = OpenAIEmbeddingClient(
            api_key=self.api_key, model="text-embedding-3-small"
        )

        # Vector Store
        self.vector_store = QdrantVectorStore(
            client=self.qdrant_client, embedding_client=self.embedding_client
        )

        # Reranker
        self.reranker = ReRanker()

        # Cliente OpenAI para RAGAS
        self.openai_client = OpenAI(api_key=self.api_key)

        # LLM e Embeddings para avaliação RAGAS
        self.eval_chat_model = ChatOpenAI(model="gpt-4o-mini", api_key=self.api_key)
        self.eval_llm = LangchainLLMWrapper(langchain_llm=self.eval_chat_model)

        # Usar LangchainEmbeddingsWrapper com OpenAIEmbeddings do langchain
        langchain_embeddings = OpenAIEmbeddings(
            model="text-embedding-3-large", openai_api_key=self.api_key
        )
        self.eval_embeddings = LangchainEmbeddingsWrapper(langchain_embeddings)

        logger.info("Componentes compartilhados inicializados com sucesso!")

    def _create_response_generator(self, model_name: str) -> ResponseGenerator:
        """Cria um ResponseGenerator para o modelo especificado."""
        return ResponseGenerator(api_key=self.api_key, model_name=model_name)

    def _create_prompt_normalizer(self, model_name: str) -> PromptNormalizer:
        """Cria um PromptNormalizer para o modelo especificado."""
        return PromptNormalizer(api_key=self.api_key, model_name=model_name)

    async def evaluate_single(
        self, model_name: str, difficulty: str, user_context: str
    ) -> EvaluationResult:
        """
        Executa uma avaliação individual para um modelo e nível de dificuldade.

        Simula o fluxo completo do endpoint /api/v1/generate.
        """
        start_time = datetime.now()

        logger.info(f"\n{'=' * 70}")
        logger.info(f"🔄 Avaliando: {model_name} | Dificuldade: {difficulty}")
        logger.info(f"{'=' * 70}")

        try:
            # Cria instâncias específicas para o modelo
            response_generator = self._create_response_generator(model_name)
            normalizer = self._create_prompt_normalizer(model_name)

            # 1. Normaliza o input do usuário
            logger.info("📝 Etapa 1: Normalizando input...")
            normalized_data = await normalizer.normalize(user_context)
            search_query = normalized_data.search_query
            generation_context = normalized_data.generation_context

            logger.info(f"   Search Query: {search_query[:100]}...")
            logger.info(f"   Generation Context: {generation_context[:100]}...")

            # 2. HyDE (Query Transformation)
            logger.info("🔍 Etapa 2: Gerando resposta hipotética (HyDE)...")
            try:
                hyde_context = await response_generator.generate_hypothetical_answer(
                    search_query
                )
            except Exception:
                hyde_context = search_query

            # 3. Retrieve (Busca Inicial)
            logger.info("📚 Etapa 3: Buscando documentos relevantes...")
            candidate_docs = self.vector_store.query(
                collection_name="phishing_articles", query_text=hyde_context, top_k=20
            )
            logger.info(f"   Documentos candidatos encontrados: {len(candidate_docs)}")

            # 4. Re-rank (Refinamento da Busca)
            logger.info("🎯 Etapa 4: Re-rankeando documentos...")
            reranked_docs = self.reranker.rerank(search_query, candidate_docs)

            # 5. Extração e Fusão do Contexto
            logger.info("🔗 Etapa 5: Fundindo contextos...")
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

            # 6. Geração Final
            logger.info("✨ Etapa 6: Gerando email de phishing...")
            phishing_example = await response_generator.generate_response(
                difficulty=difficulty,
                context=generation_context,
                relevant_docs=fused_context,
            )

            # Converte para dicionário
            generated_email = (
                phishing_example.dict()
                if hasattr(phishing_example, "dict")
                else dict(phishing_example)
            )

            logger.info("   Email gerado com sucesso!")
            logger.info(f"   Assunto: {generated_email.get('assunto', 'N/A')[:50]}...")

            # 7. Avaliação RAGAS
            logger.info("📊 Etapa 7: Executando avaliação RAGAS...")

            # CORREÇÃO: Formatar email como texto legível ao invés de JSON bruto
            # Isso melhora significativamente as métricas Response Relevancy e Faithfulness
            full_answer = format_email_as_text(generated_email)
            expanded_answer = format_email_content_only(generated_email)

            ragas_scores = await run_ragas_evaluation(
                search_question=search_query,
                generation_question=generation_context,
                expanded_answer=expanded_answer,
                full_answer=full_answer,
                contexts=final_contexts,
                eval_llm=self.eval_llm,
                eval_embeddings=self.eval_embeddings,
            )

            execution_time = (datetime.now() - start_time).total_seconds()

            result = EvaluationResult(
                model=model_name,
                difficulty=difficulty,
                user_context=user_context,
                search_query=search_query,
                generation_context=generation_context,
                contexts_retrieved=final_contexts,
                generated_email=generated_email,
                ragas_scores=ragas_scores,
                execution_time=execution_time,
            )

            self._print_result_summary(result)

            return result

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            logger.error(f"❌ Erro na avaliação: {str(e)}")

            return EvaluationResult(
                model=model_name,
                difficulty=difficulty,
                user_context=user_context,
                search_query="",
                generation_context="",
                contexts_retrieved=[],
                generated_email={},
                ragas_scores={},
                execution_time=execution_time,
                error=str(e),
            )

    def _print_result_summary(self, result: EvaluationResult):
        """Imprime um resumo do resultado da avaliação."""
        print(f"\n{'─' * 70}")
        print(f"📋 RESULTADO: {result.model} | {result.difficulty}")
        print(f"{'─' * 70}")
        print(f"⏱️  Tempo de execução: {result.execution_time:.2f}s")

        if result.error:
            print(f"❌ Erro: {result.error}")
        else:
            scores = result.ragas_scores

            cr = scores.get("context_relevance")
            f = scores.get("faithfulness")
            rr = scores.get("response_relevancy")

            print("\n📊 Métricas RAGAS:")
            print(
                f"   Context Relevance:  {cr:.4f}"
                if cr is not None
                else "   Context Relevance:  N/A"
            )
            print(
                f"   Faithfulness:       {f:.4f}"
                if f is not None
                else "   Faithfulness:       N/A"
            )
            print(
                f"   Response Relevancy: {rr:.4f}"
                if rr is not None
                else "   Response Relevancy: N/A"
            )

            # Calcula média
            valid_scores = [s for s in [cr, f, rr] if s is not None]
            if valid_scores:
                avg = sum(valid_scores) / len(valid_scores)
                print(f"\n   📈 Média: {avg:.4f}")

        print(f"{'─' * 70}\n")

    async def run_full_evaluation(self) -> list[EvaluationResult]:
        """Executa a avaliação completa para todos os modelos e dificuldades."""
        logger.info("\n" + "=" * 70)
        logger.info("🚀 INICIANDO AVALIAÇÃO COMPLETA DE MODELOS")
        logger.info("=" * 70)
        logger.info(f"Modelos: {MODELS_TO_TEST}")
        logger.info(f"Dificuldades: {list(USER_CONTEXTS.keys())}")
        logger.info("=" * 70 + "\n")

        all_results = []

        for model in MODELS_TO_TEST:
            for difficulty, user_context in USER_CONTEXTS.items():
                result = await self.evaluate_single(model, difficulty, user_context)
                all_results.append(result)
                self.results.append(result)

        return all_results

    def generate_report(self) -> dict:
        """Gera um relatório consolidado dos resultados."""
        report = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "models_tested": MODELS_TO_TEST,
                "difficulties": list(USER_CONTEXTS.keys()),
                "total_evaluations": len(self.results),
            },
            "summary_by_model": {},
            "summary_by_difficulty": {},
            "detailed_results": [],
        }

        # Agrupa por modelo
        for model in MODELS_TO_TEST:
            model_results = [
                r for r in self.results if r.model == model and not r.error
            ]
            if model_results:
                avg_scores = self._calculate_average_scores(model_results)
                report["summary_by_model"][model] = avg_scores

        # Agrupa por dificuldade
        for difficulty in USER_CONTEXTS.keys():
            diff_results = [
                r for r in self.results if r.difficulty == difficulty and not r.error
            ]
            if diff_results:
                avg_scores = self._calculate_average_scores(diff_results)
                report["summary_by_difficulty"][difficulty] = avg_scores

        # Resultados detalhados
        for result in self.results:
            report["detailed_results"].append(
                {
                    "model": result.model,
                    "difficulty": result.difficulty,
                    "user_context": result.user_context,
                    "search_query": result.search_query,
                    "generation_context": result.generation_context,
                    "generated_email": result.generated_email,
                    "ragas_scores": result.ragas_scores,
                    "execution_time": result.execution_time,
                    "error": result.error,
                }
            )

        return report

    def _calculate_average_scores(self, results: list[EvaluationResult]) -> dict:
        """Calcula as médias das métricas RAGAS."""
        cr_scores = []
        f_scores = []
        rr_scores = []

        for r in results:
            if r.ragas_scores.get("context_relevance") is not None:
                cr_scores.append(r.ragas_scores["context_relevance"])
            if r.ragas_scores.get("faithfulness") is not None:
                f_scores.append(r.ragas_scores["faithfulness"])
            if r.ragas_scores.get("response_relevancy") is not None:
                rr_scores.append(r.ragas_scores["response_relevancy"])

        return {
            "avg_context_relevance": sum(cr_scores) / len(cr_scores)
            if cr_scores
            else None,
            "avg_faithfulness": sum(f_scores) / len(f_scores) if f_scores else None,
            "avg_response_relevancy": sum(rr_scores) / len(rr_scores)
            if rr_scores
            else None,
            "avg_execution_time": sum(r.execution_time for r in results) / len(results),
            "sample_count": len(results),
        }

    def print_final_report(self):
        """Imprime o relatório final formatado."""
        print("\n" + "=" * 70)
        print("📊 RELATÓRIO FINAL DE AVALIAÇÃO")
        print("=" * 70)

        # Por modelo
        print("\n📌 RESUMO POR MODELO:")
        print("-" * 70)

        for model in MODELS_TO_TEST:
            model_results = [
                r for r in self.results if r.model == model and not r.error
            ]
            if model_results:
                avg = self._calculate_average_scores(model_results)
                print(f"\n🤖 {model}")
                print(
                    f"   Context Relevance:  {avg['avg_context_relevance']:.4f}"
                    if avg["avg_context_relevance"]
                    else "   Context Relevance:  N/A"
                )
                print(
                    f"   Faithfulness:       {avg['avg_faithfulness']:.4f}"
                    if avg["avg_faithfulness"]
                    else "   Faithfulness:       N/A"
                )
                print(
                    f"   Response Relevancy: {avg['avg_response_relevancy']:.4f}"
                    if avg["avg_response_relevancy"]
                    else "   Response Relevancy: N/A"
                )
                print(f"   Tempo médio:        {avg['avg_execution_time']:.2f}s")

        # Por dificuldade
        print("\n\n📌 RESUMO POR DIFICULDADE:")
        print("-" * 70)

        for difficulty in USER_CONTEXTS.keys():
            diff_results = [
                r for r in self.results if r.difficulty == difficulty and not r.error
            ]
            if diff_results:
                avg = self._calculate_average_scores(diff_results)
                print(f"\n🎯 {difficulty.upper()}")
                print(
                    f"   Context Relevance:  {avg['avg_context_relevance']:.4f}"
                    if avg["avg_context_relevance"]
                    else "   Context Relevance:  N/A"
                )
                print(
                    f"   Faithfulness:       {avg['avg_faithfulness']:.4f}"
                    if avg["avg_faithfulness"]
                    else "   Faithfulness:       N/A"
                )
                print(
                    f"   Response Relevancy: {avg['avg_response_relevancy']:.4f}"
                    if avg["avg_response_relevancy"]
                    else "   Response Relevancy: N/A"
                )
                print(f"   Tempo médio:        {avg['avg_execution_time']:.2f}s")

        # Erros
        errors = [r for r in self.results if r.error]
        if errors:
            print("\n\n⚠️ ERROS ENCONTRADOS:")
            print("-" * 70)
            for e in errors:
                print(f"   - {e.model} | {e.difficulty}: {e.error}")

        print("\n" + "=" * 70)


def save_report(report: dict, filename: str = None):
    """Salva o relatório em arquivo JSON."""
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"evaluation_report_{timestamp}.json"

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    logger.info(f"📄 Relatório salvo em: {filename}")
    return filename


async def main():
    """Função principal do script."""
    print("\n" + "=" * 70)
    print("🔬 SCRIPT DE AVALIAÇÃO DE MODELOS LLM")
    print("    PhishForge API - Avaliação com RAGAS")
    print("=" * 70 + "\n")

    # Verifica se a API key está configurada
    if not settings.OPENAI_API_KEY:
        print("❌ Erro: OPENAI_API_KEY não está configurada!")
        print("   Configure a variável de ambiente ou no arquivo .env")
        return

    # Cria o avaliador
    evaluator = ModelEvaluator(api_key=settings.OPENAI_API_KEY)

    # Executa avaliação completa
    await evaluator.run_full_evaluation()

    # Imprime relatório final
    evaluator.print_final_report()

    # Gera e salva relatório
    report = evaluator.generate_report()
    save_report(report)

    print("\n✅ Avaliação concluída com sucesso!")


if __name__ == "__main__":
    asyncio.run(main())
