#!/usr/bin/env python3
"""
Script de Avaliação SEM RAG

Este script testa a geração de emails de phishing SEM usar RAG
(sem buscar documentos no Qdrant). O objetivo é comparar a qualidade
da geração usando apenas o conhecimento interno do modelo.

Testa apenas GPT-4 nos 3 níveis de dificuldade.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper

from app.core.config import settings
from app.domain.models.phishing_email import PhishingEmail
from app.domain.services.response_generator import ResponseGenerator

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
class NoRagResult:
    """Estrutura para armazenar resultados do teste sem RAG."""

    model: str
    difficulty: str
    user_context: str
    generated_email: dict
    execution_time: float
    error: Optional[str] = None


async def run_no_rag_evaluation():
    """Executa avaliação sem RAG."""

    print("\n" + "=" * 70)
    print("🔬 EXPERIMENTO: Geração SEM RAG")
    print(f"    Modelo: {MODEL_TO_TEST}")
    print("=" * 70 + "\n")

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        print("❌ Erro: OPENAI_API_KEY não configurada!")
        return

    # Inicializa o gerador
    logger.info("Inicializando ResponseGenerator...")
    response_generator = ResponseGenerator(api_key=api_key, model_name=MODEL_TO_TEST)

    results = []

    for difficulty, user_context in USER_CONTEXTS.items():
        print(f"\n--- {difficulty.upper()} ---")
        start_time = datetime.now()

        try:
            # Geração SEM contexto RAG (string vazia)
            logger.info(f"Gerando email SEM RAG ({difficulty})...")

            # Passa string vazia como relevant_docs - SEM RAG
            phishing_example = await response_generator.generate_response(
                difficulty=difficulty,
                context=user_context,  # Usa o contexto do usuário diretamente
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

            result = NoRagResult(
                model=MODEL_TO_TEST,
                difficulty=difficulty,
                user_context=user_context,
                generated_email=generated_email,
                execution_time=execution_time,
            )

            results.append(result)

            # Print resultado
            print(f"   ⏱️  Tempo: {execution_time:.2f}s")
            print(f"   📧 Assunto: {generated_email.get('assunto', 'N/A')[:60]}...")
            print(f"   📝 Remetente: {generated_email.get('remetente', 'N/A')}")

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            logger.error(f"Erro: {e}")
            import traceback

            traceback.print_exc()
            results.append(
                NoRagResult(
                    model=MODEL_TO_TEST,
                    difficulty=difficulty,
                    user_context=user_context,
                    generated_email={},
                    execution_time=execution_time,
                    error=str(e),
                )
            )

    # Gera relatório
    report = generate_report(results)

    # Salva JSON
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"no_rag_evaluation_{timestamp}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n📄 Resultados salvos em: {filename}")

    # Print relatório final
    print_final_report(results)

    return results, report


def generate_report(results: list[NoRagResult]) -> dict:
    """Gera relatório consolidado."""
    report = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "model": MODEL_TO_TEST,
            "experiment": "Generation WITHOUT RAG",
            "total_evaluations": len(results),
            "rag_enabled": False,
        },
        "summary": {
            "avg_execution_time": sum(r.execution_time for r in results if not r.error)
            / max(len([r for r in results if not r.error]), 1),
            "successful_count": len([r for r in results if not r.error]),
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
                "generated_email": r.generated_email,
                "execution_time": r.execution_time,
                "error": r.error,
            }
        )

    return report


def print_final_report(results: list[NoRagResult]):
    """Imprime relatório final."""
    print("\n" + "=" * 70)
    print("📊 RELATÓRIO FINAL: Geração SEM RAG")
    print("=" * 70)

    successful = [r for r in results if not r.error]

    if successful:
        avg_time = sum(r.execution_time for r in successful) / len(successful)
        print(f"\n🔹 Modelo: {MODEL_TO_TEST}")
        print(f"   Testes bem-sucedidos: {len(successful)}/{len(results)}")
        print(f"   Tempo médio: {avg_time:.2f}s")

        print("\n📧 Emails Gerados:")
        for r in successful:
            print(f"\n   [{r.difficulty.upper()}]")
            print(f"   Assunto: {r.generated_email.get('assunto', 'N/A')}")
            print(f"   Remetente: {r.generated_email.get('remetente', 'N/A')}")
            print(f"   Tempo: {r.execution_time:.2f}s")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(run_no_rag_evaluation())
