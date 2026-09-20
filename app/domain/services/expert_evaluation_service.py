import random
from typing import List, Optional, Sequence

from app.domain.models.cue import CueTaxonomyEntry
from app.domain.models.evaluation_round import AvaliacaoRodada
from app.domain.models.expert import Especialista
from app.domain.models.expert_evaluation import ConteudoParaAvaliar, ItemParaAvaliacao
from app.dto.expert_requests import AnotacaoRequest, AvaliacaoRequest
from app.dto.expert_responses import (
    AnotacaoResponse,
    AvaliacaoResponse,
    ExpertItemResponse,
    ItemCegoConteudo,
    LinkCego,
)
from app.infra.database.repositories.cue_repository import CueRepository
from app.infra.database.repositories.expert_evaluation_repository import (
    AnotacaoParaGravar,
    ExpertEvaluationRepository,
)


class ItemNaoEncontrado(Exception):
    """`ordem` fora de 1..total para este especialista."""


class CanalNaoSuportado(Exception):
    """O item da rodada nao e um e-mail: a UI de anotacao e so de e-mail."""


class AvaliacaoInvalida(Exception):
    """Anotacao ou campo recusado (vira 422)."""


class ExpertEvaluationService:
    """Entrega cega de itens e submissao de avaliacoes (issue #37)."""

    def __init__(
        self,
        repository: ExpertEvaluationRepository,
        cue_repository: CueRepository,
        rng: Optional[random.Random] = None,
    ):
        self._repository = repository
        self._cues = cue_repository
        self._rng = rng or random.Random()

    async def obter_item(
        self, especialista: Especialista, rodada: AvaliacaoRodada, ordem: int
    ) -> ExpertItemResponse:
        item = await self._carregar(especialista, rodada, ordem)
        return self._montar(item)

    async def submeter(
        self,
        especialista: Especialista,
        rodada: AvaliacaoRodada,
        ordem: int,
        pedido: AvaliacaoRequest,
    ) -> ExpertItemResponse:
        item = await self._carregar(especialista, rodada, ordem)
        cues_ativas = await self._cues.get_all_ativas()
        anotacoes = self.validar_anotacoes(item.conteudo, pedido.anotacoes, cues_ativas)

        await self._repository.salvar_avaliacao(
            avaliacao_id=item.avaliacao_id,
            dificuldade_percebida=pedido.dificuldade_percebida,
            adequado_uso_educacional=pedido.adequado_uso_educacional,
            qualidade_geral=pedido.qualidade_geral,
            justificativa=pedido.justificativa.strip(),
            comentario=pedido.comentario,
            tempo_ms=pedido.tempo_ms,
            anotacoes=anotacoes,
        )
        return self._montar(await self._carregar(especialista, rodada, ordem))

    async def _carregar(
        self, especialista: Especialista, rodada: AvaliacaoRodada, ordem: int
    ) -> ItemParaAvaliacao:
        # Primeiro acesso: cria as N avaliacoes, com a ordem sorteada para
        # ESTE especialista (idempotente).
        await self._repository.inicializar_avaliacoes(
            especialista.id, rodada.id, self._rng.shuffle
        )
        item = await self._repository.obter_por_ordem(especialista.id, ordem)
        if item is None:
            raise ItemNaoEncontrado(f"Nao existe o item {ordem} nesta rodada.")
        if item.conteudo.channel != "email":
            raise CanalNaoSuportado(
                f"O item {ordem} e do canal '{item.conteudo.channel}'; a avaliacao so suporta e-mail."
            )
        return item

    @staticmethod
    def validar_anotacoes(
        conteudo: ConteudoParaAvaliar,
        anotacoes: Sequence[AnotacaoRequest],
        cues_ativas: Sequence[CueTaxonomyEntry],
    ) -> List[AnotacaoParaGravar]:
        """Confere cada anotacao contra o texto real do item.

        `trecho == campo[span_start:span_end]` e a validacao mais
        importante: sem ela, e possivel coletar centenas de anotacoes com
        offsets levemente errados (um bug UTF-16 vs. code points no
        cliente, por exemplo) e so descobrir na analise, quando ja e
        tarde para pedir ao especialista que refaca. Os offsets sao em
        code points -- o `len()`/fatiamento de `str` do Python.
        """
        id_por_codigo = {c.code: c.id for c in cues_ativas}
        textos = {
            "conteudo": conteudo.conteudo,
            "assunto": conteudo.assunto,
            "remetente": conteudo.remetente,
        }

        gravar: List[AnotacaoParaGravar] = []
        for i, a in enumerate(anotacoes):
            onde = f"anotacoes[{i}]"
            cue_id = id_por_codigo.get(a.cue_code)
            if cue_id is None:
                raise AvaliacaoInvalida(f"{onde}: a pista '{a.cue_code.value}' nao esta ativa na taxonomia.")

            texto = textos[a.campo]
            if texto is None:
                raise AvaliacaoInvalida(f"{onde}: este item nao tem o campo '{a.campo}'.")
            if a.span_end <= a.span_start:
                raise AvaliacaoInvalida(f"{onde}: span_end deve ser maior que span_start.")
            if a.span_end > len(texto):
                raise AvaliacaoInvalida(
                    f"{onde}: span_end ({a.span_end}) passa do tamanho do campo '{a.campo}' ({len(texto)})."
                )
            if texto[a.span_start : a.span_end] != a.trecho:
                raise AvaliacaoInvalida(
                    f"{onde}: 'trecho' nao corresponde ao texto do campo '{a.campo}' em "
                    f"[{a.span_start}:{a.span_end}]. Os offsets sao em code points (len() do Python), "
                    "nao em unidades UTF-16."
                )
            gravar.append((cue_id, a.campo, a.span_start, a.span_end, a.trecho))
        return gravar

    @staticmethod
    def _montar(item: ItemParaAvaliacao) -> ExpertItemResponse:
        """Monta a resposta CAMPO A CAMPO -- nunca `email.dict()` menos chaves."""
        c = item.conteudo
        av = item.avaliacao
        concluida = av.status == "concluida"
        return ExpertItemResponse(
            ordem=item.ordem,
            total=item.total,
            item=ItemCegoConteudo(
                remetente=c.remetente,
                receptor=c.receptor,
                assunto=c.assunto,
                conteudo_texto=c.conteudo,
                links=[LinkCego(text=link.text, href=link.href) for link in c.links],
            ),
            avaliacao=AvaliacaoResponse(
                status=av.status,
                dificuldade_percebida=av.dificuldade_percebida,
                adequado_uso_educacional=av.adequado_uso_educacional,
                qualidade_geral=av.qualidade_geral,
                justificativa=av.justificativa,
                comentario=av.comentario,
                tempo_ms=av.tempo_ms,
                anotacoes=[
                    AnotacaoResponse(
                        campo=a.campo, cue_code=a.cue_code.value, span_start=a.span_start,
                        span_end=a.span_end, trecho=a.trecho,
                    )
                    for a in av.anotacoes
                ],
            )
            if concluida
            else None,
        )
