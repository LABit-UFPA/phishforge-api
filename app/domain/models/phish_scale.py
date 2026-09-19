from enum import Enum

from pydantic import BaseModel, Field

from app.domain.models.difficulty import Difficulty


class PremiseAlignment(str, Enum):
    """Alinhamento da premissa do item com o contexto do alvo -- um
    dos dois eixos objetivos do NIST Phish Scale (issue #9).

    Diferente de `Difficulty` (que tem `_missing_` para normalizar
    sinonimos de ENTRADA da API), este enum so aparece como SAIDA do
    LLM (via `with_structured_output`) e como coluna persistida -- nao
    ha borda externa aceitando sinonimo aqui.
    """

    BAIXO = "baixo"
    MEDIO = "medio"
    ALTO = "alto"


class PhishScale(BaseModel):
    """Os dois eixos objetivos do NIST Phish Scale, mais a dificuldade
    ESTIMADA que eles derivam -- issue #9.

    Substitui a dificuldade autodeclarada pelo LLM (o modelo escrevia
    o email e simplesmente devolvia de volta o `nivel` que recebeu
    como instrucao, sem nada verificar se o item de fato ficou mais
    dificil) por dois sinais auditaveis:

    - `cue_count`: SEMPRE `len(cues)` do mesmo item (issue #5) -- nunca
      um numero que o LLM declara a parte. Duas fontes de verdade para
      a mesma contagem divergem mais cedo ou mais tarde; ver
      `ResponseGenerator._compute_phish_scale`.
    - `premise_alignment`: julgado pelo LLM contra o `context` da
      request (alto = pretexto faz parte da rotina de quem recebe;
      baixo = pretexto generico ou incoerente).

    `difficulty_estimated` e CALCULADO deterministicamente dos dois
    eixos acima (ver `ResponseGenerator._derivar_dificuldade_estimada`)
    -- nunca e um terceiro palpite do modelo. Reaproveita `Difficulty`
    porque o vocabulario e identico (facil/medio/dificil), mas este e
    um valor DERIVADO, nao um valor de entrada da API: nao confundir
    com `PhishingEmail.nivel` (o nivel PEDIDO na request) nem com
    `difficulty_calibrated` (a dificuldade MEDIDA empiricamente a
    partir de tentativas reais, calculada no backend Go -- ver
    `phishing-quest-api` #66). Os tres campos coexistem de proposito e
    respondem perguntas diferentes: pedido, estimado a priori, medido
    a posteriori.
    """

    cue_count: int = Field(ge=0)
    premise_alignment: PremiseAlignment
    difficulty_estimated: Difficulty
