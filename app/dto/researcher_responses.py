from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel


class RodadaResponse(BaseModel):
    id: UUID
    nome: str
    descricao: Optional[str] = None
    status: str
    tcle_versao: str
    created_at: Optional[datetime] = None
    total_itens: int = 0


class RodadaDetalheResponse(RodadaResponse):
    # Na ordem canonica; o front usa para pre-selecionar os itens.
    email_ids: List[UUID] = []


class RodadaItensResponse(BaseModel):
    total: int
    distribuicao: Dict[str, int]


class EspecialistaCriadoResponse(BaseModel):
    """`codigo_acesso` (e o `link` que o contem) aparece SO aqui e em
    `recodificar`: depois disso apenas o hash fica gravado.
    """

    id: UUID
    codigo_acesso: str
    link: str


class EspecialistaLinha(BaseModel):
    id: UUID
    nome: str
    sobrenome: str
    email: str
    rodada_id: Optional[UUID] = None
    concluidas: int
    total: int
    consentimento_versao: Optional[str] = None
    consentimento_em: Optional[datetime] = None
    revogado_em: Optional[datetime] = None
    ultimo_acesso_em: Optional[datetime] = None


class ResumoResponse(BaseModel):
    total_avaliacoes: int
    especialistas: int
    matriz_confusao: Dict[str, Dict[str, int]]
    concordancia_bruta: Optional[float] = None
    qualidade_media: Optional[float] = None
    adequado_uso_educacional_pct: Optional[float] = None
    frequencia_pistas: Dict[str, Dict[str, int]]
