import secrets
from typing import Optional

from dependency_injector.wiring import Provide, inject
from fastapi import Depends, Header, HTTPException

from app.core.config import settings
from app.core.container import Container
from app.domain.models.expert import Especialista
from app.domain.services.expert_auth_service import ExpertAuthError, ExpertAuthService
from app.infra.database.repositories.expert_repository import ExpertRepository

_NAO_AUTENTICADO = "Sessao invalida ou expirada."


@inject
async def require_expert(
    authorization: Optional[str] = Header(default=None),
    auth: ExpertAuthService = Depends(Provide[Container.expert_auth_service]),
    experts: ExpertRepository = Depends(Provide[Container.expert_repository]),
) -> Especialista:
    """Autentica o especialista pelo JWT de sessao (issue #36).

    Alem de validar assinatura e expiracao, consulta o banco a cada
    request para conferir `revogado_em`: revogacao (LGPD) tem efeito
    IMEDIATO mesmo com JWT stateless -- so validar o token deixaria um
    especialista revogado acessando ate o token expirar.

    Falha fechado: sem `EXPERT_JWT_SECRET` configurado, 503 (nunca um
    segredo default). Token ausente/invalido/expirado, especialista
    inexistente ou revogado: 401 com a MESMA mensagem, para nao revelar
    qual dos casos ocorreu.
    """
    if not auth.configurado:
        raise HTTPException(
            status_code=503,
            detail="EXPERT_JWT_SECRET nao configurado no servidor -- modulo de avaliacao desabilitado.",
        )

    esquema, _, token = (authorization or "").partition(" ")
    if esquema.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=401, detail=_NAO_AUTENTICADO)

    try:
        especialista_id = auth.validar_token(token.strip())
    except ExpertAuthError:
        raise HTTPException(status_code=401, detail=_NAO_AUTENTICADO)

    especialista = await experts.get_by_id(especialista_id)
    if especialista is None or especialista.revogado_em is not None:
        raise HTTPException(status_code=401, detail=_NAO_AUTENTICADO)
    return especialista


async def require_researcher(x_api_key: Optional[str] = Header(default=None)) -> None:
    """Autentica o pesquisador por X-API-Key (issue #36).

    Mesmo padrao de `app.core.security.require_api_key` (fail-closed 503
    se a chave nao esta configurada, `secrets.compare_digest`), mas
    contra `RESEARCHER_API_KEY` -- uma chave DISTINTA da que autentica o
    backend Go: dar o mesmo segredo a humanos elevaria a exposicao de
    algo pensado para nunca sair de comunicacao entre servidores.
    """
    if not settings.RESEARCHER_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="RESEARCHER_API_KEY nao configurada no servidor -- console do pesquisador desabilitado.",
        )
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.RESEARCHER_API_KEY):
        raise HTTPException(status_code=401, detail="X-API-Key ausente ou invalida.")
