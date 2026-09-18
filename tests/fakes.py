"""Fakes usados pelos testes de contrato (tests/unit) para substituir os
providers pesados do container: LLM, cross-encoder, base vetorial e
Postgres.

Nao sao mocks genericos (unittest.mock.Mock): os servicos reais tem
contratos assincronos especificos, e um fake explicito deixa claro, num
teste que falha, se o problema esta no proprio fake ou no endpoint sob
teste. Tambem servem de referencia de como escrever o pipeline
completo sem chamada paga nenhuma -- e o que faz o CI passar sem
OPENAI_API_KEY configurada (ver issue #8).

tests/integration usa Postgres de verdade e nao importa nada daqui.
"""

from uuid import uuid4

from app.domain.models.phishing_email import PhishingEmail
from app.dto.query import QueryResponse


class FakeNormalizedQuery:
    """Espelha app.domain.services.prompt_normalizer.NormalizedQuery."""

    def __init__(self, search_query: str, generation_context: str):
        self.search_query = search_query
        self.generation_context = generation_context


class FakePromptNormalizer:
    async def normalize(self, user_context: str) -> FakeNormalizedQuery:
        return FakeNormalizedQuery(
            search_query=f"search_query fake para: {user_context}",
            generation_context=f"generation_context fake para: {user_context}",
        )


class FakeResponseGenerator:
    """Substitui ResponseGenerator sem chamar nenhum LLM.

    Registra os argumentos recebidos em `self.calls` -- e o que os
    testes de paridade da futura #11a vao usar para comparar o que o
    /generate e o /generate/batch efetivamente passam ao gerador.
    """

    def __init__(self, nivel: str = "medio"):
        self.nivel = nivel
        self.calls: list[dict] = []

    async def generate_hypothetical_answer(self, query: str) -> str:
        return f"hyde fake para: {query}"

    async def fuse_and_summarize_context(
        self, generation_context: str, contexts: list[str]
    ) -> str:
        self.calls.append(
            {
                "step": "fuse_and_summarize_context",
                "generation_context": generation_context,
                "contexts": contexts,
            }
        )
        return "contexto fundido fake"

    async def generate_response(
        self, difficulty: str, context: str, relevant_docs
    ) -> PhishingEmail:
        self.calls.append(
            {
                "step": "generate_response",
                "difficulty": difficulty,
                "context": context,
                "relevant_docs": relevant_docs,
            }
        )
        return PhishingEmail(
            receptor="alvo@example.com",
            remetente="fake@example.com",
            assunto="Assunto de teste",
            conteudo="Conteudo de teste gerado pelo fake, sem chamada de LLM.",
            explicacao="Explicacao de teste.",
            nivel=self.nivel,
            categoria="teste",
            links=[],
        )


class FakeReRanker:
    """Sem cross-encoder: devolve os documentos na mesma ordem."""

    def rerank(self, query: str, documents: list[QueryResponse]) -> list[QueryResponse]:
        return documents


class FakeVectorStore:
    def __init__(self, docs: list[QueryResponse] | None = None):
        self._docs = docs if docs is not None else [
            QueryResponse(
                text="chunk filho de teste",
                score=0.9,
                id=str(uuid4()),
                payload={
                    "text": "chunk filho de teste",
                    "parent_content": "conteudo pai completo de teste, maior que o chunk",
                },
            )
        ]

    def query(self, collection_name: str, query_text: str, top_k: int = 4):
        return self._docs


class FakeRetriever:
    def __init__(self, vector_store: FakeVectorStore | None = None):
        self.vector_store = vector_store or FakeVectorStore()


class FakePhishingRepository:
    """Repositorio em memoria. Mesma interface publica usada pelos
    endpoints (create, get_by_id, get_stats) -- suficiente para os
    testes de contrato que nao precisam de Postgres real.
    """

    def __init__(self):
        self.storage: dict = {}

    async def create(self, email: PhishingEmail):
        email_id = uuid4()
        self.storage[email_id] = email
        return email_id

    async def get_by_id(self, email_id):
        return self.storage.get(email_id)

    async def get_stats(self):
        return {
            "total": len(self.storage),
            "by_difficulty": {},
            "by_category": {},
            "recent_count": 0,
        }


class FakePhishingService:
    """Mesma interface publica de PhishingEmailService, sem Postgres.

    Espelha a validacao estrita de `create_email` (issue #2): recebe
    `nivel` ja normalizado pelo endpoint e falha alto se nao for um dos
    tres valores canonicos, em vez de aceitar qualquer coisa. Um fake
    mais permissivo que a implementacao real deixaria passar batido
    exatamente o tipo de regressao que os testes de contrato de
    dificuldade existem para pegar.
    """

    def __init__(self):
        self.repository = FakePhishingRepository()

    async def create_email(self, email: PhishingEmail):
        if email.nivel not in ("facil", "medio", "dificil"):
            raise ValueError(f"nivel invalido chegou ao fake: '{email.nivel}'")
        return await self.repository.create(email)

    async def get_email_by_id(self, email_id):
        return await self.repository.get_by_id(email_id)


class FakeDbConnection:
    """Substitui DatabaseConnection no lifespan da app.

    Com httpx.ASGITransport isto nao chega a ser exercitado (esta
    versao do httpx nao dispara lifespan), mas overrideamos mesmo
    assim: e a diferenca entre um teste que so funciona com o
    transporte atual e um que continua funcionando se o transporte
    mudar, ou se algum teste futuro usar `TestClient` (que dispara
    lifespan de verdade).
    """

    async def create_pool(self):
        return None

    async def close_pool(self):
        return None
