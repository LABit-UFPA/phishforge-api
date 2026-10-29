import logging
from typing import Optional

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field

from app.domain.services.llm_factory import PROVIDER_OPENAI, build_structured_llm

logger = logging.getLogger(__name__)


class NormalizedQuery(BaseModel):
    search_query: str = Field(
        description="A pergunta otimizada e rica em palavras-chave, ideal para uma busca semântica em documentos acadêmicos."
    )
    generation_context: str = Field(
        description="O cenário específico ou a instrução criativa para a geração final. Se não houver, use uma descrição da tarefa."
    )


class PromptNormalizer:
    def __init__(
        self,
        api_key: str,
        model_name: str = "gpt-4o-mini",
        provider: str = PROVIDER_OPENAI,
        anthropic_api_key: str = "",
        seed: Optional[int] = None,
        temperature: Optional[float] = 0.0,
        max_tokens: Optional[int] = None,
    ):
        # `api_key` e a chave OpenAI (nome mantido para nao quebrar
        # chamadores antigos). `provider`/`anthropic_api_key` permitem o
        # normalizador seguir o mesmo provider do gerador (LLM_PROVIDER).
        # `seed`: reprodutibilidade best-effort na OpenAI (ignorado na
        # Anthropic -- ver build_chat_model); usado pela comparacao de
        # modelos para fixar a normalizacao junto da geracao.
        # `temperature`: default 0.0 (normalizacao deterministica, producao
        # com gpt-4o-mini). Mas modelos de reasoning so aceitam o default do
        # provider: OpenAI (gpt-5+/o-series) a omite sempre; os Claude 5.5
        # RECUSAM temperature != 1 ("temperature is deprecated for this
        # model"). Por isso o chamador passa temperature=None para esses
        # (ver construir_gerador) -- com None, build_chat_model nao envia 0.0
        # (Anthropic cai no default 1; OpenAI omite).
        # `max_tokens`: default None (sem teto na producao). Modelos de
        # reasoning GASTAM tokens raciocinando ANTES do JSON tambem no
        # normalizador: no default de 2000 da Anthropic, o Claude Haiku 5.5
        # exauria o orcamento raciocinando e devolvia vazio. O chamador passa
        # um teto generoso para reasoning (ver construir_gerador).
        self.model_name = model_name
        self.provider = provider
        # O normalizador tambem usa saida estruturada: via build_structured_llm
        # para funcionar nos Claude de reasoning (instructor JSON-mode, sem
        # tool_choice/thinking), que de outra forma estouravam no normalize,
        # antes mesmo da geracao (ver build_structured_llm).
        self.llm = build_structured_llm(
            provider,
            model_name,
            NormalizedQuery,
            openai_api_key=api_key,
            anthropic_api_key=anthropic_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed,
        )

        self.prompt_template = PromptTemplate(
            input_variables=["user_context"],
            template=(
                "You are an expert at rewriting queries for a Retrieval-Augmented Generation (RAG) system. "
                "Your task is to analyze the user context and transform it into two components:\n"
                "1. A 'search_query' - clear and technical query to search for information in academic articles about cybersecurity.\n"
                "2. A 'generation_context' - the specific scenario that the user wants to be created.\n\n"
                "**IMPORTANT RULES:**\n"
                "- BOTH 'search_query' AND 'generation_context' MUST be in ENGLISH.\n"
                "- The search_query should contain technical keywords for semantic search.\n"
                "- The generation_context should describe the specific scenario for email generation.\n\n"
                "User Context: '{user_context}'\n\n"
                "Example:\n"
                "User Context: 'cria um email de phishing dificil pro alex do chefe dele, a sarah, sobre o projeto aurora'\n"
                "JSON Output: {{"
                '  "search_query": "Advanced spear phishing techniques using social engineering and referencing internal projects to create urgency.",'
                '  "generation_context": "Create a spear phishing email for employee Alex, coming from his boss Sarah, about Project Aurora."'
                "}}\n\n"
                "Now, process the provided user context. Remember: BOTH outputs must be in ENGLISH."
            ),
        )
        self.chain = self.prompt_template | self.llm

    async def normalize(self, user_context: str) -> NormalizedQuery:
        logger.info(f"[PromptNormalizer] Model: {self.model_name}")
        logger.info(f"[PromptNormalizer] Input: {user_context[:100]}...")

        result = await self.chain.ainvoke({"user_context": user_context})

        logger.info(f"[PromptNormalizer] search_query: {result.search_query[:100]}...")
        logger.info(
            f"[PromptNormalizer] generation_context: {result.generation_context[:100]}..."
        )

        return result
