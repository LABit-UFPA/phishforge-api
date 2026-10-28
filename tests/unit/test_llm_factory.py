"""Fabrica de chat model por provider (comparacao OpenAI x Anthropic).

Nao faz chamada de rede: so constroi os objetos LangChain e confere que
o provider certo e escolhido, que temperature e omitida quando None
(modelos de reasoning) e que provider invalido falha alto.
"""

import pytest

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
