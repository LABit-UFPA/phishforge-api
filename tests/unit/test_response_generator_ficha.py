"""ResponseGenerator com a ficha de variacao e as validacoes do
lote-piloto de 26/10/2026. Mesmo padrao de
test_response_generator_cues.py: ResponseGenerator real (a construcao
nao faz chamada de rede) com a chain substituida por um espiao.
"""

import random
from string import Formatter

import pytest

from app.domain.models.cue import Cue, CueCode
from app.domain.models.generated_item_draft import GeneratedItemDraft, ValidatedItemDraft
from app.domain.models.phishing_email import PhishingEmail
from app.domain.models.variation_spec import VariationSpec
from app.domain.services.response_generator import (
    MAX_REGENERACOES_POR_MARCADOR,
    ItemInvalidoError,
    ResponseGenerator,
)
from app.domain.services.variation_sampler import VariationSampler

VARIAVEIS_DO_PROMPT_DE_EMAIL = {"context", "difficulty", "relevant_docs", "variacao"}


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


def _draft(conteudo: str, cues=None, receptor="larissa@example.com", premise="medio"):
    return GeneratedItemDraft(
        receptor=receptor,
        remetente="secretaria@exemplo-universidade.test",
        assunto="Pendência no cadastro",
        conteudo=conteudo,
        explicacao="explicacao",
        categoria="academico",
        links=[],
        cues=cues or [],
        premise_alignment=premise,
    )


def _ficha_medio(nome="Larissa Monteiro", pistas=(CueCode.URGENCY, CueCode.AUTHORITY)):
    return VariationSpec(
        nome_destinatario=nome,
        assinatura="uma pessoa com nome e cargo",
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
