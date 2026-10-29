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
from langchain_core.runnables import Runnable

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


# Claude de reasoning (Sonnet/Opus/Haiku 4.6+ e 5.x, ex.: claude-sonnet-4-6,
# claude-opus-4-8, claude-haiku-5-5): a API recusa `temperature != 1` com 400.
# Espelha o `supports_temperature=False` do eval (ModelSpec em
# avaliar_modelos_llm.py) para o caminho de PRODUCAO, onde o modelo vem do
# config em vez de uma lista fixa. Os Claude mais antigos (<=4.5) seguem
# aceitando temperature custom.
_ANTHROPIC_SO_TEMPERATURA_1 = re.compile(
    r"^claude-(?:opus|sonnet|haiku)-(?:4-[6-9]|[5-9]-\d)", re.IGNORECASE
)


def anthropic_exige_temperatura_1(model_name: str) -> bool:
    """True para os Claude de reasoning que so aceitam `temperature=1`
    (Sonnet/Opus/Haiku 4.6+ e 5.x). Nesses, o gerador omite a temperatura.
    """
    return bool(_ANTHROPIC_SO_TEMPERATURA_1.match(model_name.strip()))


def modelo_so_aceita_temperatura_padrao(provider: str, model_name: str) -> bool:
    """True quando o modelo so aceita a temperatura default do provider
    (`temperature=1`): OpenAI de nova geracao (GPT-5+/o-series) e Claude de
    reasoning (4.6+/5.x). Para esses, mandar `temperature != 1` da 400.
    """
    if provider == PROVIDER_OPENAI:
        return openai_exige_max_completion_tokens(model_name)
    if provider == PROVIDER_ANTHROPIC:
        return anthropic_exige_temperatura_1(model_name)
    return False


def temperatura_efetiva(
    provider: str, model_name: str, temperatura: Optional[float]
) -> Optional[float]:
    """A temperatura que o gerador deve de fato usar: `None` (deixa o
    default do provider) para um modelo de reasoning que so aceita
    `temperature=1`, senao a `temperatura` pedida. Com `None`, o
    ResponseGenerator entra em modo reasoning e omite temperature em TODAS
    as sub-chains -- o mesmo que o eval fez para o Sonnet 4.6
    (supports_temperature=False). Usado pelo container (producao) para o
    caminho de producao bater com o do eval.
    """
    return None if modelo_so_aceita_temperatura_padrao(provider, model_name) else temperatura


def descrever_saida_estruturada(provider: str, model_name: str = "") -> str:
    """Rotulo do mecanismo de saida estruturada em uso, para o metadata do
    relatorio (eval) e o `run_metadata` do lote (producao). OpenAI: nativo
    (tool calling). Anthropic: instructor Mode.ANTHROPIC_JSON (prefill, sem
    tool_choice/thinking) -- ver build_structured_llm. Registra a assimetria
    de metodo entre fornecedores, a documentar no artigo.
    """
    if provider == PROVIDER_OPENAI:
        return "with_structured_output nativo (tool calling)"
    if provider == PROVIDER_ANTHROPIC:
        return "instructor Mode.ANTHROPIC_JSON (prefill, sem tool_choice/thinking)"
    return provider


