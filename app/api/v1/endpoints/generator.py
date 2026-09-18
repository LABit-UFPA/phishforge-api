from typing import Optional
from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query
from ragas.embeddings import BaseRagasEmbeddings
from ragas.llms import BaseRagasLLM

from app.core.container import Container
from app.domain.models.difficulty import Difficulty
from app.domain.models.phishing_email import PhishingEmail
# TODO(#8): importado mas nunca chamado no corpo de generate() — decidir
# entre ligar via background_tasks ou remover, junto com os parametros
# eval_llm/eval_embeddings/background_tasks do endpoint.
from app.domain.services.evaluation import run_and_log_ragas_evaluation  # noqa: F401
from app.domain.services.generation_pipeline import GenerationPipeline
from app.domain.services.phishing_service import PhishingEmailService
from app.domain.services.response_generator import ResponseGenerator
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
    pipeline: GenerationPipeline = Depends(Provide[Container.generation_pipeline]),
    response_generator: ResponseGenerator = Depends(
        Provide[Container.response_generator]
    ),
    phishing_service: PhishingEmailService = Depends(
        Provide[Container.phishing_service]
    ),
    eval_llm: BaseRagasLLM = Depends(Provide[Container.evaluation_llm]),
    eval_embeddings: BaseRagasEmbeddings = Depends(
        Provide[Container.evaluation_embeddings]
    ),
):
    """
    Gera um exemplo de phishing com um pipeline RAG avançado.
    """
    # 1-5. Normalizacao, HyDE, retrieve, rerank e fusao -- ver
    # GenerationPipeline. Extraido nesta issue (#11a) porque a mesma
    # sequencia, escrita a mao aqui dentro, era exatamente o que
    # impedia o /generate/batch de reaproveita-la.
    #
    # A mensagem cobre a pipeline inteira, nao so o retrieve: com as
    # etapas consolidadas, uma falha de normalizacao ou de fusao
    # tambem passa por aqui, e "Error retrieving documents" seria
    # enganoso para essas -- confirmado na pratica ao testar contra um
    # servidor real com chave da OpenAI invalida, onde a falha real
    # era na normalizacao (a primeira chamada de LLM da pipeline).
    try:
        built = await pipeline.build_context(request.user_context)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error building context: {str(e)}"
        )

    # 6. Geração Final
    #
    # request.difficulty ja foi validado e normalizado pelo Pydantic
    # (QueryRequest.difficulty: Difficulty -- ver issue #2). Usamos
    # sempre `.value` (str puro), nunca o membro do Enum diretamente:
    # `Difficulty(str, Enum)` tem __str__ sobrescrito pelo proprio
    # Enum (a partir do Python 3.11), entao `str(request.difficulty)`
    # ou uma f-string dariam "Difficulty.FACIL" em vez de "facil" --
    # confirmado experimentalmente. O PromptTemplate do
    # response_generator usa .format() por baixo, que cairia
    # exatamente nessa armadilha.
    #
    # generate_response devolve um GeneratedItemDraft, SEM `nivel` --
    # dificuldade e entrada da geracao, nao saida do LLM (issue #11).
    # O PhishingEmail final e montado aqui, combinando o draft com o
    # nivel ja validado.
    try:
        draft = await response_generator.generate_response(
            difficulty=request.difficulty.value,
            context=built.generation_context,
            relevant_docs=built.fused_context,
        )
        phishing_example = PhishingEmail(**draft.model_dump(), nivel=request.difficulty.value)
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
    difficulties: list[Difficulty] = Body(..., embed=True),
    total: int = Body(default=10, embed=True),
    pipeline: GenerationPipeline = Depends(Provide[Container.generation_pipeline]),
    response_generator: ResponseGenerator = Depends(
        Provide[Container.response_generator]
    ),
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

    # Normalizacao, HyDE, retrieve, rerank e fusao dependem so do
    # `context`, nao da dificuldade de cada item -- rodam UMA vez para
    # o lote inteiro e sao reaproveitados entre todos os itens (issue
    # #11, passo 3). Antes desta issue, o lote nao rodava nenhuma
    # dessas etapas e usava o chunk de busca (child_text) em vez do
    # bloco completo (parent_content) como contexto academico; agora
    # usa o mesmo pipeline do /generate, so que uma vez em vez de N.
    try:
        built = await pipeline.build_context(context)
    except Exception as e:
        # Mesma ressalva do /generate: a mensagem cobre a pipeline
        # inteira (normalizacao, HyDE, retrieve, rerank, fusao), nao
        # so o retrieve.
        raise HTTPException(
            status_code=500, detail=f"Erro ao montar contexto: {str(e)}"
        )

    base, extra = divmod(total, len(difficulties))
    distribution = {d: base for d in difficulties}
    for i in range(extra):
        distribution[difficulties[i]] += 1

    results = []
    for difficulty, count in distribution.items():
        # .value pelo mesmo motivo do endpoint /generate: Difficulty
        # tem __str__ sobrescrito pelo Enum, entao passar o membro cru
        # para o PromptTemplate (via .format()) ou embuti-lo numa
        # f-string produziria "Difficulty.FACIL" em vez de "facil".
        difficulty_value = difficulty.value
        for _ in range(count):
            try:
                draft = await response_generator.generate_response(
                    difficulty=difficulty_value,
                    context=built.generation_context,
                    relevant_docs=built.fused_context,
                )
                phishing_example = PhishingEmail(**draft.model_dump(), nivel=difficulty_value)
                email_id = await phishing_service.create_email(phishing_example)
                result = phishing_example.dict()
                result["id"] = str(email_id)
                results.append(result)
            except Exception as e:
                results.append(
                    {"error": f"Falha ao gerar exemplo {difficulty_value}: {str(e)}"}
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
