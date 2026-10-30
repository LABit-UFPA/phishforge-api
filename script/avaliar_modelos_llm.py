#!/usr/bin/env python3
"""Comparacao de modelos LLM (OpenAI x Anthropic) para o gerador do
PhishForge, com metricas RAGAS -- substitui a pipeline de
`avaliacoes_antigas/evaluate_models.py` (que testava so OpenAI, com
contextos inventados a mao).

O que mudou e por que:

- **Contextos reais.** Em vez de 3 prompts escritos a mao, carrega os
  cenarios de fato do estudo da aba `lotes` de `registro_lotes.xlsx`
  (5 eixos x 3 niveis x 4 cenarios). Por padrao usa uma amostra
  estratificada de 15 (1 cenario por eixo x nivel), para cobrir a grade
  inteira a um custo controlado.
- **Multi-provider.** Cada modelo roda o MESMO pipeline RAG de ponta a
  ponta (normalizacao -> HyDE -> retrieve -> rerank -> fusao -> geracao),
  variando so o modelo gerador -- OpenAI ou Anthropic, via o seletor de
  provider do ResponseGenerator/PromptNormalizer. E o que a decisao de
  producao faz (LLM_PROVIDER vale para todas as etapas de geracao),
  entao a comparacao mede o que producao realmente faria com cada modelo.
- **Juiz duplo na rubrica (anti-vies de vendor).** A comparacao e
  cross-vendor (2 geradores OpenAI x 2 Anthropic). Um juiz unico de um
  fornecedor tende a favorecer saidas do proprio fornecedor, enviesando
  a nota. Entao a RUBRICA de qualidade e pontuada por DOIS juizes fixos,
  um de cada fornecedor (OpenAI e Anthropic), ambos distintos dos
  modelos testados e de capacidade comparavel. Reportamos a nota de cada
  juiz, o ranking dos modelos sob cada um e a concordancia (Spearman +
  rankings identicos?): ranking estavel entre juizes => o vies nao
  dirige o resultado; ranking divergente => a divergencia e o achado.

Metricas:
- **Qualidade (rubrica 1-5)** -- o diferenciador do gerador: o juiz da
  uma nota ao e-mail por criterios explicitos (ver avaliar_qualidade_
  rubrica), ciente do cenario e do nivel. Pontuada pelos DOIS juizes.
- **Relevancia do contexto** -- qualidade da recuperacao (~constante
  entre modelos, mesmo retriever); juiz UNICO (OpenAI), pois vies de
  vendor ali e irrelevante. Serve de sanidade do pipeline.
- **Tempo** medio de geracao (pipeline de ponta a ponta, por item).

NAO usa Faithfulness nem Answer Relevancy: sao metricas de RAG-QA (a
resposta ancorada no contexto / respondendo a uma pergunta). Na nossa
tarefa (instrucao -> e-mail ficticio) faithfulness fica baixo por
desenho e answer relevancy e ruidosa (o user_input e instrucao, nao
pergunta -- um e-mail melhor chegou a pontuar MENOS). Por isso a
qualidade e medida por rubrica, nao por essas metricas.

Como rodar. O RAGAS fica no grupo opcional `evaluation` (nao entra na
imagem de producao), entao instale COM esse grupo; o langchain-anthropic
ja e dep principal:

    poetry install --with evaluation
    # Qdrant no ar e as chaves no .env (OPENAI_API_KEY, ANTHROPIC_API_KEY)
    poetry run python -m script.avaliar_modelos_llm --smoke     # valida o RAGAS 0.4 com 1 avaliacao (~3 chamadas)
    poetry run python -m script.avaliar_modelos_llm --dry-run   # confere o plano SEM gastar API
    poetry run python -m script.avaliar_modelos_llm             # roda de verdade

Usa RAGAS 0.4 (metricas em `ragas.metrics.collections`, `ascore`/`.value`,
juiz via `llm_factory` e embeddings via `embedding_factory`). A versao do
RAGAS e parte do instrumento de medicao -- registre-a no artigo junto do
juiz e do embedding.

Os ids dos modelos (MODELOS_A_TESTAR) e dos juizes (JUIZ_RUBRICA_OPENAI
e JUIZ_RUBRICA_ANTHROPIC) ja estao preenchidos no topo deste arquivo. Se
precisar trocar, use o id EXATO da API (nome comercial nao e id de API);
o script valida que nenhum juiz coincide com um modelo testado.
"""

import argparse
import asyncio
import json
import logging
import random
import re
import statistics
import sys
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from qdrant_client import QdrantClient
from ragas.embeddings.base import embedding_factory
from ragas.llms import llm_factory

sys.path.append(str(Path(__file__).parent.parent))

from app.core.config import settings
from app.core.reproducibilidade import commit_do_git
from app.domain.models.difficulty import Difficulty
from app.domain.services.evaluation import (
    avaliar_qualidade_rubrica,
    run_ragas_evaluation,
)
from app.domain.services.generation_pipeline import TOP_N_PARA_FUSAO, TOP_K_RETRIEVE
from app.domain.services.llm_factory import (
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    descrever_saida_estruturada,
    openai_exige_max_completion_tokens,
)
from app.domain.services.openai.embedding_client import OpenAIEmbeddingClient
from app.domain.services.prompt_normalizer import PromptNormalizer
from app.domain.services.reranker import ReRanker
from app.domain.models.variation_spec import VariationSpec
from app.domain.services.response_generator import (
    VERSAO_GERADOR,
    ItemInvalidoError,
    ResponseGenerator,
)
from app.domain.services.variation_sampler import VariationSampler
from app.infra.qdrant.store import QdrantVectorStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ===========================================================================
# CONFIGURACAO DO EXPERIMENTO -- PREENCHA OS IDS DE MODELO
# ===========================================================================


@dataclass
class ModelSpec:
    """Um modelo a testar como gerador."""

    label: str  # nome legivel para a tabela do artigo
    tier: str  # "pequeno" | "medio"
    provider: str  # PROVIDER_OPENAI | PROVIDER_ANTHROPIC
    model: str  # id EXATO da API (nao o nome comercial)
    # False para modelos de reasoning (o-series e GPT-5+, e os Claude 5.5)
    # que rejeitam temperature != 1 -- o gerador entao omite temperature em
    # todas as sub-chains. Os 4 modelos testados sao reasoning.
    supports_temperature: bool = True


# Modelos de reasoning gastam tokens de saida RACIOCINANDO antes do JSON; o
# cap de producao (2000, do gpt-4o-mini) trunca a geracao -- GPT-6 Luna deu
# "length limit reached" em 11/15 no 1o run cheio. Cap generoso so para o
# eval (reasoning + JSON).
MAX_TOKENS_GERACAO_REASONING = 16000

# Ids definidos pelo pesquisador (out/2026). Pares de tier entre OpenAI e
# Anthropic: pequeno/barato e medio. Precos aproximados (entrada/saida por
# 1M de tokens) sao so referencia de custo, nao entram na medicao. Os 4 sao
# modelos de reasoning: supports_temperature=False (temperatura omitida). Os
# Claude de reasoning geram saida estruturada via tool_choice="auto" (ver
# with_structured_output_compat), nao por thinking.
MODELOS_A_TESTAR: list[ModelSpec] = [
    # Tier pequeno/barato
    ModelSpec("GPT-6 Luna", "pequeno", PROVIDER_OPENAI, "gpt-6-luna",          # ~$0.10/$0.50 por 1M
              supports_temperature=False),
    ModelSpec("Claude Haiku 5.5", "pequeno", PROVIDER_ANTHROPIC, "claude-haiku-5-5",
              supports_temperature=False),
    # Tier medio
    ModelSpec("GPT-6 Sol", "medio", PROVIDER_OPENAI, "gpt-6-sol",              # ~$2/$10 por 1M
              supports_temperature=False),
    # claude-sonnet-4-6 (nao o 5-5): o sonnet-5-5 retornava VAZIO de forma
    # erratica em TODOS os mecanismos de saida estruturada (tool_choice
    # forcado/auto, instructor JSON/reasoning-tools, structured output
    # nativo) -- inviavel para pesquisa. A serie 4.x e estavel (mesmo
    # mecanismo instructor JSON-mode do juiz opus-4-8).
    ModelSpec("Claude Sonnet 4.6", "medio", PROVIDER_ANTHROPIC, "claude-sonnet-4-6",
              supports_temperature=False),
]

