"""ResponseGenerator com a ficha de variacao e as validacoes do
lote-piloto de 26/10/2026. Mesmo padrao de
test_response_generator_cues.py: ResponseGenerator real (a construcao
nao faz chamada de rede) com a chain substituida por um espiao.
"""

import random
from string import Formatter

import pytest

from app.domain.models.cue import DEFINICOES_OPERACIONAIS, Cue, CueCode
from app.domain.models.generated_item_draft import GeneratedItemDraft, ValidatedItemDraft
from app.domain.models.instituicao_ficticia import InstituicaoFicticia
from app.domain.models.link_ref import LinkRef
from app.domain.models.phish_scale import PremiseAlignment
from app.domain.models.phishing_email import PhishingEmail
from app.domain.models.variation_spec import VariationSpec
from app.domain.services.response_generator import (
    MAX_REGENERACOES_POR_MARCADOR,
    AnotacaoCega,
    ItemInvalidoError,
    PistaAnotada,
    ResponseGenerator,
)
from app.domain.services.variation_sampler import VariationSampler

VARIAVEIS_DO_PROMPT_DE_EMAIL = {"context", "difficulty", "relevant_docs", "variacao", "data_atual"}

_INSTITUICAO_DE_TESTE = InstituicaoFicticia(
    nome_base="Vallonta", sigla="VAL", dominio_oficial="vallonta.com.br"
)


class _ChainSequencia:
    """Devolve os drafts na ordem dada, um por chamada, e registra a
    entrada de cada chamada.
    """

    def __init__(self, *drafts: GeneratedItemDraft):
        self._drafts = list(drafts)
        self.entradas: list[dict] = []

    async def ainvoke(self, args):
        self.entradas.append(args)
        return self._drafts[min(len(self.entradas), len(self._drafts)) - 1]


def _draft(
    conteudo: str,
    cues=None,
    receptor="larissa@unifloresta.edu.br",
    premise="medio",
    remetente="Secretaria Acadêmica <secretaria@unifloresta.edu.br>",
    assunto="Pendência no cadastro",
):
    return GeneratedItemDraft(
        receptor=receptor,
        remetente=remetente,
        assunto=assunto,
        conteudo=conteudo,
        explicacao="explicacao",
        categoria="academico",
        links=[],
        cues=cues or [],
        premise_alignment=premise,
    )


def _ficha_medio(nome="Larissa Monteiro", pistas=(CueCode.URGENCY, CueCode.AUTHORITY)):
    return VariationSpec(
        instituicao=_INSTITUICAO_DE_TESTE,
        nome_destinatario=nome,
        endereco_destinatario=(
            f"{nome.lower().replace(' ', '.')}@{_INSTITUICAO_DE_TESTE.dominio_oficial}"
            if nome
            else f"contato@{_INSTITUICAO_DE_TESTE.dominio_oficial}"
        ),
        assinatura="uma pessoa com nome e cargo",
        nome_remetente="Otávio Brito",
        endereco_remetente="use um domínio plausível da própria organização",
        estilo_assunto="em forma de pergunta",
        angulo_pretexto="um documento faltando",
        acao="abrir e preencher um anexo",
        tom="formal",
        estrutura="dois parágrafos",
        abertura="direto pelo assunto",
        pistas_alvo=list(pistas),
    )


def _generator(chain, is_malicious=True) -> ResponseGenerator:
    generator = ResponseGenerator(api_key="sk-nao-usada-neste-teste")
    if is_malicious:
        generator.chain = chain
    else:
        generator.legitimate_chain = chain
    return generator


def _variaveis(template: str) -> set:
    return {campo for _, campo, _, _ in Formatter().parse(template) if campo}


def test_prompts_de_email_pedem_exatamente_as_quatro_variaveis():
    """Uma chave a mais ou a menos no template quebra a geracao em
    runtime (KeyError no .format do PromptTemplate) -- aqui quebra antes.
    """
    generator = ResponseGenerator(api_key="sk-nao-usada-neste-teste")
    assert _variaveis(generator.prompt_template.template) == VARIAVEIS_DO_PROMPT_DE_EMAIL
    assert _variaveis(generator.legitimate_prompt_template.template) == VARIAVEIS_DO_PROMPT_DE_EMAIL


