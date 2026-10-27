from typing import List, Optional

from pydantic import BaseModel, Field

from app.domain.models.cue import CueCode


class VariationSpec(BaseModel):
    """Ficha de variacao de UM item (lote-piloto de 26/10/2026).

    O piloto do protocolo v2 (10 itens, contexto E1-M-A, nivel medio)
    descartou 5 itens como quase-duplicados, e os 5 aceitos eram o
    mesmo e-mail com o nome trocado. Causa: no lote, contexto,
    documentos fundidos, prompt e temperatura sao identicos para todos
    os itens -- a unica fonte de variacao era a temperatura. O proprio
    prompt ja registrava (issue #20) que pedir "variedade" em abstrato
    nao funciona, porque cada chamada nao sabe o que as outras geraram.

    A ficha resolve isso do lado do codigo: para cada item, o sistema
    sorteia os detalhes que o LLM convergia sempre para o mesmo valor.
    Ela NUNCA troca o cenario pedido -- so fixa detalhes dentro dele.

    E ENTRADA da geracao, como `nivel` e `is_malicious` (ver comentario
    de GeneratedItemDraft): nunca faz parte do schema que o LLM
    preenche. Persistida junto do item (`phishing_emails.variation_spec`)
    para o lote ser auditavel e reproduzivel.
    """

    # None => a saudacao deve ser generica (e o caso de `generic_greeting`
    # como pista-alvo, no nivel facil).
    nome_destinatario: Optional[str] = None
    assinatura: str
    angulo_pretexto: str
    # None para item legitimo: a acao do item legitimo ja e definida pelo
    # nivel no prompt legitimo (link oficial ou instrucao textual).
    acao: Optional[str] = None
    tom: str
    estrutura: str
    abertura: str
    # Pistas que o item DEVE conter. Vazia para item legitimo. Distinta
    # de `cues` (o que o LLM anotou depois de escrever): comparar as
    # duas e uma medida de aderencia ao alvo.
    pistas_alvo: List[CueCode] = Field(default_factory=list)