# Juizes da RUBRICA de qualidade: DOIS fixos, um de cada fornecedor,
# ambos distintos dos modelos testados e de capacidade comparavel. A
# comparacao e cross-vendor (2 geradores OpenAI x 2 Anthropic); um juiz
# unico de um fornecedor tende a favorecer as saidas do proprio
# fornecedor (self-preference de vendor), enviesando a nota. Com um juiz
# de cada lado medimos cada modelo pelos dois e olhamos se o RANKING se
# mantem -- ranking estavel => o vies nao dirige o resultado.
JUIZ_RUBRICA_OPENAI = "gpt-5.5"           # ~$5/$30 por 1M
# claude-opus-4-8 (nao o flagship claude-opus-5-5): o 5-5 RECUSA pontuar a
# rubrica (stop_reason='refusal', category 'cyber') ao ver um e-mail de
# phishing + o pedido de avalia-lo -- confirmado no --smoke, inclusive com
# preambulo defensivo explicito, devolvia qualidade_anthropic=None e
# inviabilizava o juiz duplo. O opus-4-8 (modelo anterior) avalia o
# conteudo defensivo sem recusar. Nao e nenhum dos modelos testados.
JUIZ_RUBRICA_ANTHROPIC = "claude-opus-4-8"

# Juiz de context_relevance e o embedding: UNICO (OpenAI). Context
# relevance mede recuperacao (~constante entre modelos, mesmo retriever),
# nao qualidade de geracao -- vies de vendor ali e irrelevante, nao
# precisa de juiz duplo.
JUIZ_CONTEXT_RELEVANCE = JUIZ_RUBRICA_OPENAI

# Versao dos criterios da rubrica (o artigo precisa citar o instrumento
# completo: versao do RAGAS + ids dos juizes + embedding + versao da
# rubrica). Bump a cada mudanca nos criterios de _RUBRICA_QUALIDADE.
RUBRICA_VERSAO = "2026-10-28-v1"

# Embedding do RAGAS, fixo e igual para todos (usado por context_relevance
# e, se ligado, por answer relevancy).
JUIZ_RAGAS_EMBEDDING = "text-embedding-3-large"

# Embedding da BASE vetorial (retrieve) -- o mesmo com que a colecao foi
# indexada; NAO muda entre modelos.
EMBEDDING_DA_BASE = "text-embedding-3-small"

COLLECTION_NAME = settings.COLLECTION_NAME
XLSX_PADRAO = Path(__file__).parent.parent / "registro_lotes.xlsx"


# ===========================================================================
# LEITURA DOS CONTEXTOS DO XLSX (aba `lotes`, sem dependencia extra)
# ===========================================================================

_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@dataclass
class Contexto:
    lote_id: str
    eixo: str
    nivel: str  # como no xlsx: "Fácil" | "Médio" | "Difícil"
    cenario: str  # "A".."D"
    texto: str  # o `context` do corpo_json


def _col_index(ref: str) -> int:
    letras = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for c in letras:
        n = n * 26 + (ord(c) - 64)
    return n - 1


def _ler_aba_lotes(xlsx_path: Path) -> list[Contexto]:
    """Le a aba `lotes` do xlsx direto do zip/XML (strings inline), sem
    openpyxl/pandas. Devolve um Contexto por linha de dados com
    corpo_json valido e `eixo`/`nivel`/`cenario` preenchidos.
    """
    z = zipfile.ZipFile(xlsx_path)
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    rid2tgt = {r.get("Id"): r.get("Target") for r in rels}
    alvo = None
    for s in wb.findall(".//m:sheet", _NS):
        if s.get("name") == "lotes":
            rid = s.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            alvo = rid2tgt[rid].lstrip("/")
            break
    if alvo is None:
        raise ValueError("aba 'lotes' nao encontrada no xlsx")
    if not alvo.startswith("xl/"):
        alvo = "xl/" + alvo

    root = ET.fromstring(z.read(alvo))
    linhas = []
    for row in root.findall(".//m:row", _NS):
        cells = {}
        for c in row.findall("m:c", _NS):
            isel = c.find("m:is", _NS)
            v = c.find("m:v", _NS)
            if isel is not None:
                val = "".join(t.text or "" for t in isel.findall(".//m:t", _NS))
            elif v is not None:
                val = v.text or ""
            else:
                val = ""
            cells[_col_index(c.get("r"))] = val
        linhas.append(cells)

    if not linhas:
        return []
    cab = {linhas[0].get(i, ""): i for i in linhas[0]}
    col = lambda nome: cab.get(nome)  # noqa: E731

    contextos = []
    for r in linhas[1:]:
        lote_id = r.get(col("lote_id"), "").strip()
        if not lote_id:
            continue
        corpo = r.get(col("corpo_json"), "")
        try:
            texto = json.loads(corpo).get("context", "").strip()
        except Exception:
            texto = ""
        if not texto:
            continue
        contextos.append(
            Contexto(
                lote_id=lote_id,
                eixo=r.get(col("eixo"), "").strip(),
                nivel=r.get(col("nivel_pedido"), "").strip(),
                cenario=r.get(col("cenario"), "").strip(),
                texto=texto,
            )
        )
    return contextos


def amostra_estratificada(
    contextos: list[Contexto], por_celula: int, seed: int
) -> list[Contexto]:
    """Uma amostra com `por_celula` cenarios por (eixo x nivel). Ignora
    as linhas-piloto (lote_id comecando com 'PILOTO'), que o proprio
    xlsx marca como fora do conjunto final. Deterministica pela seed.
    """
    rng = random.Random(seed)
    por_grade: dict[tuple[str, str], list[Contexto]] = {}
    for c in contextos:
        if c.lote_id.upper().startswith("PILOTO"):
            continue
        por_grade.setdefault((c.eixo, c.nivel), []).append(c)

    escolhidos = []
    for chave in sorted(por_grade):
        candidatos = sorted(por_grade[chave], key=lambda c: c.cenario)
        rng.shuffle(candidatos)
        escolhidos.extend(candidatos[:por_celula])
    return escolhidos


# ===========================================================================
# AVALIACAO
# ===========================================================================


@dataclass
class ResultadoItem:
    label: str
    tier: str
    provider: str
    model: str
    lote_id: str
    eixo: str
    nivel: str
    cenario: str
    repeticao: int
    context_relevance: Optional[float]  # recuperacao (sanidade do pipeline)
    # Rubrica 1-5 por DOIS juizes (um de cada fornecedor) -- diferenciador
    # do gerador, blindado contra self-preference de vendor.
    qualidade_openai: Optional[float]
    qualidade_anthropic: Optional[float]
    qualidade_justificativa_openai: Optional[str]
    qualidade_justificativa_anthropic: Optional[str]
    tempo_s: float
    # Item gerado COMPLETO (draft.model_dump): conteudo, remetente,
    # assunto, links, cues, premise_alignment, phish_scale
    # (difficulty_estimated) e validacao (regeneracoes, pistas removidas,
    # pistas_alvo_ausentes/fora_do_alvo). Persistido para calcular
    # aderencia/dificuldade/diversidade/vazamento OFFLINE sobre os MESMOS
    # e-mails que os juizes pontuaram -- sem pagar uma 2a geracao.
    item: Optional[dict] = None
    # Mecanismo de saida estruturada deste modelo (nativo x instructor
    # JSON-mode) -- por item, alem do resumo por fornecedor no metadata.
    saida_estruturada: Optional[str] = None
    erro: Optional[str] = None
    # Categoria da falha (quando erro != None), para o relatorio separar
    # RECUSA de conteudo (achado do estudo -- ex.: Anthropic recusar gerar
    # phishing) de erro de infra/limite/validacao. Melhor-esforco (ver
    # _classificar_erro); a mensagem crua fica em `erro`.
    erro_tipo: Optional[str] = None


