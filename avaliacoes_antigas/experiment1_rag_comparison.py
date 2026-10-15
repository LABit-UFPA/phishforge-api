#!/usr/bin/env python3
"""
Experimento 1: Comparação RAG vs SEM RAG (60 exemplos)

Gera 60 exemplos de emails de phishing educacionais:
- 30 SEM RAG (10 por nível de dificuldade)
- 30 COM RAG (10 por nível de dificuldade)

Objetivo: Avaliar o impacto da arquitetura RAG na qualidade da geração.
"""

import asyncio
import json
import logging
import random
from dataclasses import asdict, dataclass
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
# CONFIGURAÇÕES DO EXPERIMENTO
# ============================================================================

MODEL = "gpt-4"
SAMPLES_PER_DIFFICULTY = 10  # 10 exemplos por nível = 30 por condição = 60 total

# Cenários variados para cada nível de dificuldade
SCENARIOS = {
    "fácil": [
        "Crie um email de phishing simples fingindo ser de um banco genérico pedindo para o usuário atualizar seus dados cadastrais. O email deve ter erros óbvios e ser facilmente identificável como fraude.",
        "Crie um email de phishing básico fingindo ser de uma loja online genérica informando sobre uma compra não reconhecida. Deve ter erros gramaticais evidentes.",
        "Crie um email de phishing simples fingindo ser de um serviço de streaming pedindo atualização de pagamento. O email deve ter formatação amadora.",
        "Crie um email de phishing básico fingindo ser do governo sobre restituição de imposto. Deve ter links suspeitos óbvios.",
        "Crie um email de phishing simples fingindo ser de uma rede social alertando sobre atividade suspeita. O email deve ter urgência exagerada.",
        "Crie um email de phishing básico fingindo ser de uma empresa de telefonia sobre fatura em atraso. Deve ter remetente claramente falso.",
        "Crie um email de phishing simples fingindo ser de um banco digital pedindo verificação de identidade. O email deve ter ameaças diretas.",
        "Crie um email de phishing básico fingindo ser de uma empresa de entrega sobre pacote retido. Deve ter erros de português evidentes.",
        "Crie um email de phishing simples fingindo ser de um provedor de email sobre caixa de entrada cheia. O email deve ser genérico sem personalização.",
        "Crie um email de phishing básico fingindo ser de uma carteira digital sobre transação pendente. Deve ter links encurtados suspeitos.",
    ],
    "médio": [
        "Crie um email de phishing como se fosse do departamento de TI da empresa solicitando que o funcionário João Silva atualize sua senha do sistema. O email deve parecer profissional mas com alguns indicadores de suspeita.",
        "Crie um email de phishing como se fosse do RH da empresa para Ana Costa sobre atualização de dados bancários para depósito do 13º salário. Deve ter aparência corporativa.",
        "Crie um email de phishing como se fosse do suporte técnico da Microsoft para Carlos Mendes sobre licença do Office expirando. Deve parecer legítimo com sutis indicadores.",
        "Crie um email de phishing como se fosse do departamento financeiro para Roberto Lima sobre aprovação de reembolso pendente. O email deve ter formato empresarial.",
        "Crie um email de phishing como se fosse do LinkedIn para Paula Ferreira sobre nova vaga compatível com seu perfil. Deve ter design similar ao original.",
        "Crie um email de phishing como se fosse do Dropbox para Marcos Oliveira sobre compartilhamento de arquivo importante. Deve ter branding parcialmente convincente.",
        "Crie um email de phishing como se fosse do departamento jurídico para Fernanda Alves sobre documento para assinatura eletrônica. Deve ter tom profissional.",
        "Crie um email de phishing como se fosse do Google Workspace para Ricardo Santos sobre verificação de segurança obrigatória. Deve ter aparência autêntica.",
        "Crie um email de phishing como se fosse do fornecedor habitual para Juliana Pereira sobre nova forma de pagamento. Deve usar informações parcialmente corretas.",
        "Crie um email de phishing como se fosse do banco corporativo para Lucas Martins sobre nova política de segurança. Deve ter elementos visuais profissionais.",
    ],
    "difícil": [
        "Crie um email de spear phishing altamente sofisticado como se fosse da diretora financeira Maria Santos para o gerente de contas Pedro Oliveira, sobre uma transferência urgente relacionada ao Projeto Expansão 2025. O email deve ser praticamente indistinguível de uma comunicação legítima.",
        "Crie um email de spear phishing sofisticado como se fosse do CEO Antonio Rodrigues para a controller Beatriz Lima sobre aprovação emergencial de budget para aquisição estratégica. Deve ter contexto empresarial realista.",
        "Crie um email de spear phishing avançado como se fosse do diretor de operações Felipe Souza para o gerente de compras Eduardo Nunes sobre urgência em contrato com fornecedor internacional. Deve ter detalhes específicos convincentes.",
        "Crie um email de spear phishing sofisticado como se fosse da head de RH Carolina Mendes para o analista financeiro Gustavo Almeida sobre bônus confidencial que requer dados bancários atualizados. Deve explorar autoridade.",
        "Crie um email de spear phishing avançado como se fosse do CTO Ricardo Ferreira para a desenvolvedora Mariana Costa sobre acesso urgente ao repositório do cliente VIP. Deve ter terminologia técnica correta.",
        "Crie um email de spear phishing sofisticado como se fosse do partner do escritório de advocacia para o cliente corporativo sobre acordo judicial confidencial. Deve ter tom formal adequado.",
        "Crie um email de spear phishing avançado como se fosse do gerente de banco private para cliente de alta renda sobre oportunidade exclusiva de investimento. Deve ter personalização avançada.",
        "Crie um email de spear phishing sofisticado como se fosse do diretor comercial Henrique Bastos para o vendedor sênior Amanda Reis sobre comissão extraordinária do trimestre. Deve ter contexto temporal relevante.",
        "Crie um email de spear phishing avançado como se fosse do auditor externo para o controller sobre documentação urgente para fechamento fiscal. Deve explorar compliance.",
        "Crie um email de spear phishing sofisticado como se fosse do board member para o CFO sobre due diligence confidencial de M&A. Deve ter linguagem executiva autêntica.",
    ],
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
        parts.append(conteudo.replace("\\n", "\n"))
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
        parts.append(conteudo.replace("\\n", "\n"))
    return "\n".join(parts)


@dataclass
class ExperimentResult:
    """Resultado de um exemplo gerado."""

    condition: str  # "with_rag" ou "no_rag"
    difficulty: str
    sample_index: int
    user_context: str
    search_query: Optional[str]
    generation_context: Optional[str]
    generated_email: dict
    ragas_scores: dict
    execution_time: float
    error: Optional[str] = None


async def generate_without_rag(
    response_generator: ResponseGenerator,
    difficulty: str,
    user_context: str,
    sample_index: int,
) -> ExperimentResult:
    """Gera um exemplo SEM RAG."""
    start_time = datetime.now()

    try:
        phishing_example = await response_generator.generate_response(
            difficulty=difficulty,
            context=user_context,
            relevant_docs="No additional academic context available. Use your internal knowledge about phishing techniques.",
        )

        generated_email = (
            phishing_example.model_dump()
            if hasattr(phishing_example, "model_dump")
            else phishing_example.dict()
            if hasattr(phishing_example, "dict")
            else dict(phishing_example)
        )

        execution_time = (datetime.now() - start_time).total_seconds()

        return ExperimentResult(
            condition="no_rag",
            difficulty=difficulty,
            sample_index=sample_index,
            user_context=user_context,
            search_query=None,
            generation_context=None,
            generated_email=generated_email,
            ragas_scores={},  # Sem RAGAS para no_rag
            execution_time=execution_time,
        )

    except Exception as e:
        execution_time = (datetime.now() - start_time).total_seconds()
        logger.error(f"Erro SEM RAG [{difficulty}][{sample_index}]: {e}")
        return ExperimentResult(
            condition="no_rag",
            difficulty=difficulty,
            sample_index=sample_index,
            user_context=user_context,
            search_query=None,
            generation_context=None,
            generated_email={},
            ragas_scores={},
            execution_time=execution_time,
            error=str(e),
        )


async def generate_with_rag(
    response_generator: ResponseGenerator,
    normalizer: PromptNormalizer,
    vector_store: QdrantVectorStore,
    reranker: ReRanker,
    eval_llm,
    eval_embeddings,
    difficulty: str,
    user_context: str,
    sample_index: int,
) -> ExperimentResult:
    """Gera um exemplo COM RAG."""
    start_time = datetime.now()

    try:
        # 1. Normaliza
        normalized = await normalizer.normalize(user_context)
        search_query = normalized.search_query
        generation_context = normalized.generation_context

        # 2. HyDE
        hyde_context = await response_generator.generate_hypothetical_answer(
            search_query
        )

        # 3. Retrieve
        candidate_docs = vector_store.query(
            collection_name="phishing_articles", query_text=hyde_context, top_k=20
        )

        # 4. Re-rank
        reranked_docs = reranker.rerank(search_query, candidate_docs)

        # 5. Contexto
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

        # 7. RAGAS
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

        return ExperimentResult(
            condition="with_rag",
            difficulty=difficulty,
            sample_index=sample_index,
            user_context=user_context,
            search_query=search_query,
            generation_context=generation_context,
            generated_email=generated_email,
            ragas_scores=ragas_scores,
            execution_time=execution_time,
        )

    except Exception as e:
        execution_time = (datetime.now() - start_time).total_seconds()
        logger.error(f"Erro COM RAG [{difficulty}][{sample_index}]: {e}")
        import traceback

        traceback.print_exc()
        return ExperimentResult(
            condition="with_rag",
            difficulty=difficulty,
            sample_index=sample_index,
            user_context=user_context,
            search_query=None,
            generation_context=None,
            generated_email={},
            ragas_scores={},
            execution_time=execution_time,
            error=str(e),
        )


def calculate_statistics(results: list[ExperimentResult], condition: str) -> dict:
    """Calcula estatísticas para uma condição."""
    filtered = [r for r in results if r.condition == condition and not r.error]

    if not filtered:
        return {"error": "No successful results"}

    stats = {
        "total_samples": len(filtered),
        "failed_samples": len(
            [r for r in results if r.condition == condition and r.error]
        ),
        "avg_execution_time": sum(r.execution_time for r in filtered) / len(filtered),
        "by_difficulty": {},
    }

    for difficulty in ["fácil", "médio", "difícil"]:
        diff_results = [r for r in filtered if r.difficulty == difficulty]
        if diff_results:
            diff_stats = {
                "count": len(diff_results),
                "avg_execution_time": sum(r.execution_time for r in diff_results)
                / len(diff_results),
            }

            if condition == "with_rag":
                cr = [
                    r.ragas_scores.get("context_relevance")
                    for r in diff_results
                    if r.ragas_scores.get("context_relevance") is not None
                ]
                f = [
                    r.ragas_scores.get("faithfulness")
                    for r in diff_results
                    if r.ragas_scores.get("faithfulness") is not None
                ]
                rr = [
                    r.ragas_scores.get("response_relevancy")
                    for r in diff_results
                    if r.ragas_scores.get("response_relevancy") is not None
                ]

                diff_stats["avg_context_relevance"] = sum(cr) / len(cr) if cr else None
                diff_stats["avg_faithfulness"] = sum(f) / len(f) if f else None
                diff_stats["avg_response_relevancy"] = sum(rr) / len(rr) if rr else None

            stats["by_difficulty"][difficulty] = diff_stats

    # Médias gerais para with_rag
    if condition == "with_rag":
        cr_all = [
            r.ragas_scores.get("context_relevance")
            for r in filtered
            if r.ragas_scores.get("context_relevance") is not None
        ]
        f_all = [
            r.ragas_scores.get("faithfulness")
            for r in filtered
            if r.ragas_scores.get("faithfulness") is not None
        ]
        rr_all = [
            r.ragas_scores.get("response_relevancy")
            for r in filtered
            if r.ragas_scores.get("response_relevancy") is not None
        ]

        stats["avg_context_relevance"] = sum(cr_all) / len(cr_all) if cr_all else None
        stats["avg_faithfulness"] = sum(f_all) / len(f_all) if f_all else None
        stats["avg_response_relevancy"] = sum(rr_all) / len(rr_all) if rr_all else None

    return stats


async def run_experiment():
    """Executa o experimento completo."""

    print("\n" + "=" * 70)
    print("🔬 EXPERIMENTO 1: RAG vs SEM RAG (60 exemplos)")
    print(f"    Modelo: {MODEL}")
    print(f"    Amostras por nível: {SAMPLES_PER_DIFFICULTY}")
    print(f"    Total: {SAMPLES_PER_DIFFICULTY * 3 * 2} exemplos")
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
    normalizer = PromptNormalizer(api_key=api_key, model_name=MODEL)
    response_generator = ResponseGenerator(api_key=api_key, model_name=MODEL)

    # RAGAS components
    eval_chat_model = ChatOpenAI(model="gpt-4o-mini", api_key=api_key)
    eval_llm = LangchainLLMWrapper(langchain_llm=eval_chat_model)
    langchain_embeddings = OpenAIEmbeddings(
        model="text-embedding-3-large", openai_api_key=api_key
    )
    eval_embeddings = LangchainEmbeddingsWrapper(langchain_embeddings)

    all_results = []
    experiment_start = datetime.now()

    # ========================================================================
    # FASE 1: SEM RAG (30 exemplos)
    # ========================================================================
    print("\n" + "=" * 70)
    print("📝 FASE 1: Geração SEM RAG (30 exemplos)")
    print("=" * 70)

    for difficulty in ["fácil", "médio", "difícil"]:
        print(f"\n--- {difficulty.upper()} ({SAMPLES_PER_DIFFICULTY} exemplos) ---")

        for i in range(SAMPLES_PER_DIFFICULTY):
            scenario = SCENARIOS[difficulty][i % len(SCENARIOS[difficulty])]

            print(
                f"   [{i + 1}/{SAMPLES_PER_DIFFICULTY}] Gerando...", end=" ", flush=True
            )

            result = await generate_without_rag(
                response_generator=response_generator,
                difficulty=difficulty,
                user_context=scenario,
                sample_index=i + 1,
            )

            all_results.append(result)

            if result.error:
                print(f"❌ Erro: {result.error[:50]}")
            else:
                print(
                    f"✅ {result.execution_time:.1f}s - {result.generated_email.get('assunto', 'N/A')[:40]}..."
                )

    # ========================================================================
    # FASE 2: COM RAG (30 exemplos)
    # ========================================================================
    print("\n" + "=" * 70)
    print("📝 FASE 2: Geração COM RAG (30 exemplos)")
    print("=" * 70)

    for difficulty in ["fácil", "médio", "difícil"]:
        print(f"\n--- {difficulty.upper()} ({SAMPLES_PER_DIFFICULTY} exemplos) ---")

        for i in range(SAMPLES_PER_DIFFICULTY):
            scenario = SCENARIOS[difficulty][i % len(SCENARIOS[difficulty])]

            print(
                f"   [{i + 1}/{SAMPLES_PER_DIFFICULTY}] Gerando...", end=" ", flush=True
            )

            result = await generate_with_rag(
                response_generator=response_generator,
                normalizer=normalizer,
                vector_store=vector_store,
                reranker=reranker,
                eval_llm=eval_llm,
                eval_embeddings=eval_embeddings,
                difficulty=difficulty,
                user_context=scenario,
                sample_index=i + 1,
            )

            all_results.append(result)

            if result.error:
                print(f"❌ Erro: {result.error[:50]}")
            else:
                rr = result.ragas_scores.get("response_relevancy", 0)
                print(
                    f"✅ {result.execution_time:.1f}s | RR={rr:.2f} | {result.generated_email.get('assunto', 'N/A')[:30]}..."
                )

    # ========================================================================
    # RELATÓRIO FINAL
    # ========================================================================
    experiment_duration = (datetime.now() - experiment_start).total_seconds()

    # Calcula estatísticas
    no_rag_stats = calculate_statistics(all_results, "no_rag")
    with_rag_stats = calculate_statistics(all_results, "with_rag")

    # Gera relatório
    report = {
        "metadata": {
            "experiment": "Experiment 1: RAG vs No RAG",
            "model": MODEL,
            "timestamp": datetime.now().isoformat(),
            "total_duration_seconds": experiment_duration,
            "samples_per_difficulty": SAMPLES_PER_DIFFICULTY,
            "total_samples": len(all_results),
        },
        "summary": {
            "no_rag": no_rag_stats,
            "with_rag": with_rag_stats,
        },
        "detailed_results": [asdict(r) for r in all_results],
    }

    # Salva JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"experiment1_rag_vs_no_rag_{timestamp}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # Print relatório
    print("\n" + "=" * 70)
    print("📊 RELATÓRIO FINAL")
    print("=" * 70)
    print(f"\n⏱️  Duração total: {experiment_duration / 60:.1f} minutos")
    print(f"📄 Resultados salvos em: {filename}")

    print("\n🔹 SEM RAG:")
    print(f"   Exemplos gerados: {no_rag_stats.get('total_samples', 0)}")
    print(f"   Falhas: {no_rag_stats.get('failed_samples', 0)}")
    print(f"   Tempo médio: {no_rag_stats.get('avg_execution_time', 0):.2f}s")

    print("\n🔹 COM RAG:")
    print(f"   Exemplos gerados: {with_rag_stats.get('total_samples', 0)}")
    print(f"   Falhas: {with_rag_stats.get('failed_samples', 0)}")
    print(f"   Tempo médio: {with_rag_stats.get('avg_execution_time', 0):.2f}s")
    if with_rag_stats.get("avg_context_relevance"):
        print(f"   Context Relevance: {with_rag_stats['avg_context_relevance']:.4f}")
    if with_rag_stats.get("avg_faithfulness"):
        print(f"   Faithfulness: {with_rag_stats['avg_faithfulness']:.4f}")
    if with_rag_stats.get("avg_response_relevancy"):
        print(f"   Response Relevancy: {with_rag_stats['avg_response_relevancy']:.4f}")

    print("\n" + "=" * 70)
    print("✅ Experimento concluído!")
    print("=" * 70)

    return all_results, report


if __name__ == "__main__":
    asyncio.run(run_experiment())