def build_chat_model(
    provider: str,
    model_name: str,
    *,
    openai_api_key: str = "",
    anthropic_api_key: str = "",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    seed: Optional[int] = None,
) -> BaseChatModel:
    """Constroi o chat model do provider pedido.

    `temperature=None` deixa o default do provider (necessario para os
    modelos de reasoning da OpenAI, que rejeitam `temperature != 1`).
    `max_tokens` e opcional na OpenAI e obrigatorio na Anthropic -- para
    esta, cai no default quando nao informado.

    `seed` (reprodutibilidade): so a OpenAI expoe `seed` nas chat
    completions (determinismo best-effort, dependente do
    `system_fingerprint`). A Anthropic NAO tem parametro de seed, entao
    aqui o `seed` e ignorado no ramo anthropic -- as geracoes anthropic
    nao sao bit-reproduziveis. Por isso a comparacao de modelos persiste
    o item gerado de cada linha (ver avaliar_modelos_llm.py): e a
    reprodutibilidade que vale cross-vendor.

    Saida estruturada nos modelos de reasoning da Anthropic
    (claude-haiku-5-5, claude-sonnet-5-5): NAO use
    `.with_structured_output(...)` direto -- ver with_structured_output_compat
    abaixo (eles rejeitam o tool_choice forcado que o langchain usa).

    Import do cliente feito DENTRO de cada ramo de proposito: assim um
    ambiente que so usa OpenAI nao precisa ter `langchain-anthropic`
    instalado (e vice-versa), e o erro de dependencia faltando so
    aparece se aquele provider for de fato escolhido.
    """
    if provider == PROVIDER_OPENAI:
        from langchain_openai import ChatOpenAI

        kwargs = {"model": model_name, "api_key": openai_api_key}
        if seed is not None:
            # `seed` e campo nativo do ChatOpenAI (nao vai em model_kwargs):
            # convive com o max_completion_tokens da nova geracao.
            kwargs["seed"] = seed
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


def build_structured_llm(
    provider: str,
    model_name: str,
    schema: type,
    *,
    openai_api_key: str = "",
    anthropic_api_key: str = "",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    seed: Optional[int] = None,
) -> Runnable:
    """Runnable de SAIDA ESTRUTURADA: recebe um prompt (PromptValue/str) e
    devolve uma instancia Pydantic de `schema`. Usar no lugar de
    `build_chat_model(...).with_structured_output(...)`.

    - OpenAI: ChatOpenAI.with_structured_output -- saida estruturada nativa.
    - Anthropic: instructor em Mode.ANTHROPIC_JSON (prefill de JSON, SEM
      tool_choice e SEM thinking). Porque, no langchain-anthropic 0.3.18,
      nenhum caminho de saida estruturada e confiavel para os Claude 5.5 de
      reasoning: tool_choice forcado -> 400 no sonnet; tool_choice="auto" ->
      o modelo as vezes NAO chama a tool (varia por prompt/modelo -> item
      perdido), o que contaria errado como falha do modelo; thinking.enabled
      -> recusado (pedem 'adaptive'). O instructor JSON-mode e o MESMO
      mecanismo do juiz Anthropic do eval (ja validado nestes modelos) e
      nao depende de tool_choice.

    ASSIMETRIA DE METODO entre os fornecedores (nativo x instructor) --
    registrada no metadata do relatorio e a documentar no metodo do artigo.
    No ramo Anthropic NAO se envia temperature (os Claude 5.5 recusam
    temperature != 1) nem thinking (desligado; registrar no metadata).

    `instructor` e importado de forma preguicosa so no ramo Anthropic: um
    ambiente que so usa OpenAI (producao atual) nao precisa dele instalado.
    """
    if provider == PROVIDER_OPENAI:
        chat = build_chat_model(
            PROVIDER_OPENAI,
            model_name,
            openai_api_key=openai_api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed,
        )
        return chat.with_structured_output(schema)

    if provider == PROVIDER_ANTHROPIC:
        import instructor
        from anthropic import AsyncAnthropic
        from langchain_core.runnables import RunnableLambda

        client = instructor.from_anthropic(
            AsyncAnthropic(api_key=anthropic_api_key), mode=instructor.Mode.ANTHROPIC_JSON
        )
        mt = max_tokens or _MAX_TOKENS_ANTHROPIC_PADRAO

        async def _acall(prompt_value):
            if hasattr(prompt_value, "to_string"):
                content = prompt_value.to_string()
            elif isinstance(prompt_value, str):
                content = prompt_value
            else:
                content = str(prompt_value)
            # Sem temperature (recusada) e sem thinking (desligado).
            return await client.messages.create(
                model=model_name,
                max_tokens=mt,
                messages=[{"role": "user", "content": content}],
                response_model=schema,
            )

        return RunnableLambda(_acall)

    raise ValueError(
        f"provider de LLM desconhecido: {provider!r}. "
        f"Use um de {PROVIDERS_SUPORTADOS}."
    )
