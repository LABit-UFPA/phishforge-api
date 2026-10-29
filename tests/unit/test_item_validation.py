"""Validacoes deterministicas pos-geracao (lotes-piloto de 26 e
27/10/2026): spans calculados no codigo e no campo certo, falso
`generic_greeting` com nome na saudacao, marcadores de template, remetente
sem e-mail, pistas de dominio sem dominio e assunto repetido no corpo.
"""

import pytest

from app.domain.models.cue import Cue, CueCode
from app.domain.models.link_ref import LinkRef
from app.domain.services.item_validation import (
    RelatorioValidacao,
    calcular_spans,
    converter_markdown,
    desembrulhar_assinatura_de_sistema,
    encontrar_disclaimer_de_simulacao,
    encontrar_dominios_caricatos,
    encontrar_dominios_reais,
    encontrar_instituicoes_reais,
    encontrar_links_invalidos,
    encontrar_marcadores,
    encontrar_nomes_de_instituicoes_reais,
    endereco_de_email,
    formula_proibida_no_assunto,
    limpar_contexto_fundido,
    localizar_evidencia,
    normalizar_assunto,
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


# ---- Teste local da versao do piloto 3 (27/10/2026) ----------------------

@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("Suporte Acadêmico <suporte@educacao.ufrj.br>", "ufrj"),
        ("bruno.oliveira@ufrj.edu.br", "ufrj"),
        ("Secretaria da UFPA informa", "ufpa"),
        ("Universidade Federal do Pará", "universidade federal do para"),
        ("a Universidade de São Paulo", "universidade de sao paulo"),
        ("Instituto Federal de Mato Grosso do Sul", "instituto federal de mato grosso do sul"),
        ("Atualize seu cadastro no Itaú", "itau"),
        ("Banco do Brasil", "banco do brasil"),
        ("https://bancodobrasil-seguro.com/login", "bancodobrasil"),
        ("acesse receita.gov.br/restituicao", "receita.gov.br"),
        ("Sua encomenda nos Correios", "correios"),
        ("avisos@claro.com.br", "claro.com.br"),
        ("Sua fatura TIM venceu", "TIM"),
        ("Portal Puc-Rio", "puc"),
        ("contato@univesp.edu.br", "univesp"),
    ],
)
def test_encontra_instituicao_real(texto, esperado):
    assert esperado in encontrar_instituicoes_reais(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "Secretaria Acadêmica <secretaria@unifloresta.edu.br>",
        "suporteuniversidade123@gmail.com",
        "Verifique sua caixa de entrada",
        "Claro, posso ajudar. Estamos ao vivo hoje.",
        "Oi, Maria! Tudo bem?",
        "Universidade Federal Nova Esperança",
        "Universidade Federal Brasileira",
        "empresas americanas e europeias",
        "a central telefônica da faculdade",
        "precisamos unir esforços",
        "o tim-tim da comemoração",
        "suporte@suportevivo.com.br",
        "envie pelo WhatsApp",
    ],
)
def test_nao_confunde_palavra_comum_ou_organizacao_ficticia(texto):
    assert encontrar_instituicoes_reais(texto) == []


def test_instituicoes_sem_repeticao_e_varios_textos():
    achados = encontrar_instituicoes_reais("UFRJ informa", "suporte@ufrj.br", None, "")
    assert achados == ["ufrj"]


@pytest.mark.parametrize(
    "assunto",
    [
        "Ação Necessária: atualize seus dados",
        "Protocolo #123456: Ação Necessária sobre o Portal do Estudante",
        "Atualizações do Portal do Estudante – Ação Necessária",
        "AÇÃO IMEDIATA NECESSÁRIA",
        "acao requerida no cadastro",
        "Ações necessárias para a matrícula",
    ],
)
def test_formula_proibida_em_qualquer_posicao_do_assunto(assunto):
    assert formula_proibida_no_assunto(assunto) is not None


@pytest.mark.parametrize(
    "assunto",
    [
        "Atualização necessária no cadastro",
        "Ações do semestre",
        "Sua ação foi registrada",
        "",
        None,
    ],
)
def test_assunto_sem_formula_proibida(assunto):
    assert formula_proibida_no_assunto(assunto) is None



