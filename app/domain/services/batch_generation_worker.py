import json
import logging
import random
from typing import List, Optional, Sequence
from uuid import UUID

from app.domain.models.channel import Channel
from app.domain.models.generation_job import JobStatus
from app.domain.models.phishing_email import PhishingEmail
from app.domain.services.generation_pipeline import GenerationPipeline
from app.domain.services.phishing_service import PhishingEmailService
from app.domain.services.response_generator import ResponseGenerator
from app.domain.services.variation_sampler import VariationSampler
from app.infra.database.repositories.generation_job_repository import GenerationJobRepository

logger = logging.getLogger(__name__)

# Quantas vezes tentar de novo antes de descartar um item quase-
# duplicado. Nao e "quantas vezes tentar gerar" -- so entra em jogo
# quando a geracao FUNCIONOU mas o resultado ficou parecido demais com
# outro item ja aceito no mesmo lote.
MAX_DEDUP_RETRIES = 2

# Tamanho de cada chamada de embedding em lote ao carregar os itens de
# lotes anteriores (dedup entre lotes).
_TAMANHO_LOTE_EMBEDDING = 100

# Resultado de cada tentativa registrado em generation_jobs.attempt_log.
RESULTADO_ACEITO = "aceito"
# Parecido demais com um item aceito; vai tentar de novo.
RESULTADO_REPETIDO = "repetido"
# Parecido demais na ultima tentativa; item descartado.
RESULTADO_DESCARTADO = "descartado"
RESULTADO_FALHA = "falha"


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _texto_para_embedding(channel: str, content_json: dict) -> str:
    """Extrai o texto usado para o dedup por similaridade de cosseno
    dos canais novos (issue #6) -- cada canal tem seu campo de texto
    livre natural, exceto pix_qr, que nao tem nenhum (nao ha corpo de
    mensagem num QR Code): usa o payload inteiro serializado, que
    ainda detecta repeticao exata/quase-exata dentro do mesmo lote.
    """
    if channel == "website":
        return content_json.get("visible_content", "")
    if channel == "phone_call":
        return content_json.get("transcript", "")
    return json.dumps(content_json, sort_keys=True)


