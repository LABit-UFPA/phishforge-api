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

Metricas (reference-free, sem ground truth), coerentes com o que o
artigo ja reporta:
- Relevancia do contexto: os documentos recuperados sao relevantes para
  a consulta de busca.
- Relevancia da resposta: o e-mail gerado responde ao cenario pedido.
- Faithfulness: o e-mail se sustenta nos documentos recuperados.
- Tempo medio de geracao (pipeline de ponta a ponta, por item).

Mapeamento RAGAS (QA -> geracao), mantido identico ao dos experimentos
anteriores para os numeros serem comparaveis: user_input = consulta de
busca (contexto) / cenario de geracao (resposta); retrieved_contexts =
top-N documentos pos-rerank; response = e-mail gerado.

Como rodar. O RAGAS fica no grupo opcional `evaluation` (nao entra na
imagem de producao), entao instale COM esse grupo; o langchain-anthropic
ja e dep principal:

    poetry install --with evaluation
    # Qdrant no ar e as chaves no .env (OPENAI_API_KEY, ANTHROPIC_API_KEY)
    poetry run python -m script.avaliar_modelos_llm --dry-run   # confere o plano SEM gastar API
    poetry run python -m script.avaliar_modelos_llm             # roda de verdade

ANTES de rodar, PREENCHA os ids de modelo OpenAI marcados com
`<<PREENCHER-...>>` abaixo e o `JUIZ_RAGAS_MODEL` com os ids EXATOS da
API (os nomes comerciais nao sao ids de API). O script recusa rodar
enquanto houver placeholder (fail-fast, antes de gastar credito).
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

from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from qdrant_client import QdrantClient
from ragas.embeddings import LangchainEmbeddingsWrapper
from ragas.llms import LangchainLLMWrapper

sys.path.append(str(Path(__file__).parent.parent))

from app.core.config import settings
from app.domain.models.difficulty import Difficulty
from app.domain.services.evaluation import run_ragas_evaluation
from app.domain.services.generation_pipeline import TOP_N_PARA_FUSAO, TOP_K_RETRIEVE
from app.domain.services.llm_factory import PROVIDER_ANTHROPIC, PROVIDER_OPENAI
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


# Os ids da Anthropic sao os da API; os da OpenAI estao como placeholder
# porque os nomes comerciais (GPT-6 Luna, GPT-5.5, ...) nao sao ids de
# API -- troque pelos ids exatos antes de rodar.
MODELOS_A_TESTAR: list[ModelSpec] = [
    # Tier pequeno/barato
    ModelSpec("GPT pequeno", "pequeno", PROVIDER_OPENAI, "<<PREENCHER-OPENAI-PEQUENO>>"),
    ModelSpec("Claude Haiku 5.5", "pequeno", PROVIDER_ANTHROPIC, "claude-haiku-5-5"),
    # Tier medio
    ModelSpec("GPT medio", "medio", PROVIDER_OPENAI, "<<PREENCHER-OPENAI-MEDIO>>"),
    ModelSpec("Claude Sonnet 5.5", "medio", PROVIDER_ANTHROPIC, "claude-sonnet-5-5"),
]

# Juiz RAGAS: um GPT-5-class da OpenAI, FIXO, que NAO esta em
# MODELOS_A_TESTAR. Troque pelo id exato da API.
JUIZ_RAGAS_MODEL = "<<PREENCHER-OPENAI-JUIZ-GPT5>>"

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
    context_relevance: Optional[float]
    faithfulness: Optional[float]
    response_relevancy: Optional[float]
    tempo_s: float
    erro: Optional[str] = None


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

        # Juiz RAGAS fixo (nao e nenhum modelo testado).
        self.eval_llm = LangchainLLMWrapper(
            ChatOpenAI(model=JUIZ_RAGAS_MODEL, api_key=self.openai_key)
        )
        self.eval_embeddings = LangchainEmbeddingsWrapper(
            OpenAIEmbeddings(model=JUIZ_RAGAS_EMBEDDING, openai_api_key=self.openai_key)
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

            scores = await run_ragas_evaluation(
                search_question=search_query,
                generation_question=generation_context,
                expanded_answer=so_corpo,
                full_answer=full_answer,
                contexts=contexts,
                eval_llm=self.eval_llm,
                eval_embeddings=self.eval_embeddings,
            )
            tempo = (datetime.now() - inicio).total_seconds()
            logger.info(
                "OK %s | %s %s %s rep%d | cr=%s rr=%s t=%.1fs",
                spec.label, ctx.eixo, ctx.nivel, ctx.cenario, repeticao,
                _fmt(scores.get("context_relevance")), _fmt(scores.get("response_relevancy")),
                tempo,
            )
            return ResultadoItem(
                **base,
                context_relevance=scores.get("context_relevance"),
                faithfulness=scores.get("faithfulness"),
                response_relevancy=scores.get("response_relevancy"),
                tempo_s=tempo,
            )
        except Exception as e:
            tempo = (datetime.now() - inicio).total_seconds()
            logger.error("ERRO %s | %s %s %s: %s", spec.label, ctx.eixo, ctx.nivel, ctx.cenario, e)
            return ResultadoItem(
                **base, context_relevance=None, faithfulness=None,
                response_relevancy=None, tempo_s=tempo, erro=str(e),
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
        rr_m, rr_d = _media_desvio([r.response_relevancy for r in ok])
        f_m, f_d = _media_desvio([r.faithfulness for r in ok])
        t_m, _ = _media_desvio([r.tempo_s for r in ok])
        saida[g] = {
            "n": len(ok),
            "erros": len(rs) - len(ok),
            "context_relevance": cr_m, "context_relevance_std": cr_d,
            "response_relevancy": rr_m, "response_relevancy_std": rr_d,
            "faithfulness": f_m, "faithfulness_std": f_d,
            "tempo_s": t_m,
        }
    return saida


def _tabela_markdown(por_modelo: dict) -> str:
    linhas = [
        "| Modelo | Tier | Rel. contexto (%) | Rel. resposta (%) | Faithfulness (%) | Tempo (s) | n |",
        "|---|---|---|---|---|---|---|",
    ]
    def pct(m, d):
        if m is None:
            return "—"
        return f"{m*100:.1f} ± {d*100:.0f}" if d else f"{m*100:.1f}"
    for spec in MODELOS_A_TESTAR:
        a = por_modelo.get(spec.label)
        if not a:
            continue
        linhas.append(
            f"| {spec.label} | {spec.tier} | "
            f"{pct(a['context_relevance'], a['context_relevance_std'])} | "
            f"{pct(a['response_relevancy'], a['response_relevancy_std'])} | "
            f"{pct(a['faithfulness'], a['faithfulness_std'])} | "
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


async def _main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--xlsx", type=Path, default=XLSX_PADRAO, help="caminho do registro_lotes.xlsx")
    ap.add_argument("--por-celula", type=int, default=1, help="cenarios por eixo x nivel (default 1 => 15 contextos)")
    ap.add_argument("--repeticoes", type=int, default=1, help="execucoes por contexto (p/ o +/- de variacao)")
    ap.add_argument("--seed", type=int, default=42, help="semente da amostra estratificada")
    ap.add_argument("--out", type=Path, default=Path(__file__).parent.parent / "avaliacoes_antigas" / "resultados")
    ap.add_argument("--dry-run", action="store_true", help="mostra o plano e sai, sem chamar API")
    args = ap.parse_args()

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
