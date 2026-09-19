from typing import List, Optional

from pydantic import BaseModel, Field

from app.domain.models.cue import Cue
from app.domain.models.link_ref import LinkRef
from app.domain.models.phish_scale import PhishScale, PremiseAlignment


class GeneratedItemDraft(BaseModel):
    """Contrato do structured output do LLM (`ResponseGenerator`).

    Antes desta issue (#11), `nivel` fazia parte deste mesmo schema --
    ou seja, o modelo era perguntado qual dificuldade ele mesmo acabou
    de gerar, depois de já ter recebido essa dificuldade como
    instrução no prompt. Isso é exatamente a "dificuldade autodeclarada
    pelo LLM" que a issue #9 existe para substituir por eixos objetivos
    (Phish Scale): o campo nunca deveria ter sido saída, porque é
    entrada da geração.

    `nivel` é responsabilidade de quem CHAMA o gerador (o endpoint, com
    o valor já validado da request -- ver issue #2), não do próprio
    LLM. O endpoint monta o `PhishingEmail` final combinando este draft
    com o nível solicitado:

        draft = await response_generator.generate_response(...)
        item = PhishingEmail(**draft.model_dump(), nivel=difficulty.value)

    Separar os dois schemas também é o que permite #3 (`is_malicious`),
    #5 (`cues`) e #9 (`phish_scale`) evoluírem este draft sem arriscar
    o LLM contradizer a request em campos que são entrada, não saída --
    decisão registrada no comentário da issue #11.
    """

    receptor: str
    remetente: str
    assunto: str
    conteudo: str
    explicacao: str
    categoria: str
    # List[LinkRef] desde a issue #5 (antes List[str]): texto exibido
    # separado do destino real, para expressar a pista
    # link_text_mismatch. Mudanca quebra-contrato deliberada -- ver
    # docstring de LinkRef.
    links: List[LinkRef]
    # Pistas de phishing anotadas pelo proprio LLM, com codigo da
    # taxonomia compartilhada com o Go (issue #5). E SAIDA legitima do
    # gerador (ao contrario de nivel/is_malicious/channel): passa
    # direto para o PhishingEmail final, sem remapeamento. Lista vazia
    # e o valor esperado para item legitimo (ver
    # ResponseGenerator._validar_cues).
    cues: List[Cue] = Field(default_factory=list)
    # Unico pedaco do Phish Scale (issue #9) que o LLM de fato julga --
    # o outro eixo (`cue_count`) e `len(cues)` deste mesmo draft, nunca
    # um numero declarado a parte (duas fontes de verdade para a mesma
    # contagem divergem). None para item legitimo: o prompt legitimo
    # nao pede este campo, e "dificuldade de detectar phishing" nao
    # tem sentido para um item que nao e phishing.
    premise_alignment: Optional[PremiseAlignment] = None
    # Montado por ResponseGenerator._compute_phish_scale DEPOIS da
    # geracao, a partir de `cues` + `premise_alignment` -- nunca
    # preenchido pelo LLM de verdade (o default None o deixa fora do
    # `required` do structured output, mas qualquer valor que o modelo
    # tentar propor aqui e descartado e recalculado). Existe como campo
    # do draft, e nao um retorno a parte de generate_response, para
    # fluir para o PhishingEmail final do mesmo jeito que `cues` flui.
    phish_scale: Optional[PhishScale] = None