# ---- Lote-piloto 3 (27/10/2026, 50 itens faceis) -------------------------

@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("noreply@universidade123.com", "universidade123.com"),
        ("Suporte <suporte@fake-portal.com>", "fake-portal.com"),
        ("http://donotclickhere.net/login", "donotclickhere.net"),
        ("acesse portal-falso.com.br", "portal-falso.com.br"),
        ("http://golpe-matricula.com", "golpe-matricula.com"),
        ("seguranca@phishing-test.org", "phishing-test.org"),
    ],
)
def test_encontra_dominio_caricato(texto, esperado):
    assert esperado in encontrar_dominios_caricatos(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "secretaria.unifloresta@gmail.com",
        "https://seguranca-antifraude.com/verificar",
        "http://antivirus-atualizacao.net",
        "Cuidado com golpes: nunca informe sua senha.",
        "Protocolo 12345 registrado",
        "portal.unifloresta.edu.br",
    ],
)
def test_dominio_realista_ou_texto_comum_nao_e_caricato(texto):
    assert encontrar_dominios_caricatos(texto) == []


def test_normalizar_assunto_ignora_caixa_acento_espaco_e_pontuacao_final():
    assert normalizar_assunto("Pendência  na MATRÍCULA!") == normalizar_assunto("pendencia na matricula")
    assert normalizar_assunto(None) == ""


def test_converter_markdown_tira_a_sintaxe_e_leva_o_destino_para_links():
    corpo = "Clique em [Regularizar Pagamento](http://pagamentos-uni.com/r) hoje."
    novo, links, convertidos, negritos = converter_markdown(corpo, [])

    assert novo == "Clique em Regularizar Pagamento hoje."
    assert links == [LinkRef(text="Regularizar Pagamento", href="http://pagamentos-uni.com/r")]
    assert (convertidos, negritos) == (1, 0)


def test_converter_markdown_nao_duplica_link_que_ja_esta_na_lista():
    existente = LinkRef(text="Portal", href="https://portal-uni.com")
    corpo = "Acesse [o portal](https://portal-uni.com) e [o guia](https://guia-uni.com)."
    novo, links, convertidos, _ = converter_markdown(corpo, [existente])

    assert novo == "Acesse o portal e o guia."
    assert links == [existente, LinkRef(text="o guia", href="https://guia-uni.com")]
    assert convertidos == 2


def test_converter_markdown_tira_negrito_e_preserva_texto_comum():
    novo, links, convertidos, negritos = converter_markdown(
        "Prazo: **sexta-feira**. Valor [R$ 50] e 2*3=6.", []
    )
    assert novo == "Prazo: sexta-feira. Valor [R$ 50] e 2*3=6."
    assert (links, convertidos, negritos) == ([], 0, 1)



def test_ficticia_conta_como_nome_de_exemplo():
    """O modelo levou ao pe da letra 'invente um nome ficticio'."""
    assert encontrar_marcadores("Universidade Fictícia informa") == ["Fictícia"]
    assert encontrar_marcadores("contato@universidadeficticia.com.br")
    assert encontrar_marcadores("Secretaria <universidadeficticia@gmail.com>")
    assert encontrar_marcadores("um caso fictício citado no artigo") == []


def test_limpar_contexto_fundido_tira_assinatura_real_e_marcadores():
    fundido = (
        "- Urgencia: prazo curto para regularizar a matricula.\n"
        "- Exemplo: o remetente imita a secretaria academica.\n"
        "[Seu Nome]\n"
        "Universidade Federal do Rio de Janeiro\n"
        "- Saphish: app gamificado [1] de conscientizacao."
    )

    limpo, removidos = limpar_contexto_fundido(fundido)

    assert "Rio de Janeiro" not in limpo and "[" not in limpo
    assert "- Urgencia: prazo curto para regularizar a matricula." in limpo
    assert "- Exemplo: o remetente imita a secretaria academica." in limpo
    assert "- Saphish: app gamificado  de conscientizacao." in limpo
    assert "Universidade Federal do Rio de Janeiro" in removidos
    assert "[Seu Nome]" in removidos


