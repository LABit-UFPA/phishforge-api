"""Fabrica de chat model por provider (comparacao OpenAI x Anthropic).

Nao faz chamada de rede: so constroi os objetos LangChain e confere que
o provider certo e escolhido, que temperature e omitida quando None
(modelos de reasoning) e que provider invalido falha alto.
"""

import pytest
from pydantic import BaseModel, Field

from app.domain.services.llm_factory import (
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    build_chat_model,
)


def test_openai_por_padrao():
    m = build_chat_model(PROVIDER_OPENAI, "gpt-4o-mini", openai_api_key="sk-x", temperature=0.7)
    assert type(m).__name__ == "ChatOpenAI"
    assert m.temperature == 0.7


def test_anthropic():
    m = build_chat_model(
        PROVIDER_ANTHROPIC, "claude-haiku-5-5", anthropic_api_key="x", temperature=0.5, max_tokens=1500
    )
    assert type(m).__name__ == "ChatAnthropic"
    assert m.temperature == 0.5
    assert m.max_tokens == 1500


def test_anthropic_exige_max_tokens_cai_no_default():
    m = build_chat_model(PROVIDER_ANTHROPIC, "claude-sonnet-5-5", anthropic_api_key="x")
    assert m.max_tokens  # Anthropic exige max_tokens -> default != 0/None


def test_temperature_none_e_omitida_no_openai():
    """Modelo de reasoning: temperature None nao deve ser passada (o
    cliente usaria o default do provider em vez de 0.7).
    """
    m = build_chat_model(PROVIDER_OPENAI, "o-algum-reasoning", openai_api_key="sk-x", temperature=None)
    assert m.temperature is None


def test_provider_desconhecido_falha_alto():
    with pytest.raises(ValueError, match="provider de LLM desconhecido"):
        build_chat_model("gemini", "qualquer", openai_api_key="x")


def test_openai_recebe_seed():
    """Reprodutibilidade: `seed` e campo nativo do ChatOpenAI e deve ser
    repassado (tanto no caminho legado quanto no de nova geracao -- o seed
    e setado antes do branch de max_tokens).
    """
    legado = build_chat_model(
        PROVIDER_OPENAI, "gpt-4o-mini", openai_api_key="sk-x", temperature=0.7, seed=42
    )
    assert legado.seed == 42

    novo = build_chat_model(
        PROVIDER_OPENAI, "gpt-6-luna", openai_api_key="sk-x", max_tokens=2000, seed=42
    )
    assert novo.seed == 42


def test_openai_sem_seed_fica_none():
    m = build_chat_model(PROVIDER_OPENAI, "gpt-4o-mini", openai_api_key="sk-x")
    assert m.seed is None


def test_anthropic_ignora_seed_sem_quebrar():
    """A Anthropic nao tem parametro de seed; build_chat_model deve
    aceitar `seed=` no ramo anthropic sem passar adiante nem quebrar.
    """
    m = build_chat_model(
        PROVIDER_ANTHROPIC, "claude-haiku-5-5", anthropic_api_key="x", seed=42
    )
    assert type(m).__name__ == "ChatAnthropic"


class _SchemaDummy(BaseModel):
    campo: str = Field(description="um campo qualquer")


def test_structured_llm_openai_nativo():
    """OpenAI: build_structured_llm usa o with_structured_output nativo e
    devolve um Runnable.
    """
    from app.domain.services.llm_factory import build_structured_llm

    r = build_structured_llm(PROVIDER_OPENAI, "gpt-4o-mini", _SchemaDummy, openai_api_key="sk-x")
    assert hasattr(r, "ainvoke")


def test_structured_llm_anthropic_instructor_json():
    """Anthropic: build_structured_llm NAO usa with_structured_output (que
    forcaria tool_choice, recusado pelos Claude de reasoning); usa instructor
    em JSON-mode, devolvido como um RunnableLambda. Requer `instructor`
    (vem com o grupo evaluation); fora dele, o teste e pulado.
    """
    pytest.importorskip("instructor")
    from app.domain.services.llm_factory import build_structured_llm

    r = build_structured_llm(
        PROVIDER_ANTHROPIC, "claude-sonnet-5-5", _SchemaDummy, anthropic_api_key="x"
    )
    assert hasattr(r, "ainvoke")
    assert type(r).__name__ == "RunnableLambda"


