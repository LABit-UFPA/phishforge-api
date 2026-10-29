"""Extracao de texto de AIMessage, seja str (OpenAI) ou lista de blocos
(Anthropic reasoning).

Regressao: `response.content.strip()` quebrava com "'list' object has no
attribute 'strip'" quando o Claude devolvia `content` como lista de blocos,
derrubando HyDE e a fusao de contexto para o fallback SO nos modelos
Anthropic -- RAG degradado de um lado so, um confundidor na comparacao de
modelos do artigo. `_texto_da_resposta` normaliza os dois formatos.
"""

from dataclasses import dataclass
from typing import Any

from app.domain.services.response_generator import _texto_da_resposta


@dataclass
class _FakeMsg:
    content: Any


def test_openai_content_str():
    assert _texto_da_resposta(_FakeMsg("  um texto  ")) == "  um texto  "


def test_anthropic_lista_de_blocos_dict():
    msg = _FakeMsg(
        [
            {"type": "thinking", "thinking": "raciocinio interno ignorado"},
            {"type": "text", "text": "parte 1 "},
            {"type": "text", "text": "parte 2"},
        ]
    )
    # So os blocos de texto, raciocinio descartado.
    assert _texto_da_resposta(msg) == "parte 1 parte 2"


def test_lista_de_strings():
    assert _texto_da_resposta(_FakeMsg(["a", "b", "c"])) == "abc"


def test_lista_vazia_vira_string_vazia():
    assert _texto_da_resposta(_FakeMsg([])) == ""


def test_bloco_objeto_com_atributo_text():
    @dataclass
    class _Bloco:
        text: str

    assert _texto_da_resposta(_FakeMsg([_Bloco("x"), _Bloco("y")])) == "xy"


def test_content_none_nao_quebra():
    assert _texto_da_resposta(_FakeMsg(None)) == ""


def test_resultado_e_stripavel_como_antes():
    """O chamador faz `_texto_da_resposta(r).strip().strip('"')`; o retorno
    e sempre str, entao .strip encadeado nao quebra para nenhum provider.
    """
    msg = _FakeMsg([{"type": "text", "text": '  "citado"  '}])
    assert _texto_da_resposta(msg).strip().strip('"') == "citado"
