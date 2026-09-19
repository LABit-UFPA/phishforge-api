from uuid import UUID

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.container import Container
from app.core.security import limiter
from app.domain.models.phishing_email import PhishingEmail
from app.domain.services.batch_generation_worker import BatchGenerationWorker
from app.domain.services.generation_pipeline import GenerationPipeline
from app.domain.services.phishing_service import PhishingEmailService
from app.domain.services.response_generator import ResponseGenerator
from app.domain.services.user_answer_evaluator import UserAnswerEvaluator
from app.dto.estatistica import EmailStatistics
from app.dto.query import QueryRequest
from app.dto.requests import (
    BatchGenerationRequest,
    EmailSearchRequest,
    UserAnswerEvaluationRequest,
)
from app.dto.responses import UserAnswerEvaluationResponse
from app.infra.database.repositories.generation_job_repository import GenerationJobRepository

app = APIRouter()


@app.post("/api/v1/generate")
@limiter.limit(settings.GENERATION_RATE_LIMIT)
@inject
async def generate(
    request: Request,
    payload: QueryRequest,
    pipeline: GenerationPipeline = Depends(Provide[Container.generation_pipeline]),
    response_generator: ResponseGenerator = Depends(
        Provide[Container.response_generator]
    ),
    phishing_service: PhishingEmailService = Depends(
        Provide[Container.phishing_service]
    ),
):
    """
    Gera um exemplo de phishing com um pipeline RAG avançado.

    `request: Request` (issue #7): o slowapi precisa desse parametro,
    com esse nome exato, para identificar o IP de quem chama e aplicar
    `GENERATION_RATE_LIMIT`. O corpo da requisicao passou a se chamar
    `payload` para nao colidir.
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
        built = await pipeline.build_context(payload.user_context)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error building context: {str(e)}"
        )

    # 6. Geração Final
    #
    # payload.difficulty ja foi validado e normalizado pelo Pydantic
    # (QueryRequest.difficulty: Difficulty -- ver issue #2). Usamos
    # sempre `.value` (str puro), nunca o membro do Enum diretamente:
    # `Difficulty(str, Enum)` tem __str__ sobrescrito pelo proprio
    # Enum (a partir do Python 3.11), entao `str(payload.difficulty)`
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
            difficulty=payload.difficulty.value,
            context=built.generation_context,
            relevant_docs=built.fused_context,
            is_malicious=payload.is_malicious,
        )
        phishing_example = PhishingEmail(
            **draft.model_dump(),
            nivel=payload.difficulty.value,
            is_malicious=payload.is_malicious,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error generating response: {str(e)}"
        )

    # 7. Persistência
    email_id = await phishing_service.create_email(phishing_example)
    result = phishing_example.dict()
    result["id"] = str(email_id)

    return result


@app.post("/api/v1/generate/batch", status_code=202)
@limiter.limit(settings.GENERATION_RATE_LIMIT)
@inject
async def generate_batch(
    request: Request,
    payload: BatchGenerationRequest,
    background_tasks: BackgroundTasks,
    job_repository: GenerationJobRepository = Depends(
        Provide[Container.generation_job_repository]
    ),
    worker: BatchGenerationWorker = Depends(Provide[Container.batch_generation_worker]),
):
    """
    Aceita um lote de geração e processa em background (issue #11b).

    Antes desta issue, o lote era sequencial dentro da própria request
    HTTP: um `total=100` levava minutos numa única conexão, e qualquer
    ingress/proxy encerrava antes do fim -- o cliente ficava sem
    resposta mesmo com os itens já gravados no banco. Agora a request
    só cria o job e devolve 202 com o id; o progresso e o resultado
    final são lidos por polling em
    `GET /api/v1/generate/batch/{job_id}`.

    Issue #8, item 1: `difficulties` vazia, `total` fora de 1..100 e
    `malicious_ratio` fora de 0..1 são 422 do Pydantic (Field
    min_length/ge/le no DTO), não mais um `if` manual.

    `request: Request` (issue #7): mesmo motivo do `/generate` -- o
    slowapi precisa do parametro para aplicar `GENERATION_RATE_LIMIT`
    por IP. O corpo passou a se chamar `payload`.
    """
    difficulties_values = [d.value for d in payload.difficulties]

    job_id = await job_repository.create(
        context=payload.context,
        difficulties=difficulties_values,
        total=payload.total,
        malicious_ratio=payload.malicious_ratio,
    )

    background_tasks.add_task(
        worker.run,
        job_id=job_id,
        context=payload.context,
        difficulties=difficulties_values,
        total=payload.total,
        malicious_ratio=payload.malicious_ratio,
    )

    return JSONResponse(
        status_code=202,
        content={"job_id": str(job_id), "status": "pendente"},
    )


@app.get("/api/v1/generate/batch/{job_id}")
@inject
async def get_batch_job(
    job_id: UUID,
    job_repository: GenerationJobRepository = Depends(
        Provide[Container.generation_job_repository]
    ),
    phishing_service: PhishingEmailService = Depends(
        Provide[Container.phishing_service]
    ),
):
    """
    Status e resultado de um job de geração em lote (issue #11b).

    `examples` traz o conteúdo completo dos itens já gerados com
    sucesso (não só os ids) -- útil para um frontend de curadoria
    revisar sem uma segunda rodada de requisições. `failures` lista as
    tentativas que falharam, separado dos sucessos (issue #8, item 1).
    """
    job = await job_repository.get_by_id(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    emails = await phishing_service.get_emails_by_ids(job.item_ids)
    examples = []
    for item_id, email in zip(job.item_ids, emails):
        result = email.dict()
        result["id"] = str(item_id)
        examples.append(result)

    return {
        "job_id": str(job.id),
        "status": job.status.value,
        "total_requested": job.total,
        "total_generated": job.total_generated,
        "total_failed": job.total_failed,
        "total_discarded": job.total_discarded,
        "distribution": job.distribution,
        "examples": examples,
        "failures": [f.model_dump() for f in job.failures],
        "error_message": job.error_message,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
    }


@app.get("/api/v1/emails/statistics", response_model=EmailStatistics)
@inject
async def get_statistics(
    phishing_service: PhishingEmailService = Depends(
        Provide[Container.phishing_service]
    ),
):
    # Issue #8: banco fora do ar e "nenhum email cadastrado" sao estados
    # diferentes -- antes os dois respondiam 200 com estatistica zerada.
    # get_stats() nao engole mais a excecao (ver repositorio); aqui ela
    # vira 500 explicito.
    try:
        raw_stats = await phishing_service.repository.get_stats()
        return EmailStatistics(**raw_stats)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Erro ao calcular estatisticas: {str(e)}"
        )


@app.get("/api/v1/emails")
@inject
async def list_emails(
    # Issue #8: EmailSearchRequest existia sem uso, com os parametros
    # soltos repetindo o mesmo shape na mao. Depends() faz o FastAPI
    # tratar cada campo do DTO como query param independente -- mesmo
    # contrato de URL (?categoria=...&limit=...), confirmado antes de
    # trocar. Unica mudanca real: `limit` ganha `ge=1` (o parametro
    # solto so tinha `le=100`; limit=0 antes era aceito e virava
    # `LIMIT 0` silencioso na query).
    filtros: EmailSearchRequest = Depends(),
    phishing_service: PhishingEmailService = Depends(
        Provide[Container.phishing_service]
    ),
):
    try:
        if filtros.search:
            emails = await phishing_service.search_emails(filtros.search, filtros.limit)
        elif filtros.categoria:
            emails = await phishing_service.get_emails_by_categoria(
                filtros.categoria, filtros.limit
            )
        elif filtros.nivel:
            emails = await phishing_service.get_emails_by_nivel(filtros.nivel, filtros.limit)
        else:
            emails = await phishing_service.get_all_emails(filtros.limit, filtros.offset)

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
    Avalia a qualidade do raciocínio do usuário sobre um item (malicioso ou legítimo).

    Recebe:
    - item_content: O item que foi apresentado ao usuário
    - is_malicious: Rótulo verdadeiro do item (True = phishing, False = legítimo)
    - user_verdict: O que o usuário respondeu (True = "é phishing", False = "é legítimo")
    - user_justification: A justificativa do usuário para o veredito

    Retorna:
    - score: Nota de 0 a 5 pela qualidade do raciocínio
    - feedback: Feedback detalhado explicando a nota
    - strengths: Pontos fortes identificados na justificativa
    - improvements: Pontos que podem ser melhorados
    - acerto_por_sorte: True se a conclusão bateu mas o argumento não a sustenta
    """
    try:
        result = await evaluator.evaluate(
            item_content=request.item_content,
            is_malicious=request.is_malicious,
            user_verdict=request.user_verdict,
            user_justification=request.user_justification,
        )
        return UserAnswerEvaluationResponse(
            score=result.score,
            feedback=result.feedback,
            strengths=result.strengths,
            improvements=result.improvements,
            acerto_por_sorte=result.acerto_por_sorte,
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Erro ao avaliar justificativa: {str(e)}"
        )
