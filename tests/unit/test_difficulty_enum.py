"""Teste direto de app.domain.models.difficulty.Difficulty, isolado do
resto da stack -- sem passar por HTTP nem pela app inteira. Se este
teste falhar, o problema é no enum, não em como o endpoint o usa (essa
parte fica em test_generate_endpoint.py e test_generate_batch_endpoint.py).
"""

import pytest
from pydantic import BaseModel, ValidationError

from app.domain.models.difficulty import Difficulty


@pytest.mark.parametrize(
    "valor_bruto,esperado",
    [
        ("facil", Difficulty.FACIL),
        ("medio", Difficulty.MEDIO),
        ("dificil", Difficulty.DIFICIL),
        ("fácil", Difficulty.FACIL),
        ("médio", Difficulty.MEDIO),
        ("difícil", Difficulty.DIFICIL),
        ("easy", Difficulty.FACIL),
        ("medium", Difficulty.MEDIO),
        ("hard", Difficulty.DIFICIL),
        ("FACIL", Difficulty.FACIL),  # caixa alta tambem normaliza
        ("  facil  ", Difficulty.FACIL),  # espaco nas bordas
    ],
)
def test_aceita_canonico_e_sinonimo(valor_bruto, esperado):
    assert Difficulty(valor_bruto) is esperado


def test_valor_fora_do_vocabulario_levanta_value_error():
    with pytest.raises(ValueError):
        Difficulty("nivel_inventado")


def test_valor_e_string_pura_apos_normalizado():
    """O valor .value tem que ser a string canonica pura, sem acento
    -- e o que vai para o banco e para o prompt do LLM.
    """
    assert Difficulty("easy").value == "facil"
    assert Difficulty("médio").value == "medio"


def test_str_do_enum_nao_e_o_valor_direto():
    """Documenta a armadilha que motivou usar .value em todo lugar
    (generator.py): a partir do Python 3.11, Enum sobrescreve __str__,
    entao str(membro) NAO devolve o valor -- e por isso o codigo nunca
    deve depender de str(difficulty) ou f-strings com o membro cru.
    """
    assert str(Difficulty.FACIL) != "facil"
    assert f"{Difficulty.FACIL}" != "facil"
    assert Difficulty.FACIL.value == "facil"


def test_funciona_como_tipo_de_campo_pydantic_com_422_automatico():
    class Modelo(BaseModel):
        difficulty: Difficulty

    assert Modelo(difficulty="easy").difficulty is Difficulty.FACIL

    with pytest.raises(ValidationError):
        Modelo(difficulty="nivel_inventado")
