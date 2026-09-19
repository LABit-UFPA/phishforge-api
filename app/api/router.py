from fastapi import APIRouter, Depends
from app.api.v1.endpoints import generator
from app.core.security import require_api_key

router = APIRouter()

# require_api_key aplicado aqui, nao endpoint por endpoint (issue #7):
# um unico lugar garante que nenhuma rota nova esqueca a protecao --
# inclusive leitura (GET /emails*, /statistics), ja que o unico cliente
# legitimo de qualquer rota hoje e o backend Go.
router.include_router(generator.app, dependencies=[Depends(require_api_key)])
