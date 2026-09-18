from dependency_injector import containers, providers
from qdrant_client import QdrantClient

from app.core.config import settings
from app.domain.services.document_processor import DocumentProcessor
from app.domain.services.generation_pipeline import GenerationPipeline
from app.domain.services.openai.embedding_client import OpenAIEmbeddingClient
from app.domain.services.phishing_service import PhishingEmailService
from app.domain.services.pipeline import IngestionPipeline
from app.domain.services.prompt_normalizer import PromptNormalizer
from app.domain.services.reranker import ReRanker
from app.domain.services.response_generator import ResponseGenerator
from app.domain.services.user_answer_evaluator import UserAnswerEvaluator
from app.infra.database.connection import DatabaseConnection, get_db_pool
from app.infra.database.repositories.analytics_repository import AnalyticsRepository
from app.infra.database.repositories.evaluation_repository import EvaluationRepository
from app.infra.database.repositories.phishing_repository import PhishingEmailRepository
from app.infra.qdrant.store import QdrantVectorStore


class Container(containers.DeclarativeContainer):
    wiring_config = containers.WiringConfiguration(
        packages=["app.api.v1.endpoints"] 
    )

    config = providers.Configuration()
    config.from_dict(settings.model_dump())

    db_connection = providers.Singleton(
        DatabaseConnection,
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
    )

    db_pool = providers.Resource(
        get_db_pool
    )

    qdrant_client = providers.Singleton(
        QdrantClient,
        url=config.QDRANT_URL,
    )

    embedding_client_openai = providers.Singleton(
        OpenAIEmbeddingClient,
        api_key=config.OPENAI_API_KEY,
        model="text-embedding-3-small"
    )

    # ATENCAO: o modelo de embedding acima e a dimensao configurada em
    # EMBEDDING_DIMENSION (app/core/config.py) tem que ser o MESMO par
    # usado para ingerir a colecao Qdrant existente. Trocar o modelo
    # muda o espaco vetorial inteiro -- nao e uma troca de config, e uma
    # reingestao completa (apagar a colecao e rodar
    # script/run_ingestion.py de novo). O app valida isso no start (ver
    # main.py) e recusa subir se a dimensao da colecao existente nao
    # bater com EMBEDDING_DIMENSION -- ver issue #12.
    qdrant_store = providers.Singleton(
        QdrantVectorStore,
        client=qdrant_client,
        embedding_client=embedding_client_openai,
        # issue #13: dimensao vem de configuracao, nao inferida do
        # primeiro embedding calculado na ingestao.
        expected_dimension=config.EMBEDDING_DIMENSION,
    )

    # Singleton: o cross-encoder e um modelo de ML carregado do disco no
    # __init__ de ReRanker. Como Factory, cada resolucao (ou seja, cada
    # request que injeta este provider) recarregava o modelo do zero --
    # ver issue #12. CrossEncoder.predict() e chamado de forma sincrona
    # dentro de handlers async, nunca em thread separada, entao chamadas
    # concorrentes ja sao serializadas pelo proprio event loop; nao ha
    # necessidade de lock adicional para o uso atual.
    reranker = providers.Singleton(
        ReRanker
    )

    phishing_repository = providers.Factory(
        PhishingEmailRepository,
        db=db_connection
    )

    analytics_repository = providers.Factory(
        AnalyticsRepository,
        db=db_connection
    )

    # Achado adjacente ao trabalho da #8, nao resolvido aqui: este
    # provider tambem nao tem nenhum consumidor hoje (a cadeia
    # evaluation_llm/evaluation_embeddings/chat_openai_model/
    # openai_client que a #8 removeu era so para os parametros mortos
    # de generate(); EvaluationRepository e um caso separado --
    # backend das tabelas ragas_evaluations/evaluation_sessions
    # (migration V20251106120000), que parece um recurso mais amplo
    # nunca terminado. Decidir se remove ou termina de ligar e escopo
    # maior do que #8 pede, fica para issue propria.
    evaluation_repository = providers.Factory(
        EvaluationRepository,
        db_pool=db_pool
    )

    # Singleton pelo mesmo motivo do reranker: o construtor monta um
    # cliente ChatOpenAI (e, no caso do response_generator, os prompts e
    # as chains) uma vez, em vez de recriar tudo isso a cada request.
    response_generator = providers.Singleton(
        ResponseGenerator,
        api_key=config.OPENAI_API_KEY,
        model_name=config.MODEL_NAME_LLM,
    )

    prompt_normalizer = providers.Singleton(
        PromptNormalizer,
        api_key=config.OPENAI_API_KEY
        # O model_name "gpt-4o-mini" será usado como default da própria classe
    )

    user_answer_evaluator = providers.Singleton(
        UserAnswerEvaluator,
        api_key=config.OPENAI_API_KEY
    )

    # Substitui o antigo `retriever` (DocumentRetriever): aquela classe
    # so encapsulava `.vector_store` e tinha um metodo
    # (retrieve_relevant_documents) nunca chamado -- os endpoints ja
    # atravessavam direto para `.vector_store.query(...)` (ver issue
    # #12, item 4, resolvido aqui como #11a combinou). GenerationPipeline
    # depende do QdrantVectorStore diretamente, sem indirecao.
    generation_pipeline = providers.Factory(
        GenerationPipeline,
        normalizer=prompt_normalizer,
        response_generator=response_generator,
        vector_store=qdrant_store,
        reranker=reranker,
        collection_name=config.COLLECTION_NAME,
    )

    phishing_service = providers.Factory(
        PhishingEmailService,
        repository=phishing_repository,
        analytics_repository=analytics_repository
    )

    pipeline = providers.Factory(
        IngestionPipeline,
        processor=providers.Factory(DocumentProcessor),
        vector_store=qdrant_store
    )