def test_limpar_contexto_fundido_sem_problema_nao_muda_nada():
    texto = "- Autoridade: e-mail se passa pela coordenacao do curso."
    assert limpar_contexto_fundido(texto) == (texto, [])


# ---- Correcoes de qualidade do piloto 5 -----------------------------------


def test_123456_conta_como_marcador():
    assert encontrar_marcadores("Protocolo #123456: regularize seu acesso.") == ["123456"]
    assert encontrar_marcadores("Pedido ORD123456 registrado") == ["123456"]


def test_numero_que_nao_e_o_marcador_exato_nao_conta():
    assert encontrar_marcadores("Protocolo 1234567 registrado") == []
    assert encontrar_marcadores("Protocolo 0123456 registrado") == []
    assert encontrar_marcadores("Protocolo 54321 registrado") == []


def test_nome_de_instituicao_real_no_corpo_nao_conta_para_a_versao_por_campo():
    """Piloto 5: o bloqueio disparava em qualquer mencao no corpo
    ('entregue pelos Correios' num cenario de logistica), nao so em
    personificacao. A versao por campo usada na checagem pos-geracao
    (`encontrar_nomes_de_instituicoes_reais`) nao deve achar nada aqui
    -- so a versao antiga, sem distinguir campo, continua achando.
    """
    corpo = "Sua encomenda será entregue pelos Correios na próxima semana."
    assert encontrar_nomes_de_instituicoes_reais(corpo) == ["correios"]
    assert encontrar_instituicoes_reais(corpo) == ["correios"]


def test_nome_de_instituicao_real_no_remetente_continua_contando():
    remetente = "Suporte Acadêmico <suporte@educacao.ufrj.br>"
    assert "ufrj" in encontrar_nomes_de_instituicoes_reais(remetente)


def test_dominio_real_conta_em_qualquer_campo_mesmo_sem_ser_remetente():
    """Diferente do nome, um dominio real escrito no CORPO ainda e
    personificacao -- nao ha 'mencao inocente' de um dominio.
    """
    corpo = "Para mais informações, acesse bb.com.br e confira o comunicado."
    assert "bb.com.br" in encontrar_dominios_reais(corpo)
    assert encontrar_nomes_de_instituicoes_reais(corpo) == []


def test_encontrar_dominios_reais_e_nomes_somados_reproduzem_a_versao_antiga():
    for texto in (
        "UFRJ informa", "suporte@ufrj.edu.br", "Universidade Federal do Pará",
        "Banco do Brasil", "https://bancodobrasil-seguro.com/login",
        "acesse receita.gov.br/restituicao", "Sua fatura TIM venceu",
    ):
        combinado = list(
            dict.fromkeys(
                encontrar_nomes_de_instituicoes_reais(texto) + encontrar_dominios_reais(texto)
            )
        )
        assert combinado == encontrar_instituicoes_reais(texto)


# --- disclaimer de "simulacao/conscientizacao" no corpo do e-mail ----------
# (achado da comparacao de modelos: o GPT-6 Luna assava o enquadramento
# educativo DENTRO do phishing, em 56% dos itens; trechos abaixo sao reais do
# relatorio comparacao_modelos_20261029_071858.json.)

@pytest.mark.parametrize(
    "trecho",
    [
        "esta atividade de conscientizacao simula uma notificacao",
        "SIMULAÇÃO DE CONSCIENTIZAÇÃO — NÃO É UMA COMUNICAÇÃO REAL DO BANCO",
        "A mensagem fictícia alegaria que a regularização...",
        "Material educativo: https://example.invalid/simulacao",
        "esta é uma simulação educativa de phishing. Não envie documentos reais.",
        "EXEMPLO DE TREINAMENTO — mensagem simulada para conscientização",
        "Para fins deste exemplo de conscientização, a regularização...",
        "Esse detalhe faz parte da simulação e deve ser verificado",
        "Esta mensagem é um exercício de conscientização em segurança",
    ],
)
def test_disclaimer_de_simulacao_e_detectado(trecho):
    assert encontrar_disclaimer_de_simulacao(trecho), trecho


