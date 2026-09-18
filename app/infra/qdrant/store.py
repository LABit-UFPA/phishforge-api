import logging
from typing import List
import uuid
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
from app.dto.query import QueryResponse

logger = logging.getLogger(__name__)

# Namespace fixo para uuid5 (issue #13). Qualquer UUID constante serve --
# so precisa ser estavel entre execucoes, ao contrario de uuid4, que e
# aleatorio a cada chamada. Gerado uma vez com uuid.uuid4() e fixado
# aqui; nunca deve mudar (mudar o namespace regenera todos os ids e
# tem o mesmo efeito pratico de reingerir do zero).
_INGESTION_NAMESPACE = uuid.UUID("453c4647-a690-456e-9112-493fbf7e106d")


def _deterministic_point_id(collection_name: str, child_text: str) -> str:
    """Id estavel derivado do conteudo, no lugar de uuid4() (issue #13):
    reingerir o mesmo chunk sobrescreve o mesmo ponto (upsert por id) em
    vez de duplicar. Inclui `collection_name` para duas colecoes nunca
    colidirem em id mesmo com chunk identico.
    """
    return str(uuid.uuid5(_INGESTION_NAMESPACE, f"{collection_name}:{child_text}"))


class QdrantVectorStore:
    def __init__(self, client: QdrantClient, embedding_client, expected_dimension: int | None = None):
        self.client = client
        self.embedding_client = embedding_client
        # Dimensao esperada da colecao, vinda de configuracao (issue
        # #13) -- nao do dado. Se None, save() cai de volta a inferir
        # do primeiro embedding calculado (comportamento antigo,
        # arriscado), com aviso explicito no log: e o caminho que #12 e
        # #13 documentam como fonte do bug de dimensao silenciosa.
        self.expected_dimension = expected_dimension


    def create_collection(self, collection_name: str, vector_size: int):
        if not self.client.collection_exists(collection_name):
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )


    def get_collection_dimension(self, collection_name: str) -> int | None:
        """Dimensao configurada da colecao, ou None se ela ainda nao existir.

        Usado para validar no start (ver main.py) que o cliente de
        embedding configurado bate com a colecao ja ingerida -- ver
        issue #12. Nao mexe em `save`/`create_collection`: a inferencia
        de dimensao a partir do primeiro embedding calculado na
        ingestao e um problema separado, corrigido na issue #13.
        """
        if not self.client.collection_exists(collection_name):
            return None
        info = self.client.get_collection(collection_name)
        return info.config.params.vectors.size


    def save(self, collection_name: str, chunks: List[dict]):
        child_texts = [c["child_text"] for c in chunks]
        embeddings = self.embedding_client.embed_batch(child_texts)

        actual_dimension = len(embeddings[0]) if embeddings else None

        if self.expected_dimension is not None:
            # Falha explicita (issue #13): se o embedding calculado nao
            # bate com a dimensao configurada, e sinal de cliente de
            # embedding trocado sem reingestao -- melhor recusar aqui
            # do que criar/alimentar uma colecao com a dimensao errada
            # silenciosamente.
            if actual_dimension is not None and actual_dimension != self.expected_dimension:
                raise ValueError(
                    f"Embedding produzido tem dimensao {actual_dimension}, mas "
                    f"EMBEDDING_DIMENSION esta configurado para {self.expected_dimension}. "
                    "Trocar o modelo de embedding muda o espaco vetorial inteiro e exige "
                    "reingerir a base do zero -- nao ajuste so a configuracao."
                )
            vector_size = self.expected_dimension
        else:
            logger.warning(
                "QdrantVectorStore sem expected_dimension configurado -- a dimensao da "
                f"colecao '{collection_name}' esta sendo inferida do dado (issue #13), "
                "nao de configuracao explicita."
            )
            vector_size = actual_dimension

        self.create_collection(collection_name, vector_size)

        points = []
        for i, chunk_data in enumerate(chunks):
            payload = {
                "text": chunk_data["child_text"],
                "parent_content": chunk_data["parent_text"],
                **chunk_data["metadata"]
            }
            points.append(
                PointStruct(
                    # Deterministico (issue #13): reingerir o mesmo
                    # chunk sobrescreve o mesmo ponto em vez de
                    # duplicar a base vetorial.
                    id=_deterministic_point_id(collection_name, chunk_data["child_text"]),
                    vector=embeddings[i],
                    payload=payload
                )
            )

        self.client.upsert(collection_name=collection_name, points=points, wait=True)


    def query(self, collection_name: str, query_text: str, top_k: int = 4) -> List[QueryResponse]:
        query_embedding = self.embedding_client.embed(query_text)
        results = self.client.search(
            collection_name=collection_name,
            query_vector=query_embedding,
            limit=top_k,
            with_payload=True # Garante que o payload seja retornado
        )
        
        return [
            QueryResponse(
                text=hit.payload.get("text", ""), 
                score=hit.score, 
                id=str(hit.id),
                payload=hit.payload # Passa o payload inteiro
            )
            for hit in results
        ]