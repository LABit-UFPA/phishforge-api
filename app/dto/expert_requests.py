from pydantic import BaseModel, Field


class ExpertSessionRequest(BaseModel):
    codigo_acesso: str = Field(min_length=1, max_length=64)


class ConsentimentoRequest(BaseModel):
    versao: str = Field(min_length=1, max_length=32)
    aceito: bool


class PerfilRequest(BaseModel):
    anos_experiencia: int = Field(ge=0, le=80)
    area_atuacao: str = Field(min_length=1, max_length=200)
    formacao: str = Field(min_length=1, max_length=200)
