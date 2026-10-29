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
- **Juiz fixo.** O avaliador RAGAS (o LLM que pontua) e UM so modelo,
  igual para todos os testados, e NAO e nenhum dos testados -- senao a
  comparacao mediria vies de auto-preferencia e variacao do juiz, nao a
  qualidade do gerador. Idem o modelo de embedding do RAGAS. Ambos
  OpenAI, fixos.

Metricas (reference-free, sem ground truth), as MESMAS da Tabela 2 do
artigo:
- Relevancia do contexto: os documentos recuperados sao relevantes para
  a consulta de busca (qualidade da recuperacao; ~constante entre os
  modelos, serve de sanidade do pipeline).
- Relevancia da resposta: o e-mail gerado responde ao cenario pedido
  (o diferenciador real entre modelos).
- Tempo medio de geracao (pipeline de ponta a ponta, por item).

NAO usa Faithfulness: ela mede quantas afirmacoes da resposta se
sustentam no contexto recuperado -- faz sentido em RAG-QA, nao numa
geracao criativa. O e-mail de phishing e um cenario ficticio que NAO
deve repetir os artigos academicos, entao faithfulness fica baixo por
desenho (nao mede a qualidade do gerador). A Tabela 2 do artigo ja
usava so rel. contexto + rel. resposta.

Mapeamento RAGAS (QA -> geracao), mantido identico ao dos experimentos
anteriores para os numeros serem comparaveis: user_input = consulta de
busca (contexto) / cenario de geracao (resposta); retrieved_contexts =
top-N documentos pos-rerank; response = e-mail gerado.

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

Os ids dos modelos (MODELOS_A_TESTAR) e do juiz (JUIZ_RAGAS_MODEL) ja
estao preenchidos no topo deste arquivo. Se precisar trocar, use o id
EXATO da API (nome comercial nao e id de API); o script valida que o
juiz nao coincide com nenhum modelo testado.
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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from openai import AsyncOpenAI
from qdrant_client import QdrantClient
from ragas.embeddings.base import embedding_factory
from ragas.llms import llm_factory

sys.path.append(str(Path(__file__).parent.parent))

from app.core.config import settings
from app.domain.models.difficulty import Difficulty
from app.domain.services.evaluation import (
    avaliar_qualidade_rubrica,
    run_ragas_evaluation,
)
from app.domain.services.generation_pipeline import TOP_N_PARA_FUSAO, TOP_K_RETRIEVE
from app.domain.services.llm_factory import (
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    build_chat_model,
    openai_exige_max_completion_tokens,
)
from app.domain.services.openai.embedding_client import OpenAIEmbeddingClient
from app.domain.services.prompt_normalizer import PromptNormalizer
from app.domain.services.reranker import ReRanker
from app.domain.services.response_generator import ResponseGenerator
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
    # False para modelos de reasoning (o-series e alguns GPT-5) que
    # rejeitam temperature != 1 -- o gerador entao omite temperature em
    # todas as sub-chains.
    supports_temperature: bool = True


# Ids definidos pelo pesquisador (out/2026). Pares de tier entre OpenAI e
# Anthropic: pequeno/barato e medio. Precos aproximados (entrada/saida por
# 1M de tokens) sao so referencia de custo, nao entram na medicao.
MODELOS_A_TESTAR: list[ModelSpec] = [
    # Tier pequeno/barato
    ModelSpec("GPT-6 Luna", "pequeno", PROVIDER_OPENAI, "gpt-6-luna"),        # ~$0.10/$0.50 por 1M
    ModelSpec("Claude Haiku 5.5", "pequeno", PROVIDER_ANTHROPIC, "claude-haiku-5-5"),
    # Tier medio
    ModelSpec("GPT-6 Sol", "medio", PROVIDER_OPENAI, "gpt-6-sol"),           # ~$2/$10 por 1M
    ModelSpec("Claude Sonnet 5.5", "medio", PROVIDER_ANTHROPIC, "claude-sonnet-5-5"),
]

# Juiz RAGAS: FIXO e igual para todos, distinto dos dois tiers testados
# (evita vies de auto-preferencia). ~$5/$30 por 1M.
JUIZ_RAGAS_MODEL = "gpt-5.5"

# Embedding do RAGAS (Response Relevancy), fixo e igual para todos.
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
    qualidade: Optional[float]  # rubrica 1-5 (diferenciador do gerador)
    qualidade_justificativa: Optional[str]
    tempo_s: float
    erro: Optional[str] = None


