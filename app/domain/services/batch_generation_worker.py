import asyncio
import json
import logging
import random
from typing import Awaitable, Callable, Dict, List, Optional, Sequence, Set, Tuple
from uuid import UUID

from app.domain.models.channel import Channel
from app.domain.models.generation_job import JobStatus
from app.domain.models.instituicao_ficticia import InstituicaoFicticia
from app.core.reproducibilidade import commit_do_git
from app.domain.models.phishing_email import PhishingEmail
from app.domain.models.variation_spec import VariationSpec
from app.domain.services.generation_pipeline import GenerationPipeline
from app.domain.services.item_validation import normalizar_assunto
from app.domain.services.llm_factory import descrever_saida_estruturada
from app.domain.services.phishing_service import PhishingEmailService
from app.domain.services.response_generator import VERSAO_GERADOR, ResponseGenerator
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


def _e_erro_de_taxa(exc: BaseException) -> bool:
    """True quando a excecao e um limite de taxa (429) ou sobrecarga (529) do
    provider -- os unicos erros em que vale esperar e tentar de novo. Detecta
    por duck-typing (status_code na excecao, na causa ou na resposta) e pelo
    nome da classe, para nao depender de importar o SDK de um provider que o
    ambiente pode nem ter instalado (anthropic quando so se usa OpenAI)."""
    vistos = set()
    pilha = [exc]
    while pilha:
        e = pilha.pop()
        if e is None or id(e) in vistos:
            continue
        vistos.add(id(e))
        for code in (
            getattr(e, "status_code", None),
            getattr(getattr(e, "response", None), "status_code", None),
        ):
            if code in (429, 529):
                return True
        nome = type(e).__name__.lower()
        if "ratelimit" in nome or "overloaded" in nome:
            return True
        pilha.append(getattr(e, "__cause__", None))
        pilha.append(getattr(e, "__context__", None))
    return False


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _texto_email_para_embedding(assunto: Optional[str], conteudo: Optional[str]) -> str:
    """Texto do e-mail usado na dedup: assunto + corpo. So o corpo
    deixava passar assuntos identicos (piloto 2: dois pares de itens com
    o mesmo assunto, de corpos diferentes).
    """
    return f"{assunto or ''}\n\n{conteudo or ''}"


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
        concurrency: int = 1,
        backoff_base_seconds: float = 2.0,
        max_tentativas_taxa: int = 5,
    ):
        self._job_repository = job_repository
        self._phishing_service = phishing_service
        self._pipeline = pipeline
        self._response_generator = response_generator
        self._embedding_client = embedding_client
        self._dedup_threshold = dedup_threshold
        # Concorrencia da geracao (item 6). Default 1 = serial (comportamento
        # antigo), para nao surpreender quem constroi o worker direto (testes).
        # O container passa BATCH_CONCURRENCY (8 em producao).
        self._concurrency = max(1, concurrency)
        self._backoff_base_seconds = backoff_base_seconds
        self._max_tentativas_taxa = max(1, max_tentativas_taxa)

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
        instituicao: Optional[InstituicaoFicticia] = None,
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
            accepted_embeddings, accepted_assuntos = await self._carregar_lotes_anteriores(
                dedup_job_ids
            )
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
        # `instituicao` (piloto 5, item 2.1): override do lote inteiro,
        # vindo de BatchGenerationRequest.instituicao -- None sorteia por
        # item, balanceado (ver VariationSampler).
        sampler = VariationSampler(random.Random(seed), instituicao=instituicao)

        # Mesma logica de distribuicao entre dificuldades da issue #11
        # (nao mexer): o resto vai para as primeiras dificuldades da
        # lista.
        base, extra = divmod(total, len(difficulties))
        distribution = {d: base for d in difficulties}
        for i in range(extra):
            distribution[difficulties[i]] += 1

        _provider = getattr(self._response_generator, "provider", None)
        _modelo = getattr(self._response_generator, "model_name", None)
        run_metadata = {
            "versao_gerador": VERSAO_GERADOR,
            # Reprodutibilidade (plano item 5): commit do codigo, provider e o
            # mecanismo de saida estruturada em uso -- o relatorio/lote tem de
            # dizer com que codigo e por que caminho os itens foram gerados.
            "git_commit": commit_do_git(),
            "provider": _provider,
            "modelo": _modelo,
            "saida_estruturada": descrever_saida_estruturada(_provider or "", _modelo or ""),
            "temperatura": getattr(self._response_generator, "temperature", None),
            "anotacao_cega": getattr(self._response_generator, "anotacao_cega", None),
            "limiar_dedup": self._dedup_threshold,
            "max_dedup_retries": MAX_DEDUP_RETRIES,
            "seed": seed,
            "instituicao_override": instituicao.model_dump(mode="json") if instituicao else None,
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

        # --- Geracao CONCORRENTE dos itens (item 6 do plano de producao) ---
        # Os "slots" sao a composicao deterministica (dificuldade x
        # malicioso/legitimo, mesma da issue #3). A ficha inicial de cada slot
        # e pre-sorteada EM ORDEM (serial): o balanceamento de instituicao e a
        # atribuicao primaria ficam deterministicos mesmo com a geracao fora de
        # ordem. A geracao em si (cara) roda em paralelo, limitada por semaforo.
        #
        # LIMITE de determinismo (documentar no artigo): a DECISAO de dedup
        # depende da ordem de TERMINO das geracoes, entao, entre dois itens
        # parecidos, qual fica e qual e descartado pode variar de uma execucao
        # para outra. A composicao, as fichas e a saida final (em ordem de slot)
        # sao deterministicas; a escolha do par duplicado nao -- e isso ja valia
        # para a geracao Anthropic, que nao tem seed.
        slots: List[Tuple[int, str, bool]] = []
        numero_item = 0
        for difficulty_value, count in distribution.items():
            n_malicious = round(count * malicious_ratio)
            n_legitimate = count - n_malicious
            for is_malicious in [True] * n_malicious + [False] * n_legitimate:
                numero_item += 1
                slots.append((numero_item, difficulty_value, is_malicious))

        fichas_iniciais: Dict[int, VariationSpec] = {}
        if channel == Channel.EMAIL.value:
            for numero, difficulty_value, is_malicious in slots:
                fichas_iniciais[numero] = sampler.sortear(difficulty_value, is_malicious)

        # Estado compartilhado. So e mutado em secoes SINCRONAS (sem await no
        # meio) -- atomicas no asyncio (uma thread so), entao a dedup e a
        # contagem ficam corretas sem lock. O lock abaixo serializa apenas as
        # GRAVACOES de progresso (I/O) para elas nao se atropelarem.
        resultados_por_slot: Dict[int, dict] = {}
        progresso_lock = asyncio.Lock()
        semaforo = asyncio.Semaphore(self._concurrency)

        def _log_do_slot(numero: int, r: dict) -> List[dict]:
            return [{"item": numero, "nivel": r["nivel"], **t} for t in r["tentativas"]]

        async def _rodar_slot(numero: int, difficulty_value: str, is_malicious: bool) -> None:
            async with semaforo:
                resultado = await self._processar_item(
                    numero_item=numero,
                    difficulty_value=difficulty_value,
                    is_malicious=is_malicious,
                    channel=channel,
                    built=built,
                    sampler=sampler,
                    ficha_inicial=fichas_iniciais.get(numero),
                    accepted_embeddings=accepted_embeddings,
                    accepted_assuntos=accepted_assuntos,
                )
            # Secao sincrona (atomica no asyncio): guarda o resultado do slot.
            resultados_por_slot[numero] = resultado
            # Progresso parcial para o polling (o estado final, apos o gather,
            # fica em ordem de slot). Snapshot montado DENTRO do lock, para a
            # ultima gravacao ser sempre a mais completa.
            async with progresso_lock:
                feitos = list(resultados_por_slot.items())
                ids = [r["item_id"] for _, r in feitos if r["status"] == RESULTADO_ACEITO]
                falhas = [r["failure"] for _, r in feitos if r["status"] == RESULTADO_FALHA]
                descartados = sum(1 for _, r in feitos if r["status"] == RESULTADO_DESCARTADO)
                log = sorted(
                    (reg for n, r in feitos for reg in _log_do_slot(n, r)),
                    key=lambda t: (t["item"], t["tentativa"]),
                )
                await self._job_repository.update_progress(
                    job_id, len(ids), len(falhas), descartados, ids, falhas, log
                )

        await asyncio.gather(*(_rodar_slot(*slot) for slot in slots))

        # Estado final em ORDEM DE SLOT (deterministico, independente de qual
        # item terminou antes).
        item_ids: List[UUID] = []
        failures: List[dict] = []
        attempt_log: List[dict] = []
        total_discarded = 0
        for numero, difficulty_value, is_malicious in slots:
            r = resultados_por_slot[numero]
            attempt_log.extend(_log_do_slot(numero, r))
            if r["status"] == RESULTADO_ACEITO:
                item_ids.append(r["item_id"])
            elif r["status"] == RESULTADO_FALHA:
                failures.append(r["failure"])
            else:
                total_discarded += 1
        attempt_log.sort(key=lambda t: (t["item"], t["tentativa"]))

        await self._job_repository.update_progress(
            job_id, len(item_ids), len(failures), total_discarded, item_ids, failures, attempt_log
        )

        if len(item_ids) == 0:
            status = JobStatus.FALHOU
        elif len(failures) == 0:
            status = JobStatus.CONCLUIDO
        else:
            status = JobStatus.CONCLUIDO_COM_FALHAS

        await self._job_repository.mark_finished(job_id, status)

    async def _carregar_lotes_anteriores(
        self, job_ids: List[UUID]
    ) -> Tuple[List[List[float]], Set[str]]:
        """Embeddings e assuntos (normalizados) dos itens aceitos nos
        lotes `job_ids`, para a dedup do lote corrente. Embeddings
        recalculados a partir do conteudo guardado (nao persistidos):
        custa uma chamada de embedding a cada 100 itens, e evita uma
        tabela so para isso.
        """
        if not job_ids:
            return [], set()
        item_ids: List[UUID] = []
        for job_id in job_ids:
            job = await self._job_repository.get_by_id(job_id)
            if job is None:
                raise ValueError(f"lote {job_id} nao encontrado")
            item_ids.extend(job.item_ids)
        if not item_ids:
            return [], set()

        itens = await self._phishing_service.get_emails_by_ids(item_ids)
        assuntos = {normalizar_assunto(item.assunto) for item in itens if item.assunto}
        textos = [
            _texto_email_para_embedding(item.assunto, item.conteudo)
            if item.channel == Channel.EMAIL
            else _texto_para_embedding(item.channel.value, item.content_json or {})
            for item in itens
        ]
        embeddings: List[List[float]] = []
        for inicio in range(0, len(textos), _TAMANHO_LOTE_EMBEDDING):
            embeddings.extend(
                self._embedding_client.embed_batch(textos[inicio : inicio + _TAMANHO_LOTE_EMBEDDING])
            )
        return embeddings, assuntos

    def _maior_similaridade(
        self, embedding: List[float], accepted_embeddings: List[List[float]]
    ) -> float:
        return max(
            (_cosine_similarity(embedding, e) for e in accepted_embeddings),
            default=0.0,
        )

    def _registrar_tentativa(
        self,
        tentativas: List[dict],
        numero: int,
        similaridade: float,
        pistas_alvo=None,
        assunto_repetido: bool = False,
    ) -> str:
        """Registra a tentativa e devolve o resultado dela. Assunto
        identico ao de um item aceito conta como repeticao, como a
        similaridade acima do limiar.
        """
        if similaridade < self._dedup_threshold and not assunto_repetido:
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
        if assunto_repetido:
            registro["assunto_repetido"] = True
        if pistas_alvo is not None:
            registro["pistas_alvo"] = [getattr(p, "value", p) for p in pistas_alvo]
        tentativas.append(registro)
        return resultado

    async def _gerar_com_backoff(
        self, func: Callable[..., Awaitable], **kwargs
    ):
        """Chama `func(**kwargs)` (a geracao do item), com backoff exponencial
        quando o provider responde 429 (limite de taxa) ou 529 (sobrecarga).
        Espera BASE, 2*BASE, 4*BASE... ate `max_tentativas_taxa`; depois o erro
        PROPAGA (visivel -- o item falha, nao e silenciado). Qualquer outro erro
        (inclusive ItemInvalidoError apos as regeneracoes) propaga na hora: nao
        e transitorio, esperar nao ajuda."""
        for tentativa in range(1, self._max_tentativas_taxa + 1):
            try:
                return await func(**kwargs)
            except Exception as e:  # noqa: BLE001 -- reclassifica abaixo
                if _e_erro_de_taxa(e) and tentativa < self._max_tentativas_taxa:
                    espera = self._backoff_base_seconds * (2 ** (tentativa - 1))
                    logger.warning(
                        "Provider 429/529 (tentativa %d/%d) -- aguardando %.1fs e tentando de novo",
                        tentativa,
                        self._max_tentativas_taxa,
                        espera,
                    )
                    await asyncio.sleep(espera)
                    continue
                raise

    async def _processar_item(
        self,
        *,
        numero_item: int,
        difficulty_value: str,
        is_malicious: bool,
        channel: str,
        built,
        sampler: VariationSampler,
        ficha_inicial: Optional[VariationSpec],
        accepted_embeddings: List[List[float]],
        accepted_assuntos: Set[str],
    ) -> dict:
        """Gera UM item do lote (com dedup e backoff) e devolve um dict de
        resultado: status aceito/descartado/falha, tentativas, e item_id (se
        aceito) ou failure (se falha). Nunca levanta -- a falha de um item NAO
        derruba o lote (o chamador roda varios slots em paralelo).

        Concorrencia: a decisao de dedup (comparar com os ja aceitos e, se
        aceitar, RESERVAR) roda numa secao SINCRONA sem await -- atomica no
        asyncio -- entao dois itens que terminam ao mesmo tempo nao se aceitam
        como duplicatas um do outro. So a geracao (cara) e a persistencia rodam
        concorrentes entre itens.
        """
        tentativas: List[dict] = []
        resultado_base = {"nivel": difficulty_value, "tentativas": tentativas}
        try:
            for numero in range(1, MAX_DEDUP_RETRIES + 2):
                if channel == Channel.EMAIL.value:
                    # Ficha inicial pre-sorteada (ordem/balanceamento
                    # deterministicos); nas retentativas de dedup, uma ficha
                    # nova (repetir tenderia a reproduzir o mesmo item).
                    ficha = (
                        ficha_inicial
                        if numero == 1 and ficha_inicial is not None
                        else sampler.sortear(difficulty_value, is_malicious)
                    )

                    def sortear():
                        return sampler.sortear(difficulty_value, is_malicious)

                    draft = await self._gerar_com_backoff(
                        self._response_generator.generate_response,
                        difficulty=difficulty_value,
                        context=built.generation_context,
                        relevant_docs=built.fused_context,
                        is_malicious=is_malicious,
                        variacao=ficha,
                        sortear_variacao=sortear,
                    )
                    texto_embedding = _texto_email_para_embedding(draft.assunto, draft.conteudo)
                    assunto = draft.assunto
                    pistas_alvo = draft.target_cues if draft.target_cues is not None else []
                else:
                    draft = await self._gerar_com_backoff(
                        self._response_generator.generate_channel_item,
                        channel=channel,
                        difficulty=difficulty_value,
                        context=built.generation_context,
                        relevant_docs=built.fused_context,
                        is_malicious=is_malicious,
                    )
                    texto_embedding = _texto_para_embedding(channel, draft["content_json"])
                    assunto = None
                    pistas_alvo = []

                embedding = self._embedding_client.embed(texto_embedding)

                # --- SECAO SINCRONA (sem await) = atomica no asyncio ---------
                similaridade = self._maior_similaridade(embedding, accepted_embeddings)
                assunto_repetido = (
                    assunto is not None and normalizar_assunto(assunto) in accepted_assuntos
                )
                aceito = (
                    self._registrar_tentativa(
                        tentativas, numero, similaridade, pistas_alvo, assunto_repetido
                    )
                    == RESULTADO_ACEITO
                )
                assunto_norm = normalizar_assunto(assunto) if assunto is not None else None
                if aceito:
                    # Reserva ANTES de qualquer await: o proximo item ja ve
                    # este na dedup.
                    accepted_embeddings.append(embedding)
                    if assunto_norm is not None:
                        accepted_assuntos.add(assunto_norm)
                # --- fim da secao sincrona -----------------------------------

                if aceito:
                    if channel == Channel.EMAIL.value:
                        item = PhishingEmail(
                            **draft.model_dump(),
                            nivel=difficulty_value,
                            is_malicious=is_malicious,
                        )
                    else:
                        item = PhishingEmail(
                            channel=Channel(channel),
                            content_json=draft["content_json"],
                            explicacao=draft["explicacao"],
                            categoria=draft["categoria"],
                            nivel=difficulty_value,
                            is_malicious=is_malicious,
                        )
                    try:
                        item_id = await self._phishing_service.create_email(item)
                    except Exception:
                        # DESFAZ a reserva se a gravacao falhar: um embedding/
                        # assunto "fantasma" de um item que nao foi gravado faria
                        # itens seguintes serem descartados como duplicata de algo
                        # inexistente. (No modo serial antigo o append vinha depois
                        # do create_email; aqui ele vem antes, pela dedup atomica.)
                        try:
                            accepted_embeddings.remove(embedding)
                        except ValueError:
                            pass
                        if assunto_norm is not None:
                            accepted_assuntos.discard(assunto_norm)
                        raise
                    return {**resultado_base, "status": RESULTADO_ACEITO, "item_id": item_id}

            return {**resultado_base, "status": RESULTADO_DESCARTADO}
        except Exception as e:  # noqa: BLE001 -- falha de um item nao derruba o lote
            logger.error(
                "Falha ao gerar item %d (%s, is_malicious=%s): %s",
                numero_item,
                difficulty_value,
                is_malicious,
                e,
            )
            tentativas.append(
                {
                    "tentativa": len(tentativas) + 1,
                    "similaridade_max": None,
                    "resultado": RESULTADO_FALHA,
                }
            )
            return {
                **resultado_base,
                "status": RESULTADO_FALHA,
                "failure": {
                    "difficulty": difficulty_value,
                    "is_malicious": is_malicious,
                    "error": str(e),
                },
            }
