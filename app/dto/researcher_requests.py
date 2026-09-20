from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RodadaCreateRequest(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    descricao: Optional[str] = None
    tcle_versao: str = Field(min_length=1, max_length=32)
    tcle_texto_md: str = Field(min_length=1)


class RodadaItensRequest(BaseModel):
    # A ordem da lista vira `ordem_canonica`.
    email_ids: List[UUID] = Field(min_length=1, max_length=500)

    @field_validator("email_ids")
    @classmethod
    def _sem_repetidos(cls, v: List[UUID]) -> List[UUID]:
        if len(set(v)) != len(v):
            raise ValueError("email_ids nao pode conter itens repetidos.")
        return v


class EspecialistaCreateRequest(BaseModel):
    nome: str = Field(min_length=1, max_length=120)
    sobrenome: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=255, pattern=_EMAIL)
    rodada_id: UUID