def _build_juiz_ragas(client):
    """Juiz RAGAS (llm_factory) com correcao do bug de deteccao da
    ragas 0.4.3: para um modelo com minor version no nome (ex.:
    `gpt-5.5`), o `is_reasoning_model` da ragas faz `int("5.5")` ->
    ValueError e NAO mapeia `max_tokens` -> `max_completion_tokens`,
    entao a API dos modelos GPT-5+ rejeita (400: "Unsupported parameter:
    'max_tokens'"). Como `_map_openai_params` deixa os `model_args`
    passarem inalterados para modelos nao-detectados, normalizamos na
    mao: `max_completion_tokens` no lugar de `max_tokens`,
    `temperature=1` (unico aceito) e sem `top_p`.
    """
    juiz = llm_factory(JUIZ_RAGAS_MODEL, client=client)
    if openai_exige_max_completion_tokens(JUIZ_RAGAS_MODEL):
        args = getattr(juiz, "model_args", None)
        if isinstance(args, dict):
            max_t = args.pop("max_tokens", 1024)
            args.setdefault("max_completion_tokens", max_t)
            args.pop("top_p", None)
            args["temperature"] = 1.0
    return juiz


class Avaliador:
    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise SystemExit("OPENAI_API_KEY nao configurada (.env).")
        self.openai_key = settings.OPENAI_API_KEY
        self.anthropic_key = settings.ANTHROPIC_API_KEY

        # --- componentes COMPARTILHADOS (constantes entre todos os modelos) ---
        self.qdrant = QdrantClient(url=settings.QDRANT_URL)
        self.embedding_base = OpenAIEmbeddingClient(
            api_key=self.openai_key, model=EMBEDDING_DA_BASE
        )
        self.vector_store = QdrantVectorStore(
            client=self.qdrant, embedding_client=self.embedding_base
        )
        self.reranker = ReRanker()

        # Juiz RAGAS fixo (nao e nenhum modelo testado), na API nativa do
        # RAGAS 0.4: as metricas de `collections` chamam `.agenerate` no
        # LLM do `llm_factory` e usam o embedding do `embedding_factory`
        # -- os wrappers Langchain da 0.3 nao servem para elas.
        judge_client = AsyncOpenAI(api_key=self.openai_key)
        self.eval_llm = _build_juiz_ragas(judge_client)
        self.eval_embeddings = embedding_factory(
            "openai", model=JUIZ_RAGAS_EMBEDDING, client=judge_client
        )

        self.resultados: list[ResultadoItem] = []

    def _gerador(self, spec: ModelSpec) -> tuple[ResponseGenerator, PromptNormalizer]:
        temp = settings.LLM_TEMPERATURE if spec.supports_temperature else None
        rg = ResponseGenerator(
            api_key=self.openai_key,
            model_name=spec.model,
            temperature=temp,
            provider=spec.provider,
            anthropic_api_key=self.anthropic_key,
        )
        norm = PromptNormalizer(
            api_key=self.openai_key,
            model_name=spec.model,
            provider=spec.provider,
            anthropic_api_key=self.anthropic_key,
        )
        return rg, norm

    async def _avaliar_item(
        self, spec: ModelSpec, ctx: Contexto, repeticao: int
    ) -> ResultadoItem:
        inicio = datetime.now()
        base = dict(
            label=spec.label, tier=spec.tier, provider=spec.provider, model=spec.model,
            lote_id=ctx.lote_id, eixo=ctx.eixo, nivel=ctx.nivel, cenario=ctx.cenario,
            repeticao=repeticao,
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

            draft = await rg.generate_response(
                difficulty=difficulty,
                context=generation_context,
                relevant_docs=fused,
                is_malicious=True,
            )
            email = draft.model_dump() if hasattr(draft, "model_dump") else dict(draft)
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
            qual = await avaliar_qualidade_rubrica(
                self.eval_llm, cenario=ctx.texto, nivel=ctx.nivel, email=so_corpo
            )
            tempo = (datetime.now() - inicio).total_seconds()
            logger.info(
                "OK %s | %s %s %s rep%d | cr=%s qual=%s t=%.1fs",
                spec.label, ctx.eixo, ctx.nivel, ctx.cenario, repeticao,
                _fmt(scores.get("context_relevance")), _fmt(qual.get("qualidade")),
                tempo,
            )
            return ResultadoItem(
                **base,
                context_relevance=scores.get("context_relevance"),
                qualidade=qual.get("qualidade"),
                qualidade_justificativa=qual.get("qualidade_justificativa"),
                tempo_s=tempo,
            )
        except Exception as e:
            tempo = (datetime.now() - inicio).total_seconds()
            logger.error("ERRO %s | %s %s %s: %s", spec.label, ctx.eixo, ctx.nivel, ctx.cenario, e)
            return ResultadoItem(
                **base, context_relevance=None, qualidade=None,
                qualidade_justificativa=None, tempo_s=tempo, erro=str(e),
            )

    async def rodar(self, contextos: list[Contexto], repeticoes: int):
        for spec in MODELOS_A_TESTAR:
            for rep in range(1, repeticoes + 1):
                for ctx in contextos:
                    r = await self._avaliar_item(spec, ctx, rep)
                    self.resultados.append(r)


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
        q_m, q_d = _media_desvio([r.qualidade for r in ok])
        t_m, _ = _media_desvio([r.tempo_s for r in ok])
        saida[g] = {
            "n": len(ok),
            "erros": len(rs) - len(ok),
            "context_relevance": cr_m, "context_relevance_std": cr_d,
            "qualidade": q_m, "qualidade_std": q_d,
            "tempo_s": t_m,
        }
    return saida


def _tabela_markdown(por_modelo: dict) -> str:
    # Qualidade (rubrica 1-5, o diferenciador do gerador) + rel. contexto
    # (recuperacao / sanidade do pipeline) + tempo. Faithfulness e answer
    # relevancy ficam de fora (metricas de RAG-QA, ver run_ragas_evaluation
    # e a rubrica).
    linhas = [
        "| Modelo | Tier | Qualidade (1-5) | Rel. contexto (%) | Tempo (s) | n |",
        "|---|---|---|---|---|---|",
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
        linhas.append(
            f"| {spec.label} | {spec.tier} | "
            f"{nota(a['qualidade'], a['qualidade_std'])} | "
            f"{pct(a['context_relevance'], a['context_relevance_std'])} | "
            f"{a['tempo_s']:.1f} | {a['n']} |"
        )
    return "\n".join(linhas)


def salvar_relatorio(av: Avaliador, contextos, repeticoes, out_dir: Path) -> Path:
    por_modelo = _agregar(av.resultados, lambda r: r.label)
    por_tier = _agregar(av.resultados, lambda r: r.tier)
    por_nivel = _agregar(av.resultados, lambda r: f"{r.label} | {r.nivel}")

    relatorio = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "ragas_versao": "0.4.3",
            "metricas": ["qualidade_rubrica_1a5", "context_relevance"],
            "metricas_nota": (
                "Qualidade: rubrica holistica 1-5 (ciente do nivel) dada pelo juiz "
                "fixo -- diferenciador do gerador. Context relevance: qualidade da "
                "recuperacao (sanidade do pipeline). Faithfulness e answer relevancy "
                "ficaram de fora: metricas de RAG-QA, nao medem bem geracao criativa "
                "(o e-mail ficticio nao deve repetir os artigos; o user_input e "
                "instrucao, nao pergunta)."
            ),
            "modelos": [vars(m) for m in MODELOS_A_TESTAR],
            "juiz_ragas": JUIZ_RAGAS_MODEL,
            "embedding_ragas": JUIZ_RAGAS_EMBEDDING,
            "embedding_base": EMBEDDING_DA_BASE,
            "contextos": [c.lote_id for c in contextos],
            "repeticoes": repeticoes,
            "total_itens": len(av.resultados),
        },
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
        f"Juiz: `{JUIZ_RAGAS_MODEL}` · amostra: {len(contextos)} contextos · "
        f"repeticoes: {repeticoes}\n\n" + _tabela_markdown(por_modelo) + "\n",
        encoding="utf-8",
    )
    print("\n" + _tabela_markdown(por_modelo) + "\n")
    logger.info("Relatorio salvo em %s", caminho)
    return caminho