def _build_juiz_openai(model: str, client):
    """Juiz RAGAS OpenAI (llm_factory) com correcao do bug de deteccao da
    ragas 0.4.3: para um modelo com minor version no nome (ex.:
    `gpt-5.5`), o `is_reasoning_model` da ragas faz `int("5.5")` ->
    ValueError e NAO mapeia `max_tokens` -> `max_completion_tokens`,
    entao a API dos modelos GPT-5+ rejeita (400: "Unsupported parameter:
    'max_tokens'"). Como `_map_openai_params` deixa os `model_args`
    passarem inalterados para modelos nao-detectados, normalizamos na
    mao: `max_completion_tokens` no lugar de `max_tokens`,
    `temperature=1` (unico aceito) e sem `top_p`.
    """
    juiz = llm_factory(model, client=client)
    if openai_exige_max_completion_tokens(model):
        args = getattr(juiz, "model_args", None)
        if isinstance(args, dict):
            max_t = args.pop("max_tokens", 1024)
            args.setdefault("max_completion_tokens", max_t)
            args.pop("top_p", None)
            args["temperature"] = 1.0
    return juiz


def _build_juiz_anthropic(model: str, raw_client):
    """Juiz RAGAS Anthropic.

    NAO usa `llm_factory(provider='anthropic')`: para anthropic o ragas
    0.4.3 chama `instructor.from_anthropic(client)` SEM `mode`, caindo no
    default ANTHROPIC_TOOLS (tool_choice forcado), que modelos como
    `claude-opus-5-5` rejeitam (HTTP 400: "tool_choice type 'tool'/'any'
    not supported for this model"). O `mode=` do llm_factory e ignorado
    nesse ramo.

    Entao montamos a mesma classe (InstructorLLM) na mao, com o cliente
    instructor em modo JSON (prefill, sem tool_choice). O bug do
    `int("5.5")` nao afeta aqui: `_map_openai_params` so roda para
    provider openai/azure; anthropic faz pass-through dos model_args
    (temperature/top_p/max_tokens), todos aceitos pela API da Anthropic.
    """
    import instructor
    from ragas.llms.base import InstructorLLM

    patched = instructor.from_anthropic(raw_client, mode=instructor.Mode.ANTHROPIC_JSON)
    juiz = InstructorLLM(client=patched, model=model, provider=PROVIDER_ANTHROPIC)
    # Modelos de reasoning da Anthropic (claude-opus-5-5) depreciam
    # `temperature` (e `top_p`): a API recusa com 400. O pass-through dos
    # model_args enviaria o default 0.01 -- removemos os dois (max_tokens
    # fica: a API da Anthropic sempre exige). Mesma ideia do patch do
    # juiz OpenAI gpt-5.5.
    args = getattr(juiz, "model_args", None)
    if isinstance(args, dict):
        args.pop("temperature", None)
        args.pop("top_p", None)
    return juiz


def construir_gerador(
    spec: ModelSpec, openai_key: str, anthropic_key: str, seed: Optional[int]
) -> tuple[ResponseGenerator, PromptNormalizer]:
    """Gerador + normalizador para `spec`, com os ajustes por modelo que a
    comparacao exige:
    - temperatura omitida em reasoning (supports_temperature=False);
    - cap de saida generoso (reasoning gasta tokens ANTES do JSON -- o cap
      padrao truncava o GPT-6 Luna);
    - saida estruturada dos Claude de reasoning via tool_choice="auto"
      (tratado dentro de ResponseGenerator/PromptNormalizer por
      with_structured_output_compat -- eles recusam o tool_choice forcado).

    Usada pela rodada E pelo --smoke -- mesma construcao nos dois, para o
    smoke exercitar o caminho real de geracao (nao um ainvoke cru, que foi
    o furo que deixou o 1o run cheio falhar em producao).
    """
    temp = settings.LLM_TEMPERATURE if spec.supports_temperature else None
    rg = ResponseGenerator(
        api_key=openai_key,
        model_name=spec.model,
        temperature=temp,
        provider=spec.provider,
        anthropic_api_key=anthropic_key,
        seed=seed,
        max_tokens_geracao=MAX_TOKENS_GERACAO_REASONING,
    )
    norm = PromptNormalizer(
        api_key=openai_key,
        model_name=spec.model,
        provider=spec.provider,
        anthropic_api_key=anthropic_key,
        seed=seed,
        # Reasoning (supports_temperature=False): omite a temperatura 0.0 do
        # normalizador -- os Claude 5.5 recusam temperature != 1. Nao-reasoning
        # mantem 0.0 (normalizacao deterministica).
        temperature=(0.0 if spec.supports_temperature else None),
        # Reasoning gasta tokens raciocinando ANTES do JSON tambem aqui; o
        # default 2000 da Anthropic exauria o Haiku 5.5 (devolvia vazio).
        max_tokens=MAX_TOKENS_GERACAO_REASONING,
    )
    return rg, norm


def _ficha_do_contexto(ctx: Contexto, difficulty: str, seed: Optional[int]) -> VariationSpec:
    """Ficha de variacao DETERMINISTICA por contexto: a MESMA para os 4
    modelos (comparacao justa), derivada do codigo do contexto (lote_id) +
    seed global. Com isso o eval usa o mesmo prompt ficha-driven da producao,
    e as pistas-alvo ficam fixas por contexto -- a ADERENCIA a elas vira
    metrica objetiva e comparavel entre modelos (a validacao do item calcula
    pistas_alvo_ausentes/fora_do_alvo sobre essas pistas). O VariationSampler
    com uma rng semeada e reproduzivel.
    """
    rng = random.Random(f"{seed}:{ctx.lote_id}")
    return VariationSampler(rng=rng).sortear(difficulty, is_malicious=True)


def _classificar_erro(exc: Exception) -> str:
    """Categoria best-effort da falha de um item, para o relatorio separar o
    que e falha do MODELO (recusa de conteudo -- achado do estudo) do que e
    falha de INFRA/integracao (tokens, HTTP, formato de saida, validacao do
    pipeline). A mensagem crua fica preservada em ResultadoItem.erro.

    Categorias:
    - recusa: o modelo se negou a gerar (politica/conteudo). Inclui o
      "list index out of range" do instructor+Anthropic, que e a assinatura
      de resposta VAZIA (tipicamente recusa suave) nesses modelos.
    - limite_tokens: saida truncada por teto de tokens.
    - validacao: item gerado reprovado nas regras do pipeline (ItemInvalido).
    - disclaimer: subcaso de validacao -- o modelo insistiu em narrar
      "simulacao/conscientizacao" no e-mail e falhou apos as regeneracoes
      (achado por modelo: alguns so geram se auto-denunciando).
    - formato: modelo respondeu, mas sem saida estruturada valida (JSON
      invalido / nao chamou a tool) -- falha de integracao, nao do modelo.
    - http: erro de rede/status da API (timeout, 429, 5xx).
    - tool_choice: 400 de tool_choice (nao deve ocorrer apos o JSON-mode).
    - outro: nao classificado.
    """
    if isinstance(exc, ItemInvalidoError):
        # Falha por INSISTIR na meta-narracao de simulacao (o modelo nao
        # consegue gerar sem se auto-denunciar) e um achado por modelo --
        # separada das demais reprovacoes de validacao.
        if "disclaimer_simulacao" in str(exc).lower():
            return "disclaimer"
        return "validacao"
    msg = str(exc).lower()
    if any(k in msg for k in (
        "refus", "stop_reason", "usage policy", "content filter",
        "content_policy", "content management policy", "blocked", "safety",
        "index out of range",  # instructor+Anthropic: resposta vazia (recusa suave)
    )):
        return "recusa"
    if any(k in msg for k in (
        "length limit", "max_tokens", "max_completion_tokens", "max output",
        "maximum context",
    )):
        return "limite_tokens"
    if "tool_choice" in msg:
        return "tool_choice"
    if any(k in msg for k in (
        "timeout", "timed out", "connection", "rate limit", "429",
        "too many requests", "500", "502", "503", "overloaded", "httpx",
    )):
        return "http"
    if any(k in msg for k in (
        "instructorretry", "validation error", "could not parse", "failed to parse",
        "no tool call", "nonetype", "json",
    )):
        return "formato"  # respondeu mas sem saida estruturada valida (integracao)
    return "outro"


