import json
from typing import Callable, List, Optional, Sequence, Tuple
from uuid import UUID

from app.domain.models.expert_evaluation import (
    AnotacaoSubmetida,
    AvaliacaoSubmetida,
    ConteudoParaAvaliar,
    ItemParaAvaliacao,
    ProgressoAvaliacao,
)
from app.domain.models.link_ref import LinkRef
from app.infra.database.connection import DatabaseConnection

# (cue_id, campo, span_start, span_end, trecho)
AnotacaoParaGravar = Tuple[UUID, str, int, int, str]


class ExpertEvaluationRepository:
    """Avaliacoes dos especialistas (issue #37).

    O caminho de leitura seleciona SO as colunas de `phishing_emails` que
    o especialista pode ver (`ConteudoParaAvaliar`). `nivel`, `explicacao`,
    `is_malicious`, `categoria` e as pistas do LLM nem saem do banco aqui:
    o cegamento nao depende de alguem lembrar de remove-los depois.
    """

    def __init__(self, db: DatabaseConnection):
        self.db = db

    async def inicializar_avaliacoes(
        self,
        especialista_id: UUID,
        rodada_id: UUID,
        embaralhar: Callable[[List[int]], None],
    ) -> None:
        """Cria, de uma vez, uma avaliacao `pendente` por item da rodada,
        com `ordem_apresentacao` sorteada PARA ESTE especialista. Idempotente:
        se ja existem, nao faz nada.

        A linha do especialista e travada (`FOR UPDATE`) durante a checagem
        e a insercao: duas primeiras requisicoes simultaneas gerariam dois
        sorteios diferentes, e o segundo INSERT violaria
        `uq_avaliacao_ordem`. Travando, a segunda espera e ve as linhas.
        """
        async with self.db.get_connection() as conn:
            async with conn.transaction():
                await conn.execute("SELECT 1 FROM especialistas WHERE id = $1 FOR UPDATE", especialista_id)
                ja_existem = await conn.fetchval(
                    "SELECT COUNT(*) FROM avaliacoes WHERE especialista_id = $1", especialista_id
                )
                if ja_existem:
                    return

                itens = await conn.fetch(
                    "SELECT id FROM avaliacao_rodada_itens WHERE rodada_id = $1 ORDER BY ordem_canonica",
                    rodada_id,
                )
                ordens = list(range(1, len(itens) + 1))
                embaralhar(ordens)
                await conn.executemany(
                    """
                    INSERT INTO avaliacoes (especialista_id, rodada_item_id, ordem_apresentacao)
                    VALUES ($1, $2, $3)
                    """,
                    [(especialista_id, item["id"], ordem) for item, ordem in zip(itens, ordens)],
                )

    async def obter_por_ordem(self, especialista_id: UUID, ordem: int) -> Optional[ItemParaAvaliacao]:
        async with self.db.get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT a.id AS avaliacao_id, a.ordem_apresentacao, a.status,
                       a.dificuldade_percebida, a.adequado_uso_educacional,
                       a.qualidade_geral, a.justificativa, a.comentario, a.tempo_ms,
                       e.remetente, e.receptor, e.assunto, e.conteudo, e.links, e.channel,
                       (SELECT COUNT(*) FROM avaliacoes t WHERE t.especialista_id = a.especialista_id) AS total
                FROM avaliacoes a
                JOIN avaliacao_rodada_itens ri ON ri.id = a.rodada_item_id
                JOIN phishing_emails e ON e.id = ri.email_id
                WHERE a.especialista_id = $1 AND a.ordem_apresentacao = $2
                """,
                especialista_id, ordem,
            )
            if row is None:
                return None
            anotacoes = await conn.fetch(
                """
                SELECT an.campo, c.code AS cue_code, an.span_start, an.span_end, an.trecho
                FROM avaliacao_anotacoes an
                JOIN cues c ON c.id = an.cue_id
                WHERE an.avaliacao_id = $1
                ORDER BY an.campo, an.span_start, an.span_end, an.id
                """,
                row["avaliacao_id"],
            )

        links = json.loads(row["links"]) if isinstance(row["links"], str) else (row["links"] or [])
        return ItemParaAvaliacao(
            avaliacao_id=row["avaliacao_id"],
            ordem=row["ordem_apresentacao"],
            total=row["total"],
            conteudo=ConteudoParaAvaliar(
                remetente=row["remetente"],
                receptor=row["receptor"],
                assunto=row["assunto"],
                conteudo=row["conteudo"],
                links=[LinkRef(**link) for link in links],
                channel=row["channel"],
            ),
            avaliacao=AvaliacaoSubmetida(
                status=row["status"],
                dificuldade_percebida=row["dificuldade_percebida"],
                adequado_uso_educacional=row["adequado_uso_educacional"],
                qualidade_geral=row["qualidade_geral"],
                justificativa=row["justificativa"],
                comentario=row["comentario"],
                tempo_ms=row["tempo_ms"],
                anotacoes=[AnotacaoSubmetida(**dict(a)) for a in anotacoes],
            ),
        )

    async def salvar_avaliacao(
        self,
        avaliacao_id: UUID,
        dificuldade_percebida: str,
        adequado_uso_educacional: bool,
        qualidade_geral: int,
        justificativa: str,
        comentario: Optional[str],
        tempo_ms: Optional[int],
        anotacoes: Sequence[AnotacaoParaGravar],
    ) -> None:
        """Substituicao TOTAL, numa transacao: apaga as anotacoes, insere as
        novas e atualiza a avaliacao. Idempotente -- reenviar o mesmo PUT
        nao duplica nada. `concluida_em` preserva a primeira conclusao.
        """
        async with self.db.get_connection() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM avaliacao_anotacoes WHERE avaliacao_id = $1", avaliacao_id)
                if anotacoes:
                    await conn.executemany(
                        """
                        INSERT INTO avaliacao_anotacoes
                            (avaliacao_id, cue_id, campo, span_start, span_end, trecho)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        [(avaliacao_id, cue_id, campo, ini, fim, trecho) for cue_id, campo, ini, fim, trecho in anotacoes],
                    )
                await conn.execute(
                    """
                    UPDATE avaliacoes SET
                        status = 'concluida',
                        dificuldade_percebida = $2,
                        adequado_uso_educacional = $3,
                        qualidade_geral = $4,
                        justificativa = $5,
                        comentario = $6,
                        tempo_ms = $7,
                        concluida_em = COALESCE(concluida_em, now())
                    WHERE id = $1
                    """,
                    avaliacao_id, dificuldade_percebida, adequado_uso_educacional,
                    qualidade_geral, justificativa, comentario, tempo_ms,
                )

    async def progresso(self, especialista_id: UUID, total_da_rodada: int) -> ProgressoAvaliacao:
        async with self.db.get_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS n,
                       COUNT(*) FILTER (WHERE status = 'concluida') AS concluidas,
                       MIN(ordem_apresentacao) FILTER (WHERE status = 'pendente') AS proxima
                FROM avaliacoes WHERE especialista_id = $1
                """,
                especialista_id,
            )
        if row["n"] == 0:
            # Ainda nao acessou nenhum item: as avaliacoes so nascem no primeiro acesso.
            return ProgressoAvaliacao(total=total_da_rodada, concluidas=0, proxima_ordem=1)
        # Tudo concluido: `proxima_ordem` fica no ultimo item (concluidas == total sinaliza o fim).
        return ProgressoAvaliacao(
            total=row["n"], concluidas=row["concluidas"], proxima_ordem=row["proxima"] or row["n"]
        )
