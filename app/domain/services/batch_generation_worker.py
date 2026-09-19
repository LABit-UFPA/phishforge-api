import json
import logging
from typing import List, Optional
from uuid import UUID

from app.domain.models.channel import Channel
from app.domain.models.generation_job import JobStatus
from app.domain.models.phishing_email import PhishingEmail
from app.domain.services.generation_pipeline import GenerationPipeline
from app.domain.services.phishing_service import PhishingEmailService
from app.domain.services.response_generator import ResponseGenerator
from app.infra.database.repositories.generation_job_repository import GenerationJobRepository

logger = logging.getLogger(__name__)

# Quantas vezes tentar de novo antes de descartar um item quase-
# duplicado. Nao e "quantas vezes tentar gerar" -- so entra em jogo
# quando a geracao FUNCIONOU mas o resultado ficou parecido demais com
# outro item ja aceito no mesmo lote.
MAX_DEDUP_RETRIES = 2


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
    ) -> None:
        try:
            built = await self._pipeline.build_context(context)
        except Exception as e:
            logger.error(f"Job {job_id}: falha ao montar contexto: {e}")
            await self._job_repository.mark_finished(
                job_id, JobStatus.FALHOU, error_message=f"Erro ao montar contexto: {e}"
            )
            return

        # Mesma logica de distribuicao entre dificuldades da issue #11
        # (nao mexer): o resto vai para as primeiras dificuldades da
        # lista.
        base, extra = divmod(total, len(difficulties))
        distribution = {d: base for d in difficulties}
        for i in range(extra):
            distribution[difficulties[i]] += 1

        await self._job_repository.mark_em_progresso(job_id, distribution)

        item_ids: List[UUID] = []
        failures: List[dict] = []
        total_discarded = 0
        accepted_embeddings: List[List[float]] = []

        for difficulty_value, count in distribution.items():
            # Mesma composicao malicioso/legitimo da issue #3: dentro
            # de cada dificuldade, count se divide segundo
            # malicious_ratio.
            n_malicious = round(count * malicious_ratio)
            n_legitimate = count - n_malicious
            itens_do_nivel = [True] * n_malicious + [False] * n_legitimate

            for is_malicious in itens_do_nivel:
                try:
                    if channel == Channel.EMAIL.value:
                        # Caminho intocado pela issue #6 -- o mesmo de
                        # antes desta issue, byte a byte.
                        draft, embedding = await self._generate_com_dedup(
                            difficulty_value=difficulty_value,
                            is_malicious=is_malicious,
                            generation_context=built.generation_context,
                            fused_context=built.fused_context,
                            accepted_embeddings=accepted_embeddings,
                        )
                        phishing_example = (
                            None
                            if draft is None
                            else PhishingEmail(
                                **draft.model_dump(),
                                nivel=difficulty_value,
                                is_malicious=is_malicious,
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

                # Persistido a cada item, nao so no final -- e o que
                # faz o polling mostrar progresso parcial de um lote
                # ainda rodando.
                await self._job_repository.update_progress(
                    job_id, len(item_ids), len(failures), total_discarded, item_ids, failures
                )

        if len(item_ids) == 0:
            status = JobStatus.FALHOU
        elif len(failures) == 0:
            status = JobStatus.CONCLUIDO
        else:
            status = JobStatus.CONCLUIDO_COM_FALHAS

        await self._job_repository.mark_finished(job_id, status)

    async def _generate_com_dedup(
        self,
        difficulty_value: str,
        is_malicious: bool,
        generation_context: str,
        fused_context: str,
        accepted_embeddings: List[List[float]],
    ):
        """Gera um item; se ficar parecido demais com outro ja aceito
        no lote, tenta de novo ate MAX_DEDUP_RETRIES vezes. Se
        continuar parecido, devolve (None, None) -- descartado, nao e
        falha de geracao.

        Excecao de geracao (erro de LLM de verdade) NAO e capturada
        aqui: propaga para o chamador tratar como falha, distinto de
        descarte por duplicidade -- sao categorias diferentes de
        problema.
        """
        for _tentativa in range(MAX_DEDUP_RETRIES + 1):
            draft = await self._response_generator.generate_response(
                difficulty=difficulty_value,
                context=generation_context,
                relevant_docs=fused_context,
                is_malicious=is_malicious,
            )
            embedding = self._embedding_client.embed(draft.conteudo)
            maior_similaridade = max(
                (_cosine_similarity(embedding, e) for e in accepted_embeddings),
                default=0.0,
            )
            if maior_similaridade < self._dedup_threshold:
                return draft, embedding

        return None, None

    async def _generate_channel_com_dedup(
        self,
        channel: str,
        difficulty_value: str,
        is_malicious: bool,
        generation_context: str,
        fused_context: str,
        accepted_embeddings: List[List[float]],
    ) -> tuple[Optional[dict], Optional[List[float]]]:
        """Equivalente de `_generate_com_dedup` para os canais novos
        (issue #6) -- mesma logica de retry/descarte, mas chamando
        `generate_channel_item` e derivando o texto do embedding de
        `content_json` via `_texto_para_embedding` (o campo de texto
        livre varia por canal; email usa `draft.conteudo` diretamente).
        """
        for _tentativa in range(MAX_DEDUP_RETRIES + 1):
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
            maior_similaridade = max(
                (_cosine_similarity(embedding, e) for e in accepted_embeddings),
                default=0.0,
            )
            if maior_similaridade < self._dedup_threshold:
                return resultado, embedding

        return None, None
