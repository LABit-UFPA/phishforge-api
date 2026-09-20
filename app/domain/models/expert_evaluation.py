from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel

from app.domain.models.cue import CueCode
from app.domain.models.link_ref import LinkRef

Campo = Literal["conteudo", "assunto", "remetente"]
Dificuldade = Literal["facil", "medio", "dificil"]


class AnotacaoSubmetida(BaseModel):
    """Um trecho marcado pelo especialista. `span_start`/`span_end` sao em
    code points (o `len()` do Python), nao em unidades UTF-16 do JS.
    """

    campo: Campo
    cue_code: CueCode
    span_start: int
    span_end: int
    trecho: str


class ConteudoParaAvaliar(BaseModel):
    """Os UNICOS campos de um item que chegam ao especialista (issue #37).

    O repositorio le so estas colunas de `phishing_emails` -- `nivel`,
    `explicacao`, `is_malicious`, `categoria`, `cues`, `phish_scale`, o
    `id` etc. nem saem do banco neste caminho. Adicionar um campo aqui e
    uma decisao deliberada de expor um dado ao especialista, nunca um
    efeito colateral de o modelo `PhishingEmail` ter ganhado um campo.
    """

    remetente: Optional[str] = None
    receptor: Optional[str] = None
    assunto: Optional[str] = None
    conteudo: Optional[str] = None
    links: List[LinkRef] = []
    channel: str = "email"


class AvaliacaoSubmetida(BaseModel):
    """O que o PROPRIO especialista ja respondeu num item."""

    status: Literal["pendente", "concluida"]
    dificuldade_percebida: Optional[Dificuldade] = None
    adequado_uso_educacional: Optional[bool] = None
    qualidade_geral: Optional[int] = None
    justificativa: Optional[str] = None
    comentario: Optional[str] = None
    tempo_ms: Optional[int] = None
    anotacoes: List[AnotacaoSubmetida] = []


class ItemParaAvaliacao(BaseModel):
    """Uma avaliacao (do especialista) junto do conteudo cego do item."""

    avaliacao_id: UUID
    ordem: int
    total: int
    conteudo: ConteudoParaAvaliar
    avaliacao: AvaliacaoSubmetida


class ProgressoAvaliacao(BaseModel):
    total: int
    concluidas: int
    proxima_ordem: int