# ===========================================================================
# CLI
# ===========================================================================


def _validar_sem_placeholder():
    pend = [m.model for m in MODELOS_A_TESTAR if "PREENCHER" in m.model]
    if "PREENCHER" in JUIZ_RAGAS_MODEL:
        pend.append(JUIZ_RAGAS_MODEL)
    if pend:
        raise SystemExit(
            "Preencha os ids de modelo antes de rodar (ainda ha placeholders): "
            + ", ".join(pend)
            + "\nEdite MODELOS_A_TESTAR e JUIZ_RAGAS_MODEL no topo deste arquivo."
        )
    juizes = {m.model for m in MODELOS_A_TESTAR}
    if JUIZ_RAGAS_MODEL in juizes:
        raise SystemExit(
            f"O juiz ({JUIZ_RAGAS_MODEL}) nao pode ser um dos modelos testados "
            "(vies de auto-preferencia)."
        )


def _dry_run(contextos, repeticoes):
    n_gen_calls = len(MODELOS_A_TESTAR) * len(contextos) * repeticoes * 3  # norm+hyde+fusao+ger ~ 3-4
    n_juiz_calls = len(MODELOS_A_TESTAR) * len(contextos) * repeticoes * 3  # 3 metricas RAGAS
    print("=== PLANO (dry-run, nada foi chamado) ===")
    print(f"Modelos: {[m.label + ' (' + m.model + ')' for m in MODELOS_A_TESTAR]}")
    print(f"Juiz RAGAS fixo: {JUIZ_RAGAS_MODEL}")
    print(f"Contextos ({len(contextos)}): {[c.lote_id for c in contextos]}")
    print(f"Repeticoes: {repeticoes}")
    print(f"Itens avaliados: {len(MODELOS_A_TESTAR) * len(contextos) * repeticoes}")
    print(f"~Chamadas de geracao: ~{n_gen_calls} | ~Chamadas do juiz: ~{n_juiz_calls}")
    print("Confira os ids e rode sem --dry-run para valer.")


