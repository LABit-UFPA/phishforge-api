from typing import List

from pydantic import BaseModel


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
    links: List[str]
