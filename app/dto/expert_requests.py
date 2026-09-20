from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from app.domain.models.cue import CueCode


class ExpertSessionRequest(BaseModel):
    codigo_acesso: str = Field(min_length=1, max_length=64)


class ConsentimentoRequest(BaseModel):
    versao: str = Field(min_length=1, max_length=32)
    aceito: bool


class PerfilRequest(BaseModel):
    anos_experiencia: int = Field(ge=0, le=80)
    area_atuacao: str = Field(min_length=1, max_length=200)
    formacao: str = Field(min_length=1, max_length=200)


class AnotacaoRequest(BaseModel):
    campo: Literal["conteudo", "assunto", "remetente"]
    cue_code: CueCode
    # Code points (len() do Python). O backend confere que
    # campo[span_start:span_end] == trecho: um erro de conversao UTF-16 ->
    # code points no cliente vira 422 imediato, nao ruido no dataset.
    span_start: int = Field(ge=0)
    span_end: int = Field(gt=0)
    trecho: str = Field(min_length=1, max_length=5000)


class AvaliacaoRequest(BaseModel):
    dificuldade_percebida: Literal["facil", "medio", "dificil"]
    adequado_uso_educacional: bool
    qualidade_geral: int = Field(ge=1, le=5)
    justificativa: str = Field(min_length=1, max_length=10000)
    comentario: Optional[str] = Field(default=None, max_length=10000)
    tempo_ms: Optional[int] = Field(default=None, ge=0)
    anotacoes: List[AnotacaoRequest] = Field(default_factory=list, max_length=200)

    @field_validator("justificativa")
    @classmethod
    def _justificativa_nao_e_so_espaco(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("justificativa nao pode ser vazia")
        return v
