from fastapi import APIRouter, Depends
from app.api.v1.endpoints import expert, generator, researcher
from app.core.security import require_api_key

router = APIRouter()

# require_api_key aplicado aqui, nao endpoint por endpoint (issue #7):
# um unico lugar garante que nenhuma rota nova esqueca a protecao --
# inclusive leitura (GET /emails*, /statistics), ja que o unico cliente
# legitimo de qualquer rota hoje e o backend Go.
router.include_router(generator.app, dependencies=[Depends(require_api_key)])

# Modulo de avaliacao por especialistas (issue #36): SEGUNDO include_router,
# de proposito SEM `require_api_key`. A chave acima e servidor-a-servidor
# (backend Go); um especialista no navegador nao a tem e nao deve tem-la.
# Estas rotas se autenticam por JWT proprio (require_expert) -- ver
# app/api/v1/endpoints/deps.py.
router.include_router(expert.router)

# Console do pesquisador (issue #38): terceiro roteador, autenticado so por
# `require_researcher` (declarado no proprio roteador) -- nem a chave do
# Go nem o JWT do especialista valem aqui.
router.include_router(researcher.router)
