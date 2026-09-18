from dataclasses import dataclass

from app.domain.services.prompt_normalizer import PromptNormalizer
from app.domain.services.reranker import ReRanker
from app.domain.services.response_generator import ResponseGenerator
from app.infra.qdrant.store import QdrantVectorStore

# Top-k usado pelos dois fluxos. Antes desta issue, /generate usava 20
# e /generate/batch usava 80 -- mas so os 3 primeiros pos-rerank chegam
# a ser usados em qualquer um dos dois, entao os 77 documentos extras
# do lote eram recuperados e descartados sem uso (ver issue #11).
# Alinhado no valor que ja funcionava no fluxo unico.
TOP_K_RETRIEVE = 20

# Quantos documentos, ja reranqueados, entram na fusao final. Mesmo
# valor que os dois fluxos usavam antes, agora num unico lugar.
TOP_N_PARA_FUSAO = 3


@dataclass
class BuiltContext:
    """Resultado da orquestracao RAG para um `user_context` de entrada
    -- tudo que independe da dificuldade do item a ser gerado (issue
    #11). Reaproveitavel entre todos os itens de um mesmo lote: gerar
    N itens do mesmo contexto com dificuldades diferentes nao precisa
    repetir normalizacao, HyDE, retrieve, rerank nem fusao N vezes.
    """

    search_query: str
    generation_context: str
    fused_context: str


class GenerationPipeline:
    """Orquestra normalizacao, HyDE, retrieve, rerank e fusao -- as
    etapas que a issue #11 identificou divergindo entre /generate e
    /generate/batch.

    Antes desta extracao, essa sequencia estava escrita a mao dentro
    do handler do /generate, e o /generate/batch nunca teve como
    "herdar" as etapas porque nao havia nada de onde herdar -- ele
    reimplementava so um pedaco (retrieve, com top_k e campo de
    contexto diferentes) e pulava normalizacao, HyDE, rerank e fusao
    inteiramente. Com a orquestracao aqui, os dois fluxos chamam a
    mesma funcao e produzem o mesmo nivel de contexto academico.

    Nao decide o que fazer com o resultado em caso de falha -- deixa
    a excecao subir para o chamador (o endpoint), que decide o codigo
    HTTP. Esta classe nao depende de FastAPI de proposito, para poder
    ser testada e reaproveitada fora do contexto HTTP.
    """

    def __init__(
        self,
        normalizer: PromptNormalizer,
        response_generator: ResponseGenerator,
        vector_store: QdrantVectorStore,
        reranker: ReRanker,
        collection_name: str,
    ):
        self._normalizer = normalizer
        self._response_generator = response_generator
        self._vector_store = vector_store
        self._reranker = reranker
        self._collection_name = collection_name

    async def build_context(self, user_context: str) -> BuiltContext:
        # 1. Normaliza o input do usuario
        normalized = await self._normalizer.normalize(user_context)
        search_query = normalized.search_query
        generation_context = normalized.generation_context

        # 2. HyDE (Query Transformation). Falha aqui tem fallback
        # deliberado (usar a search_query crua) -- HyDE e uma melhoria
        # de recall, nao um passo obrigatorio; nao vale derrubar a
        # geracao inteira por causa dele.
        try:
            hyde_context = await self._response_generator.generate_hypothetical_answer(
                search_query
            )
        except Exception:
            hyde_context = search_query

        # 3. Retrieve (Busca Inicial). Excecao aqui SOBE para o
        # chamador -- diferente do HyDE, um retrieve quebrado nao tem
        # fallback razoavel (gerar sem nenhum documento academico e
        # silenciosamente pior, nao um degrade aceitavel).
        candidate_docs = self._vector_store.query(
            collection_name=self._collection_name,
            query_text=hyde_context,
            top_k=TOP_K_RETRIEVE,
        )

        # 4. Re-rank (Refinamento da Busca)
        reranked_docs = self._reranker.rerank(search_query, candidate_docs)

        # 5. Extracao e Fusao do Contexto. `parent_content` (o bloco
        # grande usado para geracao), nao `text`/`child_text` (o chunk
        # pequeno otimizado so para busca) -- essa e a distincao que o
        # /generate/batch antigo nao respeitava (issue #11).
        if reranked_docs:
            top_docs_payloads = [doc.payload for doc in reranked_docs[:TOP_N_PARA_FUSAO]]
            final_contexts = [
                payload["parent_content"]
                for payload in top_docs_payloads
                if "parent_content" in payload
            ]
        else:
            final_contexts = []

        fused_context = await self._response_generator.fuse_and_summarize_context(
            generation_context=generation_context, contexts=final_contexts
        )

        return BuiltContext(
            search_query=search_query,
            generation_context=generation_context,
            fused_context=fused_context,
        )
