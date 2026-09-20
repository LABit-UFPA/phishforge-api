import logging
from typing import Literal, Optional
from uuid import UUID

import asyncpg
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.api.v1.endpoints.deps import require_researcher
from app.core.config import settings
from app.core.container import Container
from app.domain.services import researcher_export_service as export
from app.domain.services.expert_auth_service import ExpertAuthService
from app.domain.services.researcher_summary_service import resumir
from app.dto.researcher_requests import (
    EspecialistaCreateRequest,
    RodadaCreateRequest,
    RodadaItensRequest,
)
from app.dto.researcher_responses import (
    EspecialistaCriadoResponse,
    EspecialistaLinha,
    ItemCorpusResponse,
    RodadaDetalheResponse,
    ResumoResponse,
    RodadaItensResponse,
    RodadaResponse,
)
from app.infra.database.repositories.evaluation_round_repository import EvaluationRoundRepository
from app.infra.database.repositories.expert_repository import ExpertRepository
from app.infra.database.repositories.researcher_repository import (
    ItensInvalidos,
    ResearcherRepository,
    RodadaNaoEditavel,
    RodadaNaoEncontrada,
    TransicaoInvalida,
)

audit_log = logging.getLogger("app.audit")

# Terceiro roteador (issue #38): fora do `require_api_key` do backend Go
# e fora do JWT do especialista -- autentica so por `require_researcher`
# (RESEARCHER_API_KEY, chave distinta das outras duas).
router = APIRouter(
    prefix="/api/v1/researcher",
    tags=["researcher"],
    dependencies=[Depends(require_researcher)],
)


def _rodada_response(r) -> RodadaResponse:
    return RodadaResponse(
        id=r.id, nome=r.nome, descricao=r.descricao, status=r.status,
        tcle_versao=r.tcle_versao, created_at=r.created_at,
    )


def _link(codigo: str) -> str:
    return f"{settings.EXPERT_FRONTEND_URL.rstrip('/')}/avaliacao/entrar?codigo={codigo}"


async def _exigir_rodada(rodada_id: UUID, rounds: EvaluationRoundRepository):
    rodada = await rounds.get_by_id(rodada_id)
    if rodada is None:
        raise HTTPException(status_code=404, detail="Rodada nao encontrada.")
    return rodada


@router.post("/rodadas", response_model=RodadaResponse, status_code=201)
@inject
async def criar_rodada(
    body: RodadaCreateRequest,
    rounds: EvaluationRoundRepository = Depends(Provide[Container.evaluation_round_repository]),
):
    rodada = await rounds.create(
        nome=body.nome, descricao=body.descricao,
        tcle_versao=body.tcle_versao, tcle_texto_md=body.tcle_texto_md,
    )
    return _rodada_response(rodada)


@router.get("/rodadas", response_model=list[RodadaResponse])
@inject
async def listar_rodadas(
    repo: ResearcherRepository = Depends(Provide[Container.researcher_repository]),
):
    return [RodadaResponse(**r) for r in await repo.listar_rodadas()]


@router.get("/rodadas/{rodada_id}", response_model=RodadaDetalheResponse)
@inject
async def obter_rodada(
    rodada_id: UUID,
    rounds: EvaluationRoundRepository = Depends(Provide[Container.evaluation_round_repository]),
    repo: ResearcherRepository = Depends(Provide[Container.researcher_repository]),
):
    rodada = await _exigir_rodada(rodada_id, rounds)
    itens = await repo.itens_da_rodada(rodada_id)
    return RodadaDetalheResponse(
        **_rodada_response(rodada).model_dump(exclude={"total_itens"}),
        total_itens=len(itens),
        email_ids=[i["id"] for i in itens],
        itens=itens,
    )


