"""Ficha de variacao por item (lote-piloto de 26/10/2026): o sorteio
precisa respeitar as regras de cada nivel do prompt e cobrir os valores
de forma balanceada dentro de um lote.
"""

import random
from collections import Counter
from itertools import combinations

import pytest

from app.domain.models.cue import CueCode
from app.domain.services.variation_sampler import (
    ACAO_ANEXO,
    ACOES_COM_LINK,
    ACOES_SEM_LINK,
    ESTRUTURAS_COMPLETAS,
    POOL_DIFICIL,
    POOL_MEDIO,
    VariationSampler,
    renderizar_ficha,
)


def _sampler(seed=7):
    return VariationSampler(random.Random(seed))


def test_medio_tem_exatamente_duas_pistas_com_nome_e_sem_link():
    sampler = _sampler()
    for _ in range(50):
        ficha = sampler.sortear("medio")
        assert len(ficha.pistas_alvo) == 2
        assert len(set(ficha.pistas_alvo)) == 2
        assert all(p in POOL_MEDIO for p in ficha.pistas_alvo)
        # Nome na saudacao: generic_greeting nunca e alvo no medio.
        assert CueCode.GENERIC_GREETING not in ficha.pistas_alvo
        assert ficha.nome_destinatario
        # MEDIO nunca tem link (issue #20).
        assert ficha.acao in ACOES_SEM_LINK
        assert ficha.estrutura in ESTRUTURAS_COMPLETAS


def test_medio_com_pista_de_anexo_pede_acao_de_anexo():
    sampler = _sampler()
    fichas = [sampler.sortear("medio") for _ in range(60)]
    com_anexo = [f for f in fichas if CueCode.UNEXPECTED_ATTACHMENT in f.pistas_alvo]
    assert com_anexo
    assert all(f.acao == ACAO_ANEXO for f in com_anexo)


def test_facil_tem_saudacao_generica_fixa_e_sem_nome():
    sampler = _sampler()
    for _ in range(30):
        ficha = sampler.sortear("facil")
        assert len(ficha.pistas_alvo) == 3
        assert ficha.pistas_alvo[0] == CueCode.GENERIC_GREETING
        assert ficha.nome_destinatario is None
        assert ficha.acao in ACOES_COM_LINK


def test_dificil_tem_uma_pista_so_que_o_link_consome():
    sampler = _sampler()
    for _ in range(20):
        ficha = sampler.sortear("dificil")
        assert len(ficha.pistas_alvo) == 1
        assert ficha.pistas_alvo[0] in POOL_DIFICIL
        assert ficha.nome_destinatario
        assert ficha.acao in ACOES_COM_LINK


def test_item_legitimo_nao_tem_pista_nem_acao_e_tem_nome():
    ficha = _sampler().sortear("medio", is_malicious=False)
    assert ficha.pistas_alvo == []
    assert ficha.acao is None
    assert ficha.nome_destinatario


def test_pares_de_pistas_do_medio_cobrem_o_pool_de_forma_balanceada():
    """21 pares possiveis no medio: em 42 itens, cada par sai exatamente
    2 vezes -- e o que o sorteio por ciclo garante, e o que um sorteio
    independente nao garantiria.
    """
    sampler = _sampler()
    pares = Counter(
        frozenset(sampler.sortear("medio").pistas_alvo) for _ in range(42)
    )
    todos = {frozenset(par) for par in combinations(POOL_MEDIO, 2)}
    assert set(pares) == todos
    assert set(pares.values()) == {2}


def test_mesma_semente_reproduz_as_mesmas_fichas():
    sampler_a, sampler_b = _sampler(123), _sampler(123)
    a = [sampler_a.sortear(n) for n in ("facil", "medio", "dificil") * 5]
    b = [sampler_b.sortear(n) for n in ("facil", "medio", "dificil") * 5]
    assert a == b


def test_fichas_seguidas_do_mesmo_nivel_variam():
    sampler = _sampler()
    fichas = [sampler.sortear("medio") for _ in range(10)]
    assert len({f.nome_destinatario for f in fichas}) == 10
    assert len({f.angulo_pretexto for f in fichas}) > 1
    assert len({f.abertura for f in fichas}) > 1


def test_nomes_padrao_do_modelo_ficam_fora_do_sorteio():
    """'Joao', 'Maria' e 'Silva' eram os nomes que o modelo usava sozinho
    no piloto: fora do sorteio, um item que volte com eles denuncia que a
    ficha foi ignorada.
    """
    sampler = _sampler()
    palavras = {
        palavra
        for _ in range(200)
        for palavra in sampler.sortear("medio").nome_destinatario.split()
    }
    assert not palavras & {"João", "Joao", "Maria", "Silva"}


def test_dificuldade_fora_do_vocabulario_falha_alto():
    with pytest.raises(ValueError):
        _sampler().sortear("Médio")


def test_renderizar_ficha_traz_nome_pistas_e_acao():
    ficha = _sampler().sortear("medio")
    texto = renderizar_ficha(ficha)
    assert ficha.nome_destinatario in texto
    assert ficha.acao in texto
    for pista in ficha.pistas_alvo:
        assert f"`{pista.value}`" in texto


def test_renderizar_ficha_sem_nome_pede_saudacao_generica():
    texto = renderizar_ficha(_sampler().sortear("facil"))
    assert "saudação deve ser genérica" in texto


def test_renderizar_sem_ficha_devolve_instrucao_de_escolha_livre():
    assert "Nenhuma ficha" in renderizar_ficha(None)