class Avaliador:
    def __init__(self, seed: Optional[int] = None):
        if not settings.OPENAI_API_KEY:
            raise SystemExit("OPENAI_API_KEY nao configurada (.env).")
        self.openai_key = settings.OPENAI_API_KEY
        self.anthropic_key = settings.ANTHROPIC_API_KEY
        # Semente de geracao (reprodutibilidade, exigencia do protocolo).
        # A MESMA que estratifica a amostra -- uma rodada inteira fica
        # presa a uma seed. Chega ao gerador/normalizador via _gerador ->
        # build_chat_model: best-effort na OpenAI, ignorada na Anthropic
        # (sem parametro de seed) -- por isso o item gerado e persistido
        # por linha, a reprodutibilidade que vale cross-vendor.
        self.seed = seed

        # --- componentes COMPARTILHADOS (constantes entre todos os modelos) ---
        self.qdrant = QdrantClient(url=settings.QDRANT_URL)
        self.embedding_base = OpenAIEmbeddingClient(
            api_key=self.openai_key, model=EMBEDDING_DA_BASE
        )
        self.vector_store = QdrantVectorStore(
            client=self.qdrant, embedding_client=self.embedding_base
        )
        self.reranker = ReRanker()

        # Juizes RAGAS (API nativa 0.4: as metricas/rubrica chamam
        # `.agenerate` no LLM do `llm_factory`; o embedding vem do
        # `embedding_factory`). A RUBRICA e pontuada pelos DOIS (um de
        # cada fornecedor). context_relevance usa so o OpenAI.
        openai_client = AsyncOpenAI(api_key=self.openai_key)
        self.juiz_openai = _build_juiz_openai(JUIZ_RUBRICA_OPENAI, openai_client)
        self.eval_embeddings = embedding_factory(
            "openai", model=JUIZ_RAGAS_EMBEDDING, client=openai_client
        )
        # context_relevance usa o juiz OpenAI (unico).
        self.eval_llm = self.juiz_openai

        if not self.anthropic_key:
            raise SystemExit("ANTHROPIC_API_KEY nao configurada (.env) -- juiz duplo exige.")
        anthropic_client = AsyncAnthropic(api_key=self.anthropic_key)
        self.juiz_anthropic = _build_juiz_anthropic(JUIZ_RUBRICA_ANTHROPIC, anthropic_client)

        self.resultados: list[ResultadoItem] = []

    def _gerador(self, spec: ModelSpec) -> tuple[ResponseGenerator, PromptNormalizer]:
        return construir_gerador(spec, self.openai_key, self.anthropic_key, self.seed)

    async def _avaliar_item(
        self, spec: ModelSpec, ctx: Contexto, repeticao: int
    ) -> ResultadoItem:
        inicio = datetime.now()
        base = dict(
            label=spec.label, tier=spec.tier, provider=spec.provider, model=spec.model,
            lote_id=ctx.lote_id, eixo=ctx.eixo, nivel=ctx.nivel, cenario=ctx.cenario,
            repeticao=repeticao,
            saida_estruturada=descrever_saida_estruturada(spec.provider, spec.model),
        )
        try:
            rg, norm = self._gerador(spec)
            difficulty = Difficulty(ctx.nivel).value  # normaliza acento/caixa

            normalized = await norm.normalize(ctx.texto)
            search_query = normalized.search_query
            generation_context = normalized.generation_context

            try:
                hyde = await rg.generate_hypothetical_answer(search_query)
            except Exception:
                hyde = search_query

            candidatos = self.vector_store.query(
                collection_name=COLLECTION_NAME, query_text=hyde, top_k=TOP_K_RETRIEVE
            )
            reranked = self.reranker.rerank(search_query, candidatos)
            contexts = [
                doc.payload["parent_content"]
                for doc in reranked[:TOP_N_PARA_FUSAO]
                if "parent_content" in doc.payload
            ]
            fused = await rg.fuse_and_summarize_context(
                generation_context=generation_context, contexts=contexts
            )

            # Ficha deterministica por contexto (VariationSampler): a MESMA
            # para os 4 modelos neste contexto, derivada do codigo do contexto
            # + seed -> comparacao justa e reproduzivel, no MESMO prompt que a
            # producao usa. Com a ficha, o item traz pistas-alvo, e a validacao
            # calcula pistas_alvo_ausentes -> aderencia vira metrica primaria.
            ficha = _ficha_do_contexto(ctx, difficulty, self.seed)
            draft = await rg.generate_response(
                difficulty=difficulty,
                context=generation_context,
                relevant_docs=fused,
                is_malicious=True,
                variacao=ficha,
            )
            # mode="json": o item vai inteiro para o JSON do relatorio
            # (campo `item`), entao enums/aninhados tem de sair ja
            # serializaveis (str, nao membros de Enum nem datetime). Os
            # campos de texto que _formatar_email le ficam identicos.
            email = draft.model_dump(mode="json") if hasattr(draft, "model_dump") else dict(draft)
            full_answer, so_corpo = _formatar_email(email)

            # Metricas da comparacao: rel. contexto (recuperacao) +
            # rubrica de qualidade (gerador). Faithfulness e answer
            # relevancy ficam de fora -- sao de RAG-QA e nao medem bem
            # geracao criativa (ver run_ragas_evaluation e a rubrica).
            scores = await run_ragas_evaluation(
                search_question=search_query,
                generation_question=generation_context,
                expanded_answer=so_corpo,
                full_answer=full_answer,
                contexts=contexts,
                eval_llm=self.eval_llm,
                eval_embeddings=self.eval_embeddings,
                incluir_faithfulness=False,
                incluir_response_relevancy=False,
            )
            # Rubrica pontuada pelos DOIS juizes (um de cada fornecedor),
            # para blindar contra self-preference de vendor.
            qual_o = await avaliar_qualidade_rubrica(
                self.juiz_openai, cenario=ctx.texto, nivel=ctx.nivel, email=so_corpo
            )
            qual_a = await avaliar_qualidade_rubrica(
                self.juiz_anthropic, cenario=ctx.texto, nivel=ctx.nivel, email=so_corpo
            )
            tempo = (datetime.now() - inicio).total_seconds()
            logger.info(
                "OK %s | %s %s %s rep%d | cr=%s qual(o/a)=%s/%s t=%.1fs",
                spec.label, ctx.eixo, ctx.nivel, ctx.cenario, repeticao,
                _fmt(scores.get("context_relevance")),
                _fmt(qual_o.get("qualidade")), _fmt(qual_a.get("qualidade")),
                tempo,
            )
            return ResultadoItem(
                **base,
                context_relevance=scores.get("context_relevance"),
                qualidade_openai=qual_o.get("qualidade"),
                qualidade_anthropic=qual_a.get("qualidade"),
                qualidade_justificativa_openai=qual_o.get("qualidade_justificativa"),
                qualidade_justificativa_anthropic=qual_a.get("qualidade_justificativa"),
                tempo_s=tempo,
                # Guarda o item COMPLETO que os juizes acabaram de pontuar
                # (o mesmo `email` ja formatado acima). Antes era descartado
                # aqui -- a aderencia/dificuldade/diversidade/vazamento viram
                # calculaveis offline sobre ESTE e-mail, sem uma 2a geracao.
                item=email,
            )
        except Exception as e:
            tempo = (datetime.now() - inicio).total_seconds()
            tipo = _classificar_erro(e)
            logger.error(
                "ERRO[%s] %s | %s %s %s: %s",
                tipo, spec.label, ctx.eixo, ctx.nivel, ctx.cenario, e,
            )
            return ResultadoItem(
                **base, context_relevance=None,
                qualidade_openai=None, qualidade_anthropic=None,
                qualidade_justificativa_openai=None, qualidade_justificativa_anthropic=None,
                tempo_s=tempo, erro=str(e), erro_tipo=tipo,
            )

    def _carregar_checkpoint(self, checkpoint_path: Optional[Path]) -> set:
        """Resume: pre-carrega os itens BEM-SUCEDIDOS de uma rodada anterior.

        Cada item e gravado em JSONL assim que termina (ver `rodar`), entao
        um timeout/crash no meio da rodada NAO perde o que ja foi pago --
        uma re-execucao com os mesmos parametros retoma de onde parou. A
        1a tentativa da cheia estourou o `timeout` com ~81/180 itens e
        nada salvo (o relatorio so e escrito no fim); este checkpoint
        existe para isso nao se repetir.

        So os itens com `erro is None` contam como feitos (sao pulados no
        resume). Os que falharam -- 429 por creditos OpenAI zerados, HTTP,
        timeout, recusa -- NAO entram em `feitos`: sao re-tentados na
        proxima rodada. Assim um incidente transitorio (ex.: creditos
        acabaram no meio) so custa os itens que de fato falharam, nao a
        rodada inteira. Linhas repetidas da mesma chave: a ultima vence (um
        item re-tentado e salvo de novo), entao um erro seguido de sucesso
        conta como feito. Retorna o conjunto de chaves (label, lote_id,
        repeticao) bem-sucedidas.
        """
        feitos: set = set()
        if not checkpoint_path or not checkpoint_path.exists():
            return feitos
        # Ultimo estado por chave (um item re-tentado aparece 2x no arquivo).
        por_chave: dict = {}
        for linha in checkpoint_path.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if not linha:
                continue
            try:
                r = ResultadoItem(**json.loads(linha))
            except Exception:
                # linha truncada (crash no meio de uma escrita): ignora.
                continue
            por_chave[(r.label, r.lote_id, r.repeticao)] = r
        falhos = 0
        for chave, r in por_chave.items():
            if r.erro is None:
                feitos.add(chave)
                self.resultados.append(r)
            else:
                falhos += 1
        if feitos or falhos:
            logger.info(
                "Resume: %d itens OK reaproveitados, %d com erro serao re-tentados (%s)",
                len(feitos), falhos, checkpoint_path,
            )
        return feitos

    async def rodar(
        self,
        contextos: list[Contexto],
        repeticoes: int,
        checkpoint_path: Optional[Path] = None,
    ):
        feitos = self._carregar_checkpoint(checkpoint_path)
        ckpt = open(checkpoint_path, "a", encoding="utf-8") if checkpoint_path else None
        try:
            for spec in MODELOS_A_TESTAR:
                for rep in range(1, repeticoes + 1):
                    for ctx in contextos:
                        if (spec.label, ctx.lote_id, rep) in feitos:
                            continue
                        r = await self._avaliar_item(spec, ctx, rep)
                        self.resultados.append(r)
                        if ckpt is not None:
                            # grava+flush por item: o custo ja pago sobrevive
                            # a um timeout/crash do processo.
                            ckpt.write(json.dumps(vars(r), ensure_ascii=False) + "\n")
                            ckpt.flush()
        finally:
            if ckpt is not None:
                ckpt.close()