@router.get("/corpus", response_model=list[ItemCorpusResponse])
@inject
async def listar_corpus(
    nivel: Optional[Literal["facil", "medio", "dificil"]] = Query(default=None),
    search: Optional[str] = Query(default=None, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    repo: ResearcherRepository = Depends(Provide[Container.researcher_repository]),
):
    return await repo.listar_corpus(nivel, search.strip() if search else None, limit, offset)


@router.put("/rodadas/{rodada_id}/itens", response_model=RodadaItensResponse)
@inject
async def definir_itens(
    rodada_id: UUID,
    body: RodadaItensRequest,
    repo: ResearcherRepository = Depends(Provide[Container.researcher_repository]),
):
    try:
        distribuicao = await repo.substituir_itens(rodada_id, body.email_ids)
    except RodadaNaoEncontrada:
        raise HTTPException(status_code=404, detail="Rodada nao encontrada.")
    except RodadaNaoEditavel as e:
        raise HTTPException(
            status_code=409,
            detail=f"A composicao da rodada esta congelada (status '{e}'): so e possivel alterar itens em rascunho.",
        )
    except ItensInvalidos as e:
        raise HTTPException(status_code=422, detail=e.detalhe)
    return RodadaItensResponse(total=len(body.email_ids), distribuicao=distribuicao)


async def _transicao(repo: ResearcherRepository, rodada_id: UUID, de: str, para: str, esperados=None):
    try:
        rodada = await repo.transicionar(rodada_id, de, para, esperados)
    except RodadaNaoEncontrada:
        raise HTTPException(status_code=404, detail="Rodada nao encontrada.")
    except TransicaoInvalida as e:
        raise HTTPException(
            status_code=409, detail=f"Transicao invalida: a rodada esta '{e.atual}', esperado '{de}'."
        )
    except ItensInvalidos as e:
        raise HTTPException(status_code=409, detail=e.detalhe)
    return _rodada_response(rodada)


@router.post("/rodadas/{rodada_id}/abrir", response_model=RodadaResponse)
@inject
async def abrir_rodada(
    rodada_id: UUID,
    repo: ResearcherRepository = Depends(Provide[Container.researcher_repository]),
):
    return await _transicao(repo, rodada_id, "rascunho", "aberta", settings.RODADA_ITENS_ESPERADOS)


@router.post("/rodadas/{rodada_id}/encerrar", response_model=RodadaResponse)
@inject
async def encerrar_rodada(
    rodada_id: UUID,
    repo: ResearcherRepository = Depends(Provide[Container.researcher_repository]),
):
    return await _transicao(repo, rodada_id, "aberta", "encerrada")


@router.post("/especialistas", response_model=EspecialistaCriadoResponse, status_code=201)
@inject
async def criar_especialista(
    body: EspecialistaCreateRequest,
    rounds: EvaluationRoundRepository = Depends(Provide[Container.evaluation_round_repository]),
    experts: ExpertRepository = Depends(Provide[Container.expert_repository]),
):
    rodada = await _exigir_rodada(body.rodada_id, rounds)
    if rodada.status == "encerrada":
        raise HTTPException(status_code=409, detail="A rodada esta encerrada.")

    codigo = ExpertAuthService.gerar_codigo()
    try:
        especialista = await experts.create(
            nome=body.nome, sobrenome=body.sobrenome, email=body.email,
            codigo_hash=ExpertAuthService.hash_codigo(codigo),
            codigo_prefixo=ExpertAuthService.prefixo_codigo(codigo),
            rodada_id=rodada.id,
        )
    except asyncpg.exceptions.UniqueViolationError:
        raise HTTPException(status_code=409, detail="Ja existe um especialista com este e-mail.")
    return EspecialistaCriadoResponse(id=especialista.id, codigo_acesso=codigo, link=_link(codigo))


@router.post("/especialistas/{especialista_id}/recodificar", response_model=EspecialistaCriadoResponse)
@inject
async def recodificar_especialista(
    especialista_id: UUID,
    repo: ResearcherRepository = Depends(Provide[Container.researcher_repository]),
    experts: ExpertRepository = Depends(Provide[Container.expert_repository]),
):
    especialista = await experts.get_by_id(especialista_id)
    if especialista is None:
        raise HTTPException(status_code=404, detail="Especialista nao encontrado.")
    if especialista.revogado_em is not None:
        raise HTTPException(status_code=409, detail="Especialista revogou o consentimento.")

    codigo = ExpertAuthService.gerar_codigo()
    await repo.recodificar(
        especialista_id, ExpertAuthService.hash_codigo(codigo), ExpertAuthService.prefixo_codigo(codigo)
    )
    return EspecialistaCriadoResponse(id=especialista_id, codigo_acesso=codigo, link=_link(codigo))


@router.get("/especialistas", response_model=list[EspecialistaLinha])
@inject
async def listar_especialistas(
    rodada_id: Optional[UUID] = Query(default=None),
    repo: ResearcherRepository = Depends(Provide[Container.researcher_repository]),
):
    linhas = await repo.listar_especialistas(rodada_id)
    return [
        EspecialistaLinha(
            id=r["id"], nome=r["nome"], sobrenome=r["sobrenome"], email=r["email"],
            rodada_id=r["rodada_id"], concluidas=r["concluidas"], total=r["total"],
            consentimento_versao=r["consentimento_versao"], consentimento_em=r["consentimento_em"],
            revogado_em=r["revogado_em"], ultimo_acesso_em=r["ultimo_acesso_em"],
        )
        for r in linhas
    ]


@router.get("/rodadas/{rodada_id}/resumo", response_model=ResumoResponse)
@inject
async def resumo_rodada(
    rodada_id: UUID,
    rounds: EvaluationRoundRepository = Depends(Provide[Container.evaluation_round_repository]),
    repo: ResearcherRepository = Depends(Provide[Container.researcher_repository]),
):
    await _exigir_rodada(rodada_id, rounds)
    avaliacoes = await repo.dataset_avaliacoes(rodada_id)
    anotacoes = await repo.dataset_anotacoes(rodada_id)
    return resumir(avaliacoes, anotacoes)


@router.get("/rodadas/{rodada_id}/export")
@inject
async def exportar(
    rodada_id: UUID,
    request: Request,
    dataset: Literal["avaliacoes", "anotacoes", "itens", "especialistas"] = Query(...),
    format: Literal["csv", "json"] = Query(default="csv"),
    incluir_pii: bool = Query(default=False),
    rounds: EvaluationRoundRepository = Depends(Provide[Container.evaluation_round_repository]),
    repo: ResearcherRepository = Depends(Provide[Container.researcher_repository]),
):
    await _exigir_rodada(rodada_id, rounds)

    if incluir_pii and dataset != "especialistas":
        raise HTTPException(status_code=422, detail="incluir_pii so se aplica ao dataset 'especialistas'.")
    if incluir_pii:
        # A chave do pesquisador e compartilhada, entao "quem" e o que
        # o servidor consegue saber: origem da conexao.
        origem = request.client.host if request.client else "desconhecida"
        audit_log.warning(
            "EXPORT_PII rodada=%s dataset=%s origem=%s", rodada_id, dataset, origem
        )

    if dataset == "avaliacoes":
        linhas = await repo.dataset_avaliacoes(rodada_id)
    elif dataset == "anotacoes":
        linhas = await repo.dataset_anotacoes(rodada_id)
    elif dataset == "itens":
        linhas = await repo.dataset_itens(rodada_id)
    else:
        linhas = await repo.dataset_especialistas(rodada_id, incluir_pii)

    if format == "csv":
        corpo = export.para_csv(dataset, linhas, incluir_pii)
        return Response(
            content=corpo,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{dataset}.csv"'},
        )
    return Response(content=export.para_json(dataset, linhas, incluir_pii), media_type="application/json")
