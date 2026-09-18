from enum import Enum


class Difficulty(str, Enum):
    """Vocabulario canonico de dificuldade.

    Decisao registrada na issue #2 (comentario de 2026-09-18): portugues
    sem acento e o canonico interno -- e o que o CHECK do banco ja exige
    (migration V20260517120000) e o que o dominio da pesquisa usa. Nao
    ha nenhum lugar no codigo, a partir desta issue, que deva enxergar
    um valor diferente destes tres.

    Sinonimos em ingles e em portugues acentuado sao aceitos na BORDA
    (ver _missing_ abaixo), nunca usados internamente -- inclusive no
    payload que a futura integracao com o backend Go vai enviar, que e
    serializado em ingles separadamente (ver comentario da issue).
    """

    FACIL = "facil"
    MEDIO = "medio"
    DIFICIL = "dificil"

    @classmethod
    def _missing_(cls, value: object) -> "Difficulty | None":
        """Normaliza sinonimos aceitos na borda para o valor canonico.

        Chamado automaticamente pelo proprio Enum (e, por extensao,
        pela validacao do Pydantic/FastAPI) quando o valor bruto nao
        bate com nenhum membro por igualdade direta -- e o que faz
        `Difficulty("easy")`, `QueryRequest(difficulty="easy")` e
        `list[Difficulty]` num Body do FastAPI aceitarem sinonimo e
        normalizarem numa unica passada, sem validator repetido em
        cada DTO. Confirmado experimentalmente que o Pydantic v2
        respeita este hook.

        Qualquer valor fora do vocabulario (canonico ou sinonimo)
        devolve None, e o Pydantic converte isso em 422 automatico --
        nao ha fallback silencioso aqui.
        """
        if not isinstance(value, str):
            return None

        synonyms = {
            "facil": cls.FACIL,
            "fácil": cls.FACIL,
            "easy": cls.FACIL,
            "medio": cls.MEDIO,
            "médio": cls.MEDIO,
            "medium": cls.MEDIO,
            "dificil": cls.DIFICIL,
            "difícil": cls.DIFICIL,
            "hard": cls.DIFICIL,
        }
        return synonyms.get(value.strip().lower())