def test_prompt_de_phishing_amarra_as_pistas_do_nivel_a_ficha():
    template = ResponseGenerator(api_key="sk-nao-usada-neste-teste").prompt_template.template
    assert "FICHA DO ITEM" in template
    assert "EXATAMENTE as 2 pistas-alvo da FICHA DO ITEM" in template
    # A meta de contagem sem alvo foi o que gerou o generic_greeting falso.
    assert "mire em EXATAMENTE 2 pistas" not in template
    # As posicoes deixaram de ser pedidas ao LLM.
    assert "Deixe `span_start`/`span_end` como null" in template


async def test_ficha_entra_renderizada_na_chamada_do_llm():
    chain = _ChainSequencia(_draft("Prezada Larissa Monteiro,\n\nTexto."))
    ficha = _ficha_medio()

    await _generator(chain).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=ficha
    )

    texto = chain.entradas[0]["variacao"]
    assert "Larissa Monteiro" in texto
    assert "`urgency`" in texto and "`authority`" in texto


async def test_sem_ficha_o_prompt_recebe_instrucao_de_escolha_livre():
    chain = _ChainSequencia(_draft("Texto."))
    await _generator(chain).generate_response(difficulty="medio", context="ctx", relevant_docs="docs")
    assert "Nenhuma ficha" in chain.entradas[0]["variacao"]


async def test_span_e_calculado_mesmo_quando_o_llm_nao_informa():
    conteudo = "Prezada Larissa Monteiro,\n\nRegularize até sexta-feira."
    evidencia = "Regularize até sexta-feira"
    chain = _ChainSequencia(_draft(conteudo, [Cue(code=CueCode.URGENCY, evidencia=evidencia)]))

    resultado = await _generator(chain).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )

    cue = resultado.cues[0]
    assert conteudo[cue.span_start : cue.span_end] == evidencia


async def test_generic_greeting_com_nome_da_ficha_sai_e_fica_no_relatorio():
    conteudo = "Prezada Larissa Monteiro,\n\nRegularize até sexta-feira."
    cues = [
        Cue(code=CueCode.GENERIC_GREETING, evidencia="Prezada Larissa Monteiro,"),
        Cue(code=CueCode.URGENCY, evidencia="Regularize até sexta-feira"),
    ]
    chain = _ChainSequencia(_draft(conteudo, cues))

    resultado = await _generator(chain).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )

    assert [c.code for c in resultado.cues] == [CueCode.URGENCY]
    removidas = resultado.validacao["pistas_removidas"]
    assert removidas[0]["code"] == "generic_greeting"
    # cue_count do Phish Scale conta o que sobrou, nao o que o LLM anotou.
    assert resultado.phish_scale.cue_count == 1
    # Aderencia: authority era alvo e nao foi anotada.
    assert resultado.validacao["pistas_alvo_ausentes"] == ["authority"]


async def test_marcador_de_template_faz_gerar_de_novo():
    com_marcador = _draft("Prezado(a) [Nome do Estudante],\n\nTexto.")
    limpo = _draft("Prezada Larissa Monteiro,\n\nTexto.")
    chain = _ChainSequencia(com_marcador, limpo)

    resultado = await _generator(chain).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )

    assert len(chain.entradas) == 2
    assert resultado.conteudo == limpo.conteudo
    assert resultado.validacao["regeneracoes_por_marcador"] == 1


async def test_marcador_no_receptor_tambem_conta():
    chain = _ChainSequencia(
        _draft("Texto.", receptor="[Nome do Estudante] <aluno@x.test>"), _draft("Texto.")
    )
    await _generator(chain).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )
    assert len(chain.entradas) == 2


async def test_marcador_que_persiste_vira_item_invalido():
    chain = _ChainSequencia(_draft("Olá [Nome do Estudante], texto."))

    with pytest.raises(ItemInvalidoError):
        await _generator(chain).generate_response(
            difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
        )
    assert len(chain.entradas) == MAX_REGENERACOES_POR_MARCADOR + 1