async def _smoke():
    """Valida, com poucas chamadas reais e sem RAG, as duas pontas que
    so a execucao real exercita:

    1. Juiz RAGAS 0.4 (as 3 metricas em dados minimos) -- ~3 chamadas.
    2. Gerador OpenAI de nova geracao (build_chat_model) -- 1 chamada
       trivial por modelo OpenAI testado, para pegar o problema de
       parametro (max_tokens vs max_completion_tokens / temperature)
       antes da comparacao cheia.

    Nao testa Qdrant, Anthropic nem o pipeline RAG completo.
    """
    _validar_sem_placeholder()
    if not settings.OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY nao configurada (.env).")

    # 1. Juiz RAGAS
    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    eval_llm = _build_juiz_ragas(client)
    eval_embeddings = embedding_factory("openai", model=JUIZ_RAGAS_EMBEDDING, client=client)
    print(f"[1/2] Smoke do juiz RAGAS 0.4 + rubrica ({JUIZ_RAGAS_MODEL}) ...")
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
    qual = await avaliar_qualidade_rubrica(
        eval_llm,
        cenario="E-mail de uma universidade avisando o estudante sobre uma pendencia de matricula.",
        nivel="Médio",
        email=email_exemplo,
    )
    print("    Rel. contexto:", scores.get("context_relevance"))
    print(f"    Qualidade (rubrica 1-5): {qual.get('qualidade')} -- {qual.get('qualidade_justificativa')}")
    if scores.get("error") or scores.get("context_relevance") is None:
        raise SystemExit(f"Smoke do juiz (rel. contexto) FALHOU: {scores.get('error')}")
    if qual.get("qualidade") is None:
        raise SystemExit(f"Smoke da rubrica FALHOU: {qual.get('error')}")

    # 2. Geradores OpenAI (so os OpenAI; Anthropic e outra API/credencial)
    print("[2/2] Smoke dos geradores OpenAI (1 chamada trivial cada) ...")
    for spec in MODELOS_A_TESTAR:
        if spec.provider != PROVIDER_OPENAI:
            continue
        temp = settings.LLM_TEMPERATURE if spec.supports_temperature else None
        chat = build_chat_model(
            spec.provider, spec.model, openai_api_key=settings.OPENAI_API_KEY,
            temperature=temp, max_tokens=64,
        )
        try:
            resp = await chat.ainvoke("Responda apenas: ok")
        except Exception as e:
            raise SystemExit(f"Smoke do gerador {spec.label} ({spec.model}) FALHOU: {e}")
        texto = getattr(resp, "content", str(resp))
        print(f"    {spec.label} ({spec.model}): OK -> {str(texto)[:40]!r}")

    print("\nSmoke OK: juiz RAGAS 0.4 e geradores OpenAI respondem. Pode rodar a comparacao cheia.")


async def _main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xlsx", type=Path, default=XLSX_PADRAO, help="caminho do registro_lotes.xlsx")
    ap.add_argument("--por-celula", type=int, default=1, help="cenarios por eixo x nivel (default 1 => 15 contextos)")
    ap.add_argument("--repeticoes", type=int, default=1, help="execucoes por contexto (p/ o +/- de variacao)")
    ap.add_argument("--seed", type=int, default=42, help="semente da amostra estratificada")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent.parent / "avaliacoes_antigas" / "resultados")
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

    av = Avaliador()
    await av.rodar(contextos, args.repeticoes)
    salvar_relatorio(av, contextos, args.repeticoes, args.out)
    print("\nConcluido.")


if __name__ == "__main__":
    asyncio.run(_main())
