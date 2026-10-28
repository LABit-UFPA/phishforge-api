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

import re
from typing import Optional

from langchain_core.language_models import BaseChatModel

PROVIDER_OPENAI = "openai"
PROVIDER_ANTHROPIC = "anthropic"
PROVIDERS_SUPORTADOS = (PROVIDER_OPENAI, PROVIDER_ANTHROPIC)

# Anthropic exige `max_tokens` na construcao (OpenAI nao). Teto de
# seguranca quando o chamador nao informa um -- o mesmo default de
# geracao de ResponseGenerator.
_MAX_TOKENS_ANTHROPIC_PADRAO = 2000

# o-series (o1..o9) e GPT-5+ (gpt-5, gpt-5.5, gpt-6-luna, ...): a API da
# OpenAI rejeita `max_tokens` (exige `max_completion_tokens`) e aceita so
# `temperature=1`. gpt-4/gpt-4o/gpt-4o-mini (producao) seguem no caminho
# antigo. Aceita minor version com ponto (gpt-5.5) -- o parse por `int`
# da propria ragas 0.4.3 falha nesse caso.
_OPENAI_NOVA_GERACAO = re.compile(r"^(o[1-9]|gpt-(?:[5-9]|1[0-9]))", re.IGNORECASE)


def openai_exige_max_completion_tokens(model_name: str) -> bool:
    """True para os modelos OpenAI que exigem `max_completion_tokens` no
    lugar de `max_tokens` e so aceitam `temperature=1` (o-series e
    GPT-5+). Usado aqui e espelhado no juiz RAGAS do script de avaliacao.
    """
    return bool(_OPENAI_NOVA_GERACAO.match(model_name.strip()))


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
        if openai_exige_max_completion_tokens(model_name):
            # GPT-5+/o-series: `max_completion_tokens` (via model_kwargs,
            # cru para a API) no lugar de `max_tokens`, e temperature
            # omitida (a API so aceita o default 1). Passar `max_tokens`
            # ou `temperature != 1` aqui da 400.
            if max_tokens is not None:
                kwargs["model_kwargs"] = {"max_completion_tokens": max_tokens}
        else:
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
