from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    """Estados de um job de geracao em lote (issue #11b).

    pendente -> em_progresso -> {concluido | concluido_com_falhas | falhou}.
    Nao ha estado de retomada: um processo interrompido no meio deixa
    o job preso em em_progresso -- limitacao aceita para o escopo desta
    issue (ver comentario na migration).
    """

    PENDENTE = "pendente"
    EM_PROGRESSO = "em_progresso"
    CONCLUIDO = "concluido"
    CONCLUIDO_COM_FALHAS = "concluido_com_falhas"
    FALHOU = "falhou"


class GenerationFailure(BaseModel):
    """Uma tentativa de geracao que falhou dentro do job (issue #8,
    item 1: separar falhas de sucessos em vez de contar as duas coisas
    juntas em total_generated).
    """

    difficulty: str
    is_malicious: bool
    error: str


class GenerationJob(BaseModel):
    id: UUID
    status: JobStatus
    context: str
    difficulties: List[str]
    total: int
    malicious_ratio: float
    distribution: Optional[dict] = None
    total_generated: int = 0
    total_failed: int = 0
    # Itens gerados mas descartados por serem quase-duplicados de outro
    # item do mesmo lote (issue #11b) -- nao e sucesso nem falha de
    # geracao, e uma decisao de qualidade do corpus.
    total_discarded: int = 0
    item_ids: List[UUID] = Field(default_factory=list)
    failures: List[GenerationFailure] = Field(default_factory=list)
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
