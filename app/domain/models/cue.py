from enum import Enum
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CueCode(str, Enum):
    """Taxonomia canonica de pistas de phishing (issue #5).

    Espelha, com os MESMOS 10 codigos, a taxonomia ja semeada no
    backend Go (phishing-quest-api, migration
    V20260917110000__add_cues_tables.sql, com UUIDs fixos). Tres
    mecanicas inteiras do Go dependem de saber quais pistas cada item
    contem (byCue em /me/stats, selecao adaptativa, fila Leitner) e
    nenhuma delas tem alimentacao automatica sem este campo.

    Enum (nao string livre) de proposito: e o que restringe o
    `with_structured_output` do LLM a nao inventar codigo fora da
    taxonomia -- o principal risco que esta issue existe para evitar.
    Mesmo `str(Enum)` gotcha de `Difficulty` (ver #2): sempre usar
    `.value` explicitamente, nunca o membro cru em f-string/`.format()`.
    """

    SENDER_DOMAIN_MISMATCH = "sender_domain_mismatch"
    TYPOSQUAT = "typosquat"
    HOMOGLYPH = "homoglyph"
    URGENCY = "urgency"
    AUTHORITY = "authority"
    GENERIC_GREETING = "generic_greeting"
    CREDENTIAL_REQUEST = "credential_request"
    LINK_TEXT_MISMATCH = "link_text_mismatch"
    UNEXPECTED_ATTACHMENT = "unexpected_attachment"
    SCARCITY = "scarcity"


class Cue(BaseModel):
    """Uma pista anotada num item -- saida do LLM (nao entrada, ao
    contrario de `nivel`/`is_malicious`/`channel`; ver o comentario de
    `GeneratedItemDraft` sobre essa distincao). Por isso o mesmo
    formato serve tanto no draft do gerador quanto no `PhishingEmail`
    persistido: nao ha remapeamento entre os dois, so passagem direta.

    `span_start`/`span_end` sao opcionais de proposito (issue #5, passo
    4): se o modelo nao localizar a evidencia com precisao no
    `conteudo`, e preferivel devolver ambos `None` a um intervalo
    errado -- um destaque no lugar errado e pior que nenhum destaque.
    `ResponseGenerator._validar_cues` e quem aplica essa regra depois
    da geracao (passo 5): confere `conteudo[span_start:span_end] ==
    evidencia` e zera os dois campos quando nao bate.
    """

    code: CueCode
    evidencia: str = Field(
        description="Trecho literal do conteudo que evidencia esta pista -- pedido "
        "explicitamente para reduzir alucinacao: o modelo precisa apontar onde esta, "
        "nao so alegar que a pista existe."
    )
    span_start: Optional[int] = None
    span_end: Optional[int] = None


class CueTaxonomyEntry(BaseModel):
    """Uma LINHA da taxonomia (tabela `cues`), issue #35 -- o vocabulario
    que o anotador humano ve. Nao e `Cue`: aquele representa uma
    ANOTACAO (code + evidencia + span) num item, este representa uma
    entrada do vocabulario. Reaproveita `CueCode` para o codigo.
    """

    id: UUID
    code: CueCode
    label_pt: str
    descricao_pt: str
    category: Literal["technical", "psychological"]
    ativo: bool
