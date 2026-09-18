"""Cobre o item da issue #12: "Teste de que uma coleção com dimensão
incompatível é detectada no start, não na primeira query."

Duas camadas:
- get_collection_dimension (app/infra/qdrant/store.py): unidade pura,
  com um stub de QdrantClient.
- _validate_qdrant_dimension (main.py): a funcao chamada no lifespan,
  com o container inteiro trocado por um fake.

Nenhum dos dois toca um Qdrant de verdade.
"""

import os

os.environ.setdefault("OPENAI_API_KEY", "sk-test-nao-usada-em-nenhuma-chamada-real")

import pytest

from app.infra.qdrant.store import QdrantVectorStore
from main import _validate_qdrant_dimension


class _StubVectorParams:
    def __init__(self, size):
        self.size = size


class _StubParams:
    def __init__(self, size):
        self.vectors = _StubVectorParams(size)


class _StubConfig:
    def __init__(self, size):
        self.params = _StubParams(size)


class _StubCollectionInfo:
    def __init__(self, size):
        self.config = _StubConfig(size)


class _StubQdrantClient:
    """Duck-type minimo de QdrantClient: so os dois metodos que
    get_collection_dimension usa.
    """

    def __init__(self, existing_collections: dict[str, int]):
        self._collections = existing_collections

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self._collections

    def get_collection(self, collection_name: str) -> _StubCollectionInfo:
        return _StubCollectionInfo(self._collections[collection_name])


def test_get_collection_dimension_retorna_none_se_colecao_nao_existe():
    store = QdrantVectorStore(client=_StubQdrantClient({}), embedding_client=None)
    assert store.get_collection_dimension("nao_existe") is None


def test_get_collection_dimension_retorna_o_tamanho_configurado():
    store = QdrantVectorStore(
        client=_StubQdrantClient({"phishing_articles": 1536}), embedding_client=None
    )
    assert store.get_collection_dimension("phishing_articles") == 1536


class _FakeStore:
    def __init__(self, dimension):
        self._dimension = dimension

    def get_collection_dimension(self, collection_name):
        return self._dimension


class _FakeContainer:
    def __init__(self, dimension):
        self._store = _FakeStore(dimension)

    def qdrant_store(self):
        return self._store


class _RaisingContainer:
    def qdrant_store(self):
        raise ConnectionError("Qdrant fora do ar, simulado no teste")


def test_validate_qdrant_dimension_nao_faz_nada_se_bater(monkeypatch):
    import main as main_module

    monkeypatch.setattr(main_module.settings, "EMBEDDING_DIMENSION", 1536)
    _validate_qdrant_dimension(_FakeContainer(dimension=1536))  # nao deve levantar


def test_validate_qdrant_dimension_falha_explicito_se_divergir(monkeypatch):
    import main as main_module

    monkeypatch.setattr(main_module.settings, "EMBEDDING_DIMENSION", 1536)

    with pytest.raises(RuntimeError, match="dimensao"):
        _validate_qdrant_dimension(_FakeContainer(dimension=384))


def test_validate_qdrant_dimension_ignora_colecao_inexistente(monkeypatch):
    import main as main_module

    monkeypatch.setattr(main_module.settings, "EMBEDDING_DIMENSION", 1536)
    _validate_qdrant_dimension(_FakeContainer(dimension=None))  # nao deve levantar


def test_validate_qdrant_dimension_nao_derruba_o_start_se_qdrant_estiver_fora(caplog):
    # Qdrant inalcancavel no start nao deve impedir a app de subir --
    # so o erro genuino de dimensao incompativel deve.
    _validate_qdrant_dimension(_RaisingContainer())