def test_disclaimer_vazio_quando_email_e_limpo():
    # Phishing realista, sem auto-denuncia (exemplo real do Haiku, nota 3/4).
    corpo = (
        "Olá, Railson Pinheiro, sou da Secretaria de Registro Acadêmico da "
        "Universidade Grão Sul. Identificamos uma divergência no seu registro "
        "que impede a emissão do diploma. O protocolo de referência é GRS-2026-48217."
    )
    assert encontrar_disclaimer_de_simulacao(corpo) == []


@pytest.mark.parametrize(
    "pretexto_legitimo",
    [
        "Conclua seu treinamento obrigatório de integração até sexta-feira.",
        "O exercício fiscal de 2026 exige a atualização do seu cadastro.",
        "Segue o cronograma de treinamento da nova equipe de vendas.",
        # "phishing" sozinho NAO dispara (ate um phishing como isca pode cita-la;
        # um aviso de seguranca verdadeiro tambem) -- so o enquadramento
        # simulacao/conscientizacao conta.
        "Cuidado com tentativas de phishing: nunca compartilhe sua senha.",
        "Nossa equipe nunca pede senha por e-mail; desconfie de phishing.",
    ],
)
def test_pretexto_legitimo_nao_dispara_falso_positivo(pretexto_legitimo):
    # "treinamento"/"exercicio"/"phishing" sozinhos sao validos; so o
    # enquadramento educativo/de simulacao conta.
    assert encontrar_disclaimer_de_simulacao(pretexto_legitimo) == []


def test_disclaimer_ignora_acento_e_caixa():
    assert encontrar_disclaimer_de_simulacao("SIMULAÇÃO") == encontrar_disclaimer_de_simulacao("simulacao")
    assert encontrar_disclaimer_de_simulacao("Fictício") != []


def test_disclaimer_varre_varios_campos():
    achados = encontrar_disclaimer_de_simulacao(
        "Equipe de Conscientização <x@y.com>", "Assunto normal", "corpo normal"
    )
    assert achados  # pega no remetente


# ---------------------------------------------------------------------------
# Item 2 (cenario C): assinatura de "notificacao de sistema" entre colchetes.
# Das 5 falhas do Sonnet na comparacao, 4 eram isso: [UCRV], [SISTEMA ANR],
# [RMP], [ESM], [AVISO AUTOMATICO] -- rotulo de sistema, nao campo por preencher.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rotulo",
    ["[UCRV]", "[SISTEMA ANR]", "[SISTEMA CBR]", "[RMP]", "[ESM]",
     "[AVISO AUTOMÁTICO]", "[NOTIFICAÇÃO AUTOMÁTICA – CBR]"],
)
def test_assinatura_de_sistema_no_corpo_e_desembrulhada(rotulo):
    corpo = f"Prezado cliente,\n\nSua fatura venceu.\n\n{rotulo}"
    _, _, limpo, n = desembrulhar_assinatura_de_sistema(None, None, corpo)
    assert n == 1
    miolo = rotulo.strip("[]")
    assert miolo in limpo and rotulo not in limpo
    # E, desembrulhada, nao e mais marcador de template.
    assert encontrar_marcadores(limpo) == []


def test_assinatura_de_sistema_no_remetente_e_desembrulhada():
    rem = "[SISTEMA CBR] <sistema@cbr-documentos.com.br>"
    novo_rem, _, _, n = desembrulhar_assinatura_de_sistema(rem, None, "corpo")
    assert n == 1
    assert novo_rem == "SISTEMA CBR <sistema@cbr-documentos.com.br>"
    assert encontrar_marcadores(novo_rem) == []


def test_tag_de_sistema_no_inicio_do_assunto_e_desembrulhada():
    _, novo_ass, _, n = desembrulhar_assinatura_de_sistema(
        None, "[AVISO AUTOMÁTICO] Pendência no cadastro", "corpo"
    )
    assert n == 1
    assert novo_ass == "AVISO AUTOMÁTICO Pendência no cadastro"


