import logging
from typing import Optional

from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field

from app.domain.services.llm_factory import PROVIDER_OPENAI, build_chat_model

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
    ):
        # `api_key` e a chave OpenAI (nome mantido para nao quebrar
        # chamadores antigos). `provider`/`anthropic_api_key` permitem o
        # normalizador seguir o mesmo provider do gerador (LLM_PROVIDER).
        # `seed`: reprodutibilidade best-effort na OpenAI (ignorado na
        # Anthropic -- ver build_chat_model); usado pela comparacao de
        # modelos para fixar a normalizacao junto da geracao.
        self.model_name = model_name
        self.provider = provider
        self.llm = build_chat_model(
            provider,
            model_name,
            openai_api_key=api_key,
            anthropic_api_key=anthropic_api_key,
            temperature=0.0,
            seed=seed,
        ).with_structured_output(NormalizedQuery)

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
