# Avaliações antigas

Scripts e resultados dos experimentos de avaliação de janeiro de 2026,
movidos da raiz do projeto para cá. Ficam como registro histórico: não
fazem parte da API, da suíte de testes nem do lint do CI.

| Script | O que avalia | Resultado em `resultados/` |
|---|---|---|
| `evaluate_models.py` | Modelos LLM (GPT-3.5 Turbo, GPT-4, o4-mini) com métricas RAGAS, nos 3 níveis de dificuldade | `evaluation_report_*.json` |
| `evaluate_with_rag.py` | Geração COM RAG (GPT-4) | `with_rag_evaluation_*.json` |
| `evaluate_no_rag.py` | Geração SEM RAG (GPT-4) | `no_rag_evaluation_*.json` |
| `experiment1_rag_comparison.py` | Experimento 1: 60 exemplos, 30 COM e 30 SEM RAG | `experiment1_rag_vs_no_rag_*.json` |
| `evaluate_zero_shot_vs_cot.py` | Prompt zero-shot vs. chain-of-thought (GPT-4) | `zero_shot_vs_cot_*.json` |
| `../script/experiments/test_ragas_fix.py` | Teste da correção do RAGAS | `ragas_fix_test_*.json` |

As análises desses resultados estão em `docs/analise_rag_vs_no_rag.md` e
`docs/analise_zero_shot_vs_cot.md`.

## Rodar de novo

Os scripts importam `app`, então rode **da raiz do projeto**, como módulo:

```bash
poetry run python -m avaliacoes_antigas.evaluate_with_rag
```

Eles chamam a OpenAI (precisam de `OPENAI_API_KEY` no `.env`) e o Qdrant, e
gravam o JSON de saída no diretório corrente. Mova o arquivo para
`resultados/` depois, para não voltar a poluir a raiz.
