"""Testes de QdrantVectorStore.save (issue #13): idempotencia via id
deterministico e validacao de dimensao na escrita. Nenhum Qdrant real
-- stub de client rastreando pontos por id, como o Qdrant real faria
no upsert.

A leitura (validar coleção existente no start) já tem seus próprios
testes em test_qdrant_dimension.py (issue #12); aqui é sobre o que
acontece durante a ESCRITA (ingestão).
"""

import pytest

from app.infra.qdrant.store import QdrantVectorStore, _deterministic_point_id


class _StubQdrantClient:
    """Emula upsert por id (como o Qdrant real faz): salvar de novo com
    o MESMO id sobrescreve, nao duplica.
    """

    def __init__(self, colecoes_existentes: dict[str, int] | None = None):
        self._colecoes = colecoes_existentes or {}
        self.pontos: dict[str, dict] = {}

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self._colecoes

    def create_collection(self, collection_name: str, vectors_config):
        self._colecoes[collection_name] = vectors_config.size

    def upsert(self, collection_name: str, points, wait: bool = True):
        for point in points:
            self.pontos[point.id] = {"vector": point.vector, "payload": point.payload}


class _FakeEmbeddingClient:
    def __init__(self, dimension: int = 1536):
        self.dimension = dimension

    def embed_batch(self, texts):
        return [[0.1] * self.dimension for _ in texts]


def _chunks_de_teste(n=3):
    return [
        {
            "child_text": f"chunk filho numero {i}",
            "parent_text": f"bloco pai completo numero {i}",
            "metadata": {"source": "teste.pdf", "page": i},
        }
        for i in range(n)
    ]


def test_reingestao_sobrescreve_em_vez_de_duplicar():
    client = _StubQdrantClient()
    store = QdrantVectorStore(
        client=client, embedding_client=_FakeEmbeddingClient(), expected_dimension=1536
    )
    chunks = _chunks_de_teste()

    store.save("colecao_teste", chunks)
    assert len(client.pontos) == 3

    # Reingerir o MESMO conteudo -- contagem de pontos nao deve mudar.
    store.save("colecao_teste", chunks)
    assert len(client.pontos) == 3


def test_id_deterministico_e_estavel_entre_chamadas():
    id1 = _deterministic_point_id("colecao", "mesmo texto")
    id2 = _deterministic_point_id("colecao", "mesmo texto")
    assert id1 == id2


def test_id_deterministico_muda_com_a_colecao():
    """Mesmo child_text em colecoes diferentes nao deve colidir."""
    id_a = _deterministic_point_id("colecao_a", "mesmo texto")
    id_b = _deterministic_point_id("colecao_b", "mesmo texto")
    assert id_a != id_b


def test_id_deterministico_muda_com_o_conteudo():
    id1 = _deterministic_point_id("colecao", "texto 1")
    id2 = _deterministic_point_id("colecao", "texto 2")
    assert id1 != id2


def test_falha_explicita_quando_embedding_nao_bate_com_dimensao_configurada():
    client = _StubQdrantClient()
    store = QdrantVectorStore(
        client=client,
        embedding_client=_FakeEmbeddingClient(dimension=384),  # errado de proposito
        expected_dimension=1536,
    )

    with pytest.raises(ValueError, match="dimensao"):
        store.save("colecao_teste", _chunks_de_teste())

    # Nao deve ter criado colecao nem inserido nada com a dimensao errada.
    assert len(client.pontos) == 0


def test_sem_expected_dimension_infere_do_dado_e_ainda_funciona(caplog):
    """Comportamento antigo preservado quando ninguem configura
    expected_dimension -- com aviso no log (issue #13), nao mais
    silencioso.
    """
    client = _StubQdrantClient()
    store = QdrantVectorStore(client=client, embedding_client=_FakeEmbeddingClient(dimension=777))

    store.save("colecao_teste", _chunks_de_teste())

    assert len(client.pontos) == 3
    assert client._colecoes["colecao_teste"] == 777
