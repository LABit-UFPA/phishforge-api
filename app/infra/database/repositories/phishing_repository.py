import json
from typing import Dict, List, Optional
from uuid import UUID

from app.domain.models.cue import Cue
from app.domain.models.phish_scale import PhishScale
from app.domain.models.phishing_email import PhishingEmail
from app.infra.database.connection import DatabaseConnection


class PhishingEmailRepository:
    def __init__(self, db: DatabaseConnection):
        self.db = db

    async def create(self, email: PhishingEmail) -> UUID:
        """Cria um novo email de phishing e suas pistas anotadas
        (issue #5), numa unica transacao: um email nunca deve existir
        com so parte das pistas persistidas.
        """
        async with self.db.get_connection() as conn:
            async with conn.transaction():
                query = """
                    INSERT INTO phishing_emails
                    (receptor, remetente, assunto, conteudo, explicacao, nivel, categoria, links, is_malicious,
                     phish_scale_cue_count, phish_scale_premise_alignment, difficulty_estimated,
                     channel, content_json)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
                    RETURNING id
                """
                phish_scale = email.phish_scale
                email_id = await conn.fetchval(
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
                    phish_scale.cue_count if phish_scale else None,
                    phish_scale.premise_alignment.value if phish_scale else None,
                    phish_scale.difficulty_estimated.value if phish_scale else None,
                    email.channel.value,
                    json.dumps(email.content_json) if email.content_json is not None else None,
                )

                if email.cues:
                    # Resolve code -> cue_id contra a tabela `cues`, em
                    # vez de duplicar o mapeamento UUID<->code em
                    # Python: a tabela e a fonte de verdade (mesmos
                    # ids literais da migration do Go), e um erro aqui
                    # (codigo que nao existe) e bug real, nao deveria
                    # ser possivel dado que CueCode ja restringe o
                    # structured output -- mas fail loud em vez de
                    # inserir pista nenhuma se algum dia acontecer.
                    codigos = [cue.code.value for cue in email.cues]
                    cue_rows = await conn.fetch(
                        "SELECT id, code FROM cues WHERE code = ANY($1::text[])",
                        codigos,
                    )
                    id_por_codigo = {row["code"]: row["id"] for row in cue_rows}

                    for cue in email.cues:
                        cue_id = id_por_codigo.get(cue.code.value)
                        if cue_id is None:
                            raise ValueError(
                                f"codigo de pista '{cue.code.value}' nao existe na "
                                "tabela cues -- taxonomia local desalinhada da "
                                "migration (ver issue #5)."
                            )
                        await conn.execute(
                            """
                            INSERT INTO email_cues
                            (email_id, cue_id, span_start, span_end, evidencia)
                            VALUES ($1, $2, $3, $4, $5)
                            """,
                            email_id,
                            cue_id,
                            cue.span_start,
                            cue.span_end,
                            cue.evidencia,
                        )

                return email_id

    async def get_by_id(self, email_id: UUID) -> Optional[PhishingEmail]:
        async with self.db.get_connection() as conn:
            query = """
                SELECT id, receptor, remetente, assunto, conteudo, explicacao,
                       nivel, categoria, links, is_malicious, created_at, updated_at,
                       phish_scale_cue_count, phish_scale_premise_alignment, difficulty_estimated,
                       channel, content_json
                FROM phishing_emails
                WHERE id = $1
            """
            row = await conn.fetchrow(query, email_id)
            if not row:
                return None
            cues_por_email = await self._fetch_cues_map(conn, [email_id])
            return self._row_to_model(row, cues_por_email.get(row["id"], []))

    async def get_by_ids(self, email_ids: List[UUID]) -> List[PhishingEmail]:
        """Busca varios emails de uma vez, na MESMA ordem de
        `email_ids` (issue #11b: o job de lote guarda uma lista
        ordenada de ids, e o endpoint de status busca todos numa
        query so, em vez de N chamadas a get_by_id). As pistas de
        todos os emails tambem vem numa unica query bulk (issue #5) --
        e o mesmo caminho que expoe o resultado de um lote recem-
        gerado para curadoria, com as pistas anotadas ja visiveis.
        """
        if not email_ids:
            return []
        async with self.db.get_connection() as conn:
            query = """
                SELECT * FROM phishing_emails
                WHERE id = ANY($1::uuid[])
                ORDER BY array_position($1::uuid[], id)
            """
            rows = await conn.fetch(query, email_ids)
            cues_por_email = await self._fetch_cues_map(conn, email_ids)
            return [
                self._row_to_model(row, cues_por_email.get(row["id"], []))
                for row in rows
            ]

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
        """Retorna estatísticas dos emails no formato correto com validação robusta.

        Issue #8: antes, uma excecao aqui (banco fora do ar, por
        exemplo) era engolida e devolvia estatistica ZERADA -- o mesmo
        formato de "nenhum email cadastrado ainda". Os dois estados sao
        completamente diferentes e nao podem ter a mesma resposta.
        Deixa a excecao propagar; o endpoint decide o codigo HTTP.
        """
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

    async def delete(self, email_id: UUID) -> bool:
        async with self.db.get_connection() as conn:
            result = await conn.execute("DELETE FROM phishing_emails WHERE id = $1", email_id)
            return result.split()[-1] == "1"

    async def _fetch_cues_map(
        self, conn, email_ids: List[UUID]
    ) -> Dict[UUID, List[Cue]]:
        """Busca as pistas de varios emails numa unica query (issue
        #5), evitando N+1 quando get_by_ids traz uma lista inteira.
        `get_all`/`get_by_categoria`/`get_by_nivel`/`search_content`
        NAO chamam isto -- decisao de escopo: a issue pede as pistas
        expostas em GET /emails/{id} (e, por extensao, no resultado do
        lote via get_by_ids), nao nas listagens gerais.
        """
        if not email_ids:
            return {}
        rows = await conn.fetch(
            """
            SELECT ec.email_id, c.code, ec.span_start, ec.span_end, ec.evidencia
            FROM email_cues ec
            JOIN cues c ON c.id = ec.cue_id
            WHERE ec.email_id = ANY($1::uuid[])
            ORDER BY ec.created_at
            """,
            email_ids,
        )
        cues_por_email: Dict[UUID, List[Cue]] = {}
        for row in rows:
            cues_por_email.setdefault(row["email_id"], []).append(
                Cue(
                    code=row["code"],
                    span_start=row["span_start"],
                    span_end=row["span_end"],
                    evidencia=row["evidencia"],
                )
            )
        return cues_por_email

    def _row_to_model(self, row, cues: Optional[List[Cue]] = None) -> PhishingEmail:
        phish_scale = None
        if row["difficulty_estimated"] is not None:
            phish_scale = PhishScale(
                cue_count=row["phish_scale_cue_count"],
                premise_alignment=row["phish_scale_premise_alignment"],
                difficulty_estimated=row["difficulty_estimated"],
            )
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
            cues=cues or [],
            phish_scale=phish_scale,
            channel=row["channel"],
            content_json=json.loads(row["content_json"]) if row["content_json"] else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
