"""Validacoes deterministicas pos-geracao (lote-piloto de 26/10/2026):
spans calculados no codigo, falso `generic_greeting` com nome na
saudacao e marcador de template no texto.
"""

from app.domain.models.cue import Cue, CueCode
from app.domain.services.item_validation import (
    RelatorioValidacao,
    calcular_spans,
    encontrar_marcadores,
    localizar_evidencia,
    registrar_aderencia,
    remover_saudacao_generica_falsa,
)

CONTEUDO = (
    "Prezada Larissa Monteiro,\n\n"
    "Identificamos uma pendência no seu cadastro. Regularize até sexta-feira "
    "para evitar o bloqueio da sua matrícula."
)


def test_span_e_calculado_a_partir_da_evidencia_literal():
    evidencia = "Regularize até sexta-feira"
    cues = calcular_spans(CONTEUDO, [Cue(code=CueCode.URGENCY, evidencia=evidencia)])
    inicio = CONTEUDO.index(evidencia)
    assert (cues[0].span_start, cues[0].span_end) == (inicio, inicio + len(evidencia))


def test_span_informado_errado_pelo_llm_e_substituido_pelo_calculado():
    evidencia = "evitar o bloqueio"
    cue = Cue(code=CueCode.URGENCY, evidencia=evidencia, span_start=0, span_end=3)
    resultado = calcular_spans(CONTEUDO, [cue])[0]
    assert CONTEUDO[resultado.span_start : resultado.span_end] == evidencia


def test_evidencia_entre_aspas_ainda_e_localizada():
    resultado = calcular_spans(
        CONTEUDO, [Cue(code=CueCode.URGENCY, evidencia='"Regularize até sexta-feira"')]
    )[0]
    assert resultado.evidencia == "Regularize até sexta-feira"
    assert CONTEUDO[resultado.span_start : resultado.span_end] == resultado.evidencia


def test_evidencia_nao_literal_fica_sem_span_e_vai_para_o_relatorio():
    relatorio = RelatorioValidacao()
    resultado = calcular_spans(
        CONTEUDO,
        [Cue(code=CueCode.AUTHORITY, evidencia="ordem da reitoria", span_start=1, span_end=5)],
        relatorio,
    )
    # A pista continua: o codigo pode estar certo mesmo sem citacao literal.
    assert resultado[0].code == CueCode.AUTHORITY
    assert resultado[0].span_start is None and resultado[0].span_end is None
    assert relatorio.evidencias_nao_literais == [CueCode.AUTHORITY]


def test_localizar_evidencia_vazia_devolve_none():
    assert localizar_evidencia(CONTEUDO, "   ") is None


def test_generic_greeting_com_nome_da_ficha_na_saudacao_e_removido():
    """O falso positivo do piloto: 'Prezado Joao Silva' anotado como
    saudacao generica.
    """
    relatorio = RelatorioValidacao()
    cues = [
        Cue(code=CueCode.GENERIC_GREETING, evidencia="Prezada Larissa Monteiro,"),
        Cue(code=CueCode.URGENCY, evidencia="Regularize até sexta-feira"),
    ]
    resultado = remover_saudacao_generica_falsa(CONTEUDO, cues, "Larissa Monteiro", relatorio)
    assert [c.code for c in resultado] == [CueCode.URGENCY]
    assert relatorio.pistas_removidas[0].code == CueCode.GENERIC_GREETING
    assert relatorio.pistas_removidas[0].motivo == "saudacao_com_nome_do_destinatario"


def test_generic_greeting_de_verdade_e_mantido():
    conteudo = "Prezado(a) estudante,\n\nSua matrícula tem uma pendência."
    cues = [Cue(code=CueCode.GENERIC_GREETING, evidencia="Prezado(a) estudante,")]
    resultado = remover_saudacao_generica_falsa(conteudo, cues, "Larissa Monteiro")
    assert [c.code for c in resultado] == [CueCode.GENERIC_GREETING]


def test_sem_nome_conhecido_nada_e_removido():
    cues = [Cue(code=CueCode.GENERIC_GREETING, evidencia="Prezada Larissa Monteiro,")]
    assert remover_saudacao_generica_falsa(CONTEUDO, cues, None) == cues


def test_nome_que_e_prefixo_de_outra_palavra_nao_conta_como_nome():
    """'Ana' nao pode casar com 'Analista' na saudacao."""
    conteudo = "Prezado Analista,\n\nHá uma pendência."
    cues = [Cue(code=CueCode.GENERIC_GREETING, evidencia="Prezado Analista,")]
    resultado = remover_saudacao_generica_falsa(conteudo, cues, "Ana Costa")
    assert [c.code for c in resultado] == [CueCode.GENERIC_GREETING]


def test_marcadores_de_template_sao_encontrados():
    achados = encontrar_marcadores(
        "Prezado(a) [Nome do Estudante],", "Acesse: [link]", "Olá {nome}", None
    )
    assert achados == ["[Nome do Estudante]", "[link]", "{nome}"]


def test_texto_ancora_de_link_nao_e_marcador():
    assert encontrar_marcadores(
        "[Clique aqui] para acessar.", "[Acessar o Portal do Aluno]", "[Nomeação]"
    ) == []


def test_aderencia_registra_pistas_ausentes_e_fora_do_alvo():
    relatorio = RelatorioValidacao()
    cues = [
        Cue(code=CueCode.URGENCY, evidencia="x"),
        Cue(code=CueCode.SCARCITY, evidencia="y"),
    ]
    registrar_aderencia(cues, [CueCode.URGENCY, CueCode.AUTHORITY], relatorio)
    assert relatorio.pistas_alvo_ausentes == [CueCode.AUTHORITY]
    assert relatorio.pistas_fora_do_alvo == [CueCode.SCARCITY]


def test_sem_pistas_alvo_aderencia_nao_registra_nada():
    relatorio = RelatorioValidacao()
    registrar_aderencia([Cue(code=CueCode.URGENCY, evidencia="x")], [], relatorio)
    assert relatorio.pistas_alvo_ausentes == []
    assert relatorio.pistas_fora_do_alvo == []