def test_assinatura_com_traco_decorativo_antes():
    _, _, limpo, n = desembrulhar_assinatura_de_sistema(
        None, None, "Mensagem automática.\n— [SISTEMA ANR]\nNão responda."
    )
    assert n == 1
    assert "[SISTEMA ANR]" not in limpo and "SISTEMA ANR" in limpo


@pytest.mark.parametrize(
    "placeholder",
    ["[Nome do Estudante]", "[Seu Nome]", "[Informações de Contato]"],
)
def test_placeholder_de_preenchimento_nao_e_desembrulhado(placeholder):
    """Miolo com minuscula = campo por preencher, nao rotulo de sistema:
    fica entre colchetes e segue barrado por encontrar_marcadores."""
    corpo = f"Prezado(a) {placeholder},\n\nTexto."
    _, _, limpo, n = desembrulhar_assinatura_de_sistema(None, None, corpo)
    assert n == 0
    assert placeholder in limpo
    assert encontrar_marcadores(limpo)  # continua sendo marcador


def test_colchete_no_meio_da_frase_nao_e_desembrulhado():
    corpo = "Confirme em [PORTAL] agora para liberar o acesso."
    _, _, limpo, n = desembrulhar_assinatura_de_sistema(None, None, corpo)
    assert n == 0
    assert limpo == corpo  # so linha isolada / inicio de campo conta


# ---------------------------------------------------------------------------
# Item 3: validacao de links (TLD/dominio reservado, porta :0, sem dominio).
# Exemplos reais da comparacao: "cbr-documentos.example", "confiarnacional.com.br:0".
# ---------------------------------------------------------------------------


def _links(*hrefs):
    return [LinkRef(text="Acessar", href=h) for h in hrefs]


def test_tld_reservado_example_e_invalido():
    achados = encontrar_links_invalidos(_links("https://cbr-documentos.example/acesso"))
    assert len(achados) == 1
    assert achados[0][0] == "https://cbr-documentos.example/acesso"
    assert achados[0][1] == "tld_reservado"


@pytest.mark.parametrize("href", [
    "https://x.test/a", "http://y.invalid", "https://portal.localhost/login",
])
def test_outros_tlds_reservados_sao_invalidos(href):
    achados = encontrar_links_invalidos(_links(href))
    assert achados and achados[0][1] in {"tld_reservado", "sem_tld"}


def test_dominio_de_exemplo_classico_e_invalido():
    achados = encontrar_links_invalidos(_links("https://example.com/login", "http://example.org"))
    assert {m for _, m in achados} == {"dominio_de_exemplo"}


def test_porta_zero_e_invalida():
    achados = encontrar_links_invalidos(_links("https://confiarnacional.com.br:0/doc"))
    assert len(achados) == 1
    assert achados[0][1] == "porta_invalida"


@pytest.mark.parametrize("href", ["http://semponto", "https://", "", "nao-e-url"])
def test_href_sem_dominio_plausivel_e_invalido(href):
    achados = encontrar_links_invalidos(_links(href))
    assert achados  # algum motivo (vazio, sem_dominio, sem_tld)


@pytest.mark.parametrize("href", [
    "https://vallonta.com.br/login",
    "https://acesso.vallonta.com.br/portal?id=3",
    "http://portal.nortega.com.br:8443/x",
    "https://192.168.0.10/reset",  # IP cru e tecnica real, aceita
])
def test_links_plausiveis_nao_sao_rejeitados(href):
    assert encontrar_links_invalidos(_links(href)) == []


def test_example_no_meio_do_nome_nao_e_falso_positivo():
    # "example-corp.com" e "examples.com.br" sao dominios validos.
    assert encontrar_links_invalidos(_links("https://example-corp.com/x")) == []
    assert encontrar_links_invalidos(_links("https://examples.com.br/x")) == []


def test_lista_vazia_nada_a_corrigir():
    assert encontrar_links_invalidos([]) == []
    assert encontrar_links_invalidos(None) == []
