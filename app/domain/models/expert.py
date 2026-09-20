from datetime import datetime
from typing import Any, Dict, Literal, Optional
from uuid import UUID

from pydantic import BaseModel


class Especialista(BaseModel):
    """Pessoa que avalia (ou administra) uma rodada (issue #36).

    Nao tem `codigo_hash`: o hash do codigo de acesso nunca sai do
    repositorio, entao nenhuma resposta da API pode expo-lo nem por
    descuido de serializacao.
    """

    id: UUID
    nome: str
    sobrenome: str
    email: str
    papel: Literal["especialista", "pesquisador"] = "especialista"
    codigo_prefixo: str
    rodada_id: Optional[UUID] = None
    perfil_json: Optional[Dict[str, Any]] = None
    perfil_em: Optional[datetime] = None
    consentimento_versao: Optional[str] = None
    consentimento_em: Optional[datetime] = None
    revogado_em: Optional[datetime] = None
    ultimo_acesso_em: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
