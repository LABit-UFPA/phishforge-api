from typing import List
import uuid
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance
from app.dto.query import QueryResponse


class QdrantVectorStore:
    def __init__(self, client: QdrantClient, embedding_client):
        self.client = client
        self.embedding_client = embedding_client


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

        self.create_collection(collection_name, len(embeddings[0]))

        points = []
        for i, chunk_data in enumerate(chunks):
            payload = {
                "text": chunk_data["child_text"],
                "parent_content": chunk_data["parent_text"],
                **chunk_data["metadata"]
            }
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
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