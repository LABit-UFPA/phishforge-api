import json
from typing import List, Optional
from uuid import UUID

from app.domain.models.generation_job import GenerationFailure, GenerationJob, JobStatus
from app.infra.database.connection import DatabaseConnection


class GenerationJobRepository:
    """Persistencia do estado do job de geracao em lote (issue #11b).

    Existe para o estado sobreviver a restart do processo: o worker em
    background le/escreve aqui, e o endpoint de polling
    (GET /generate/batch/{job_id}) le daqui tambem -- os dois nunca
    dependem de estado em memoria compartilhado.
    """

    def __init__(self, db: DatabaseConnection):
        self.db = db

    async def create(
        self,
        context: str,
        difficulties: List[str],
        total: int,
        malicious_ratio: float,
        channel: str = "email",
    ) -> UUID:
        async with self.db.get_connection() as conn:
            query = """
                INSERT INTO generation_jobs (context, difficulties, total, malicious_ratio, channel)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
            """
            return await conn.fetchval(
                query, context, json.dumps(difficulties), total, malicious_ratio, channel
            )

    async def get_by_id(self, job_id: UUID) -> Optional[GenerationJob]:
        async with self.db.get_connection() as conn:
            row = await conn.fetchrow("SELECT * FROM generation_jobs WHERE id = $1", job_id)
            return self._row_to_model(row) if row else None

    async def mark_em_progresso(self, job_id: UUID, distribution: dict) -> None:
        async with self.db.get_connection() as conn:
            await conn.execute(
                "UPDATE generation_jobs SET status = 'em_progresso', distribution = $2 WHERE id = $1",
                job_id,
                json.dumps(distribution),
            )

    async def update_progress(
        self,
        job_id: UUID,
        total_generated: int,
        total_failed: int,
        total_discarded: int,
        item_ids: List[UUID],
        failures: List[dict],
    ) -> None:
        """Chamado apos CADA item processado (sucesso, falha ou
        descarte por duplicidade), para o polling refletir progresso
        parcial em vez de so o resultado final.
        """
        async with self.db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE generation_jobs
                SET total_generated = $2, total_failed = $3, total_discarded = $4,
                    item_ids = $5, failures = $6
                WHERE id = $1
                """,
                job_id,
                total_generated,
                total_failed,
                total_discarded,
                json.dumps([str(i) for i in item_ids]),
                json.dumps(failures),
            )

    async def mark_finished(
        self, job_id: UUID, status: JobStatus, error_message: Optional[str] = None
    ) -> None:
        async with self.db.get_connection() as conn:
            await conn.execute(
                """
                UPDATE generation_jobs
                SET status = $2, error_message = $3, completed_at = CURRENT_TIMESTAMP
                WHERE id = $1
                """,
                job_id,
                status.value,
                error_message,
            )

    def _row_to_model(self, row) -> GenerationJob:
        return GenerationJob(
            id=row["id"],
            status=row["status"],
            context=row["context"],
            difficulties=json.loads(row["difficulties"]),
            total=row["total"],
            malicious_ratio=row["malicious_ratio"],
            channel=row["channel"],
            distribution=json.loads(row["distribution"]) if row["distribution"] else None,
            total_generated=row["total_generated"],
            total_failed=row["total_failed"],
            total_discarded=row["total_discarded"],
            item_ids=[UUID(i) for i in json.loads(row["item_ids"])],
            failures=[GenerationFailure(**f) for f in json.loads(row["failures"])],
            error_message=row["error_message"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )
