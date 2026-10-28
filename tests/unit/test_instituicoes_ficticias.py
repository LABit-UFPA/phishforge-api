"""A lista versionada de identidades ficticias (piloto 5, item 2.1):
nenhuma entrada pode disparar os proprios detectores de instituicao
real, dominio caricato ou marcador -- senao o item recem-criado com
ela seria barrado e mandado gerar de novo, o mesmo laco que a ficha
pronta (ver instituicoes_ficticias.py) existe para romper. Referenciado
pela docstring de `instituicoes_ficticias.py` e de `InstituicaoFicticia`.
"""

import pytest

from app.domain.models.instituicao_ficticia import InstituicaoFicticia
from app.domain.services.instituicoes_ficticias import INSTITUICOES
from app.domain.services.item_validation import (
    encontrar_dominios_caricatos,
    encontrar_instituicoes_reais,
    encontrar_marcadores,
)


def test_lista_tem_pelo_menos_vinte_entradas():
    """Variedade para o ciclo balanceado nao repetir a mesma
    instituicao cedo demais num lote grande do protocolo (50-200 itens).
    """
    assert len(INSTITUICOES) >= 20


def test_nomes_siglas_e_dominios_sao_unicos_entre_si():
    nomes = [i.nome_base for i in INSTITUICOES]
    siglas = [i.sigla for i in INSTITUICOES]
    dominios = [i.dominio_oficial for i in INSTITUICOES]
    assert len(nomes) == len(set(nomes))
    assert len(siglas) == len(set(siglas))
    assert len(dominios) == len(set(dominios))


@pytest.mark.parametrize("instituicao", INSTITUICOES, ids=lambda i: i.nome_base)
def test_instituicao_nao_dispara_bloqueio_de_instituicao_real(instituicao):
    for valor in (instituicao.nome_base, instituicao.sigla, instituicao.dominio_oficial):
        assert encontrar_instituicoes_reais(valor) == []


@pytest.mark.parametrize("instituicao", INSTITUICOES, ids=lambda i: i.nome_base)
def test_instituicao_nao_dispara_dominio_caricato(instituicao):
    assert encontrar_dominios_caricatos(instituicao.dominio_oficial) == []
    assert encontrar_dominios_caricatos(f"contato@{instituicao.dominio_oficial}") == []


@pytest.mark.parametrize("instituicao", INSTITUICOES, ids=lambda i: i.nome_base)
def test_instituicao_nao_dispara_marcador(instituicao):
    for valor in (
        instituicao.nome_base,
        instituicao.sigla,
        instituicao.dominio_oficial,
        f"contato@{instituicao.dominio_oficial}",
    ):
        assert encontrar_marcadores(valor) == []


def test_instituicao_ficticia_e_hashable():
    """Regressao: BaseModel do pydantic v2 so e hashable com
    `model_config = ConfigDict(frozen=True)` -- sem isso, `__eq__`
    definido sem `__hash__` desliga o hash por omissao (regra do
    proprio Python), e `set(INSTITUICOES)` ou `{ficha.instituicao for
    ...}` (usados no sorteio balanceado e nos testes do worker)
    levantam `TypeError: unhashable type`.
    """
    a = InstituicaoFicticia(nome_base="X", sigla="X", dominio_oficial="x.com.br")
    b = InstituicaoFicticia(nome_base="X", sigla="X", dominio_oficial="x.com.br")
    assert hash(a) == hash(b)
    assert {a, b} == {a}
    assert set(INSTITUICOES) == set(INSTITUICOES)