async def test_devolve_validated_draft_que_leva_o_relatorio_ate_o_item():
    chain = _ChainSequencia(_draft("Prezada Larissa Monteiro,\n\nTexto."))
    resultado = await _generator(chain).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )
    assert isinstance(resultado, ValidatedItemDraft)

    item = PhishingEmail(**resultado.model_dump(), nivel="medio", is_malicious=True)
    assert item.validacao is not None
    assert item.validacao["regeneracoes_por_marcador"] == 0


async def test_item_legitimo_registra_pistas_removidas_com_motivo():
    chain = _ChainSequencia(
        _draft("Prezada Larissa,\n\nTexto.", [Cue(code=CueCode.URGENCY, evidencia="Texto.")])
    )
    ficha = VariationSampler(random.Random(1)).sortear("medio", is_malicious=False)

    resultado = await _generator(chain, is_malicious=False).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", is_malicious=False, variacao=ficha
    )

    assert resultado.cues == []
    assert resultado.validacao["pistas_removidas"][0]["motivo"] == "item_legitimo"
    # Sem pistas-alvo, nao ha aderencia a medir.
    assert resultado.validacao["pistas_alvo_ausentes"] == []


# ---------------------------------------------------------------------------
# Lote-piloto 2 (27/10/2026)
# ---------------------------------------------------------------------------


class _AnotadorEspiao:
    """Substitui a chain do anotador as cegas: registra a entrada e
    devolve a anotacao dada.
    """

    def __init__(self, anotacao: AnotacaoCega):
        self._anotacao = anotacao
        self.entradas: list[dict] = []

    async def ainvoke(self, args):
        self.entradas.append(args)
        return self._anotacao


def _generator_cego(chain, anotacao: AnotacaoCega, is_malicious=True):
    generator = ResponseGenerator(api_key="sk-nao-usada-neste-teste", anotacao_cega=True)
    if is_malicious:
        generator.chain = chain
    else:
        generator.legitimate_chain = chain
    generator.annotation_chain = _AnotadorEspiao(anotacao)
    return generator


def test_prompts_de_email_trazem_as_regras_de_forma():
    generator = ResponseGenerator(api_key="sk-nao-usada-neste-teste")
    for template in (generator.prompt_template.template, generator.legitimate_prompt_template.template):
        assert "REGRAS DE FORMA" in template
        assert "Ação Necessária" in template
        assert "em nenhuma parte do assunto" in template
        assert "instituição real" in template
        assert "Se o cenário não dá o nome" not in template
        assert "`receptor` é SEMPRE o endereço de e-mail" in template
        assert "sem Markdown" in template
        assert "empresa123" not in template
        # Piloto 5: nao pede mais ao LLM para inventar a identidade --
        # ela ja vem pronta na ficha (nome-base, sigla, dominio).
        assert "invente um nome fictício" not in template
        assert "nome-base" in template
        assert "Data de hoje" in template
        assert "'123456'" in template


def test_prompt_do_anotador_usa_as_definicoes_dos_especialistas_e_nao_ve_a_ficha():
    generator = ResponseGenerator(api_key="sk-nao-usada-neste-teste")
    template = generator.annotation_prompt_template.template
    assert _variaveis(template) == {
        "cenario", "remetente", "receptor", "assunto", "conteudo", "links"
    }
    assert DEFINICOES_OPERACIONAIS[CueCode.SCARCITY] in template
    assert "FICHA" not in template and "{difficulty}" not in template


