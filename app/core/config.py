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

    # Limiar de similaridade de cosseno (0..1) acima do qual dois itens
    # do MESMO lote sao considerados quase-duplicados (issue #11b).
    # Com o mesmo context/dificuldade/documentos, a unica variacao
    # entre itens e a temperatura -- sem essa checagem, itens quase
    # identicos entram no corpus e o participante "reencontra" o mesmo
    # item, medindo memoria em vez de deteccao. Configuravel porque o
    # valor certo e empirico, nao um numero obvio.
    DEDUP_SIMILARITY_THRESHOLD: float = 0.95

    CHUNK_SIZE: int = 1024
    CHUNK_OVERLAP: int = 256
    TOP_K_DOCUMENTS: int = 4
    
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "phishforge"
    DB_PASSWORD: str = "phishforge"
    DB_NAME: str = "phishforge"

    # Autenticacao entre servicos (issue #7). Vazio por default para a
    # suite de testes nao precisar configurar nada -- mas
    # `require_api_key` (app/core/security.py) falha FECHADO (503)
    # quando vazio, entao "vazio" nunca significa "sem autenticacao"
    # em produção, so em ambiente que nao configurou nada de proposito
    # (dev local sem chamar os endpoints protegidos).
    API_KEY: str = ""

    # Lista de origens separadas por virgula (ex.:
    # "https://curadoria.exemplo.com,https://outra.exemplo.com").
    # Vazio = sem CORSMiddleware nenhum -- a API e chamada servidor-a-
    # servidor pelo backend Go, entao CORS aberto nunca foi necessario
    # (issue #7); so configurar se algum navegador precisar chamar a
    # API diretamente.
    CORS_ALLOWED_ORIGINS: str = ""

    # Limite de requisicoes por IP nos endpoints de geracao (issue #7):
    # protege contra abuso da chave da OpenAI e contra loop acidental
    # de um frontend de curadoria disparando geracoes em sequencia.
    # Sintaxe da lib `limits` (usada pelo slowapi): "<numero>/<unidade>".
    GENERATION_RATE_LIMIT: str = "20/minute"

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings():
    return Settings()

settings = Settings()