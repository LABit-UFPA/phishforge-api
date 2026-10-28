from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    MODEL_NAME_EMBEDDING: str = "all-MiniLM-L6-v2"

    # Provedor do LLM de GERACAO (normalizacao, HyDE, fusao, geracao do
    # item e anotacao as cegas -- todas as etapas de geracao). `openai`
    # ou `anthropic`. O embedding NAO segue este seletor: continua
    # OpenAI (`OPENAI_API_KEY`), porque trocar o modelo de embedding
    # mudaria o espaco vetorial e exigiria reindexar a base Qdrant.
    # `MODEL_NAME_LLM` e o id do modelo DENTRO do provider escolhido.
    LLM_PROVIDER: str = "openai"

    MODEL_NAME_LLM: str = "gpt-4o-mini"

    # Temperatura das chains que GERAM itens (email e canais novos). As
    # etapas auxiliares (HyDE, fusao, normalizacao) mantem as suas
    # proprias, mais baixas. Antes ficava fixa em 0.7 no codigo; no
    # config, um lote registra (run_metadata) e um piloto pode variar
    # sem mexer no codigo.
    LLM_TEMPERATURE: float = 0.7

    # Anotacao as cegas das pistas (piloto 2, 27/10/2026): com o gerador
    # anotando as proprias pistas sabendo as pistas-alvo, as anotadas
    # coincidiam 100% com o alvo mesmo sem lastro no texto. Ligado,
    # `cues` e `premise_alignment` vem de uma 2a chamada de LLM que so ve
    # o item pronto. Desligar volta a autoanotacao do gerador.
    ANOTACAO_CEGA: bool = True

    # Teto de tokens de saida das chamadas de geracao e de anotacao
    # (piloto 5, item 2.5): sem teto, uma chamada que entra em repeticao
    # estoura o contexto do modelo (16k tokens -- confirmado em 1 falha
    # por piloto) e so falha DEPOIS de consumir a chamada inteira. Com o
    # teto, a mesma chamada falha cedo e barato. Anotacao pede menos
    # texto de saida que geracao, dai o teto menor.
    MAX_TOKENS_GERACAO: int = 2000
    MAX_TOKENS_ANOTACAO: int = 1000

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

    # Chave do provider OpenAI: usada pelo LLM de geracao quando
    # LLM_PROVIDER=openai, pelo embedding (sempre) e pelo juiz do RAGAS
    # nos scripts de avaliacao.
    OPENAI_API_KEY: str = ""

    # Chave do provider Anthropic: usada pelo LLM de geracao quando
    # LLM_PROVIDER=anthropic. Vazia quando so se usa OpenAI. Distinta da
    # `API_KEY` abaixo, que e autenticacao servidor-a-servidor, nao
    # chave de modelo.
    ANTHROPIC_API_KEY: str = ""

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

    # Modulo de avaliacao por especialistas (issue #36).
    #
    # Segredo HS256 dos JWTs de sessao do especialista. SEM default de
    # proposito (diferente do fallback do backend Go): vazio => o modulo
    # inteiro responde 503. E pesquisa com seres humanos -- um segredo
    # hardcoded valido para qualquer um seria pior do que o modulo fora
    # do ar.
    EXPERT_JWT_SECRET: str = ""
    EXPERT_JWT_EXPIRES_HOURS: int = 12

    # Chave X-API-Key do pesquisador (console de gestao). DISTINTA de
    # `API_KEY` (servidor-a-servidor com o backend Go): dar o mesmo
    # segredo a humanos elevaria a exposicao de algo pensado para nunca
    # sair de comunicacao entre servidores. Vazio => 503 (fail-closed).
    RESEARCHER_API_KEY: str = ""

    # Origem publica do frontend, usada para montar o link de acesso
    # (`{EXPERT_FRONTEND_URL}/avaliacao/entrar?codigo=...`).
    EXPERT_FRONTEND_URL: str = "http://localhost:5173"

    # Quantos itens uma rodada precisa ter vinculados para poder ser
    # aberta (composicao 10/10/10 do plano de validacao). Rodadas piloto
    # menores baixam este valor no .env.
    RODADA_ITENS_ESPERADOS: int = 30

    class Config:
        env_file = ".env"

@lru_cache()
def get_settings():
    return Settings()

settings = Settings()