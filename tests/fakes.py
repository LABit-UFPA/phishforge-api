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

from datetime import datetime, timezone
from uuid import uuid4

from app.domain.models.cue import CueCode, CueTaxonomyEntry
from app.domain.models.generated_item_draft import GeneratedItemDraft
from app.domain.models.generation_job import GenerationFailure, GenerationJob, JobStatus
from app.domain.models.phishing_email import PhishingEmail
from app.dto.query import QueryResponse


class FakeNormalizedQuery:
    """Espelha app.domain.services.prompt_normalizer.NormalizedQuery."""

    def __init__(self, search_query: str, generation_context: str):
        self.search_query = search_query
        self.generation_context = generation_context


class FakePromptNormalizer:
    """Registra cada chamada em `self.calls` -- e o que os testes de
    reaproveitamento da #11a usam para provar que a normalizacao roda
    UMA vez por lote, nao uma vez por item gerado.
    """

    def __init__(self):
        self.calls: list[str] = []

    async def normalize(self, user_context: str) -> FakeNormalizedQuery:
        self.calls.append(user_context)
        return FakeNormalizedQuery(
            search_query=f"search_query fake para: {user_context}",
            generation_context=f"generation_context fake para: {user_context}",
        )


class FakeResponseGenerator:
    """Substitui ResponseGenerator sem chamar nenhum LLM.

    Registra os argumentos recebidos em `self.calls`, cada um marcado
    com `step` -- o que os testes de paridade e de reaproveitamento da
    #11a usam para comparar o que o /generate e o /generate/batch
    efetivamente passam ao gerador, e para contar quantas vezes cada
    etapa rodou.
    """

    def __init__(self):
        self.calls: list[dict] = []
        self._contador = 0
        # Issue #5: testes de contrato que precisam verificar a
        # propagacao de `cues` ate a resposta HTTP setam isto antes de
        # chamar o endpoint. Vazio por padrao para nao afetar nenhum
        # teste existente.
        self.cues_a_devolver: list = []
        # Issue #5: mesmo mecanismo para `links` -- agora List[LinkRef],
        # nao mais List[str]. Vazio por padrao (mesmo valor de antes).
        self.links_a_devolver: list = []

    async def generate_hypothetical_answer(self, query: str) -> str:
        self.calls.append({"step": "generate_hypothetical_answer", "query": query})
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
        self, difficulty: str, context: str, relevant_docs, is_malicious: bool = True
    ) -> GeneratedItemDraft:
        self.calls.append(
            {
                "step": "generate_response",
                "difficulty": difficulty,
                "context": context,
                "relevant_docs": relevant_docs,
                "is_malicious": is_malicious,
            }
        )
        # Sem `nivel`: o draft nunca inclui dificuldade (issue #11) --
        # quem monta o PhishingEmail final e o endpoint, combinando
        # este draft com o `difficulty` acima.
        #
        # `conteudo` inclui um contador para ser unico por chamada: com
        # FakeEmbeddingClient (deriva o embedding do texto), conteudo
        # identico em toda chamada faria a dedup por similaridade de
        # cosseno da #11b descartar todos os itens exceto o primeiro.
        self._contador += 1
        return GeneratedItemDraft(
            receptor="alvo@example.com",
            remetente="fake@example.com",
            assunto="Assunto de teste",
            conteudo=f"Conteudo de teste gerado pelo fake #{self._contador}, sem chamada de LLM.",
            explicacao="Explicacao de teste.",
            categoria="teste",
            links=list(self.links_a_devolver),
            cues=list(self.cues_a_devolver),
        )

    async def generate_channel_item(
        self, channel: str, difficulty: str, context: str, relevant_docs, is_malicious: bool = True
    ) -> dict:
        """Equivalente de `generate_response` para os canais novos
        (issue #6), sem chamar LLM. `content_json` inclui um contador
        pelo mesmo motivo de `conteudo` acima -- unicidade para a
        dedup por embedding nao descartar tudo menos o primeiro item.
        """
        self.calls.append(
            {
                "step": "generate_channel_item",
                "channel": channel,
                "difficulty": difficulty,
                "context": context,
                "relevant_docs": relevant_docs,
                "is_malicious": is_malicious,
            }
        )
        self._contador += 1
        content_por_canal = {
            "website": {
                "url": "http://exemplo-falso.test",
                "title": "Titulo de teste",
                "visible_content": f"Conteudo de pagina de teste #{self._contador}.",
            },
            "phone_call": {
                "caller": "+5500000000000",
                "transcript": f"Roteiro de teste #{self._contador}.",
            },
            "pix_qr": {
                "payload": f"payload-de-teste-{self._contador}",
                "recipient": "Recebedor de teste",
                "amount": "10.00",
                "pix_key": "chave-de-teste",
            },
            "sms": {
                "sender": "+5500000000000",
                "text": f"Texto de SMS de teste #{self._contador}.",
                "links": [],
            },
            "whatsapp": {
                "sender": "+5500000000000",
                "display_name": "Contato de teste",
                "messages": [
                    {"author": "contact", "text": f"Mensagem de teste #{self._contador}."}
                ],
            },
        }
        return {
            "content_json": content_por_canal[channel],
            "explicacao": "Explicacao de teste.",
            "categoria": "teste",
        }


