from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel


class AvaliacaoRodada(BaseModel):
    """Uma rodada de avaliacao: conjunto fixo de itens + TCLE versionado
    (issue #36). O TCLE e dado, nao codigo: o CEP pode exigir alteracao
    no meio da coleta, e quem consentiu com a versao anterior reconsente.
    """

    id: UUID
    nome: str
    descricao: Optional[str] = None
    status: Literal["rascunho", "aberta", "encerrada"] = "rascunho"
    tcle_versao: str
    tcle_texto_md: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
