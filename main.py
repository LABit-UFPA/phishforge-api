import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.api.router import router as app_router
from app.core.config import settings
from app.core.container import Container
from app.core.security import limiter

logger = logging.getLogger("phishforge.main")


def configure_logging() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)


def _validate_qdrant_dimension(container: Container) -> None:
    """Recusa subir se a colecao Qdrant existente tiver dimensao
    diferente da configurada em EMBEDDING_DIMENSION -- em vez de deixar
    o erro aparecer so na primeira busca, obscuro, ja dentro de uma
    request do usuario (ver issue #12).

    Se o Qdrant estiver inalcancavel neste momento, so registra um
    aviso e segue: nao torna o Qdrant uma dependencia obrigatoria do
    start (hoje ele ja e acessado de forma preguicosa, por request), e
    o erro real vai aparecer de qualquer forma na primeira busca.
    """
    collection_name = settings.COLLECTION_NAME
    expected_dimension = settings.EMBEDDING_DIMENSION

    try:
        store = container.qdrant_store()
        actual_dimension = store.get_collection_dimension(collection_name)
    except Exception as e:
        logger.warning(
            "Nao foi possivel verificar a dimensao da colecao Qdrant "
            f"'{collection_name}' no start ({e}). Prosseguindo sem "
            "validar -- se o Qdrant estiver fora do ar, o erro vai "
            "aparecer na primeira busca."
        )
        return

    if actual_dimension is not None and actual_dimension != expected_dimension:
        raise RuntimeError(
            f"A colecao Qdrant '{collection_name}' tem dimensao "
            f"{actual_dimension}, mas EMBEDDING_DIMENSION esta "
            f"configurado para {expected_dimension}. Trocar o modelo de "
            "embedding muda o espaco vetorial inteiro e exige reingerir "
            "a base do zero (apague a colecao e rode "
            "script/run_ingestion.py de novo) -- nao ajuste so a "
            "configuracao."
        )


def create_lifespan(container: Container):
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        db_connection = container.db_connection()
        await db_connection.create_pool()
        logger.info("Database connection pool created")

        _validate_qdrant_dimension(container)

        try:
            yield
        finally:
            await db_connection.close_pool()
            logger.info("Database connection pool closed")

    return lifespan


def create_app() -> FastAPI:
    configure_logging()
    container = Container()

    app = FastAPI(
        title="Phishing Forge API",
        version="0.1.0",
        lifespan=create_lifespan(container),
    )

    app.container = container

    # Rate limit (issue #7): `limiter` e um singleton de modulo (os
    # decorators `@limiter.limit(...)` nos endpoints o referenciam
    # diretamente, no padrao do slowapi). `reset()` a cada app nova
    # evita que o contador de uma app anterior (ex.: outro teste, ou um
    # restart de dev com reload) vaze para esta -- mesmo raciocinio do
    # "Container novo por teste" que tests/conftest.py ja aplica.
    limiter.reset()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS (issue #7): so registrado se houver origem configurada. A
    # API e chamada servidor-a-servidor pelo backend Go -- CORS aberto
    # nunca foi necessario, e `allow_origins=["*"]` com
    # `allow_credentials=True` (a config antiga) e uma combinacao que a
    # especificacao proibe, entao nem cumpria o que prometia.
    cors_origins = [
        origin.strip() for origin in settings.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()
    ]
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(app_router)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
