from datetime import datetime
from typing import Optional
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
