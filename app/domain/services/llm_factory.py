"""Fabrica de modelos de chat (LangChain) por provider.

Um unico ponto para construir o LLM de geracao, seja OpenAI ou
Anthropic. `ResponseGenerator` e `PromptNormalizer` chamam `build_chat_model`
em vez de instanciar `ChatOpenAI` direto, para o provider do gerador
virar configuracao (`LLM_PROVIDER`) em vez de um nome de classe fixo no
codigo (comparacao de modelos OpenAI x Anthropic para o artigo).

Os dois modelos retornados sao `BaseChatModel` do LangChain, entao
`.with_structured_output(...)` e as chains `prompt | llm` funcionam
igual para os dois -- nada mais no codigo precisa saber qual provider
esta em uso. O EMBEDDING nao passa por aqui: continua OpenAI, porque
trocar o espaco vetorial exigiria reindexar o Qdrant.
"""

from typing import Optional

from langchain_core.language_models import BaseChatModel

PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDERS_SUPORTADOS = (PROVIDER_OPENAI, PROVIDER_ANTHROPIC)

# Anthropic exige `max_tokens` na construcao (OpenAI nao). Teto de
# seguranca quando o chamador nao informa um -- o mesmo default de
# geracao de ResponseGenerator.
_MAX_TOKENS_ANTHROPIC_PADRAO = 2000


def build_chat_model(
    provider: str,
    model_name: str,
    *,
    openai_api_key: str = "",
    anthropic_api_key: str = "",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
) -> BaseChatModel:
    """Constroi o chat model do provider pedido.

    `temperature=None` deixa o default do provider (necessario para os
    modelos de reasoning da OpenAI, que rejeitam `temperature != 1`).
    `max_tokens` e opcional na OpenAI e obrigatorio na Anthropic -- para
    esta, cai no default quando nao informado.

    Import do cliente feito DENTRO de cada ramo de proposito: assim um
    ambiente que so usa OpenAI nao precisa ter `langchain-anthropic`
    instalado (e vice-versa), e o erro de dependencia faltando so
    aparece se aquele provider for de fato escolhido.
    """
    if provider == PROVIDER_OPENAI:
        from langchain_openai import ChatOpenAI

        kwargs = {"model": model_name, "api_key": openai_api_key}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        return ChatOpenAI(**kwargs)

    if provider == PROVIDER_ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model_name,
            api_key=anthropic_api_key,
            # Anthropic aceita temperature em 0..1; None vira o default
            # da classe (1.0).
            temperature=temperature if temperature is not None else 1.0,
            max_tokens=max_tokens or _MAX_TOKENS_ANTHROPIC_PADRAO,
        )

    raise ValueError(
        f"provider de LLM desconhecido: {provider!r}. "
        f"Use um de {PROVIDERS_SUPORTADOS}."
    )
