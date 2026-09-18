"""Teste da logica pura do script de checagem anti-atalho (issue #3):
deteccao de separacao perfeita e as heuristicas de saudacao/prazo.
Nao toca banco -- isso e testado manualmente contra um lote real, ver
nota no proprio script sobre o motivo de nao ter sido rodado neste PR.
"""

from script.checar_atalho_estrutural import (
    _bucket_tamanho,
    _tem_prazo,
    _tem_saudacao_personalizada,
    _tem_separacao_perfeita,
)


def test_deteta_separacao_perfeita_quando_uma_combinacao_e_exclusiva():
    tabela = {
        True: {"malicioso": 10, "legitimo": 0},
        False: {"malicioso": 0, "legitimo": 10},
    }
    assert _tem_separacao_perfeita(tabela) is True


def test_nao_deteta_separacao_quando_as_duas_classes_se_misturam():
    tabela = {
        True: {"malicioso": 6, "legitimo": 4},
        False: {"malicioso": 4, "legitimo": 6},
    }
    assert _tem_separacao_perfeita(tabela) is False


def test_nao_deteta_separacao_falsa_quando_so_ha_uma_classe_no_lote():
    """Um lote 100% malicioso "separaria" qualquer variavel
    trivialmente -- isso nao e um atalho real, e ausencia de item
    legitimo no lote. A funcao nao deve alarmar falso neste caso.
    """
    tabela = {
        True: {"malicioso": 10, "legitimo": 0},
        False: {"malicioso": 5, "legitimo": 0},
    }
    assert _tem_separacao_perfeita(tabela) is False


def test_bucket_tamanho():
    assert _bucket_tamanho("a" * 100) == "curto(<500)"
    assert _bucket_tamanho("a" * 1000) == "medio(500-1500)"
    assert _bucket_tamanho("a" * 2000) == "longo(>1500)"


def test_tem_prazo_detecta_urgencia_e_data():
    assert _tem_prazo("Responda em até 24 horas") is True
    assert _tem_prazo("O prazo final é sexta-feira") is True
    assert _tem_prazo("Segue o relatório mensal em anexo") is False


def test_saudacao_generica_nao_conta_como_personalizada():
    assert _tem_saudacao_personalizada("Prezado cliente, informamos que...") is False
    assert _tem_saudacao_personalizada("Olá usuário, seu pedido...") is False


def test_saudacao_com_nome_conta_como_personalizada():
    assert _tem_saudacao_personalizada("Prezado João, sua avaliação de desempenho...") is True


def test_ausencia_de_saudacao_nao_conta_como_personalizada():
    assert _tem_saudacao_personalizada("Segue o relatório mensal em anexo, sem saudação.") is False