# ---- formatacao e relatorio -----------------------------------------------


def _formatar_email(email: dict) -> tuple[str, str]:
    """(texto completo p/ faithfulness, so corpo p/ response relevancy).
    Email como texto legivel, nao JSON cru -- o JSON degrada as metricas.
    """
    conteudo = (email.get("conteudo") or "").replace("\\n", "\n")
    cabecalho = []
    if email.get("remetente"):
        cabecalho.append(f"De: {email['remetente']}")
    if email.get("receptor"):
        cabecalho.append(f"Para: {email['receptor']}")
    if email.get("assunto"):
        cabecalho.append(f"Assunto: {email['assunto']}")
    so_corpo = "\n".join(cabecalho + ["", conteudo])
    extras = []
    if email.get("explicacao"):
        extras.append("--- Analise Tecnica ---")
        extras.append(email["explicacao"])
    completo = "\n".join([so_corpo, ""] + extras) if extras else so_corpo
    return completo, so_corpo


def _fmt(v) -> str:
    return f"{v:.3f}" if isinstance(v, (int, float)) else "N/A"


def _media_desvio(valores: list[float]) -> tuple[Optional[float], Optional[float]]:
    vals = [v for v in valores if isinstance(v, (int, float))]
    if not vals:
        return None, None
    media = statistics.mean(vals)
    desvio = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    return media, desvio


def _agregar(resultados: list[ResultadoItem], chave) -> dict:
    grupos: dict = {}
    for r in resultados:
        grupos.setdefault(chave(r), []).append(r)
    saida = {}
    for g, rs in grupos.items():
        ok = [r for r in rs if r.erro is None]
        cr_m, cr_d = _media_desvio([r.context_relevance for r in ok])
        qo_m, qo_d = _media_desvio([r.qualidade_openai for r in ok])
        qa_m, qa_d = _media_desvio([r.qualidade_anthropic for r in ok])
        t_m, _ = _media_desvio([r.tempo_s for r in ok])
        # Erros por categoria (recusa de conteudo vs infra/limite/validacao):
        # a taxa de recusa e um achado do estudo, nao pode sumir como "erro".
        erros_tipo = Counter(r.erro_tipo or "outro" for r in rs if r.erro is not None)
        saida[g] = {
            "n": len(ok),
            "erros": len(rs) - len(ok),
            "erros_por_tipo": dict(erros_tipo),
            "taxa_recusa": (erros_tipo.get("recusa", 0) / len(rs)) if rs else None,
            "context_relevance": cr_m, "context_relevance_std": cr_d,
            "qualidade_openai": qo_m, "qualidade_openai_std": qo_d,
            "qualidade_anthropic": qa_m, "qualidade_anthropic_std": qa_d,
            # Media dos dois juizes: nota "consenso" por modelo.
            "qualidade_media_juizes": (
                (qo_m + qa_m) / 2 if (qo_m is not None and qa_m is not None) else None
            ),
            "tempo_s": t_m,
        }
    return saida


def _spearman(pares: list[tuple[float, float]]) -> Optional[float]:
    """Correlacao de Spearman (rho) entre duas series pareadas, com
    ranks medios para empates (notas 1-5 empatam muito). None quando ha
    menos de 2 pares ou variancia zero. Implementada na mao para nao
    depender de scipy.
    """
    pares = [(a, b) for a, b in pares if isinstance(a, (int, float)) and isinstance(b, (int, float))]
    if len(pares) < 2:
        return None

    def ranks(valores: list[float]) -> list[float]:
        ordenado = sorted(range(len(valores)), key=lambda i: valores[i])
        r = [0.0] * len(valores)
        i = 0
        while i < len(ordenado):
            j = i
            while j + 1 < len(ordenado) and valores[ordenado[j + 1]] == valores[ordenado[i]]:
                j += 1
            rank_medio = (i + j) / 2 + 1  # ranks de 1..n, media no empate
            for k in range(i, j + 1):
                r[ordenado[k]] = rank_medio
            i = j + 1
        return r

    xa = ranks([a for a, _ in pares])
    xb = ranks([b for _, b in pares])
    n = len(pares)
    ma, mb = sum(xa) / n, sum(xb) / n
    cov = sum((xa[i] - ma) * (xb[i] - mb) for i in range(n))
    va = sum((xa[i] - ma) ** 2 for i in range(n)) ** 0.5
    vb = sum((xb[i] - mb) ** 2 for i in range(n)) ** 0.5
    if va == 0 or vb == 0:
        return None
    return cov / (va * vb)


