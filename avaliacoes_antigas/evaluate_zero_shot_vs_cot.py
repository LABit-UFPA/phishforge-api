#!/usr/bin/env python3
"""
Script de Avaliação Zero-Shot vs Chain-of-Thought

Este script compara a geração de emails de phishing usando:
- Prompt Zero-Shot (direto, sem etapas de raciocínio)
- Prompt Chain-of-Thought (com etapas estruturadas)

Testa apenas GPT-4 nos 3 níveis de dificuldade.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from openai import OpenAI
from qdrant_client import QdrantClient
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper

from app.core.config import settings
from app.domain.models.phishing_email import PhishingEmail
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


# ============================================================================
# PROMPT ZERO-SHOT (Simples, direto, sem etapas de raciocínio)
# ============================================================================

ZERO_SHOT_PROMPT = PromptTemplate(
    input_variables=["context", "difficulty", "relevant_docs"],
    template=(
        "You are a cybersecurity expert specialized in creating educational phishing emails.\n\n"
        "**Academic Knowledge:**\n"
        "{relevant_docs}\n\n"
        "**Task:**\n"
        "Create a phishing email with difficulty level '{difficulty}' for the following scenario:\n"
        "{context}\n\n"
        "**Difficulty Levels:**\n"
        "- EASY: Obvious errors, suspicious sender, exaggerated urgency, visible red flags\n"
        "- MEDIUM: Professional appearance with subtle suspicious indicators\n"
        "- HARD: Highly sophisticated, nearly indistinguishable from legitimate communication\n\n"
        "Generate the phishing email in the PhishingEmail JSON format."
    ),
)


# ============================================================================
# PROMPT CHAIN-OF-THOUGHT (Com etapas estruturadas de raciocínio)
# ============================================================================

COT_PROMPT = PromptTemplate(
    input_variables=["context", "difficulty", "relevant_docs"],
    template=(
        "## 1. SYSTEM INSTRUCTION\n"
        "You are a cybersecurity expert specialized in creating educational phishing emails based on academic research.\n\n"
        "## 2. RETRIEVED CONTEXT\n"
        "**ACADEMIC KNOWLEDGE FROM VECTOR DATABASE:**\n"
        "{relevant_docs}\n\n"
        "## 3. TASK SPECIFICATION\n"
        "**Difficulty Level:** {difficulty}\n"
        "**Specific Scenario:** {context}\n\n"
        "### DIFFICULTY LEVEL CHARACTERISTICS\n\n"
        "**EASY:**\n"
        "- Clearly suspicious or generic sender (e.g., noreply@company123.com)\n"
        "- Subject with obvious spelling or grammar errors\n"
        "- Exaggerated and obvious urgency ('URGENT!!!', 'IMMEDIATE ACTION')\n"
        "- Visibly suspicious or shortened links\n"
        "- Inconsistent or amateur formatting\n"
        "- No personalization (generic greeting)\n"
        "- Direct and explicit threats\n"
        "- Obvious request for sensitive information\n\n"
        "**MEDIUM:**\n"
        "- Partially convincing sender with minor inconsistencies\n"
        "- Plausible subject with some suspicious indicators\n"
        "- Moderate urgency with apparent justification\n"
        "- Links that appear legitimate at first glance\n"
        "- More professional formatting, similar to business communications\n"
        "- Basic personalization (recipient's name)\n"
        "- Mix of true and false information\n"
        "- Partially convincing logos and visual identity\n"
        "- Indirect call-to-action (download, click, verify)\n\n"
        "**HARD:**\n"
        "- Highly convincing sender, indistinguishable from legitimate communications\n"
        "- Contextually perfect and relevant subject\n"
        "- Subtle and well-justified urgency (realistic business context)\n"
        "- Links with domains similar to originals (subtle typosquatting)\n"
        "- Professional formatting identical to official communications\n"
        "- Advanced personalization (role, specific projects, colleagues)\n"
        "- Specific and verifiable information about company/person\n"
        "- Perfect visual identity (logos, signatures, layout)\n"
        "- Relevant temporal context (current events, important dates)\n"
        "- Sophisticated social engineering (psychology, authority, reciprocity)\n\n"
        "## 4. CHAIN OF THOUGHT - STRUCTURED REASONING PROCESS\n"
        "Follow this step-by-step reasoning process:\n\n"
        "**STEP 1 - ANALYSIS:**\n"
        "- What is the requested scenario? What organization/situation is being simulated?\n"
        "- Who would be the typical target? What elements make this scenario plausible?\n\n"
        "**STEP 2 - TACTIC SELECTION:**\n"
        "- Which phishing techniques from academic knowledge are most applicable?\n"
        "- Relevant psychological triggers: which ones to use?\n"
        "- Attack vectors appropriate to the context\n\n"
        "**STEP 3 - EMAIL CONSTRUCTION:**\n"
        "How should the '{difficulty}' level influence each component?\n"
        "- Sender: How should it appear at {difficulty} level?\n"
        "- Subject: What degree of sophistication is expected?\n"
        "- Body: How convincing and personalized should it be?\n"
        "- Links/URLs: What level of camouflage is needed?\n"
        "- Call-to-action: How direct or subtle should it be?\n\n"
        "**STEP 4 - VALIDATION:**\n"
        "Check completeness and consistency:\n"
        "- ✓ Sender defined?\n"
        "- ✓ Appropriate subject?\n"
        "- ✓ Complete and convincing body?\n"
        "- ✓ Clear call-to-action?\n"
        "- ✓ Academic techniques implemented?\n"
        "- ✓ Difficulty level respected?\n"
        "- ✓ Coherence between scenario + tactics + level?\n\n"
        "## RESPONSE FORMAT\n"
        "Generate ONLY the JSON object in PhishingEmail format.\n"
        "Do not explicitly show reasoning steps, but your result should demonstrate that you followed the Chain-of-Thought process."
    ),
)


class ZeroShotResponseGenerator:
    """Gerador de respostas usando prompt Zero-Shot."""

    def __init__(self, api_key: str, model_name: str = "gpt-4"):
        self.llm = ChatOpenAI(
            model_name=model_name, api_key=api_key, temperature=0.7
        ).with_structured_output(PhishingEmail)

        self.text_llm = ChatOpenAI(
            model_name=model_name, api_key=api_key, temperature=0.2
        )

        self.prompt_template = ZERO_SHOT_PROMPT
        self.chain = self.prompt_template | self.llm

        # HyDE prompt (mesmo do original)
        self.hyde_prompt_template = PromptTemplate(
            input_variables=["query"],
            template=(
                "As a cybersecurity expert, generate a technical and specific response to the user's query. "
                "This response should include precise terminology, technical concepts, and specific details "
                "that an academic document on the topic would contain.\n\n"
                "**Query:** {query}\n\n"
                "**Technical response:**\n"
            ),
        )
        self.hyde_chain = self.hyde_prompt_template | self.text_llm

    async def generate_response(
        self, difficulty: str, context: str, relevant_docs: str
    ):
        difficulty_normalized = difficulty.lower().strip()
        if difficulty_normalized not in [
            "fácil",
            "médio",
            "difícil",
            "facil",
            "medio",
            "dificil",
            "easy",
            "medium",
            "hard",
        ]:
            difficulty_normalized = "medium"

        # Mapear para inglês
        difficulty_map = {
            "fácil": "easy",
            "facil": "easy",
            "easy": "easy",
            "médio": "medium",
            "medio": "medium",
            "medium": "medium",
            "difícil": "hard",
            "dificil": "hard",
            "hard": "hard",
        }
        difficulty_en = difficulty_map.get(difficulty_normalized, "medium")

        return await self.chain.ainvoke(
            {
                "context": context,
                "difficulty": difficulty_en,
                "relevant_docs": relevant_docs,
            }
        )

    async def generate_hypothetical_answer(self, query: str) -> str:
        try:
            response = await self.hyde_chain.ainvoke({"query": query})
            return response.content.strip().strip('"')
        except Exception as e:
            logging.error(f"Error generating hypothetical answer: {e}")
            return query

    async def fuse_and_summarize_context(
        self, generation_context: str, contexts: list[str]
    ) -> str:
        if not contexts:
            return "No specific technical knowledge available."

        full_context_text = "\n\n---\n\n".join(contexts)

        prompt = PromptTemplate(
            input_variables=["generation_context", "full_context_text"],
            template=(
                "Extract relevant technical information from the academic documents for the task.\n\n"
                "**Task:** {generation_context}\n\n"
                "**Documents:** {full_context_text}\n\n"
                "**Extracted knowledge (focused and actionable):**"
            ),
        )

        fusion_chain = prompt | self.text_llm

        try:
            response = await fusion_chain.ainvoke(
                {
                    "generation_context": generation_context,
                    "full_context_text": full_context_text,
                }
            )
            return response.content.strip()
        except Exception as e:
            logging.error(f"Error fusing context: {e}")
            return full_context_text


class CoTResponseGenerator:
    """Gerador de respostas usando prompt Chain-of-Thought."""

    def __init__(self, api_key: str, model_name: str = "gpt-4"):
        self.llm = ChatOpenAI(
            model_name=model_name, api_key=api_key, temperature=0.7
        ).with_structured_output(PhishingEmail)

        self.text_llm = ChatOpenAI(
            model_name=model_name, api_key=api_key, temperature=0.2
        )

        self.prompt_template = COT_PROMPT
        self.chain = self.prompt_template | self.llm

        self.hyde_prompt_template = PromptTemplate(
            input_variables=["query"],
            template=(
                "As a cybersecurity expert, generate a technical and specific response to the user's query. "
                "This response should include precise terminology, technical concepts, and specific details "
                "that an academic document on the topic would contain.\n\n"
                "**Query:** {query}\n\n"
                "**Technical response:**\n"
            ),
        )
        self.hyde_chain = self.hyde_prompt_template | self.text_llm

    async def generate_response(
        self, difficulty: str, context: str, relevant_docs: str
    ):
        difficulty_normalized = difficulty.lower().strip()
        if difficulty_normalized not in [
            "fácil",
            "médio",
            "difícil",
            "facil",
            "medio",
            "dificil",
            "easy",
            "medium",
            "hard",
        ]:
            difficulty_normalized = "medium"

        difficulty_map = {
            "fácil": "easy",
            "facil": "easy",
            "easy": "easy",
            "médio": "medium",
            "medio": "medium",
            "medium": "medium",
            "difícil": "hard",
            "dificil": "hard",
            "hard": "hard",
        }
        difficulty_en = difficulty_map.get(difficulty_normalized, "medium")

        return await self.chain.ainvoke(
            {
                "context": context,
                "difficulty": difficulty_en,
                "relevant_docs": relevant_docs,
            }
        )

    async def generate_hypothetical_answer(self, query: str) -> str:
        try:
            response = await self.hyde_chain.ainvoke({"query": query})
            return response.content.strip().strip('"')
        except Exception as e:
            logging.error(f"Error generating hypothetical answer: {e}")
            return query

    async def fuse_and_summarize_context(
        self, generation_context: str, contexts: list[str]
    ) -> str:
        if not contexts:
            return "No specific technical knowledge available."

        full_context_text = "\n\n---\n\n".join(contexts)

        prompt = PromptTemplate(
            input_variables=["generation_context", "full_context_text"],
            template=(
                "Analyze the academic documents and extract specific technical information for the requested task.\n\n"
                "**Creative Task:** {generation_context}\n\n"
                "**Academic Documents:** {full_context_text}\n\n"
                "**Extraction Instructions:**\n"
                "1. Identify specific tactics, techniques and methods relevant to the task\n"
                "2. Extract psychological triggers and strategies mentioned\n"
                "3. Include practical examples and technical terminology\n"
                "4. Keep only information DIRECTLY useful for email creation\n"
                "5. Organize in clear and actionable format\n"
                "6. Relate techniques to sophistication levels (easy, medium, hard)\n\n"
                "**Focused Technical Knowledge:**"
            ),
        )

        fusion_chain = prompt | self.text_llm

        try:
            response = await fusion_chain.ainvoke(
                {
                    "generation_context": generation_context,
                    "full_context_text": full_context_text,
                }
            )
            return response.content.strip()
        except Exception as e:
            logging.error(f"Error fusing context: {e}")
            return full_context_text


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
class ExperimentResult:
    """Estrutura para armazenar resultados do experimento."""

    prompt_type: str  # "zero-shot" ou "chain-of-thought"
    difficulty: str
    user_context: str
    search_query: str
    generation_context: str
    generated_email: dict
    ragas_scores: dict
    execution_time: float
    error: Optional[str] = None


async def run_experiment():
    """Executa o experimento Zero-Shot vs Chain-of-Thought."""

    print("\n" + "=" * 70)
    print("🔬 EXPERIMENTO: Zero-Shot vs Chain-of-Thought")
    print(f"    Modelo: {MODEL_TO_TEST}")
    print("=" * 70 + "\n")

    api_key = settings.OPENAI_API_KEY
    if not api_key:
        print("❌ Erro: OPENAI_API_KEY não configurada!")
        return

    # Inicializa componentes compartilhados
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

    # RAGAS components
    eval_chat_model = ChatOpenAI(model="gpt-4o-mini", api_key=api_key)
    eval_llm = LangchainLLMWrapper(langchain_llm=eval_chat_model)
    langchain_embeddings = OpenAIEmbeddings(
        model="text-embedding-3-large", openai_api_key=api_key
    )
    eval_embeddings = LangchainEmbeddingsWrapper(langchain_embeddings)

    # Geradores
    zero_shot_generator = ZeroShotResponseGenerator(
        api_key=api_key, model_name=MODEL_TO_TEST
    )
    cot_generator = CoTResponseGenerator(api_key=api_key, model_name=MODEL_TO_TEST)

    results = []

    for prompt_type, generator in [
        ("zero-shot", zero_shot_generator),
        ("chain-of-thought", cot_generator),
    ]:
        print(f"\n{'=' * 70}")
        print(f"📝 Testando: {prompt_type.upper()}")
        print(f"{'=' * 70}")

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
                hyde_context = await generator.generate_hypothetical_answer(
                    search_query
                )

                # 3. Retrieve
                logger.info("Buscando documentos...")
                candidate_docs = vector_store.query(
                    collection_name="phishing_articles",
                    query_text=hyde_context,
                    top_k=20,
                )

                # 4. Re-rank
                logger.info("Re-rankeando...")
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

                fused_context = await generator.fuse_and_summarize_context(
                    generation_context=generation_context, contexts=final_contexts
                )

                # 6. Geração
                logger.info(f"Gerando email ({prompt_type})...")
                phishing_example = await generator.generate_response(
                    difficulty=difficulty,
                    context=generation_context,
                    relevant_docs=fused_context,
                )

                generated_email = (
                    phishing_example.dict()
                    if hasattr(phishing_example, "dict")
                    else dict(phishing_example)
                )

                logger.info(
                    f"   Assunto: {generated_email.get('assunto', 'N/A')[:50]}..."
                )

                # 7. RAGAS
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

                result = ExperimentResult(
                    prompt_type=prompt_type,
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
                print(
                    f"   📊 Context Relevance: {cr:.4f}"
                    if cr
                    else "   📊 Context Relevance: N/A"
                )
                print(
                    f"   📊 Faithfulness: {f:.4f}" if f else "   📊 Faithfulness: N/A"
                )
                print(
                    f"   📊 Response Relevancy: {rr:.4f}"
                    if rr
                    else "   📊 Response Relevancy: N/A"
                )

            except Exception as e:
                execution_time = (datetime.now() - start_time).total_seconds()
                logger.error(f"Erro: {e}")
                results.append(
                    ExperimentResult(
                        prompt_type=prompt_type,
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
    filename = f"zero_shot_vs_cot_{timestamp}.json"
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n📄 Resultados salvos em: {filename}")

    # Print relatório final
    print_final_report(results)

    return results, report


def generate_report(results: list[ExperimentResult]) -> dict:
    """Gera relatório consolidado."""
    report = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "model": MODEL_TO_TEST,
            "experiment": "Zero-Shot vs Chain-of-Thought",
            "total_evaluations": len(results),
        },
        "summary_by_prompt_type": {},
        "summary_by_difficulty": {},
        "detailed_results": [],
    }

    # Por tipo de prompt
    for prompt_type in ["zero-shot", "chain-of-thought"]:
        type_results = [
            r for r in results if r.prompt_type == prompt_type and not r.error
        ]
        if type_results:
            cr_scores = [
                r.ragas_scores.get("context_relevance")
                for r in type_results
                if r.ragas_scores.get("context_relevance") is not None
            ]
            f_scores = [
                r.ragas_scores.get("faithfulness")
                for r in type_results
                if r.ragas_scores.get("faithfulness") is not None
            ]
            rr_scores = [
                r.ragas_scores.get("response_relevancy")
                for r in type_results
                if r.ragas_scores.get("response_relevancy") is not None
            ]

            report["summary_by_prompt_type"][prompt_type] = {
                "avg_context_relevance": sum(cr_scores) / len(cr_scores)
                if cr_scores
                else None,
                "avg_faithfulness": sum(f_scores) / len(f_scores) if f_scores else None,
                "avg_response_relevancy": sum(rr_scores) / len(rr_scores)
                if rr_scores
                else None,
                "avg_execution_time": sum(r.execution_time for r in type_results)
                / len(type_results),
                "sample_count": len(type_results),
            }

    # Por dificuldade
    for difficulty in USER_CONTEXTS.keys():
        diff_results = [
            r for r in results if r.difficulty == difficulty and not r.error
        ]
        if diff_results:
            cr_scores = [
                r.ragas_scores.get("context_relevance")
                for r in diff_results
                if r.ragas_scores.get("context_relevance") is not None
            ]
            f_scores = [
                r.ragas_scores.get("faithfulness")
                for r in diff_results
                if r.ragas_scores.get("faithfulness") is not None
            ]
            rr_scores = [
                r.ragas_scores.get("response_relevancy")
                for r in diff_results
                if r.ragas_scores.get("response_relevancy") is not None
            ]

            report["summary_by_difficulty"][difficulty] = {
                "avg_context_relevance": sum(cr_scores) / len(cr_scores)
                if cr_scores
                else None,
                "avg_faithfulness": sum(f_scores) / len(f_scores) if f_scores else None,
                "avg_response_relevancy": sum(rr_scores) / len(rr_scores)
                if rr_scores
                else None,
                "avg_execution_time": sum(r.execution_time for r in diff_results)
                / len(diff_results),
                "sample_count": len(diff_results),
            }

    # Detalhado
    for r in results:
        report["detailed_results"].append(
            {
                "prompt_type": r.prompt_type,
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


def print_final_report(results: list[ExperimentResult]):
    """Imprime relatório final."""
    print("\n" + "=" * 70)
    print("📊 RELATÓRIO FINAL: Zero-Shot vs Chain-of-Thought")
    print("=" * 70)

    for prompt_type in ["zero-shot", "chain-of-thought"]:
        type_results = [
            r for r in results if r.prompt_type == prompt_type and not r.error
        ]
        if type_results:
            cr_scores = [
                r.ragas_scores.get("context_relevance")
                for r in type_results
                if r.ragas_scores.get("context_relevance") is not None
            ]
            f_scores = [
                r.ragas_scores.get("faithfulness")
                for r in type_results
                if r.ragas_scores.get("faithfulness") is not None
            ]
            rr_scores = [
                r.ragas_scores.get("response_relevancy")
                for r in type_results
                if r.ragas_scores.get("response_relevancy") is not None
            ]

            avg_cr = sum(cr_scores) / len(cr_scores) if cr_scores else 0
            avg_f = sum(f_scores) / len(f_scores) if f_scores else 0
            avg_rr = sum(rr_scores) / len(rr_scores) if rr_scores else 0
            avg_time = sum(r.execution_time for r in type_results) / len(type_results)

            print(f"\n🔹 {prompt_type.upper()}")
            print(f"   Context Relevance:  {avg_cr:.4f}")
            print(f"   Faithfulness:       {avg_f:.4f}")
            print(f"   Response Relevancy: {avg_rr:.4f}")
            print(f"   Tempo médio:        {avg_time:.2f}s")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    asyncio.run(run_experiment())
