import json
from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID

from app.domain.models.expert import Especialista
from app.infra.database.connection import DatabaseConnection

# Nunca inclui `codigo_hash`: ele so entra por parametro de busca/criacao
# e nunca volta num Especialista (nem, portanto, numa resposta da API).
_COLUNAS = """
    id, nome, sobrenome, email, papel, codigo_prefixo, rodada_id, perfil_json,
    perfil_em, consentimento_versao, consentimento_em, revogado_em,
    ultimo_acesso_em, created_at, updated_at
"""


class ExpertRepository:
    """Persistencia de especialistas (issue #36)."""

    def __init__(self, db: DatabaseConnection):
        self.db = db

    async def create(
        self,
        nome: str,
        sobrenome: str,
        email: str,
        codigo_hash: str,
        codigo_prefixo: str,
        rodada_id: Optional[UUID] = None,
        papel: str = "especialista",
    ) -> Especialista:
        async with self.db.get_connection() as conn:
            row = await conn.fetchrow(
                f"""
                INSERT INTO especialistas
                    (nome, sobrenome, email, papel, codigo_hash, codigo_prefixo, rodada_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING {_COLUNAS}
                """,
                nome, sobrenome, email, papel, codigo_hash, codigo_prefixo, rodada_id,
            )
        return self._row_to_model(row)

    async def get_by_id(self, especialista_id: UUID) -> Optional[Especialista]:
        async with self.db.get_connection() as conn:
            row = await conn.fetchrow(
                f"SELECT {_COLUNAS} FROM especialistas WHERE id = $1", especialista_id
            )
        return self._row_to_model(row) if row else None

    async def get_by_codigo_hash(self, codigo_hash: str) -> Optional[Especialista]:
        async with self.db.get_connection() as conn:
            row = await conn.fetchrow(
                f"SELECT {_COLUNAS} FROM especialistas WHERE codigo_hash = $1", codigo_hash
            )
        return self._row_to_model(row) if row else None

    async def registrar_acesso(self, especialista_id: UUID) -> None:
        async with self.db.get_connection() as conn:
            await conn.execute(
                "UPDATE especialistas SET ultimo_acesso_em = now() WHERE id = $1",
                especialista_id,
            )

    async def registrar_consentimento(self, especialista_id: UUID, versao: str) -> None:
        async with self.db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE especialistas
                SET consentimento_versao = $2, consentimento_em = now()
                WHERE id = $1
                """,
                especialista_id, versao,
            )

    async def registrar_perfil(self, especialista_id: UUID, perfil: Dict[str, Any]) -> None:
        async with self.db.get_connection() as conn:
            await conn.execute(
                "UPDATE especialistas SET perfil_json = $2::jsonb, perfil_em = now() WHERE id = $1",
                especialista_id, json.dumps(perfil),
            )

    async def revogar(self, especialista_id: UUID) -> Optional[datetime]:
        """LGPD: marca `revogado_em` (nao apaga a linha). Idempotente --
        revogar de novo preserva a data original.
        """
        async with self.db.get_connection() as conn:
            return await conn.fetchval(
                """
                UPDATE especialistas SET revogado_em = COALESCE(revogado_em, now())
                WHERE id = $1 RETURNING revogado_em
                """,
                especialista_id,
            )

    def _row_to_model(self, row) -> Especialista:
        dados = dict(row)
        if isinstance(dados.get("perfil_json"), str):
            dados["perfil_json"] = json.loads(dados["perfil_json"])
        return Especialista(**dados)