def _concordancia_juizes(resultados: list[ResultadoItem]) -> dict:
    """Concordancia entre os dois juizes na rubrica: Spearman das notas
    por item, taxa de concordancia exata (mesma nota 1-5), e os rankings
    dos modelos sob cada juiz -- com a leitura central do metodo: se o
    ranking dos 4 modelos e o mesmo sob os dois juizes, o vies de vendor
    nao esta dirigindo o resultado.
    """
    ok = [
        r for r in resultados
        if r.erro is None and r.qualidade_openai is not None and r.qualidade_anthropic is not None
    ]
    pares = [(r.qualidade_openai, r.qualidade_anthropic) for r in ok]
    rho = _spearman(pares)
    exata = (
        sum(1 for a, b in pares if a == b) / len(pares) if pares else None
    )

    por_modelo = _agregar(ok, lambda r: r.label)
    def ranking(chave_nota: str) -> list[str]:
        itens = [(lbl, a[chave_nota]) for lbl, a in por_modelo.items() if a[chave_nota] is not None]
        return [lbl for lbl, _ in sorted(itens, key=lambda t: t[1], reverse=True)]

    rank_openai = ranking("qualidade_openai")
    rank_anthropic = ranking("qualidade_anthropic")
    return {
        "n_itens": len(pares),
        "spearman_notas_por_item": rho,
        "concordancia_exata": exata,
        "ranking_juiz_openai": rank_openai,
        "ranking_juiz_anthropic": rank_anthropic,
        "rankings_identicos": rank_openai == rank_anthropic and bool(rank_openai),
    }


def _tabela_markdown(por_modelo: dict) -> str:
    # Qualidade (rubrica 1-5) pontuada pelos DOIS juizes + rel. contexto
    # (recuperacao / sanidade do pipeline) + tempo. Faithfulness e answer
    # relevancy ficam de fora (metricas de RAG-QA, ver run_ragas_evaluation
    # e a rubrica).
    linhas = [
        "| Modelo | Tier | Qual. juiz OpenAI (1-5) | Qual. juiz Anthropic (1-5) "
        "| Rel. contexto (%) | Tempo (s) | n (erros) |",
        "|---|---|---|---|---|---|---|",
    ]
    def pct(m, d):
        if m is None:
            return "—"
        return f"{m*100:.1f} ± {d*100:.0f}" if d else f"{m*100:.1f}"
    def nota(m, d):
        if m is None:
            return "—"
        return f"{m:.2f} ± {d:.2f}" if d else f"{m:.2f}"
    for spec in MODELOS_A_TESTAR:
        a = por_modelo.get(spec.label)
        if not a:
            continue
        # tempo_s e None quando o modelo nao teve NENHUM item OK (era o
        # crash do 1o run: f"{None:.1f}"). Guard aqui.
        tempo = f"{a['tempo_s']:.1f}" if a["tempo_s"] is not None else "—"
        linhas.append(
            f"| {spec.label} | {spec.tier} | "
            f"{nota(a['qualidade_openai'], a['qualidade_openai_std'])} | "
            f"{nota(a['qualidade_anthropic'], a['qualidade_anthropic_std'])} | "
            f"{pct(a['context_relevance'], a['context_relevance_std'])} | "
            f"{tempo} | {a['n']} ({a['erros']}) |"
        )
    return "\n".join(linhas)


def _bloco_concordancia(conc: dict) -> str:
    def f3(v):
        return f"{v:.3f}" if isinstance(v, (int, float)) else "—"
    linhas = [
        "## Concordancia entre juizes (rubrica)",
        f"- Spearman das notas por item: {f3(conc['spearman_notas_por_item'])} "
        f"(n={conc['n_itens']})",
        f"- Concordancia exata (mesma nota 1-5): "
        f"{f3(conc['concordancia_exata'] * 100) if conc['concordancia_exata'] is not None else '—'}%",
        f"- Ranking sob o juiz OpenAI:    {' > '.join(conc['ranking_juiz_openai']) or '—'}",
        f"- Ranking sob o juiz Anthropic: {' > '.join(conc['ranking_juiz_anthropic']) or '—'}",
        f"- Rankings identicos entre os juizes: "
        f"{'SIM -- o vies de vendor nao esta dirigindo o resultado' if conc['rankings_identicos'] else 'NAO -- a divergencia e o achado'}",
    ]
    return "\n".join(linhas)


def _bloco_erros(por_modelo: dict) -> str:
    """Erros por modelo SEPARANDO recusa de conteudo (achado do estudo --
    ex.: um gerador recusar criar phishing) de infra/limite/validacao. A
    taxa de recusa so ganha chao com por_celula>=2-3 (com n=1 por celula e
    ruidosa). A mensagem crua de cada erro fica em detalhado[].erro.
    """
    linhas = ["## Erros por modelo (recusa vs infra/limite/validacao)"]
    for spec in MODELOS_A_TESTAR:
        a = por_modelo.get(spec.label)
        if not a:
            continue
        tipos = a.get("erros_por_tipo") or {}
        detalhe = ", ".join(f"{k}={v}" for k, v in sorted(tipos.items())) or "nenhum"
        tr = a.get("taxa_recusa")
        tr_s = f"{tr * 100:.0f}%" if isinstance(tr, (int, float)) else "—"
        linhas.append(
            f"- {spec.label}: {a['erros']} erro(s) [{detalhe}] · taxa de recusa: {tr_s}"
        )
    return "\n".join(linhas)


def _git_commit() -> Optional[str]:
    """Hash curto do commit atual para o metadata (reprodutibilidade), com
    sufixo '-dirty' se houver alteracoes. Delega ao helper compartilhado, que
    aceita a variavel de ambiente GIT_COMMIT como fonte (caminho de dentro do
    Docker, onde `git` pode faltar ou cair em 'dubious ownership' -- foi assim
    que o relatorio saiu com git_commit=None)."""
    return commit_do_git()


