from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Path

from app.api.v1.endpoints.deps import require_expert
from app.core.container import Container
from app.domain.models.evaluation_round import AvaliacaoRodada
from app.domain.models.expert import Especialista
from app.domain.services.expert_auth_service import ExpertAuthService
from app.domain.services.expert_evaluation_service import (
    AvaliacaoInvalida,
    CanalNaoSuportado,
    ExpertEvaluationService,
    ItemNaoEncontrado,
)
from app.dto.expert_requests import (
    AvaliacaoRequest,
    ConsentimentoRequest,
    ExpertSessionRequest,
    PerfilRequest,
)
from app.dto.expert_responses import (
    ConsentimentoEstado,
    EspecialistaResumo,
    CueResponse,
    ExpertItemResponse,
    ExpertMeResponse,
    ExpertSessionResponse,
    PerfilEstado,
    Progresso,
    RevogacaoResponse,
    RodadaResumo,
    TcleResponse,
)
from app.infra.database.repositories.cue_repository import CueRepository
from app.infra.database.repositories.evaluation_round_repository import EvaluationRoundRepository
from app.infra.database.repositories.expert_evaluation_repository import ExpertEvaluationRepository
from app.infra.database.repositories.expert_repository import ExpertRepository

# Roteador SEPARADO, sem `require_api_key` (issue #36). A chave
# servidor-a-servidor do backend Go e aplicada a todo o roteador de
# geracao em app/api/router.py; estas rotas sao usadas por um
# especialista no navegador, que nao tem (e nao deve ter) essa chave --
# elas se autenticam por JWT proprio (`require_expert`).
router = APIRouter(prefix="/api/v1/expert", tags=["expert"])


async def _rodada_aberta(
    especialista: Especialista, rounds: EvaluationRoundRepository
) -> AvaliacaoRodada:
    if especialista.rodada_id is None:
        raise HTTPException(status_code=409, detail="Especialista sem rodada de avaliacao vinculada.")
    rodada = await rounds.get_by_id(especialista.rodada_id)
    if rodada is None or rodada.status != "aberta":
        raise HTTPException(status_code=409, detail="A rodada de avaliacao nao esta aberta.")
    return rodada


async def _estado(
    especialista: Especialista,
    rodada: AvaliacaoRodada,
    rounds: EvaluationRoundRepository,
    evals: ExpertEvaluationRepository,
) -> dict:
    total = await rounds.contar_itens(rodada.id)
    progresso = await evals.progresso(especialista.id, total)
    return {
        "especialista": EspecialistaResumo(
            id=especialista.id, nome=especialista.nome, sobrenome=especialista.sobrenome
        ),
        "rodada": RodadaResumo(
            id=rodada.id, nome=rodada.nome, status=rodada.status, tcle_versao=rodada.tcle_versao
        ),
        # Reconsentimento: quem consentiu com outra versao do TCLE (ou
        # nunca consentiu) precisa consentir de novo.
        "consentimento": ConsentimentoEstado(
            necessario=especialista.consentimento_versao != rodada.tcle_versao,
            versao=rodada.tcle_versao,
        ),
        "perfil": PerfilEstado(necessario=especialista.perfil_em is None),
        # Quando tudo esta concluido, `proxima_ordem` fica no ultimo item e
        # `concluidas == total` sinaliza o fim.
        "progresso": Progresso(
            total=progresso.total, concluidas=progresso.concluidas, proxima_ordem=progresso.proxima_ordem
        ),
    }


@router.post("/session", response_model=ExpertSessionResponse)
@inject
async def criar_sessao(
    payload: ExpertSessionRequest,
    auth: ExpertAuthService = Depends(Provide[Container.expert_auth_service]),
    experts: ExpertRepository = Depends(Provide[Container.expert_repository]),
    rounds: EvaluationRoundRepository = Depends(Provide[Container.evaluation_round_repository]),
    evals: ExpertEvaluationRepository = Depends(Provide[Container.expert_evaluation_repository]),
):
    """Troca o codigo de acesso por um JWT de sessao (12h, sem refresh)."""
    if not auth.configurado:
        raise HTTPException(
            status_code=503,
            detail="EXPERT_JWT_SECRET nao configurado no servidor -- modulo de avaliacao desabilitado.",
        )

    especialista = await experts.get_by_codigo_hash(auth.hash_codigo(payload.codigo_acesso))
    # Mesma resposta para "codigo inexistente" e "especialista revogado":
    # nao revelar quais codigos existem.
    if especialista is None or especialista.revogado_em is not None:
        raise HTTPException(status_code=401, detail="Codigo de acesso invalido.")

    rodada = await _rodada_aberta(especialista, rounds)
    estado = await _estado(especialista, rodada, rounds, evals)

    await experts.registrar_acesso(especialista.id)
    token, expira = auth.emitir_token(especialista.id)
    return ExpertSessionResponse(token=token, expires_at=expira, **estado)


@router.get("/me", response_model=ExpertMeResponse)
@inject
async def me(
    especialista: Especialista = Depends(require_expert),
    rounds: EvaluationRoundRepository = Depends(Provide[Container.evaluation_round_repository]),
    evals: ExpertEvaluationRepository = Depends(Provide[Container.expert_evaluation_repository]),
):
    rodada = await _rodada_aberta(especialista, rounds)
    return ExpertMeResponse(**await _estado(especialista, rodada, rounds, evals))


@router.get("/tcle", response_model=TcleResponse)
@inject
async def tcle(
    especialista: Especialista = Depends(require_expert),
    rounds: EvaluationRoundRepository = Depends(Provide[Container.evaluation_round_repository]),
):
    rodada = await _rodada_aberta(especialista, rounds)
    return TcleResponse(versao=rodada.tcle_versao, texto_md=rodada.tcle_texto_md)


