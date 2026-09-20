"""Verificacao de cegamento (issue #37), compartilhada por unit e integracao.

O especialista NUNCA pode ver o rotulo verdadeiro nem as pistas que o LLM
ja anotou: isso ancoraria a anotacao humana e destruiria a independencia
das duas medidas, que e o ponto de ter as duas. Por isso a checagem e
RECURSIVA (chave proibida em qualquer profundidade) e olha tambem o
esquema declarado da resposta -- um campo novo adicionado ao modelo de
resposta falha aqui mesmo que o teste de runtime nao o exercite.
"""

from typing import Any, Iterator, Set

CAMPOS_PROIBIDOS: Set[str] = {
    "nivel",
    "explicacao",
    "is_malicious",
    "categoria",
    "cues",
    "phish_scale",
    "id",
    "created_at",
    "updated_at",
    "channel",
    "content_json",
}


def chaves_recursivas(dado: Any) -> Iterator[str]:
    if isinstance(dado, dict):
        for chave, valor in dado.items():
            yield chave
            yield from chaves_recursivas(valor)
    elif isinstance(dado, list):
        for elemento in dado:
            yield from chaves_recursivas(elemento)


def chaves_proibidas_em(json_resposta: Any) -> Set[str]:
    return set(chaves_recursivas(json_resposta)) & CAMPOS_PROIBIDOS


def propriedades_do_esquema(modelo) -> Set[str]:
    """Todas as propriedades declaradas no esquema de um modelo Pydantic,
    inclusive nos modelos aninhados (`$defs`).
    """
    esquema = modelo.model_json_schema()
    nomes: Set[str] = set()
    for definicao in [esquema, *esquema.get("$defs", {}).values()]:
        nomes |= set(definicao.get("properties", {}))
    return nomes
