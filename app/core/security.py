import secrets

from fastapi import Header, HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

# Instanciado uma vez por processo (nao por request) -- e o padrao do
# slowapi: o decorator `@limiter.limit(...)` referencia este objeto no
# momento em que o modulo do endpoint e importado. `main.create_app()`
# chama `limiter.reset()` a cada app nova (issue #7), para que o estado
# de rate limit de um teste (ou de um restart) nao vaze para o
# proximo -- mesma filosofia de "app + Container novos por teste" que
# tests/conftest.py ja aplica ao container de DI.
limiter = Limiter(key_func=get_remote_address)


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Autenticacao entre servicos (issue #7).

    O unico cliente legitimo hoje e o backend Go, chamando servidor-a-
    servidor -- nao precisa de OAuth, uma chave compartilhada basta.
    Aplicada a TODA rota sob `/api/v1` via `dependencies=` no
    `include_router` (app/api/router.py), inclusive leitura
    (`GET /emails*`, `/statistics`): o unico cliente legitimo de
    QUALQUER rota hoje e o mesmo backend Go, entao nao ha razao para um
    subconjunto ficar publico.

    `API_KEY` ausente na configuracao falha FECHADO (503), nao abre a
    API sem querer -- diferente de simplesmente pular a checagem. Uma
    chave configurada errado deve ser visivel na hora (erro de
    servidor), nao silenciosamente equivalente a "sem autenticacao".

    Comparacao em tempo constante (`secrets.compare_digest`) para nao
    vazar informacao sobre a chave por timing.
    """
    if not settings.API_KEY:
        raise HTTPException(
            status_code=503,
            detail="API_KEY nao configurada no servidor -- geracao/leitura desabilitadas.",
        )
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.API_KEY):
        raise HTTPException(status_code=401, detail="X-API-Key ausente ou invalida.")
