from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MODEL_NAME_EMBEDDING: str = "all-MiniLM-L6-v2"
    
    MODEL_NAME_LLM: str = "gpt-4o-mini"
    
    QDRANT_URL: str = "http://localhost:6333"
    COLLECTION_NAME: str = "phishing_articles"

    # Dimensao do vetor produzido pelo cliente de embedding realmente
    # usado na colecao (embedding_client_openai no container, modelo
    # "text-embedding-3-small" -> 1536). NAO e derivada automaticamente:
    # trocar o modelo de embedding muda o espaco vetorial inteiro e
    # exige reingerir a base do zero, entao o numero fica explicito aqui
    # em vez de inferido do primeiro embedding calculado na ingestao
    # (que e o que a issue #13 corrige em QdrantVectorStore.save). O
    # app valida este valor contra a colecao Qdrant existente no start
    # (ver main.py) -- issue #12.
    EMBEDDING_DIMENSION: int = 1536

    OPENAI_API_KEY: str = ""
    
    CHUNK_SIZE: int = 1024
    CHUNK_OVERLAP: int = 256
    TOP_K_DOCUMENTS: int = 4
    
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "phishforge"
    DB_PASSWORD: str = "phishforge"
    DB_NAME: str = "phishforge"
    
    class Config:
        env_file = ".env"

@lru_cache()
def get_settings():
    return Settings()

settings = Settings()