class FakeReRanker:
    """Sem cross-encoder: devolve os documentos na mesma ordem, so
    registrando a chamada.
    """

    def __init__(self):
        self.calls: list[dict] = []

    def rerank(self, query: str, documents: list[QueryResponse]) -> list[QueryResponse]:
        self.calls.append({"query": query, "documents": documents})
        return documents


class FakeVectorStore:
    """Por padrao, devolve um documento cujo `text` (chunk filho) e
    `parent_content` (bloco pai) sao visivelmente diferentes -- e o
    que permite um teste provar que o pipeline usa `parent_content` e
    nao `text` na fusao (issue #11, o bug do /generate/batch antigo).
    """

    def __init__(self, docs: list[QueryResponse] | None = None):
        self._docs = docs if docs is not None else [
            QueryResponse(
                text="CHUNK_FILHO_pequeno_otimizado_para_busca",
                score=0.9,
                id=str(uuid4()),
                payload={
                    "text": "CHUNK_FILHO_pequeno_otimizado_para_busca",
                    "parent_content": "BLOCO_PAI_completo_usado_na_geracao",
                },
            )
        ]
        self.calls: list[dict] = []

    def query(self, collection_name: str, query_text: str, top_k: int = 4):
        self.calls.append(
            {"collection_name": collection_name, "query_text": query_text, "top_k": top_k}
        )
        return self._docs


