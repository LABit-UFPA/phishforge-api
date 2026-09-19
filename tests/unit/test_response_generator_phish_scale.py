"""ResponseGenerator._compute_phish_scale / _derivar_dificuldade_estimada
(issue #9): a derivacao deterministica dos dois eixos do NIST Phish
Scale, que roda depois da geracao e da validacao de cues.

Mesmo padrao dos outros testes diretos de ResponseGenerator: constroi
a classe real (sem chamada de rede) e substitui a chain por um espiao
que devolve um GeneratedItemDraft controlado.
"""

import pytest

from app.domain.models.cue import Cue, CueCode
from app.domain.models.difficulty import Difficulty
from app.domain.models.generated_item_draft import GeneratedItemDraft
from app.domain.models.phish_scale import PremiseAlignment
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


def _draft(cues: list[Cue], premise_alignment) -> GeneratedItemDraft:
    return GeneratedItemDraft(
        receptor="a@b.com",
        remetente="c@d.com",
        assunto="assunto",
        conteudo="conteudo de teste, sem espacos reservados para evidencia",
        explicacao="explicacao",
        categoria="teste",
        links=[],
        cues=cues,
        premise_alignment=premise_alignment,
    )


@pytest.mark.parametrize(
    "n_cues,alinhamento,esperado",
    [
        (0, PremiseAlignment.ALTO, Difficulty.DIFICIL),  # 2+2=4
        (1, PremiseAlignment.ALTO, Difficulty.DIFICIL),  # 2+2=4
        (3, PremiseAlignment.BAIXO, Difficulty.FACIL),  # 0+0=0
        (4, PremiseAlignment.BAIXO, Difficulty.FACIL),  # 0+0=0
        (0, PremiseAlignment.BAIXO, Difficulty.MEDIO),  # 2+0=2
        (2, PremiseAlignment.ALTO, Difficulty.MEDIO),  # 1+2=3
        (2, PremiseAlignment.MEDIO, Difficulty.MEDIO),  # 1+1=2
        (3, PremiseAlignment.ALTO, Difficulty.MEDIO),  # 0+2=2
    ],
)
async def test_derivacao_bate_com_a_regra_documentada(n_cues, alinhamento, esperado):
    cues = [
        Cue(code=CueCode.URGENCY, evidencia=f"evidencia {i}") for i in range(n_cues)
    ]
    draft = _draft(cues, alinhamento)
    generator = _generator_com_draft(draft, is_malicious=True)

    resultado = await generator.generate_response(
        difficulty="facil", context="ctx", relevant_docs="docs", is_malicious=True
    )

    assert resultado.phish_scale is not None
    assert resultado.phish_scale.cue_count == n_cues
    assert resultado.phish_scale.premise_alignment == alinhamento
    assert resultado.phish_scale.difficulty_estimated == esperado


async def test_cue_count_e_sempre_o_tamanho_de_cues_ja_validado():
    """cue_count nunca e um numero declarado a parte -- e o tamanho da
    lista de cues DEPOIS de _validar_cues (issue #9, passo 2). Aqui
    forcamos um span incoerente (que _validar_cues zera mas NAO
    remove) para confirmar que a pista continua contando.
    """
    draft = _draft(
        [Cue(code=CueCode.URGENCY, evidencia="nao esta no conteudo", span_start=0, span_end=5)],
        PremiseAlignment.MEDIO,
    )
    generator = _generator_com_draft(draft, is_malicious=True)

    resultado = await generator.generate_response(
        difficulty="facil", context="ctx", relevant_docs="docs", is_malicious=True
    )

    assert resultado.cues[0].span_start is None  # span foi zerado
    assert resultado.phish_scale.cue_count == 1  # mas a pista continua contando


async def test_item_legitimo_nao_tem_phish_scale():
    draft = _draft([], None)
    generator = _generator_com_draft(draft, is_malicious=False)

    resultado = await generator.generate_response(
        difficulty="facil", context="ctx", relevant_docs="docs", is_malicious=False
    )

    assert resultado.phish_scale is None


async def test_item_malicioso_sem_premise_alignment_nao_tem_phish_scale():
    """Defesa contra LLM que "esquece" de julgar premise_alignment --
    sem esse eixo, nao ha como derivar difficulty_estimated, entao o
    Phish Scale inteiro fica None em vez de meio-preenchido.
    """
    draft = _draft([Cue(code=CueCode.URGENCY, evidencia="algo")], None)
    generator = _generator_com_draft(draft, is_malicious=True)

    resultado = await generator.generate_response(
        difficulty="facil", context="ctx", relevant_docs="docs", is_malicious=True
    )

    assert resultado.phish_scale is None