class BatchGenerationWorker:
    """Processa um job de geracao em lote em background (issue #11b).

    Roda como BackgroundTask do FastAPI, DENTRO do mesmo processo que
    aceitou a requisicao -- nao ha fila distribuida. O estado vai para
    `generation_jobs` a cada item processado, para o endpoint de
    polling (GET /generate/batch/{job_id}) sempre ler do banco, nunca
    de memoria compartilhada com o worker.
    """

    def __init__(
        self,
        job_repository: GenerationJobRepository,
        phishing_service: PhishingEmailService,
        pipeline: GenerationPipeline,
        response_generator: ResponseGenerator,
        embedding_client,
        dedup_threshold: float,
    ):
        self._job_repository = job_repository
        self._phishing_service = phishing_service
        self._pipeline = pipeline
        self._response_generator = response_generator
        self._embedding_client = embedding_client
        self._dedup_threshold = dedup_threshold

    async def run(
        self,
        job_id: UUID,
        context: str,
        difficulties: List[str],
        total: int,
        malicious_ratio: float,
        channel: str = "email",
        dedup_job_ids: Optional[Sequence[UUID]] = None,
        seed: Optional[int] = None,
    ) -> None:
        try:
            built = await self._pipeline.build_context(context)
        except Exception as e:
            logger.error(f"Job {job_id}: falha ao montar contexto: {e}")
            await self._job_repository.mark_finished(
                job_id, JobStatus.FALHOU, error_message=f"Erro ao montar contexto: {e}"
            )
            return

        # Dedup entre lotes (lote-piloto de 26/10/2026): os itens aceitos
        # dos lotes indicados entram na comparacao desde o primeiro item
        # deste lote. Sem isso, os 4 lotes de 50 de uma mesma celula do
        # protocolo podiam repetir itens entre si -- a dedup so via o
        # proprio lote. Quem escolhe os lotes e quem pede (o piloto, por
        # exemplo, nao deve entrar).
        dedup_job_ids = list(dedup_job_ids or [])
        try:
            accepted_embeddings = await self._embeddings_de_lotes_anteriores(dedup_job_ids)
        except Exception as e:
            logger.error(f"Job {job_id}: falha ao carregar itens de lotes anteriores: {e}")
            await self._job_repository.mark_finished(
                job_id,
                JobStatus.FALHOU,
                error_message=f"Erro ao carregar itens de lotes anteriores: {e}",
            )
            return
        itens_de_lotes_anteriores = len(accepted_embeddings)

        # Semente do sorteio das fichas: sempre registrada, mesmo quando
        # nao veio na requisicao, para o lote poder ser reproduzido.
        if seed is None:
            seed = random.SystemRandom().randrange(2**31)
        sampler = VariationSampler(random.Random(seed))

        # Mesma logica de distribuicao entre dificuldades da issue #11
        # (nao mexer): o resto vai para as primeiras dificuldades da
        # lista.
        base, extra = divmod(total, len(difficulties))
        distribution = {d: base for d in difficulties}
        for i in range(extra):
            distribution[difficulties[i]] += 1

        run_metadata = {
            "modelo": getattr(self._response_generator, "model_name", None),
            "temperatura": getattr(self._response_generator, "temperature", None),
            "limiar_dedup": self._dedup_threshold,
            "max_dedup_retries": MAX_DEDUP_RETRIES,
            "seed": seed,
            "ficha_por_item": channel == Channel.EMAIL.value,
            "dedup_job_ids": [str(j) for j in dedup_job_ids],
            "itens_de_lotes_anteriores": itens_de_lotes_anteriores,
            # O que o gerador de fato recebeu: o normalizador reescreve o
            # contexto (em ingles), entao a string original do job nao
            # basta para reproduzir o lote.
            "generation_context": built.generation_context,
            "fused_context": built.fused_context,
        }
        await self._job_repository.mark_em_progresso(job_id, distribution, run_metadata)

        item_ids: List[UUID] = []
        failures: List[dict] = []
        total_discarded = 0
        attempt_log: List[dict] = []
        numero_item = 0

        for difficulty_value, count in distribution.items():
            # Mesma composicao malicioso/legitimo da issue #3: dentro
            # de cada dificuldade, count se divide segundo
            # malicious_ratio.
            n_malicious = round(count * malicious_ratio)
            n_legitimate = count - n_malicious
            itens_do_nivel = [True] * n_malicious + [False] * n_legitimate

            for is_malicious in itens_do_nivel:
                numero_item += 1
                tentativas_do_item: List[dict] = []
                try:
                    if channel == Channel.EMAIL.value:
                        draft, embedding, ficha = await self._generate_com_dedup(
                            difficulty_value=difficulty_value,
                            is_malicious=is_malicious,
                            generation_context=built.generation_context,
                            fused_context=built.fused_context,
                            accepted_embeddings=accepted_embeddings,
                            sampler=sampler,
                            tentativas=tentativas_do_item,
                        )
                        phishing_example = (
                            None
                            if draft is None
                            else PhishingEmail(
                                **draft.model_dump(),
                                nivel=difficulty_value,
                                is_malicious=is_malicious,
                                target_cues=list(ficha.pistas_alvo) if is_malicious else None,
                                variation_spec=ficha.model_dump(mode="json"),
                            )
                        )
                    else:
                        resultado, embedding = await self._generate_channel_com_dedup(
                            channel=channel,
                            difficulty_value=difficulty_value,
                            is_malicious=is_malicious,
                            generation_context=built.generation_context,
                            fused_context=built.fused_context,
                            accepted_embeddings=accepted_embeddings,
                            tentativas=tentativas_do_item,
                        )
                        phishing_example = (
                            None
                            if resultado is None
                            else PhishingEmail(
                                channel=Channel(channel),
                                content_json=resultado["content_json"],
                                explicacao=resultado["explicacao"],
                                categoria=resultado["categoria"],
                                nivel=difficulty_value,
                                is_malicious=is_malicious,
                            )
                        )

                    if phishing_example is None:
                        total_discarded += 1
                    else:
                        item_id = await self._phishing_service.create_email(phishing_example)
                        item_ids.append(item_id)
                        accepted_embeddings.append(embedding)
                except Exception as e:
                    logger.error(
                        f"Job {job_id}: falha ao gerar item {difficulty_value} "
                        f"(is_malicious={is_malicious}): {e}"
                    )
                    failures.append(
                        {
                            "difficulty": difficulty_value,
                            "is_malicious": is_malicious,
                            "error": str(e),
                        }
                    )
                    tentativas_do_item.append(
                        {
                            "tentativa": len(tentativas_do_item) + 1,
                            "similaridade_max": None,
                            "resultado": RESULTADO_FALHA,
                        }
                    )

                for tentativa in tentativas_do_item:
                    attempt_log.append({"item": numero_item, "nivel": difficulty_value, **tentativa})

                # Persistido a cada item, nao so no final -- e o que
                # faz o polling mostrar progresso parcial de um lote
                # ainda rodando.
                await self._job_repository.update_progress(
                    job_id,
                    len(item_ids),
                    len(failures),
                    total_discarded,
                    item_ids,
                    failures,
                    attempt_log,
                )

        if len(item_ids) == 0:
            status = JobStatus.FALHOU
        elif len(failures) == 0:
            status = JobStatus.CONCLUIDO
        else:
            status = JobStatus.CONCLUIDO_COM_FALHAS

        await self._job_repository.mark_finished(job_id, status)

    async def _embeddings_de_lotes_anteriores(self, job_ids: List[UUID]) -> List[List[float]]:
        """Embeddings dos itens aceitos nos lotes `job_ids`, calculados
        com o mesmo texto e o mesmo cliente da dedup do lote corrente.
        Recalculados a partir do conteudo guardado (nao persistidos):
        custa uma chamada de embedding a cada 100 itens, e evita uma
        tabela so para isso.
        """
        if not job_ids:
            return []
        item_ids: List[UUID] = []
        for job_id in job_ids:
            job = await self._job_repository.get_by_id(job_id)
            if job is None:
                raise ValueError(f"lote {job_id} nao encontrado")
            item_ids.extend(job.item_ids)
        if not item_ids:
            return []

        itens = await self._phishing_service.get_emails_by_ids(item_ids)
        textos = [
            item.conteudo
            if item.channel == Channel.EMAIL
            else _texto_para_embedding(item.channel.value, item.content_json or {})
            for item in itens
        ]
        embeddings: List[List[float]] = []
        for inicio in range(0, len(textos), _TAMANHO_LOTE_EMBEDDING):
            embeddings.extend(
                self._embedding_client.embed_batch(textos[inicio : inicio + _TAMANHO_LOTE_EMBEDDING])
            )
        return embeddings

    def _maior_similaridade(
        self, embedding: List[float], accepted_embeddings: List[List[float]]
    ) -> float:
        return max(
            (_cosine_similarity(embedding, e) for e in accepted_embeddings),
            default=0.0,
        )

    def _registrar_tentativa(
        self, tentativas: List[dict], numero: int, similaridade: float, ficha=None
    ) -> str:
        """Registra a tentativa e devolve o resultado dela."""
        if similaridade < self._dedup_threshold:
            resultado = RESULTADO_ACEITO
        elif numero < MAX_DEDUP_RETRIES + 1:
            resultado = RESULTADO_REPETIDO
        else:
            resultado = RESULTADO_DESCARTADO
        registro = {
            "tentativa": numero,
            "similaridade_max": round(similaridade, 4),
            "resultado": resultado,
        }
        if ficha is not None:
            registro["pistas_alvo"] = [p.value for p in ficha.pistas_alvo]
        tentativas.append(registro)
        return resultado

    async def _generate_com_dedup(
        self,
        difficulty_value: str,
        is_malicious: bool,
        generation_context: str,
        fused_context: str,
        accepted_embeddings: List[List[float]],
        sampler: VariationSampler,
        tentativas: List[dict],
    ):
        """Gera um item; se ficar parecido demais com outro ja aceito
        (no lote ou nos lotes anteriores indicados), tenta de novo ate
        MAX_DEDUP_RETRIES vezes. Se continuar parecido, devolve
        (None, None, None) -- descartado, nao e falha de geracao.

        Cada tentativa usa uma ficha NOVA (proxima do sorteio
        balanceado): repetir a mesma ficha tenderia a reproduzir o
        mesmo item. A ficha devolvida e a do item aceito.

        Excecao de geracao (erro de LLM de verdade) NAO e capturada
        aqui: propaga para o chamador tratar como falha, distinto de
        descarte por duplicidade -- sao categorias diferentes de
        problema.
        """
        for numero in range(1, MAX_DEDUP_RETRIES + 2):
            ficha = sampler.sortear(difficulty_value, is_malicious)
            draft = await self._response_generator.generate_response(
                difficulty=difficulty_value,
                context=generation_context,
                relevant_docs=fused_context,
                is_malicious=is_malicious,
                variacao=ficha,
            )
            embedding = self._embedding_client.embed(draft.conteudo)
            similaridade = self._maior_similaridade(embedding, accepted_embeddings)
            if self._registrar_tentativa(tentativas, numero, similaridade, ficha) == RESULTADO_ACEITO:
                return draft, embedding, ficha

        return None, None, None

    async def _generate_channel_com_dedup(
        self,
        channel: str,
        difficulty_value: str,
        is_malicious: bool,
        generation_context: str,
        fused_context: str,
        accepted_embeddings: List[List[float]],
        tentativas: List[dict],
    ) -> tuple[Optional[dict], Optional[List[float]]]:
        """Equivalente de `_generate_com_dedup` para os canais novos
        (issue #6) -- mesma logica de retry/descarte, mas chamando
        `generate_channel_item` e derivando o texto do embedding de
        `content_json` via `_texto_para_embedding` (o campo de texto
        livre varia por canal; email usa `draft.conteudo` diretamente).
        Sem ficha: os prompts dos canais novos ainda nao a recebem.
        """
        for numero in range(1, MAX_DEDUP_RETRIES + 2):
            resultado = await self._response_generator.generate_channel_item(
                channel=channel,
                difficulty=difficulty_value,
                context=generation_context,
                relevant_docs=fused_context,
                is_malicious=is_malicious,
            )
            embedding = self._embedding_client.embed(
                _texto_para_embedding(channel, resultado["content_json"])
            )
            similaridade = self._maior_similaridade(embedding, accepted_embeddings)
            if self._registrar_tentativa(tentativas, numero, similaridade) == RESULTADO_ACEITO:
                return resultado, embedding

        return None, None
