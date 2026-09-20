from typing import List

from app.domain.models.cue import CueTaxonomyEntry
from app.infra.database.connection import DatabaseConnection


class CueRepository:
    """Leitura da taxonomia de pistas (tabela `cues`) para uso humano
    (issue #35). A escrita/persistencia de ANOTACOES continua em
    `PhishingEmailRepository` -- este repositorio so lista o vocabulario.
    """

    def __init__(self, db: DatabaseConnection):
        self.db = db

    async def get_all_ativas(self) -> List[CueTaxonomyEntry]:
        """Pistas ativas, agrupadas por categoria e ordenadas por codigo
        (ordem estavel para o popover de anotacao nao pular entre
        requests). Pistas desativadas (`ativo = false`) ficam de fora,
        mas continuam validas para o historico que as referencia.
        """
        async with self.db.get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT id, code, label_pt, descricao_pt, category, ativo
                FROM cues
                WHERE ativo = TRUE
                ORDER BY category, code
                """
            )
        return [CueTaxonomyEntry(**dict(row)) for row in rows]