@router.post("/consentimento", response_model=ExpertMeResponse)
@inject
async def consentimento(
    payload: ConsentimentoRequest,
    especialista: Especialista = Depends(require_expert),
    experts: ExpertRepository = Depends(Provide[Container.expert_repository]),
    rounds: EvaluationRoundRepository = Depends(Provide[Container.evaluation_round_repository]),
    evals: ExpertEvaluationRepository = Depends(Provide[Container.expert_evaluation_repository]),
):
    rodada = await _rodada_aberta(especialista, rounds)
    if not payload.aceito:
        raise HTTPException(
            status_code=422, detail="Sem consentimento (aceito=false) nao e possivel participar da avaliacao."
        )
    # Forca reconsentimento: aceitar uma versao que nao e a vigente nao vale.
    if payload.versao != rodada.tcle_versao:
        raise HTTPException(
            status_code=409,
            detail=f"Versao do TCLE desatualizada. Versao vigente: {rodada.tcle_versao}.",
        )

    await experts.registrar_consentimento(especialista.id, payload.versao)
    atualizado = await experts.get_by_id(especialista.id)
    return ExpertMeResponse(**await _estado(atualizado, rodada, rounds, evals))


@router.post("/perfil", response_model=ExpertMeResponse)
@inject
async def perfil(
    payload: PerfilRequest,
    especialista: Especialista = Depends(require_expert),
    experts: ExpertRepository = Depends(Provide[Container.expert_repository]),
    rounds: EvaluationRoundRepository = Depends(Provide[Container.evaluation_round_repository]),
    evals: ExpertEvaluationRepository = Depends(Provide[Container.expert_evaluation_repository]),
):
    rodada = await _rodada_aberta(especialista, rounds)
    await experts.registrar_perfil(especialista.id, payload.model_dump())
    atualizado = await experts.get_by_id(especialista.id)
    return ExpertMeResponse(**await _estado(atualizado, rodada, rounds, evals))


@router.post("/revogacao", response_model=RevogacaoResponse)
@inject
async def revogacao(
    especialista: Especialista = Depends(require_expert),
    experts: ExpertRepository = Depends(Provide[Container.expert_repository]),
):
    """Autoatendimento LGPD: o proprio especialista revoga seu acesso.
    Nao exige rodada aberta -- revogar deve ser sempre possivel.
    """
    return RevogacaoResponse(revogado_em=await experts.revogar(especialista.id))


def _exigir_consentimento(especialista: Especialista, rodada: AvaliacaoRodada) -> None:
    """Sem consentimento na versao vigente do TCLE, nenhum item e entregue
    -- inclusive apos uma nova versao do TCLE no meio da coleta.
    """
    if especialista.consentimento_versao != rodada.tcle_versao:
        raise HTTPException(
            status_code=403,
            detail=f"Consentimento pendente para a versao {rodada.tcle_versao} do TCLE.",
        )


@router.get("/cues", response_model=list[CueResponse])
@inject
async def cues(
    _: Especialista = Depends(require_expert),
    cue_repository: CueRepository = Depends(Provide[Container.cue_repository]),
):
    """Vocabulario de pistas (issue #35), com a definicao operacional.
    Nao e sensivel ao cegamento: e o vocabulario, nao o rotulo de item nenhum.
    """
    entradas = await cue_repository.get_all_ativas()
    return [
        CueResponse(
            id=e.id, code=e.code.value, label_pt=e.label_pt, descricao_pt=e.descricao_pt, category=e.category
        )
        for e in entradas
    ]


@router.get("/itens/{ordem}", response_model=ExpertItemResponse)
@inject
async def obter_item(
    ordem: int = Path(ge=1),
    especialista: Especialista = Depends(require_expert),
    rounds: EvaluationRoundRepository = Depends(Provide[Container.evaluation_round_repository]),
    service: ExpertEvaluationService = Depends(Provide[Container.expert_evaluation_service]),
):
    """Entrega o item as cegas. `ordem` e a posicao DO PROPRIO especialista
    (sorteada por ele), nunca o id do item: o id nao sai do servidor, entao
    nem ha como correlacionar itens entre especialistas pelo cliente.
    """
    rodada = await _rodada_aberta(especialista, rounds)
    _exigir_consentimento(especialista, rodada)
    try:
        return await service.obter_item(especialista, rodada, ordem)
    except ItemNaoEncontrado as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CanalNaoSuportado as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.put("/itens/{ordem}", response_model=ExpertItemResponse)
@inject
async def submeter_avaliacao(
    payload: AvaliacaoRequest,
    ordem: int = Path(ge=1),
    especialista: Especialista = Depends(require_expert),
    rounds: EvaluationRoundRepository = Depends(Provide[Container.evaluation_round_repository]),
    service: ExpertEvaluationService = Depends(Provide[Container.expert_evaluation_service]),
):
    """Substituicao total das anotacoes + avaliacao, numa transacao (idempotente)."""
    rodada = await _rodada_aberta(especialista, rounds)
    _exigir_consentimento(especialista, rodada)
    try:
        return await service.submeter(especialista, rodada, ordem, payload)
    except ItemNaoEncontrado as e:
        raise HTTPException(status_code=404, detail=str(e))
    except CanalNaoSuportado as e:
        raise HTTPException(status_code=409, detail=str(e))
    except AvaliacaoInvalida as e:
        raise HTTPException(status_code=422, detail=str(e))
