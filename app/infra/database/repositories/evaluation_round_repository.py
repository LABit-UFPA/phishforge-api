from typing import Optional
from uuid import UUID

from app.domain.models.evaluation_round import AvaliacaoRodada
from app.infra.database.connection import DatabaseConnection


class EvaluationRoundRepository:
    """Persistencia de rodadas de avaliacao (issue #36)."""

    def __init__(self, db: DatabaseConnection):
        self.db = db

    async def create(
        self,
        nome: str,
        tcle_versao: str,
        tcle_texto_md: str,
        descricao: Optional[str] = None,
        status: str = "rascunho",
    ) -> AvaliacaoRodada:
        async with self.db.get_connection() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO avaliacao_rodadas (nome, descricao, status, tcle_versao, tcle_texto_md)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING *
                """,
                nome, descricao, status, tcle_versao, tcle_texto_md,
            )
        return AvaliacaoRodada(**dict(row))

    async def get_by_id(self, rodada_id: UUID) -> Optional[AvaliacaoRodada]:
        async with self.db.get_connection() as conn:
            row = await conn.fetchrow("SELECT * FROM avaliacao_rodadas WHERE id = $1", rodada_id)
        return AvaliacaoRodada(**dict(row)) if row else None

    async def adicionar_item(self, rodada_id: UUID, email_id: UUID, ordem_canonica: int) -> None:
        async with self.db.get_connection() as conn:
            await conn.execute(
                """
                INSERT INTO avaliacao_rodada_itens (rodada_id, email_id, ordem_canonica)
                VALUES ($1, $2, $3)
                """,
                rodada_id, email_id, ordem_canonica,
            )

    async def contar_itens(self, rodada_id: UUID) -> int:
        async with self.db.get_connection() as conn:
            return await conn.fetchval(
                "SELECT COUNT(*) FROM avaliacao_rodada_itens WHERE rodada_id = $1", rodada_id
            )