def test_openai_nova_geracao_detecta_gpt5_gpt6_oseries():
    from app.domain.services.llm_factory import openai_exige_max_completion_tokens as exige

    assert exige("gpt-5.5") and exige("gpt-6-luna") and exige("gpt-6-sol")
    assert exige("gpt-5") and exige("o1") and exige("o3-mini")
    # Modelos legados (producao) seguem no caminho antigo (max_tokens).
    assert not exige("gpt-4o-mini") and not exige("gpt-4o-mini-2024-07-18")
    assert not exige("gpt-4o") and not exige("gpt-4")


def test_openai_nova_geracao_omite_temperature():
    """GPT-5+/o-series: a API so aceita `temperature=1`, entao
    build_chat_model NAO passa temperature (usa o default do provider);
    gpt-4o-mini (producao) continua recebendo a temperature pedida e o
    `max_tokens`.

    O roteamento do limite de tokens (max_completion_tokens via
    model_kwargs) e validado de verdade pelo --smoke contra a API; aqui
    o foco e a temperature, cujo comportamento e estavel entre o
    langchain real e o fake de teste (o langchain real move o
    max_completion_tokens do model_kwargs para o proprio campo, entao o
    valor de `.max_tokens` nao e um sinal estavel para asserir).
    """
    novo = build_chat_model(
        PROVIDER_OPENAI, "gpt-6-luna", openai_api_key="sk-x", temperature=0.7, max_tokens=2000
    )
    assert novo.temperature is None

    legado = build_chat_model(
        PROVIDER_OPENAI, "gpt-4o-mini", openai_api_key="sk-x", temperature=0.7, max_tokens=2000
    )
    assert legado.temperature == 0.7 and legado.max_tokens == 2000


# ---------------------------------------------------------------------------
# Item 1 (plano de producao): Sonnet 4.6 como gerador padrao, mesmo mecanismo
# do eval (instructor JSON-mode, sem temperature), sem fallback silencioso.
# ---------------------------------------------------------------------------


def test_anthropic_reasoning_exige_temperatura_1():
    from app.domain.services.llm_factory import anthropic_exige_temperatura_1 as exige

    # Claude de reasoning (4.6+ e 5.x) so aceitam temperature=1.
    assert exige("claude-sonnet-4-6") and exige("claude-opus-4-8") and exige("claude-haiku-5-5")
    assert exige("claude-sonnet-5-5")
    # Claude mais antigos (<=4.5) aceitam temperature custom.
    assert not exige("claude-3-5-sonnet-20241022") and not exige("claude-sonnet-4-5")


def test_temperatura_efetiva_omite_para_modelo_de_reasoning():
    from app.domain.services.llm_factory import temperatura_efetiva as efetiva

    # Sonnet 4.6 (producao) e GPT-5+: temperatura omitida (None) -- igual ao
    # supports_temperature=False do eval.
    assert efetiva(PROVIDER_ANTHROPIC, "claude-sonnet-4-6", 0.7) is None
    assert efetiva(PROVIDER_OPENAI, "gpt-6-sol", 0.7) is None
    # Modelos nao-reasoning mantem a temperatura pedida.
    assert efetiva(PROVIDER_OPENAI, "gpt-4o-mini", 0.7) == 0.7
    assert efetiva(PROVIDER_ANTHROPIC, "claude-3-5-sonnet-20241022", 0.5) == 0.5


def test_descrever_saida_estruturada_por_fornecedor():
    from app.domain.services.llm_factory import descrever_saida_estruturada as descr

    assert "nativo" in descr(PROVIDER_OPENAI, "gpt-6-sol")
    anth = descr(PROVIDER_ANTHROPIC, "claude-sonnet-4-6")
    assert "instructor" in anth and "ANTHROPIC_JSON" in anth


def test_provider_desconhecido_falha_alto_na_saida_estruturada():
    """Sem fallback silencioso: um provider que nao existe levanta, nao cai
    num modelo qualquer (plano item 1)."""
    from app.domain.services.llm_factory import build_structured_llm

    with pytest.raises(ValueError, match="provider de LLM desconhecido"):
        build_structured_llm("provedor-inexistente", "x", _SchemaDummy)


def test_config_de_producao_usa_sonnet_4_6_sem_fallback():
    """O default de producao e Claude Sonnet 4.6 pela Anthropic; nenhum
    fallback para sonnet-5-5 (que saiu vazio no eval) esta cravado no config."""
    from app.core.config import Settings

    campos = Settings.model_fields
    assert campos["LLM_PROVIDER"].default == PROVIDER_ANTHROPIC
    assert campos["MODEL_NAME_LLM"].default == "claude-sonnet-4-6"
