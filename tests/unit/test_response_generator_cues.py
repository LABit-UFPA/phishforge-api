"""ResponseGenerator._validar_cues (issue #5, passos 5 e 9): a
validacao que roda DEPOIS do LLM devolver o draft, antes de qualquer
persistencia.

Mesmo padrao de test_response_generator_is_malicious.py: constroi um
ResponseGenerator real (a construcao so monta objetos LangChain, sem
chamada de rede) e substitui as chains por espioes que devolvem um
GeneratedItemDraft controlado.
"""

from app.domain.models.cue import Cue, CueCode
from app.domain.models.generated_item_draft import GeneratedItemDraft
from app.domain.services.response_generator import ResponseGenerator


class _ChainQueDevolve:
    def __init__(self, draft: GeneratedItemDraft):
        self._draft = draft

    async def ainvoke(self, args):
        return self._draft


def _generator_com_draft(draft: GeneratedItemDraft, is_malicious: bool) -> ResponseGenerator:
    generator = ResponseGenerator(api_key="sk-nao-usada-neste-teste")
    chain = _ChainQueDevolve(draft)
    if is_malicious:
        generator.chain = chain
    else:
        generator.legitimate_chain = chain
    return generator


def _draft_com_cues(conteudo: str, cues: list[Cue]) -> GeneratedItemDraft:
    return GeneratedItemDraft(
        receptor="a@b.com",
        remetente="c@d.com",
        assunto="assunto",
        conteudo=conteudo,
        explicacao="explicacao",
        categoria="teste",
        links=[],
        cues=cues,
    )


async def test_span_coerente_e_preservado():
    conteudo = "Sua conta sera bloqueada em ate 2 horas se voce nao agir."
    evidencia = "em ate 2 horas"
    inicio = conteudo.index(evidencia)
    fim = inicio + len(evidencia)
    draft = _draft_com_cues(
        conteudo,
        [Cue(code=CueCode.URGENCY, evidencia=evidencia, span_start=inicio, span_end=fim)],
    )
    generator = _generator_com_draft(draft, is_malicious=True)

    resultado = await generator.generate_response(
        difficulty="facil", context="ctx", relevant_docs="docs", is_malicious=True
    )

    assert len(resultado.cues) == 1
    assert resultado.cues[0].span_start == inicio
    assert resultado.cues[0].span_end == fim


async def test_span_incoerente_e_zerado_mas_pista_e_mantida():
    """Trecho declarado nao bate com o que de fato esta em `conteudo`
    naquela posicao -- span vira None/None, mas o codigo da pista
    continua na lista (issue #5, passo 5).
    """
    conteudo = "Prezado cliente, sua fatura esta disponivel."
    draft = _draft_com_cues(
        conteudo,
        [Cue(code=CueCode.URGENCY, evidencia="em ate 2 horas", span_start=5, span_end=10)],
    )
    generator = _generator_com_draft(draft, is_malicious=True)

    resultado = await generator.generate_response(
        difficulty="facil", context="ctx", relevant_docs="docs", is_malicious=True
    )

    assert len(resultado.cues) == 1
    assert resultado.cues[0].code == CueCode.URGENCY
    assert resultado.cues[0].span_start is None
    assert resultado.cues[0].span_end is None


async def test_span_fora_dos_limites_do_texto_e_zerado():
    conteudo = "texto curto"
    draft = _draft_com_cues(
        conteudo,
        [Cue(code=CueCode.SCARCITY, evidencia="oferta", span_start=500, span_end=506)],
    )
    generator = _generator_com_draft(draft, is_malicious=True)

    resultado = await generator.generate_response(
        difficulty="facil", context="ctx", relevant_docs="docs", is_malicious=True
    )

    assert resultado.cues[0].span_start is None
    assert resultado.cues[0].span_end is None


async def test_cue_sem_span_passa_direto_sem_validacao():
    conteudo = "conteudo qualquer"
    draft = _draft_com_cues(
        conteudo,
        [Cue(code=CueCode.GENERIC_GREETING, evidencia="Prezado cliente")],
    )
    generator = _generator_com_draft(draft, is_malicious=True)

    resultado = await generator.generate_response(
        difficulty="facil", context="ctx", relevant_docs="docs", is_malicious=True
    )

    assert len(resultado.cues) == 1
    assert resultado.cues[0].span_start is None
    assert resultado.cues[0].span_end is None


async def test_item_legitimo_com_cues_e_esvaziado():
    """Passo 9: mesmo que o LLM "esqueca" a instrucao do prompt legitimo
    e emita pistas, o item legitimo nunca deve sair de
    generate_response com cues nao-vazio.
    """
    draft = _draft_com_cues(
        "comunicado legitimo",
        [Cue(code=CueCode.URGENCY, evidencia="algo")],
    )
    generator = _generator_com_draft(draft, is_malicious=False)

    resultado = await generator.generate_response(
        difficulty="facil", context="ctx", relevant_docs="docs", is_malicious=False
    )

    assert resultado.cues == []


async def test_item_legitimo_sem_cues_permanece_vazio():
    draft = _draft_com_cues("comunicado legitimo", [])
    generator = _generator_com_draft(draft, is_malicious=False)

    resultado = await generator.generate_response(
        difficulty="facil", context="ctx", relevant_docs="docs", is_malicious=False
    )

    assert resultado.cues == []