async def test_anotacao_cega_substitui_pistas_e_premissa_do_gerador():
    """O gerador anotou o alvo (urgency + authority) e premissa alta; o
    anotador as cegas so encontrou urgency, com premissa media -- e o que
    vale, e o que o gerador declarou fica no relatorio.
    """
    conteudo = "Prezada Larissa Monteiro,\n\nRegularize até sexta-feira."
    gerado = _draft(
        conteudo,
        [
            Cue(code=CueCode.URGENCY, evidencia="Regularize até sexta-feira"),
            Cue(code=CueCode.AUTHORITY, evidencia="Reitoria"),
        ],
        premise="alto",
    )
    anotacao = AnotacaoCega(
        pistas=[PistaAnotada(code=CueCode.URGENCY, campo="conteudo", evidencia="Regularize até sexta-feira")],
        premise_alignment="medio",
    )
    generator = _generator_cego(_ChainSequencia(gerado), anotacao)

    resultado = await generator.generate_response(
        difficulty="medio", context="cenario X", relevant_docs="docs", variacao=_ficha_medio()
    )

    assert [c.code for c in resultado.cues] == [CueCode.URGENCY]
    assert resultado.cues[0].campo == "conteudo"
    assert resultado.premise_alignment == PremiseAlignment.MEDIO
    assert resultado.phish_scale.cue_count == 1
    v = resultado.validacao
    assert v["anotacao_cega"] is True
    assert v["cues_autodeclaradas"] == ["urgency", "authority"]
    assert v["premise_alignment_autodeclarado"] == "alto"
    assert v["pistas_alvo_ausentes"] == ["authority"]

    entrada = generator.annotation_chain.entradas[0]
    assert entrada["cenario"] == "cenario X"
    assert entrada["conteudo"] == conteudo
    # Nada da ficha nem do nivel chega ao anotador.
    assert set(entrada) == {"cenario", "remetente", "receptor", "assunto", "conteudo", "links"}
    assert entrada["links"] == "(nenhum)"


async def test_anotacao_cega_no_remetente_tem_span_no_remetente():
    remetente = "Secretaria <secretaria@unifl0resta.edu.br>"
    gerado = _draft("Prezada Larissa Monteiro,\n\nTexto.", remetente=remetente)
    anotacao = AnotacaoCega(
        pistas=[PistaAnotada(code=CueCode.TYPOSQUAT, campo="remetente", evidencia="unifl0resta.edu.br")],
        premise_alignment="alto",
    )
    resultado = await _generator_cego(_ChainSequencia(gerado), anotacao).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )
    cue = resultado.cues[0]
    assert cue.campo == "remetente"
    assert remetente[cue.span_start : cue.span_end] == "unifl0resta.edu.br"


async def test_item_legitimo_nao_passa_pelo_anotador():
    gerado = _draft("Prezada Larissa,\n\nTexto.", premise=None)
    ficha = VariationSampler(random.Random(1)).sortear("medio", is_malicious=False)
    generator = _generator_cego(
        _ChainSequencia(gerado), AnotacaoCega(premise_alignment="alto"), is_malicious=False
    )
    resultado = await generator.generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", is_malicious=False, variacao=ficha
    )
    assert generator.annotation_chain.entradas == []
    assert resultado.cues == [] and resultado.phish_scale is None
    assert resultado.target_cues is None


async def test_remetente_sem_email_faz_gerar_de_novo():
    """Piloto 2: 4 de 9 remetentes eram nomes, sem endereco."""
    sem_email = _draft("Texto.", remetente="Maria Silva, Coordenadora de Matrícula")
    chain = _ChainSequencia(sem_email, _draft("Texto."))

    resultado = await _generator(chain).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )

    assert len(chain.entradas) == 2
    assert resultado.validacao["regeneracoes_por_remetente"] == 1


async def test_regeneracao_usa_ficha_nova_e_o_draft_devolve_a_usada():
    """Piloto 2: com a mesma ficha, o item com '[Nome da Universidade]'
    repetiu o marcador nas 2 regeneracoes.
    """
    chain = _ChainSequencia(_draft("Olá, [Nome da Universidade] informa."), _draft("Texto."))
    primeira = _ficha_medio(nome="Larissa Monteiro")
    segunda = _ficha_medio(nome="Otávio Brito", pistas=(CueCode.SCARCITY, CueCode.TYPOSQUAT))

    resultado = await _generator(chain).generate_response(
        difficulty="medio",
        context="ctx",
        relevant_docs="docs",
        variacao=primeira,
        sortear_variacao=lambda: segunda,
    )

    assert "Larissa Monteiro" in chain.entradas[0]["variacao"]
    assert "Otávio Brito" in chain.entradas[1]["variacao"]
    assert resultado.target_cues == [CueCode.SCARCITY, CueCode.TYPOSQUAT]
    assert resultado.variation_spec["nome_destinatario"] == "Otávio Brito"
    assert resultado.validacao["regeneracoes_por_marcador"] == 1


