"""Smoke do item 1 (plano de producao): gera 3 itens validos pelo CAMINHO DE
PRODUCAO (o Container -- mesma fiacao do /generate e do lote), confirmando que
o default de producao e Claude Sonnet 4.6 pela Anthropic, via instructor
JSON-mode (sem temperature), sem fallback silencioso.

Uso (dentro do Docker, com a rede do Qdrant e o commit do host):
  docker run --rm --network phishforge_network \
    -e QDRANT_URL=http://phishforge-qdrant:6333 \
    -e LLM_PROVIDER=anthropic -e MODEL_NAME_LLM=claude-sonnet-4-6 \
    -e GIT_COMMIT=$(git rev-parse --short HEAD) \
    -v "$PWD":/app -w /app phishforge-api-phishforge-api:latest \
    sh -c "poetry install ... --with evaluation; poetry run python -m script.smoke_producao"

NAO usa os juizes RAGAS (o criterio do item 1 e 'gera item valido', nao a
nota de qualidade) -- custo so da geracao.
"""

import asyncio
import random

from app.core.config import settings
from app.core.container import Container
from app.core.reproducibilidade import commit_do_git
from app.domain.services.llm_factory import (
    PROVIDER_ANTHROPIC,
    descrever_saida_estruturada,
)
from app.domain.services.variation_sampler import VariationSampler

# Importa o carregador de contextos do eval (reaproveita a aba `lotes`).
from script.avaliar_modelos_llm import _ler_aba_lotes, XLSX_PADRAO

NIVEIS = ("facil", "medio", "dificil")


async def main() -> int:
    # 1. O caminho de producao tem de estar apontando para o Sonnet 4.6.
    print("=== CONFIG DE PRODUCAO ===")
    print(f"LLM_PROVIDER   = {settings.LLM_PROVIDER}")
    print(f"MODEL_NAME_LLM = {settings.MODEL_NAME_LLM}")
    assert settings.LLM_PROVIDER == PROVIDER_ANTHROPIC, (
        f"esperava provider anthropic, veio {settings.LLM_PROVIDER!r}"
    )
    assert settings.MODEL_NAME_LLM == "claude-sonnet-4-6", (
        f"esperava claude-sonnet-4-6, veio {settings.MODEL_NAME_LLM!r}"
    )

    # 2. Fiacao de producao (Container): gerador + pipeline de contexto.
    container = Container()
    rg = container.response_generator()
    pipeline = container.generation_pipeline()

    print("\n=== GERADOR (do Container) ===")
    print(f"provider          = {rg.provider}")
    print(f"model_name        = {rg.model_name}")
    print(f"temperature       = {rg.temperature}  (None = modo reasoning, temperatura omitida)")
    print(f"saida_estruturada = {descrever_saida_estruturada(rg.provider, rg.model_name)}")
    print(f"git_commit        = {commit_do_git()}")
    assert rg.provider == PROVIDER_ANTHROPIC
    assert rg.model_name == "claude-sonnet-4-6"
    # temperatura_efetiva deve ter zerado a temperatura para o modelo de reasoning.
    assert rg.temperature is None, f"temperatura deveria ser omitida, veio {rg.temperature}"

    # 3. Um contexto real do estudo (cenario C, onde o item 2 ataca) x 3 niveis.
    contextos = [c for c in _ler_aba_lotes(XLSX_PADRAO) if c.cenario == "C"]
    if not contextos:
        contextos = _ler_aba_lotes(XLSX_PADRAO)
    ctx = contextos[0]
    print(f"\n=== GERACAO (contexto {ctx.lote_id}, cenario {ctx.cenario}) ===")

    sampler = VariationSampler(random.Random(42))
    validos = 0
    for nivel in NIVEIS:
        built = await pipeline.build_context(ctx.texto)
        ficha = sampler.sortear(nivel, is_malicious=True)
        draft = await rg.generate_response(
            difficulty=nivel,
            context=built.generation_context,
            relevant_docs=built.fused_context,
            is_malicious=True,
            variacao=ficha,
        )
        valido = bool(draft.conteudo and draft.remetente and draft.assunto)
        validos += int(valido)
        regen = draft.validacao or {}
        print(
            f"[{nivel:8}] valido={valido} | assunto={draft.assunto!r} | "
            f"remetente={draft.remetente!r}"
        )
        print(
            f"           cues={[c.code.value for c in draft.cues]} | "
            f"regen_marcador={regen.get('regeneracoes_por_marcador')} | "
            f"regen_link={regen.get('regeneracoes_por_link')} | "
            f"assinaturas_desembrulhadas={regen.get('assinaturas_de_sistema_desembrulhadas')}"
        )

    print(f"\nITENS VALIDOS: {validos}/{len(NIVEIS)}")
    return 0 if validos == len(NIVEIS) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
