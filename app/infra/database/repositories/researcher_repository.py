import json
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.domain.models.evaluation_round import AvaliacaoRodada
from app.infra.database.connection import DatabaseConnection

NIVEIS = ("facil", "medio", "dificil")


class RodadaNaoEncontrada(Exception):
    pass


class RodadaNaoEditavel(Exception):
    """A composicao de itens so muda em `rascunho`."""


class ItensInvalidos(Exception):
    def __init__(self, detalhe: str):
        super().__init__(detalhe)
        self.detalhe = detalhe


class TransicaoInvalida(Exception):
    def __init__(self, atual: str):
        super().__init__(atual)
        self.atual = atual


class ResearcherRepository:
    """Gestao de rodadas/especialistas e consultas de export (issue #38).

    Todas as consultas de export excluem especialistas revogados
    (`revogado_em IS NOT NULL`) e so contam avaliacoes `concluida`: o
    dataset de analise nao pode conter dado de quem retirou o
    consentimento nem respostas pela metade.
    """

    def __init__(self, db: DatabaseConnection):
        self.db = db

    # ---- rodadas ----------------------------------------------------------

    async def substituir_itens(self, rodada_id: UUID, email_ids: List[UUID]) -> Dict[str, int]:
        """Troca a composicao da rodada por `email_ids` (na ordem dada).
        Tudo numa transacao com a linha da rodada travada: um `abrir`
        concorrente nao pode passar entre a checagem de status e o INSERT.
        """
        async with self.db.get_connection() as conn:
            async with conn.transaction():
                status = await conn.fetchval(
                    "SELECT status FROM avaliacao_rodadas WHERE id = $1 FOR UPDATE", rodada_id
                )
                if status is None:
                    raise RodadaNaoEncontrada()
                if status != "rascunho":
                    raise RodadaNaoEditavel(status)

                emails = await conn.fetch(
                    "SELECT id, nivel, channel FROM phishing_emails WHERE id = ANY($1::uuid[])",
                    email_ids,
                )
                por_id = {r["id"]: r for r in emails}
                ausentes = [str(i) for i in email_ids if i not in por_id]
                if ausentes:
                    raise ItensInvalidos(f"Itens inexistentes: {', '.join(ausentes)}")
                nao_email = [str(i) for i in email_ids if por_id[i]["channel"] != "email"]
                if nao_email:
                    raise ItensInvalidos(
                        "A avaliacao cega so suporta itens do canal 'email'. "
                        f"Itens de outros canais: {', '.join(nao_email)}"
                    )

                await conn.execute("DELETE FROM avaliacao_rodada_itens WHERE rodada_id = $1", rodada_id)
                await conn.executemany(
                    "INSERT INTO avaliacao_rodada_itens (rodada_id, email_id, ordem_canonica) VALUES ($1, $2, $3)",
                    [(rodada_id, email_id, pos) for pos, email_id in enumerate(email_ids, start=1)],
                )

        distribuicao = {n: 0 for n in NIVEIS}
        for email_id in email_ids:
            distribuicao[por_id[email_id]["nivel"]] += 1
        return distribuicao

    async def transicionar(
        self, rodada_id: UUID, de: str, para: str, itens_esperados: Optional[int] = None
    ) -> AvaliacaoRodada:
        async with self.db.get_connection() as conn:
            async with conn.transaction():
                atual = await conn.fetchval(
                    "SELECT status FROM avaliacao_rodadas WHERE id = $1 FOR UPDATE", rodada_id
                )
                if atual is None:
                    raise RodadaNaoEncontrada()
                if atual != de:
                    raise TransicaoInvalida(atual)
                if itens_esperados is not None:
                    total = await conn.fetchval(
                        "SELECT COUNT(*) FROM avaliacao_rodada_itens WHERE rodada_id = $1", rodada_id
                    )
                    if total != itens_esperados:
                        raise ItensInvalidos(
                            f"A rodada tem {total} itens vinculados; sao esperados {itens_esperados}."
                        )
                row = await conn.fetchrow(
                    "UPDATE avaliacao_rodadas SET status = $2 WHERE id = $1 RETURNING *",
                    rodada_id, para,
                )
        return AvaliacaoRodada(**dict(row))

    # ---- especialistas ----------------------------------------------------

    async def recodificar(self, especialista_id: UUID, codigo_hash: str, codigo_prefixo: str) -> bool:
        async with self.db.get_connection() as conn:
            resultado = await conn.execute(
                "UPDATE especialistas SET codigo_hash = $2, codigo_prefixo = $3 WHERE id = $1",
                especialista_id, codigo_hash, codigo_prefixo,
            )
        return resultado.endswith(" 1")

    async def listar_especialistas(self, rodada_id: Optional[UUID]) -> List[Dict[str, Any]]:
        async with self.db.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT e.id, e.nome, e.sobrenome, e.email, e.rodada_id, e.codigo_prefixo,
                       e.consentimento_versao, e.consentimento_em, e.revogado_em,
                       e.ultimo_acesso_em,
                       COUNT(a.id) FILTER (WHERE a.status = 'concluida') AS concluidas,
                       COUNT(a.id) AS total
                FROM especialistas e
                LEFT JOIN avaliacoes a ON a.especialista_id = e.id
                WHERE e.papel = 'especialista' AND ($1::uuid IS NULL OR e.rodada_id = $1)
                GROUP BY e.id
                ORDER BY e.created_at, e.id
                """,
                rodada_id,
            )
        return [dict(r) for r in rows]

    # ---- export -----------------------------------------------------------

    _FILTRO = """
        ri.rodada_id = $1
        AND e.revogado_em IS NULL
        AND e.papel = 'especialista'
        AND a.status = 'concluida'
    """

    async def dataset_avaliacoes(self, rodada_id: UUID) -> List[Dict[str, Any]]:
        async with self.db.get_connection() as conn:
            rows = await conn.fetch(
                f"""
                SELECT e.id AS especialista_id, ri.email_id AS item_id, ri.ordem_canonica,
                       a.ordem_apresentacao, pe.nivel AS nivel_sistema,
                       a.dificuldade_percebida,
                       (pe.nivel = a.dificuldade_percebida) AS nivel_concordou,
                       a.adequado_uso_educacional, a.qualidade_geral, a.justificativa,
                       a.comentario, a.tempo_ms, a.concluida_em,
                       (SELECT COUNT(*) FROM avaliacao_anotacoes an WHERE an.avaliacao_id = a.id)
                           AS n_anotacoes
                FROM avaliacoes a
                JOIN especialistas e ON e.id = a.especialista_id
                JOIN avaliacao_rodada_itens ri ON ri.id = a.rodada_item_id
                JOIN phishing_emails pe ON pe.id = ri.email_id
                WHERE {self._FILTRO}
                ORDER BY e.id, a.ordem_apresentacao
                """,
                rodada_id,
            )
        return [dict(r) for r in rows]

    async def dataset_anotacoes(self, rodada_id: UUID) -> List[Dict[str, Any]]:
        async with self.db.get_connection() as conn:
            rows = await conn.fetch(
                f"""
                SELECT e.id AS especialista_id, ri.email_id AS item_id, an.campo,
                       c.code AS cue_code, an.span_start, an.span_end, an.trecho,
                       EXISTS (
                           SELECT 1 FROM email_cues ec
                           WHERE ec.email_id = ri.email_id AND ec.cue_id = an.cue_id
                       ) AS cue_tambem_no_llm
                FROM avaliacao_anotacoes an
                JOIN avaliacoes a ON a.id = an.avaliacao_id
                JOIN especialistas e ON e.id = a.especialista_id
                JOIN avaliacao_rodada_itens ri ON ri.id = a.rodada_item_id
                JOIN cues c ON c.id = an.cue_id
                WHERE {self._FILTRO}
                ORDER BY e.id, a.ordem_apresentacao, an.span_start, an.id
                """,
                rodada_id,
            )
        return [dict(r) for r in rows]

    async def dataset_itens(self, rodada_id: UUID) -> List[Dict[str, Any]]:
        async with self.db.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT ri.ordem_canonica, pe.id AS item_id, pe.nivel AS nivel_sistema,
                       pe.categoria, pe.is_malicious, pe.channel, pe.difficulty_estimated,
                       pe.phish_scale_cue_count,
                       COALESCE((
                           SELECT string_agg(c.code, ';' ORDER BY c.code)
                           FROM email_cues ec JOIN cues c ON c.id = ec.cue_id
                           WHERE ec.email_id = pe.id
                       ), '') AS cues_llm,
                       (
                           SELECT COUNT(*) FROM avaliacoes a
                           JOIN especialistas e ON e.id = a.especialista_id
                           WHERE a.rodada_item_id = ri.id AND a.status = 'concluida'
                             AND e.revogado_em IS NULL
                       ) AS avaliacoes_concluidas
                FROM avaliacao_rodada_itens ri
                JOIN phishing_emails pe ON pe.id = ri.email_id
                WHERE ri.rodada_id = $1
                ORDER BY ri.ordem_canonica
                """,
                rodada_id,
            )
        return [dict(r) for r in rows]

    async def dataset_especialistas(self, rodada_id: UUID, incluir_pii: bool) -> List[Dict[str, Any]]:
        # PII so entra no SELECT quando pedida: nao e "buscar tudo e
        # filtrar depois".
        pii = ", e.nome, e.sobrenome, e.email" if incluir_pii else ""
        async with self.db.get_connection() as conn:
            rows = await conn.fetch(
                f"""
                SELECT e.id AS especialista_id, e.perfil_json, e.consentimento_versao,
                       e.consentimento_em, e.ultimo_acesso_em{pii},
                       COUNT(a.id) FILTER (WHERE a.status = 'concluida') AS avaliacoes_concluidas,
                       COUNT(a.id) AS avaliacoes_total
                FROM especialistas e
                LEFT JOIN avaliacoes a ON a.especialista_id = e.id
                WHERE e.rodada_id = $1 AND e.revogado_em IS NULL AND e.papel = 'especialista'
                GROUP BY e.id
                ORDER BY e.id
                """,
                rodada_id,
            )
        saida = []
        for r in rows:
            d = dict(r)
            perfil = d.pop("perfil_json")
            if isinstance(perfil, str):
                perfil = json.loads(perfil)
            perfil = perfil or {}
            d["anos_experiencia"] = perfil.get("anos_experiencia")
            d["area_atuacao"] = perfil.get("area_atuacao")
            d["formacao"] = perfil.get("formacao")
            saida.append(d)
        return saida
