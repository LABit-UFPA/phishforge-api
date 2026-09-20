from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class EspecialistaResumo(BaseModel):
    id: UUID
    nome: str
    sobrenome: str


class RodadaResumo(BaseModel):
    id: UUID
    nome: str
    status: str
    tcle_versao: str


class ConsentimentoEstado(BaseModel):
    necessario: bool
    versao: str


class PerfilEstado(BaseModel):
    necessario: bool


class Progresso(BaseModel):
    total: int
    concluidas: int
    proxima_ordem: int


class ExpertMeResponse(BaseModel):
    especialista: EspecialistaResumo
    rodada: RodadaResumo
    consentimento: ConsentimentoEstado
    perfil: PerfilEstado
    progresso: Progresso


class ExpertSessionResponse(ExpertMeResponse):
    token: str
    expires_at: datetime


class TcleResponse(BaseModel):
    versao: str
    texto_md: str


class RevogacaoResponse(BaseModel):
    revogado_em: Optional[datetime]


class LinkCego(BaseModel):
    text: str
    href: str


class ItemCegoConteudo(BaseModel):
    """Contrato de cegamento (issue #37). Montado CAMPO A CAMPO, nunca a
    partir de `PhishingEmail`: um campo novo do modelo nao entra aqui por
    default. O teste de cegamento falha se qualquer chave proibida
    (`nivel`, `explicacao`, `is_malicious`, `categoria`, `cues`,
    `phish_scale`, `id`, `created_at`...) aparecer, recursivamente.

    `conteudo_texto` e a string canonica EXATA a que os offsets
    (`span_start`/`span_end`) se referem.
    """

    remetente: Optional[str]
    receptor: Optional[str]
    assunto: Optional[str]
    conteudo_texto: Optional[str]
    links: List[LinkCego]


class AnotacaoResponse(BaseModel):
    campo: str
    cue_code: str
    span_start: int
    span_end: int
    trecho: str


class AvaliacaoResponse(BaseModel):
    """O que o proprio especialista ja respondeu (para reabrir o item)."""

    status: str
    dificuldade_percebida: Optional[str]
    adequado_uso_educacional: Optional[bool]
    qualidade_geral: Optional[int]
    justificativa: Optional[str]
    comentario: Optional[str]
    tempo_ms: Optional[int]
    anotacoes: List[AnotacaoResponse]


class ExpertItemResponse(BaseModel):
    ordem: int
    total: int
    item: ItemCegoConteudo
    # None enquanto o especialista nao respondeu este item.
    avaliacao: Optional[AvaliacaoResponse]


class CueResponse(BaseModel):
    id: UUID
    code: str
    label_pt: str
    descricao_pt: str
    category: str
