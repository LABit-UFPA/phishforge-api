import json
from typing import List, Optional
from uuid import UUID

from app.domain.models.phishing_email import PhishingEmail
from app.infra.database.connection import DatabaseConnection


class PhishingEmailRepository:
    def __init__(self, db: DatabaseConnection):
        self.db = db

    async def create(self, email: PhishingEmail) -> UUID:
        """Cria um novo email de phishing no banco"""
        async with self.db.get_connection() as conn:
            query = """
                INSERT INTO phishing_emails
                (receptor, remetente, assunto, conteudo, explicacao, nivel, categoria, links, is_malicious)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                RETURNING id
            """
            return await conn.fetchval(
                query,
                email.receptor,
                email.remetente,
                email.assunto,
                email.conteudo,
                email.explicacao,
                email.nivel,
                email.categoria,
                json.dumps(email.links) if email.links else "[]",
                email.is_malicious,
            )

    async def get_by_id(self, email_id: UUID) -> Optional[PhishingEmail]:
        async with self.db.get_connection() as conn:
            query = """
                SELECT id, receptor, remetente, assunto, conteudo, explicacao,
                       nivel, categoria, links, is_malicious, created_at, updated_at
                FROM phishing_emails
                WHERE id = $1
            """
            row = await conn.fetchrow(query, email_id)
            return self._row_to_model(row) if row else None

    async def get_by_categoria(self, categoria: str, limit: int = 50) -> List[PhishingEmail]:
        async with self.db.get_connection() as conn:
            query = """
                SELECT * FROM phishing_emails 
                WHERE categoria = $1
                ORDER BY created_at DESC
                LIMIT $2
            """
            rows = await conn.fetch(query, categoria, limit)
            return [self._row_to_model(row) for row in rows]

    async def get_by_nivel(self, nivel: str, limit: int = 50) -> List[PhishingEmail]:
        async with self.db.get_connection() as conn:
            query = """
                SELECT * FROM phishing_emails 
                WHERE nivel = $1
                ORDER BY created_at DESC
                LIMIT $2
            """
            rows = await conn.fetch(query, nivel, limit)
            return [self._row_to_model(row) for row in rows]

    async def get_all(self, limit: int = 100, offset: int = 0) -> List[PhishingEmail]:
        async with self.db.get_connection() as conn:
            query = """
                SELECT * FROM phishing_emails 
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
            """
            rows = await conn.fetch(query, limit, offset)
            return [self._row_to_model(row) for row in rows]

    async def search_content(self, search_term: str, limit: int = 50) -> List[PhishingEmail]:
        async with self.db.get_connection() as conn:
            query = """
                SELECT * FROM phishing_emails 
                WHERE to_tsvector('portuguese', conteudo || ' ' || assunto) @@ plainto_tsquery('portuguese', $1)
                ORDER BY ts_rank(to_tsvector('portuguese', conteudo || ' ' || assunto), plainto_tsquery('portuguese', $1)) DESC
                LIMIT $2
            """
            rows = await conn.fetch(query, search_term, limit)
            return [self._row_to_model(row) for row in rows]

    async def get_stats(self) -> dict:
        """Retorna estatísticas dos emails no formato correto com validação robusta"""
        try:
            async with self.db.get_connection() as conn:
                # total
                total_row = await conn.fetchrow("SELECT COUNT(*) as total FROM phishing_emails")
                total = int(total_row["total"]) if total_row else 0

                # por dificuldade
                by_difficulty = {"facil": 0, "medio": 0, "dificil": 0}
                diff_rows = await conn.fetch(
                    "SELECT nivel, COUNT(*) as count FROM phishing_emails GROUP BY nivel"
                )
                for row in diff_rows:
                    if row["nivel"] in by_difficulty:
                        by_difficulty[row["nivel"]] = int(row["count"])

                # por categoria
                by_category = {}
                cat_rows = await conn.fetch(
                    "SELECT categoria, COUNT(*) as count FROM phishing_emails GROUP BY categoria"
                )
                for row in cat_rows:
                    if row["categoria"]:
                        by_category[row["categoria"]] = int(row["count"])

                # últimos 7 dias
                recent_row = await conn.fetchrow(
                    "SELECT COUNT(*) as recent_count FROM phishing_emails WHERE created_at >= NOW() - INTERVAL '7 days'"
                )
                recent_count = int(recent_row["recent_count"]) if recent_row else 0

                return {
                    "total": total,
                    "by_difficulty": by_difficulty,
                    "by_category": by_category,
                    "recent_count": recent_count,
                }
        except Exception as e:
            print(f"Erro em get_stats: {e}")
            return {
                "total": 0,
                "by_difficulty": {"facil": 0, "medio": 0, "dificil": 0},
                "by_category": {},
                "recent_count": 0,
            }

    async def delete(self, email_id: UUID) -> bool:
        async with self.db.get_connection() as conn:
            result = await conn.execute("DELETE FROM phishing_emails WHERE id = $1", email_id)
            return result.split()[-1] == "1"

    def _row_to_model(self, row) -> PhishingEmail:
        return PhishingEmail(
            id=row["id"],
            receptor=row["receptor"],
            remetente=row["remetente"],
            assunto=row["assunto"],
            conteudo=row["conteudo"],
            explicacao=row["explicacao"],
            nivel=row["nivel"],
            categoria=row["categoria"],
            links=json.loads(row["links"]) if row["links"] else [],
            is_malicious=row["is_malicious"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
