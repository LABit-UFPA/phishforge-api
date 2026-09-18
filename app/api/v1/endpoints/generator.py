from typing import Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from ragas.embeddings import BaseRagasEmbeddings
from ragas.llms import BaseRagasLLM

from app.core.config import settings
from app.core.container import Container
# TODO(#8): importado mas nunca chamado no corpo de generate() — decidir
# entre ligar via background_tasks ou remover, junto com os parametros
# eval_llm/eval_embeddings/background_tasks do endpoint.
from app.domain.services.evaluation import run_and_log_ragas_evaluation  # noqa: F401
from app.domain.services.phishing_service import PhishingEmailService
from app.domain.services.prompt_normalizer import PromptNormalizer
from app.domain.services.reranker import ReRanker
from app.domain.services.response_generator import ResponseGenerator
from app.domain.services.retriever import DocumentRetriever
from app.domain.services.user_answer_evaluator import UserAnswerEvaluator
from app.dto.estatistica import EmailStatistics
from app.dto.query import QueryRequest
from app.dto.requests import UserAnswerEvaluationRequest
from app.dto.responses import UserAnswerEvaluationResponse

app = APIRouter()


@app.post("/api/v1/generate")
@inject
async def generate(
    request: QueryRequest,
    background_tasks: BackgroundTasks,
    response_generator: ResponseGenerator = Depends(
        Provide[Container.response_generator]
    ),
    normalizer: PromptNormalizer = Depends(Provide[Container.prompt_normalizer]),
    retriever: DocumentRetriever = Depends(Provide[Container.retriever]),
    phishing_service: PhishingEmailService = Depends(
        Provide[Container.phishing_service]
    ),
    reranker: ReRanker = Depends(Provide[Container.reranker]),
    eval_llm: BaseRagasLLM = Depends(Provide[Container.evaluation_llm]),
    eval_embeddings: BaseRagasEmbeddings = Depends(
        Provide[Container.evaluation_embeddings]
    ),
):
    """
    Gera um exemplo de phishing com um pipeline RAG avançado.
    """
    # 1. Normaliza o input do usuário
    normalized_data = await normalizer.normalize(request.user_context)
    search_query = normalized_data.search_query
    generation_context = normalized_data.generation_context

    # 2. HyDE (Query Transformation)
    try:
        hyde_context = await response_generator.generate_hypothetical_answer(
            search_query
        )
    except Exception:
        hyde_context = search_query

    # 3. Retrieve (Busca Inicial)
    try:
        candidate_docs = retriever.vector_store.query(
            collection_name=settings.COLLECTION_NAME, query_text=hyde_context, top_k=20
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving documents: {str(e)}"
        )

    # 4. Re-rank (Refinamento da Busca)
    reranked_docs = reranker.rerank(search_query, candidate_docs)

    # 5. Extração e Fusão do Contexto
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
    try:
        phishing_example = await response_generator.generate_response(
            difficulty=request.difficulty,
            context=generation_context,
            relevant_docs=fused_context,
        )
        phishing_example.nivel = request.difficulty
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error generating response: {str(e)}"
        )

    # 7. Persistência
    email_id = await phishing_service.create_email(phishing_example)
    result = phishing_example.dict()
    result["id"] = str(email_id)

    return result


@app.post("/api/v1/generate/batch")
@inject
async def generate_batch(
    context: str = Body(..., embed=True),
    difficulties: list[str] = Body(..., embed=True),
    total: int = Body(default=10, embed=True),
    response_generator: ResponseGenerator = Depends(
        Provide[Container.response_generator]
    ),
    retriever: DocumentRetriever = Depends(Provide[Container.retriever]),
    phishing_service: PhishingEmailService = Depends(
        Provide[Container.phishing_service]
    ),
):
    if not difficulties:
        raise HTTPException(
            status_code=400, detail="A lista de dificuldades não pode estar vazia"
        )
    if total <= 0:
        raise HTTPException(status_code=400, detail="O total deve ser maior que 0")
    if total > 100:
        raise HTTPException(status_code=400, detail="O total máximo permitido é 100")

    try:
        relevant_docs = retriever.vector_store.query(
            collection_name=settings.COLLECTION_NAME, query_text=context, top_k=80
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Erro ao recuperar documentos: {str(e)}"
        )

    docs_texts = [doc.text for doc in relevant_docs[:3]] if relevant_docs else []
    docs_text = "\n\n".join(docs_texts) if docs_texts else "Sem documentos relevantes."

    base, extra = divmod(total, len(difficulties))
    distribution = {d: base for d in difficulties}
    for i in range(extra):
        distribution[difficulties[i]] += 1

    results = []
    for difficulty, count in distribution.items():
        for _ in range(count):
            try:
                phishing_example = await response_generator.generate_response(
                    difficulty=difficulty, context=context, relevant_docs=docs_text
                )
                phishing_example.nivel = difficulty
                email_id = await phishing_service.create_email(phishing_example)
                result = phishing_example.dict()
                result["id"] = str(email_id)
                results.append(result)
            except Exception as e:
                results.append(
                    {"error": f"Falha ao gerar exemplo {difficulty}: {str(e)}"}
                )

    return {
        "total_requested": total,
        "total_generated": len(results),
        "distribution": distribution,
        "examples": results,
    }


@app.get("/api/v1/emails/statistics", response_model=EmailStatistics)
@inject
async def get_statistics(
    phishing_service: PhishingEmailService = Depends(
        Provide[Container.phishing_service]
    ),
):
    try:
        raw_stats = await phishing_service.repository.get_stats()
        return EmailStatistics(**raw_stats)
    except Exception as e:  # noqa: F841 -- ver #8: deveria propagar 500, nao engolir
        return EmailStatistics()


@app.get("/api/v1/emails/statistics/debug")
@inject
async def debug_statistics(
    phishing_service: PhishingEmailService = Depends(
        Provide[Container.phishing_service]
    ),
):
    try:
        raw_stats = await phishing_service.repository.get_stats()
        return {
            "raw_stats": raw_stats,
            "raw_stats_type": str(type(raw_stats)),
            "by_difficulty_type": str(type(raw_stats.get("by_difficulty"))),
            "by_category_type": str(type(raw_stats.get("by_category"))),
            "total_type": str(type(raw_stats.get("total"))),
            "recent_count_type": str(type(raw_stats.get("recent_count"))),
        }
    except Exception as e:
        return {"error": str(e), "error_type": str(type(e).__name__)}


@app.get("/api/v1/emails")
@inject
async def list_emails(
    categoria: Optional[str] = None,
    nivel: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    phishing_service: PhishingEmailService = Depends(
        Provide[Container.phishing_service]
    ),
):
    try:
        if search:
            emails = await phishing_service.search_emails(search, limit)
        elif categoria:
            emails = await phishing_service.get_emails_by_categoria(categoria, limit)
        elif nivel:
            emails = await phishing_service.get_emails_by_nivel(nivel, limit)
        else:
            emails = await phishing_service.get_all_emails(limit, offset)

        return {"emails": [email.dict() for email in emails], "count": len(emails)}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving emails: {str(e)}"
        )


@app.get("/api/v1/emails/{email_id}")
@inject
async def get_email(
    email_id: UUID,
    phishing_service: PhishingEmailService = Depends(
        Provide[Container.phishing_service]
    ),
):
    email = await phishing_service.get_email_by_id(email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return email.dict()


@app.delete("/api/v1/emails/{email_id}")
@inject
async def delete_email(
    email_id: UUID,
    phishing_service: PhishingEmailService = Depends(
        Provide[Container.phishing_service]
    ),
):
    try:
        success = await phishing_service.delete_email(email_id)
        if not success:
            raise HTTPException(status_code=404, detail="Email not found")
        return {"message": "Email deleted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting email: {str(e)}")


@app.post("/api/v1/evaluate/user-answer", response_model=UserAnswerEvaluationResponse)
@inject
async def evaluate_user_answer(
    request: UserAnswerEvaluationRequest,
    evaluator: UserAnswerEvaluator = Depends(Provide[Container.user_answer_evaluator]),
):
    """
    Avalia a justificativa do usuário sobre identificação de phishing.

    Recebe:
    - phishing_example: O exemplo de phishing que foi apresentado ao usuário
    - user_justification: A justificativa do usuário explicando por que é phishing

    Retorna:
    - score: Nota de 0 a 5
    - feedback: Feedback detalhado explicando a nota
    - strengths: Pontos fortes identificados na justificativa
    - improvements: Pontos que podem ser melhorados
    """
    try:
        result = await evaluator.evaluate(
            phishing_example=request.phishing_example,
            user_justification=request.user_justification,
        )
        return UserAnswerEvaluationResponse(
            score=result.score,
            feedback=result.feedback,
            strengths=result.strengths,
            improvements=result.improvements,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Erro ao avaliar justificativa: {str(e)}"
        )
