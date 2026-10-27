"""Validacoes deterministicas pos-geracao (lotes-piloto de 26 e
27/10/2026): spans calculados no codigo e no campo certo, falso
`generic_greeting` com nome na saudacao, marcadores de template, remetente
sem e-mail, pistas de dominio sem dominio e assunto repetido no corpo.
"""

from app.domain.models.cue import Cue, CueCode
from app.domain.services.item_validation import (
    RelatorioValidacao,
    calcular_spans,
    encontrar_marcadores,
    endereco_de_email,
    localizar_evidencia,
    registrar_aderencia,
    remover_assunto_repetido,
    remover_pistas_de_dominio_sem_dominio,
    remover_saudacao_generica_falsa,
)

CONTEUDO = (
    "Prezada Larissa Monteiro,\n\n"
    "Identificamos uma pendência no seu cadastro. Regularize até sexta-feira "
    "para evitar o bloqueio da sua matrícula."
)
CAMPOS = {"conteudo": CONTEUDO}


def test_span_e_calculado_a_partir_da_evidencia_literal():
    evidencia = "Regularize até sexta-feira"
    cues = calcular_spans(CAMPOS, [Cue(code=CueCode.URGENCY, evidencia=evidencia)])
    inicio = CONTEUDO.index(evidencia)
    assert (cues[0].span_start, cues[0].span_end) == (inicio, inicio + len(evidencia))


def test_span_informado_errado_pelo_llm_e_substituido_pelo_calculado():
    evidencia = "evitar o bloqueio"
    cue = Cue(code=CueCode.URGENCY, evidencia=evidencia, span_start=0, span_end=3)
    resultado = calcular_spans(CAMPOS, [cue])[0]
    assert CONTEUDO[resultado.span_start : resultado.span_end] == evidencia


def test_evidencia_entre_aspas_ainda_e_localizada():
    resultado = calcular_spans(
        CAMPOS, [Cue(code=CueCode.URGENCY, evidencia='"Regularize até sexta-feira"')]
    )[0]
    assert resultado.evidencia == "Regularize até sexta-feira"
    assert CONTEUDO[resultado.span_start : resultado.span_end] == resultado.evidencia


def test_evidencia_nao_literal_fica_sem_span_e_vai_para_o_relatorio():
    relatorio = RelatorioValidacao()
    resultado = calcular_spans(
        CAMPOS,
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


def test_qualquer_colchete_e_marcador_inclusive_os_do_piloto_2():
    """'[Informacoes de Contato]' passou pelo filtro antigo, que so
    reconhecia colchetes comecando com palavras como 'nome' ou 'data'.
    """
    achados = encontrar_marcadores(
        "Fale conosco: [Informações de Contato]", "[Nome da Universidade]"
    )
    assert achados == ["[Informações de Contato]", "[Nome da Universidade]"]


def test_colchete_com_texto_de_link_ou_sintaxe_de_link_nao_e_marcador():
    assert encontrar_marcadores(
        "Acesse [Portal do Aluno] para regularizar.",
        "Veja [aqui](https://portal.univ.test).",
        textos_de_link=["Portal do Aluno"],
    ) == []


def test_nomes_e_dominios_de_exemplo_sao_marcadores():
    achados = encontrar_marcadores(
        "Secretaria da Universidade Exemplo",
        "suporte@universidade-exemplo.edu.br",
        "Atenciosamente, Fulano de Tal",
    )
    assert "Exemplo" in achados
    assert "universidade-exemplo.edu.br" in achados
    assert "Fulano" in achados


def test_por_exemplo_em_minuscula_nao_e_marcador():
    assert encontrar_marcadores("Envie, por exemplo, o comprovante de matrícula.") == []


def test_sem_nomes_genericos_so_colchetes_contam():
    assert encontrar_marcadores("aluno@example.com", nomes_genericos=False) == []
    assert encontrar_marcadores("[Destinatário]", nomes_genericos=False) == ["[Destinatário]"]


def test_endereco_de_email_aceita_nome_de_exibicao():
    assert endereco_de_email("Secretaria <secretaria@uni.edu.br>") == "secretaria@uni.edu.br"
    assert endereco_de_email("Maria Silva, Coordenadora de Matrícula") is None
    assert endereco_de_email(None) is None


def test_span_no_remetente_registra_o_campo():
    """Piloto 2: pista no remetente ficava sem span, porque a busca so
    olhava o corpo.
    """
    campos = {
        "conteudo": CONTEUDO,
        "assunto": "Pendência no cadastro",
        "remetente": "Secretaria <secretaria@univers1dade.com>",
    }
    cue = Cue(code=CueCode.TYPOSQUAT, evidencia="univers1dade.com", campo="remetente")
    resultado = calcular_spans(campos, [cue])[0]
    assert resultado.campo == "remetente"
    assert campos["remetente"][resultado.span_start : resultado.span_end] == "univers1dade.com"


def test_campo_declarado_errado_e_corrigido_pela_busca():
    campos = {"conteudo": CONTEUDO, "assunto": "Último aviso: pendência"}
    cue = Cue(code=CueCode.URGENCY, evidencia="Último aviso", campo="conteudo")
    resultado = calcular_spans(campos, [cue])[0]
    assert resultado.campo == "assunto"
    assert resultado.span_start == 0


def test_pista_de_dominio_sem_dominio_e_removida():
    """Casos do piloto 2: sender_domain_mismatch com evidencia que e um
    nome de setor; typosquat com evidencia 'Universidade Exemplo'.
    """
    relatorio = RelatorioValidacao()
    cues = [
        Cue(code=CueCode.SENDER_DOMAIN_MISMATCH, evidencia="Escritório de Administração Acadêmica"),
        Cue(code=CueCode.TYPOSQUAT, evidencia="Universidade Exemplo"),
        Cue(code=CueCode.TYPOSQUAT, evidencia="secretaria@univers1dade.com"),
        Cue(code=CueCode.URGENCY, evidencia="até sexta-feira"),
    ]
    resultado = remover_pistas_de_dominio_sem_dominio(cues, relatorio)
    assert [c.evidencia for c in resultado] == ["secretaria@univers1dade.com", "até sexta-feira"]
    assert [r.motivo for r in relatorio.pistas_removidas] == ["pista_de_dominio_sem_dominio"] * 2


def test_assunto_repetido_na_primeira_linha_e_removido():
    corpo = "Ação Necessária: Divergência em Seus Dados\n\nPrezada Larissa,\n\nTexto."
    novo, removido = remover_assunto_repetido("Ação Necessária: Divergência em Seus Dados", corpo)
    assert removido
    assert novo == "Prezada Larissa,\n\nTexto."


def test_assunto_repetido_com_prefixo_assunto_tambem_sai():
    novo, removido = remover_assunto_repetido(
        "Pendência no cadastro", "Assunto: Pendência no cadastro\nPrezada Larissa,"
    )
    assert removido and novo == "Prezada Larissa,"


def test_corpo_que_nao_repete_o_assunto_fica_igual():
    novo, removido = remover_assunto_repetido("Pendência no cadastro", CONTEUDO)
    assert not removido and novo == CONTEUDO


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
