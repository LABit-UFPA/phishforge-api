from collections import defaultdict
from typing import Any, Dict, Sequence

NIVEIS = ("facil", "medio", "dificil")


def resumir(
    avaliacoes: Sequence[Dict[str, Any]], anotacoes: Sequence[Dict[str, Any]]
) -> Dict[str, Any]:
    """Contagens simples sobre os datasets ja filtrados (sem revogados,
    so avaliacoes concluidas). Nao calcula kappa: isso e analise
    estatistica versionada fora da API; aqui so o que responde "o nivel
    do sistema bate com o percebido?".
    """
    matriz = {s: {p: 0 for p in NIVEIS} for s in NIVEIS}
    for a in avaliacoes:
        matriz[a["nivel_sistema"]][a["dificuldade_percebida"]] += 1

    total = len(avaliacoes)
    diagonal = sum(matriz[n][n] for n in NIVEIS)

    pistas: Dict[str, Dict[str, int]] = defaultdict(lambda: {"anotacoes": 0, "tambem_no_llm": 0})
    for an in anotacoes:
        p = pistas[an["cue_code"]]
        p["anotacoes"] += 1
        if an["cue_tambem_no_llm"]:
            p["tambem_no_llm"] += 1

    return {
        "total_avaliacoes": total,
        "especialistas": len({a["especialista_id"] for a in avaliacoes}),
        "matriz_confusao": matriz,
        "concordancia_bruta": (diagonal / total) if total else None,
        "qualidade_media": (sum(a["qualidade_geral"] for a in avaliacoes) / total) if total else None,
        "adequado_uso_educacional_pct": (
            sum(1 for a in avaliacoes if a["adequado_uso_educacional"]) / total if total else None
        ),
        "frequencia_pistas": dict(sorted(pistas.items())),
    }