def salvar_relatorio(av: Avaliador, contextos, repeticoes, out_dir: Path) -> Path:
    por_modelo = _agregar(av.resultados, lambda r: r.label)
    por_tier = _agregar(av.resultados, lambda r: r.tier)
    por_nivel = _agregar(av.resultados, lambda r: f"{r.label} | {r.nivel}")
    concordancia = _concordancia_juizes(av.resultados)

    relatorio = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "ragas_versao": "0.4.3",
            "rubrica_versao": RUBRICA_VERSAO,
            # Reprodutibilidade: versao do gerador (prompts+validacoes) e o
            # commit exato -- muda a geracao, tem de constar no relatorio
            # (ex.: a regra/validacao anti-disclaimer do piloto 6).
            "versao_gerador": VERSAO_GERADOR,
            "git_commit": _git_commit(),
            "metricas": ["qualidade_rubrica_1a5 (2 juizes)", "context_relevance"],
            "metricas_nota": (
                "Qualidade: rubrica holistica 1-5 (ciente do nivel), pontuada por DOIS "
                "juizes fixos (um de cada fornecedor) para blindar contra "
                "self-preference de vendor -- diferenciador do gerador. Context "
                "relevance: qualidade da recuperacao (juiz unico OpenAI; ~constante "
                "entre modelos, vies de vendor irrelevante). Faithfulness e answer "
                "relevancy ficaram de fora: metricas de RAG-QA, nao medem bem geracao "
                "criativa."
            ),
            "modelos": [vars(m) for m in MODELOS_A_TESTAR],
            "juiz_rubrica_openai": JUIZ_RUBRICA_OPENAI,
            "juiz_rubrica_anthropic": JUIZ_RUBRICA_ANTHROPIC,
            "juiz_context_relevance": JUIZ_CONTEXT_RELEVANCE,
            "embedding_ragas": JUIZ_RAGAS_EMBEDDING,
            "embedding_base": EMBEDDING_DA_BASE,
            # ASSIMETRIA DE METODO (documentar no artigo): a saida estruturada
            # dos geradores usa mecanismos diferentes por fornecedor. OpenAI
            # tem saida estruturada nativa confiavel; nos Claude 5.5 de
            # reasoning, nenhum caminho do langchain-anthropic e confiavel
            # (tool_choice forcado -> 400; "auto" -> o modelo as vezes nao
            # chama a tool, varia por prompt; thinking.enabled -> recusado,
            # pedem "adaptive"), entao usamos instructor em JSON-mode -- o
            # MESMO mecanismo (ja validado) do juiz Anthropic. Thinking
            # desligado nos dois. Isso evita penalizar os Claude por falhas de
            # integracao em vez de qualidade do modelo.
            "saida_estruturada": {
                "openai": "with_structured_output nativo (tool calling)",
                "anthropic": "instructor Mode.ANTHROPIC_JSON (prefill, sem tool_choice/thinking)",
                "thinking": "desligado (ambos os fornecedores)",
            },
            "contextos": [c.lote_id for c in contextos],
            "repeticoes": repeticoes,
            "seed": av.seed,
            "reprodutibilidade": (
                f"Seed {av.seed} fixa (1) a amostra estratificada de contextos e (2) a "
                "geracao via build_chat_model. OpenAI: seed best-effort (determinismo "
                "dependente do system_fingerprint). Anthropic: NAO tem parametro de seed, "
                "logo suas geracoes nao sao bit-reproduziveis. Por isso cada linha de "
                "'detalhado' guarda o item gerado COMPLETO (campo 'item'): a aderencia/"
                "dificuldade/diversidade/vazamento se calculam offline sobre os MESMOS "
                "e-mails que os juizes pontuaram, sem uma 2a geracao paga."
            ),
            "total_itens": len(av.resultados),
        },
        "concordancia_juizes": concordancia,
        "por_modelo": por_modelo,
        "por_tier": por_tier,
        "por_modelo_e_nivel": por_nivel,
        "detalhado": [vars(r) for r in av.resultados],
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    caminho = out_dir / f"comparacao_modelos_{ts}.json"
    caminho.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"comparacao_modelos_{ts}.md").write_text(
        "# Comparacao de modelos (RAGAS)\n\n"
        f"Juizes da rubrica: `{JUIZ_RUBRICA_OPENAI}` (OpenAI) + `{JUIZ_RUBRICA_ANTHROPIC}` "
        f"(Anthropic) · amostra: {len(contextos)} contextos · repeticoes: {repeticoes}\n\n"
        + _tabela_markdown(por_modelo) + "\n\n" + _bloco_erros(por_modelo) + "\n\n"
        + _bloco_concordancia(concordancia) + "\n",
        encoding="utf-8",
    )
    print(
        "\n" + _tabela_markdown(por_modelo) + "\n\n" + _bloco_erros(por_modelo) + "\n\n"
        + _bloco_concordancia(concordancia) + "\n"
    )
    logger.info("Relatorio salvo em %s", caminho)
    return caminho


# ===========================================================================
# CLI
# ===========================================================================


def _validar_sem_placeholder():
    juizes_rubrica = [JUIZ_RUBRICA_OPENAI, JUIZ_RUBRICA_ANTHROPIC]
    pend = [m.model for m in MODELOS_A_TESTAR if "PREENCHER" in m.model]
    pend += [j for j in juizes_rubrica if "PREENCHER" in j]
    if pend:
        raise SystemExit(
            "Preencha os ids de modelo antes de rodar (ainda ha placeholders): "
            + ", ".join(pend)
            + "\nEdite MODELOS_A_TESTAR e JUIZ_RUBRICA_* no topo deste arquivo."
        )
    testados = {m.model for m in MODELOS_A_TESTAR}
    colididos = [j for j in juizes_rubrica if j in testados]
    if colididos:
        raise SystemExit(
            f"Juiz(es) tambem na lista de testados: {colididos} -- "
            "o juiz nao pode ser um modelo testado (vies de auto-preferencia)."
        )


def _dry_run(contextos, repeticoes):
    itens = len(MODELOS_A_TESTAR) * len(contextos) * repeticoes
    n_gen_calls = itens * 3  # norm + hyde + fusao + geracao ~ 3-4 por item
    n_juiz_calls = itens * 3  # context_relevance (~2 chamadas) + rubrica x2 juizes
    print("=== PLANO (dry-run, nada foi chamado) ===")
    print(f"Modelos: {[m.label + ' (' + m.model + ')' for m in MODELOS_A_TESTAR]}")
    print(f"Juizes da rubrica: {JUIZ_RUBRICA_OPENAI} (OpenAI) + {JUIZ_RUBRICA_ANTHROPIC} (Anthropic)")
    print(f"Juiz de context_relevance: {JUIZ_CONTEXT_RELEVANCE}")
    print(f"Contextos ({len(contextos)}): {[c.lote_id for c in contextos]}")
    print(f"Repeticoes: {repeticoes}")
    print(f"Itens avaliados: {itens}")
    print(f"~Chamadas de geracao: ~{n_gen_calls} | ~Chamadas de juiz: ~{n_juiz_calls}")
    print("Confira os ids e rode sem --dry-run para valer.")