class FakePhishingRepository:
    """Repositorio em memoria. Mesma interface publica usada pelos
    endpoints (create, get_by_id, get_stats, listagem/busca) --
    suficiente para os testes de contrato que nao precisam de Postgres
    real.
    """

    def __init__(self):
        self.storage: dict = {}

    async def create(self, email: PhishingEmail):
        email_id = uuid4()
        # Issue #24: o repositorio real preenche id/created_at/
        # updated_at ao persistir. Um fake que devolvesse o email
        # exatamente como recebeu (sem id) seria mais permissivo que o
        # real e deixaria passar batido uma regressao do tipo que a
        # #24 corrigiu.
        self.storage[email_id] = email.model_copy(
            update={
                "id": email_id,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )
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

    async def get_all(self, limit: int = 100, offset: int = 0):
        items = list(self.storage.values())
        return items[offset : offset + limit]

    async def get_by_categoria(self, categoria: str, limit: int = 50):
        return [e for e in self.storage.values() if e.categoria == categoria][:limit]

    async def get_by_nivel(self, nivel: str, limit: int = 50):
        return [e for e in self.storage.values() if e.nivel == nivel][:limit]

    async def search_content(self, search_term: str, limit: int = 50):
        termo = search_term.lower()
        return [e for e in self.storage.values() if termo in e.conteudo.lower()][:limit]


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

    async def get_all_emails(self, limit: int = 100, offset: int = 0):
        return await self.repository.get_all(limit, offset)

    async def get_emails_by_categoria(self, categoria: str, limit: int = 50):
        return await self.repository.get_by_categoria(categoria, limit)

    async def get_emails_by_nivel(self, nivel: str, limit: int = 50):
        return await self.repository.get_by_nivel(nivel, limit)

    async def search_emails(self, search_term: str, limit: int = 50):
        return await self.repository.search_content(search_term, limit)

    async def get_emails_by_ids(self, email_ids: list) -> list:
        """Usado por GET /generate/batch/{job_id} (issue #11b) para
        trazer o conteudo completo dos itens do job. Preserva a ordem
        de `email_ids`, igual ao repositorio real (ORDER BY
        array_position).
        """
        # FakePhishingRepository guarda por id como chave -- basta
        # olhar direto no storage, sem precisar reconstruir um indice.
        return [
            self.repository.storage[email_id]
            for email_id in email_ids
            if email_id in self.repository.storage
        ]


class FakeUserAnswerScore:
    """Espelha app.domain.services.user_answer_evaluator.UserAnswerScore."""

    def __init__(self, score=3, feedback="feedback fake", strengths=None, improvements=None, acerto_por_sorte=False):
        self.score = score
        self.feedback = feedback
        self.strengths = strengths or ["ponto forte fake"]
        self.improvements = improvements or ["ponto de melhoria fake"]
        self.acerto_por_sorte = acerto_por_sorte


class FakeUserAnswerEvaluator:
    """Substitui UserAnswerEvaluator sem chamar nenhum LLM. Registra os
    argumentos recebidos -- e o que os testes de contrato da #4 usam
    para provar que is_malicious/user_verdict chegam corretamente do
    endpoint, sem depender do LLM realmente distinguir os 4 casos.
    """

    def __init__(self):
        self.calls: list[dict] = []

    async def evaluate(self, item_content, is_malicious, user_verdict, user_justification):
        self.calls.append(
            {
                "item_content": item_content,
                "is_malicious": is_malicious,
                "user_verdict": user_verdict,
                "user_justification": user_justification,
            }
        )
        return FakeUserAnswerScore()


class FakeEmbeddingClient:
    """Substitui OpenAIEmbeddingClient sem chamar a OpenAI (issue #11b:
    BatchGenerationWorker usa `embed()` para a dedup por similaridade
    de cosseno).

    O embedding e derivado de forma deterministica do proprio texto via
    hash, em vez de fixo: textos iguais produzem o mesmo vetor
    (similaridade 1.0, o caso que a dedup precisa detectar), e textos
    diferentes produzem vetores praticamente ortogonais (similaridade
    proxima de 0) -- o suficiente para os testes de dedup exercitarem a
    comparacao de verdade, sem exigir uma chave de API real.
    """

    DIMENSAO = 32

    def embed(self, text: str) -> list[float]:
        import hashlib

        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [b / 255.0 for b in digest[: self.DIMENSAO]]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


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


class FakeCueRepository:
    """Taxonomia em memoria (issue #35). Registra chamadas em `calls`."""

    def __init__(self):
        self.calls: list[str] = []
        _categorias = {
            "sender_domain_mismatch": "technical", "typosquat": "technical",
            "homoglyph": "technical", "urgency": "psychological",
            "authority": "psychological", "generic_greeting": "psychological",
            "credential_request": "technical", "link_text_mismatch": "technical",
            "unexpected_attachment": "technical", "scarcity": "psychological",
        }
        self.entries = [
            CueTaxonomyEntry(
                id=uuid4(),
                code=CueCode(code),
                label_pt=f"rotulo {code}",
                descricao_pt=f"definicao operacional de {code}",
                category=categoria,
                ativo=True,
            )
            for code, categoria in _categorias.items()
        ]

    async def get_all_ativas(self):
        self.calls.append("get_all_ativas")
        return [e for e in self.entries if e.ativo]


class FakeGenerationJobRepository:
    """Em memoria, mesma interface publica de GenerationJobRepository
    (issue #11b).

    Existe porque o repositorio real fala SQL direto via
    `db.get_connection()`, que FakeDbConnection nao implementa (ela so
    cobre create_pool/close_pool, usados no lifespan) -- sem este fake,
    os testes de /generate/batch em tests/unit exigiriam Postgres real.
    BatchGenerationWorker e resolvido pelo container a partir deste
    mesmo provider, entao overrideando so `generation_job_repository`
    o worker tambem passa a usar o fake, sem precisar de um
    FakeBatchGenerationWorker.
    """

    def __init__(self):
        self.storage: dict = {}

    async def create(
        self,
        context: str,
        difficulties: list,
        total: int,
        malicious_ratio: float,
        channel: str = "email",
    ):
        job_id = uuid4()
        now = datetime.now(timezone.utc)
        self.storage[job_id] = GenerationJob(
            id=job_id,
            status=JobStatus.PENDENTE,
            context=context,
            difficulties=difficulties,
            total=total,
            malicious_ratio=malicious_ratio,
            channel=channel,
            created_at=now,
            updated_at=now,
        )
        return job_id

    async def get_by_id(self, job_id):
        return self.storage.get(job_id)

    async def mark_em_progresso(self, job_id, distribution: dict) -> None:
        job = self.storage[job_id]
        job.status = JobStatus.EM_PROGRESSO
        job.distribution = distribution

    async def update_progress(
        self, job_id, total_generated, total_failed, total_discarded, item_ids, failures
    ) -> None:
        job = self.storage[job_id]
        job.total_generated = total_generated
        job.total_failed = total_failed
        job.total_discarded = total_discarded
        job.item_ids = list(item_ids)
        job.failures = [
            f if isinstance(f, GenerationFailure) else GenerationFailure(**f) for f in failures
        ]

    async def mark_finished(self, job_id, status: JobStatus, error_message=None) -> None:
        job = self.storage[job_id]
        job.status = status
        job.error_message = error_message
        job.completed_at = datetime.now(timezone.utc)
