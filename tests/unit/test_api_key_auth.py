"""Contrato de autenticacao entre servicos (issue #7): TODA rota sob
/api/v1 exige X-API-Key, aplicada uma unica vez via `dependencies=` em
app/api/router.py -- nao endpoint por endpoint. Por isso os testes
aqui cobrem uma rota de escrita (POST /generate) e uma de leitura
(GET /emails) para provar que a protecao nao e um subconjunto.

Usa um client PROPRIO, sem o header default que tests/conftest.py
injeta em `client` -- e exatamente esse header que este arquivo testa.
"""

import httpx
import pytest

from app.core.config import settings


async def _client_sem_header(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_sem_x_api_key_da_401(app_and_fakes):
    app, _fakes = app_and_fakes
    async with await _client_sem_header(app) as client:
        response = await client.post(
            "/api/v1/generate", json={"context": "ctx", "difficulty": "facil"}
        )
    assert response.status_code == 401


async def test_x_api_key_errada_da_401(app_and_fakes):
    app, _fakes = app_and_fakes
    async with await _client_sem_header(app) as client:
        response = await client.post(
            "/api/v1/generate",
            json={"context": "ctx", "difficulty": "facil"},
            headers={"X-API-Key": "chave-errada"},
        )
    assert response.status_code == 401


async def test_x_api_key_correta_passa(app_and_fakes):
    app, _fakes = app_and_fakes
    async with await _client_sem_header(app) as client:
        response = await client.post(
            "/api/v1/generate",
            json={"context": "ctx", "difficulty": "facil"},
            headers={"X-API-Key": settings.API_KEY},
        )
    assert response.status_code == 200


async def test_leitura_tambem_exige_x_api_key(app_and_fakes):
    """A protecao e por dependencies= no include_router, nao por
    endpoint -- GET /emails precisa exigir a chave tanto quanto
    POST /generate, senao a decisao de proteger tudo nao valeu.
    """
    app, _fakes = app_and_fakes
    async with await _client_sem_header(app) as client:
        sem_chave = await client.get("/api/v1/emails")
        com_chave = await client.get(
            "/api/v1/emails", headers={"X-API-Key": settings.API_KEY}
        )
    assert sem_chave.status_code == 401
    assert com_chave.status_code == 200


async def test_api_key_nao_configurada_falha_fechado(app_and_fakes, monkeypatch):
    """API_KEY vazia nao significa "sem autenticacao" -- significa
    servidor mal configurado, 503, mesmo com uma chave qualquer no
    header.
    """
    monkeypatch.setattr(settings, "API_KEY", "")
    app, _fakes = app_and_fakes
    async with await _client_sem_header(app) as client:
        response = await client.post(
            "/api/v1/generate",
            json={"context": "ctx", "difficulty": "facil"},
            headers={"X-API-Key": "qualquer-coisa"},
        )
    assert response.status_code == 503


@pytest.mark.parametrize("origin_configurada", [""])
async def test_sem_cors_allowed_origins_nao_registra_middleware(origin_configurada, monkeypatch):
    """CORS_ALLOWED_ORIGINS vazio (default) -- servidor-a-servidor nao
    precisa de CORS -- entao o middleware nem e adicionado (issue #7).
    """
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", origin_configurada)
    import main as main_module

    app = main_module.create_app()
    middleware_classes = [m.cls.__name__ for m in app.user_middleware]
    assert "CORSMiddleware" not in middleware_classes


async def test_com_cors_allowed_origins_registra_middleware(monkeypatch):
    monkeypatch.setattr(settings, "CORS_ALLOWED_ORIGINS", "https://curadoria.exemplo.com")
    import main as main_module

    app = main_module.create_app()
    middleware_classes = [m.cls.__name__ for m in app.user_middleware]
    assert "CORSMiddleware" in middleware_classes