async def test_universidade_exemplo_faz_gerar_de_novo():
    chain = _ChainSequencia(_draft("Secretaria da Universidade Exemplo."), _draft("Texto."))
    await _generator(chain).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )
    assert len(chain.entradas) == 2


async def test_assunto_repetido_no_corpo_e_removido():
    assunto = "Divergência em Seus Dados"
    gerado = _draft(f"{assunto}\n\nPrezada Larissa Monteiro,\n\nTexto.", assunto=assunto)

    resultado = await _generator(_ChainSequencia(gerado)).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )

    assert resultado.conteudo == "Prezada Larissa Monteiro,\n\nTexto."
    assert resultado.validacao["assunto_removido_do_corpo"] is True


async def test_pista_de_dominio_sem_dominio_sai_do_item():
    gerado = _draft(
        "Prezada Larissa Monteiro,\n\nEscritório de Administração Acadêmica",
        [Cue(code=CueCode.SENDER_DOMAIN_MISMATCH, evidencia="Escritório de Administração Acadêmica")],
    )
    resultado = await _generator(_ChainSequencia(gerado)).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )
    assert resultado.cues == []
    assert resultado.validacao["pistas_removidas"][0]["motivo"] == "pista_de_dominio_sem_dominio"


async def test_instituicao_real_no_remetente_faz_gerar_de_novo():
    """Teste da versao do piloto 3: dominios da UFRJ num cenario que so
    dizia 'universidade federal brasileira'.
    """
    real = _draft("Texto.", remetente="Suporte Acadêmico <suporte@educacao.ufrj.br>")
    chain = _ChainSequencia(real, _draft("Texto."))

    resultado = await _generator(chain).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )

    assert len(chain.entradas) == 2
    assert resultado.validacao["regeneracoes_por_instituicao_real"] == 1
    assert "ufrj" not in resultado.remetente


async def test_instituicao_real_no_link_tambem_conta():
    real = _draft("Texto.")
    real.links = [LinkRef(text="Portal do Aluno", href="https://portal.usp.br/login")]
    chain = _ChainSequencia(real, _draft("Texto."))

    await _generator(chain).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )

    assert len(chain.entradas) == 2


async def test_acao_necessaria_no_meio_do_assunto_faz_gerar_de_novo():
    """O piloto 3 local teve 'Protocolo #123456: Ação Necessária sobre...':
    a proibicao so valia para o inicio do assunto.
    """
    formula = _draft("Texto.", assunto="Protocolo #4471: Ação Necessária sobre o Portal")
    chain = _ChainSequencia(formula, _draft("Texto."))

    resultado = await _generator(chain).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )

    assert len(chain.entradas) == 2
    assert resultado.validacao["regeneracoes_por_assunto"] == 1
    assert resultado.assunto == "Pendência no cadastro"


async def test_regras_de_forma_valem_para_o_item_legitimo():
    """Paridade: se so o phishing fosse barrado, 'Acao Necessaria' ou
    instituicao real virariam atalho para o rotulo legitimo.
    """
    chain = _ChainSequencia(
        _draft("Texto.", assunto="Ação Requerida: atualização"),
        _draft("Texto.", remetente="Banco do Brasil <avisos@bb.com.br>"),
        _draft("Texto."),
    )

    resultado = await _generator(chain, is_malicious=False).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", is_malicious=False,
        variacao=_ficha_medio(),
    )

    assert len(chain.entradas) == 3
    assert resultado.validacao["regeneracoes_por_assunto"] == 1
    assert resultado.validacao["regeneracoes_por_instituicao_real"] == 1


async def test_instituicao_real_que_persiste_vira_item_invalido():
    """Instituicao real no REMETENTE (personificacao) continua barrada
    ate esgotar as regeneracoes -- diferente de uma mencao so no corpo
    (ver test_mencao_de_instituicao_real_so_no_corpo_nao_faz_gerar_de_novo).
    """
    chain = _ChainSequencia(
        _draft("Texto.", remetente="Atendimento Itaú <atendimento@itau-suporte.com>")
    )
    with pytest.raises(ItemInvalidoError, match="instituicao_real"):
        await _generator(chain).generate_response(
            difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
        )
    assert len(chain.entradas) == 3