async def _smoke():
    """Valida, com poucas chamadas reais e sem RAG, as pontas que so a
    execucao real exercita:

    1. Juiz OpenAI: context_relevance + rubrica.
    2. Juiz Anthropic: rubrica (confirma o wiring do 2o fornecedor).
    3. Geradores OpenAI de nova geracao (build_chat_model) -- 1 chamada
       trivial cada, para pegar problema de parametro (max_tokens vs
       max_completion_tokens / temperature) antes da comparacao cheia.

    Nao testa Qdrant nem o pipeline RAG completo. Anthropic como gerador
    nao e exercitado aqui (so como juiz); a rodada cheia o cobre.
    """
    _validar_sem_placeholder()
    if not settings.OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY nao configurada (.env).")
    if not settings.ANTHROPIC_API_KEY:
        raise SystemExit("ANTHROPIC_API_KEY nao configurada (.env) -- juiz duplo exige.")

    # Juizes
    openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    juiz_openai = _build_juiz_openai(JUIZ_RUBRICA_OPENAI, openai_client)
    eval_embeddings = embedding_factory("openai", model=JUIZ_RAGAS_EMBEDDING, client=openai_client)
    juiz_anthropic = _build_juiz_anthropic(
        JUIZ_RUBRICA_ANTHROPIC, AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    )
    eval_llm = juiz_openai
    print(f"[1/2] Smoke dos juizes RAGAS 0.4 (OpenAI={JUIZ_RUBRICA_OPENAI}, Anthropic={JUIZ_RUBRICA_ANTHROPIC}) ...")
    # Par realista (consulta de busca <-> contexto academico <-> e-mail
    # coerente com o cenario). So demonstra o wiring (rel. contexto +
    # rubrica de qualidade); nao substitui a comparacao real sobre os
    # contextos do xlsx.
    email_exemplo = (
        "De: Secretaria Academica <secretaria@uni-exemplo.edu.br>\n"
        "Para: joao.silva@uni-exemplo.edu.br\n"
        "Assunto: Pendencia na sua matricula do semestre\n\n"
        "Prezado Joao,\n\n"
        "Identificamos uma pendencia de documentacao na sua matricula deste "
        "semestre. Para evitar o cancelamento da inscricao nas disciplinas, "
        "regularize seus dados no portal do aluno ate amanha as 18h pelo "
        "endereco informado abaixo. Em caso de duvida, procure a secretaria.\n\n"
        "Atenciosamente,\nSecretaria Academica"
    )
    scores = await run_ragas_evaluation(
        search_question="phishing email pending enrollment urgency deadline credential link",
        generation_question=(
            "Write a realistic phishing email, from a university, warning a "
            "student about a pending enrollment issue that must be resolved via a link."
        ),
        expanded_answer=email_exemplo,
        full_answer=email_exemplo,
        contexts=[
            "Phishing emails frequently impersonate a trusted institution and create "
            "urgency with a short deadline, directing the victim to a link to 'resolve' "
            "a pending issue and disclose credentials."
        ],
        eval_llm=eval_llm,
        eval_embeddings=eval_embeddings,
        incluir_faithfulness=False,
        incluir_response_relevancy=False,
    )
    cenario_exemplo = (
        "E-mail de uma universidade avisando o estudante sobre uma pendencia de matricula."
    )
    qual_o = await avaliar_qualidade_rubrica(
        juiz_openai, cenario=cenario_exemplo, nivel="Médio", email=email_exemplo
    )
    qual_a = await avaliar_qualidade_rubrica(
        juiz_anthropic, cenario=cenario_exemplo, nivel="Médio", email=email_exemplo
    )
    print("    Rel. contexto:", scores.get("context_relevance"))
    print(f"    Qualidade juiz OpenAI (1-5): {qual_o.get('qualidade')} -- {qual_o.get('qualidade_justificativa')}")
    print(f"    Qualidade juiz Anthropic (1-5): {qual_a.get('qualidade')} -- {qual_a.get('qualidade_justificativa')}")
    if scores.get("error") or scores.get("context_relevance") is None:
        raise SystemExit(f"Smoke do juiz (rel. contexto) FALHOU: {scores.get('error')}")
    if qual_o.get("qualidade") is None:
        raise SystemExit(f"Smoke da rubrica (juiz OpenAI) FALHOU: {qual_o.get('error')}")
    if qual_a.get("qualidade") is None:
        raise SystemExit(f"Smoke da rubrica (juiz Anthropic) FALHOU: {qual_a.get('error')}")

    # 2. Geradores -- os QUATRO x os 3 NIVEIS, pelo CAMINHO REAL (normalize +
    # generate_response FICHA-DRIVEN, o mesmo da producao), nao um ainvoke
    # cru. Sem Qdrant (relevant_docs triviais). Classificacao por item:
    #  - draft valido        -> OK (integracao ok; confere ficha aplicada:
    #                           variation_spec + target_cues + pistas_alvo_ausentes);
    #  - ItemInvalidoError   -> OK p/ gate (API/ficha ok; validacao de conteudo
    #                           barrou no contexto trivial);
    #  - recusa              -> AVISA (modelo devolveu vazio; vira TAXA DE
    #                           RECUSA na cheia -- nao bloqueia o gate);
    #  - formato/tool_choice/limite/http/outro -> FALHA de integracao (bloqueia).
    # Gate (criterios do pesquisador): nenhuma falha de integracao; ao menos 1
    # item com a ficha de fato aplicada.
    print("[2/2] Smoke dos geradores (4 modelos x 3 niveis, ficha-driven real) ...")
    docs_trivial = (
        "Phishing emails impersonate a trusted institution and create urgency with a short "
        "deadline, directing the victim to a link to resolve a pending issue."
    )
    ctx_por_nivel = {
        "Fácil": Contexto("SMOKE-F", "E0", "Fácil", "A",
                          "Uma organizacao avisa uma pessoa sobre uma pendencia simples a resolver."),
        "Médio": Contexto("SMOKE-M", "E0", "Médio", "A",
                          "Uma organizacao notifica uma pessoa sobre uma pendencia a regularizar."),
        "Difícil": Contexto("SMOKE-D", "E0", "Difícil", "A",
                            "Uma organizacao comunica uma pessoa sobre um procedimento a confirmar."),
    }
    falhas, recusas = [], []
    ficha_aplicada = False
    for spec in MODELOS_A_TESTAR:
        rg, norm = construir_gerador(
            spec, settings.OPENAI_API_KEY, settings.ANTHROPIC_API_KEY, seed=42
        )
        for nivel, ctx in ctx_por_nivel.items():
            difficulty = Difficulty(nivel).value
            ficha = _ficha_do_contexto(ctx, difficulty, seed=42)
            try:
                normalized = await norm.normalize(ctx.texto)
                draft = await rg.generate_response(
                    difficulty=difficulty, context=normalized.generation_context,
                    relevant_docs=docs_trivial, is_malicious=True, variacao=ficha,
                )
                email = draft.model_dump(mode="json") if hasattr(draft, "model_dump") else dict(draft)
                val = email.get("validacao") or {}
                tc = email.get("target_cues")
                tem_ficha = bool(email.get("variation_spec")) and tc and "pistas_alvo_ausentes" in val
                ficha_aplicada = ficha_aplicada or tem_ficha
                print(
                    f"    {spec.label} [{nivel}]: OK -> assunto={str(email.get('assunto'))[:38]!r} "
                    f"target_cues={tc} ausentes={val.get('pistas_alvo_ausentes')}"
                )
            except ItemInvalidoError as e:
                print(f"    {spec.label} [{nivel}]: OK (API/ficha ok; validacao barrou: {str(e)[:70]})")
            except Exception as e:
                tipo = _classificar_erro(e)
                if tipo == "recusa":
                    recusas.append(f"{spec.label}[{nivel}]")
                    print(f"    {spec.label} [{nivel}]: ⚠ RECUSA -> {str(e)[:90]}")
                else:
                    falhas.append(f"{spec.label}[{nivel}] [{tipo}]")
                    print(f"    {spec.label} [{nivel}]: FALHOU [{tipo}] -> {str(e)[:130]}")
    if falhas:
        raise SystemExit("Smoke dos geradores FALHOU (integracao): " + "; ".join(falhas))
    if not ficha_aplicada:
        raise SystemExit(
            "Smoke: nenhum item veio com variation_spec + target_cues + "
            "pistas_alvo_ausentes -- a ficha nao esta sendo aplicada."
        )
    if recusas:
        print("\n⚠ RECUSAS (modelo devolveu vazio; vira taxa de recusa na cheia): "
              + "; ".join(recusas))
    print("\nSmoke [2/2] OK: integracao valida nos 3 niveis e ficha aplicada "
          "(target_cues/pistas_alvo_ausentes presentes).")


async def _main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xlsx", type=Path, default=XLSX_PADRAO, help="caminho do registro_lotes.xlsx")
    ap.add_argument("--por-celula", type=int, default=1, help="cenarios por eixo x nivel (default 1 => 15 contextos)")
    ap.add_argument("--repeticoes", type=int, default=1, help="execucoes por contexto (p/ o +/- de variacao)")
    ap.add_argument("--seed", type=int, default=42, help="semente: amostra estratificada + geracao (best-effort OpenAI; Anthropic nao tem seed)")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent.parent / "avaliacoes_antigas" / "resultados")
    ap.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="JSONL de checkpoint (resume). Default: <out>/checkpoint_seed<seed>_pc<por_celula>_rep<rep>.jsonl. "
        "Grava cada item ao terminar; re-rodar com os mesmos parametros retoma de onde parou.",
    )
    ap.add_argument(
        "--sem-checkpoint",
        action="store_true",
        help="desliga o checkpoint/resume (nao grava JSONL incremental).",
    )
    ap.add_argument("--dry-run", action="store_true", help="mostra o plano e sai, sem chamar API")
    ap.add_argument("--smoke", action="store_true", help="valida o RAGAS 0.4 com 1 avaliacao minima (~3 chamadas ao juiz)")
    args = ap.parse_args()

    if args.smoke:
        await _smoke()
        return

    _validar_sem_placeholder()
    todos = _ler_aba_lotes(args.xlsx)
    contextos = amostra_estratificada(todos, por_celula=args.por_celula, seed=args.seed)
    if not contextos:
        raise SystemExit("nenhum contexto carregado do xlsx")

    if args.dry_run:
        _dry_run(contextos, args.repeticoes)
        return

    checkpoint_path: Optional[Path] = None
    if not args.sem_checkpoint:
        checkpoint_path = args.checkpoint or (
            args.out / f"checkpoint_seed{args.seed}_pc{args.por_celula}_rep{args.repeticoes}.jsonl"
        )
        args.out.mkdir(parents=True, exist_ok=True)

    av = Avaliador(seed=args.seed)
    await av.rodar(contextos, args.repeticoes, checkpoint_path=checkpoint_path)
    salvar_relatorio(av, contextos, args.repeticoes, args.out)
    print("\nConcluido.")


if __name__ == "__main__":
    asyncio.run(_main())