async def test_mencao_de_instituicao_real_so_no_corpo_nao_faz_gerar_de_novo():
    """Piloto 5 (refinamento do bloqueio): o bloqueio disparava em
    qualquer MENCAO no corpo, mesmo sem nenhuma personificacao real
    (remetente, dominio, links) -- 'Recadastramento obrigatório no
    Itaú' não personifica ninguém, só cita o nome dentro do pretexto.
    Agora só personificação barra.
    """
    chain = _ChainSequencia(_draft("Recadastramento obrigatório no Itaú."))
    resultado = await _generator(chain).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )
    assert len(chain.entradas) == 1
    assert resultado.validacao["regeneracoes_por_instituicao_real"] == 0



async def test_destinatario_sem_email_faz_gerar_de_novo():
    """Piloto 3: 'Prezados Alunos,' no destinatario em 49 de 50 itens."""
    saudacao = _draft("Texto.", receptor="Prezados Alunos,")
    chain = _ChainSequencia(saudacao, _draft("Prezados alunos,\n\nTexto."))

    resultado = await _generator(chain).generate_response(
        difficulty="medio", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )

    assert len(chain.entradas) == 2
    assert resultado.validacao["regeneracoes_por_destinatario"] == 1


async def test_dominio_caricato_faz_gerar_de_novo():
    caricato = _draft("Texto.", remetente="Financeiro <noreply@universidade123.com>")
    chain = _ChainSequencia(caricato, _draft("Texto."))

    resultado = await _generator(chain).generate_response(
        difficulty="facil", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )

    assert len(chain.entradas) == 2
    assert resultado.validacao["regeneracoes_por_dominio_caricato"] == 1


class _AnotadorQueRegistra:
    def __init__(self):
        self.entradas = []

    async def ainvoke(self, args):
        self.entradas.append(args)
        return AnotacaoCega(pistas=[], premise_alignment=PremiseAlignment.MEDIO)


async def test_markdown_vira_texto_antes_da_anotacao_e_o_link_vai_para_a_lista():
    """Piloto 3: '[Regularizar Pagamento](http://...)' cru no corpo em 28
    itens; o especialista ve o corpo como texto puro.
    """
    corpo = "Prezada Larissa Monteiro,\n\nUse [Regularizar Pagamento](http://pagar-uni.com/x)."
    generator = _generator(_ChainSequencia(_draft(corpo)))
    generator.anotacao_cega = True
    anotador = _AnotadorQueRegistra()
    generator.annotation_chain = anotador

    resultado = await generator.generate_response(
        difficulty="facil", context="ctx", relevant_docs="docs", variacao=_ficha_medio()
    )

    assert "](" not in resultado.conteudo
    assert "Use Regularizar Pagamento." in resultado.conteudo
    assert [(link.text, link.href) for link in resultado.links] == [
        ("Regularizar Pagamento", "http://pagar-uni.com/x")
    ]
    assert "](" not in anotador.entradas[0]["conteudo"]
    assert "http://pagar-uni.com/x" in anotador.entradas[0]["links"]
    assert resultado.validacao["links_markdown_convertidos"] == 1



async def test_fusao_nao_deixa_passar_email_pronto_de_instituicao_real():
    """Lote local de 27/10: a fusao devolveu um e-mail assinado pela UFRJ
    com '[Seu Nome]', que ia igual para todos os itens do lote.
    """
    from langchain_core.messages import AIMessage
    from langchain_core.runnables import RunnableLambda

    recebido = {}

    def fusao_falsa(prompt_value):
        recebido["prompt"] = prompt_value.to_string()
        return AIMessage(
            content="- Urgencia: prazo curto.\nAtenciosamente,\n[Seu Nome]\nUniversidade Federal do Rio de Janeiro"
        )

    generator = ResponseGenerator(api_key="sk-nao-usada-neste-teste")
    generator.text_llm = RunnableLambda(fusao_falsa)

    fundido = await generator.fuse_and_summarize_context("cenario", ["doc da UFRJ sobre o Saphish"])

    assert "Rio de Janeiro" not in fundido and "[Seu Nome]" not in fundido
    assert "- Urgencia: prazo curto." in fundido
    assert "NÃO escreve o e-mail" in recebido["prompt"]
    assert "TAREFA CRIATIVA" not in recebido["prompt"]
