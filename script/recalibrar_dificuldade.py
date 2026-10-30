#!/usr/bin/env python3
"""Recalibra difficulty_estimated sobre os 960 ja gerados (Opcao D, aprovada
pelo orientador em 30/10/2026) e consolida tudo num JSONL.

A regra e DETERMINISTICA sobre rotulos ja salvos (cue_count + premise_alignment):
nao gera nenhum exemplo, nao chama API. Opcao D = a MESMA estrutura aditiva da
regra de producao (ver response_generator._derivar_dificuldade_estimada), com os
cortes de cue_count recalibrados a densidade observada no gerador (mediana 5):

    pontos_cue = 2 se cue<=4 ; 1 se cue==5 ; 0 se cue>=6
    pontos_alinhamento = alto 2 / medio 1 / baixo 0
    soma <=1 -> facil ; 2-3 -> medio ; 4 -> dificil

Preserva o rotulo original (phish_scale.difficulty_estimated) e adiciona
`difficulty_estimated_recalibrado`. Tambem anexa a cada item as chaves de
agrupamento (eixo/nivel_pedido/cenario/lote_id), extraidas do nome do export,
para o split por grupo do classificador.

Uso: python3 script/recalibrar_dificuldade.py
Saida: dataset/phishforge_960.jsonl  (+ distribuicao no stdout)
"""

import glob
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
EXPORTS = RAIZ / "dataset" / "exports"
SAIDA = RAIZ / "dataset" / "phishforge_960.jsonl"

_NIVEL = {"F": "facil", "M": "medio", "D": "dificil"}
_PADRAO = re.compile(r"(E[1-5])-([FMD])-([ABCD])-\d+")  # casa o lote mesmo em -TU

# --- Opcao D (aprovada) -----------------------------------------------------
PONTOS_ALINHAMENTO = {"alto": 2, "medio": 1, "baixo": 0}
CORTE_CUE_2PTS = 4   # cue_count <= 4  -> 2 pontos
CORTE_CUE_1PT = 5    # cue_count == 5  -> 1 ponto ; >=6 -> 0


def dificuldade_recalibrada(cue_count: int, premise_alignment: str) -> str:
    pc = 2 if cue_count <= CORTE_CUE_2PTS else (1 if cue_count == CORTE_CUE_1PT else 0)
    soma = pc + PONTOS_ALINHAMENTO[premise_alignment]
    return "facil" if soma <= 1 else ("medio" if soma <= 3 else "dificil")


def main() -> int:
    dist_orig = {"facil": 0, "medio": 0, "dificil": 0}
    dist_novo = {"facil": 0, "medio": 0, "dificil": 0}
    n = 0
    sem_scale = 0
    with SAIDA.open("w", encoding="utf-8") as out:
        for arq in sorted(glob.glob(str(EXPORTS / "*.json"))):
            m = _PADRAO.match(Path(arq).name)
            if not m:
                continue
            eixo, nivel_code, cenario = m.groups()
            lote_id = m.group(0)
            job = json.loads(Path(arq).read_text(encoding="utf-8"))
            for it in job.get("examples", []):
                ps = it.get("phish_scale") or {}
                cc, pa = ps.get("cue_count"), ps.get("premise_alignment")
                it["eixo"] = eixo
                it["nivel_pedido"] = _NIVEL[nivel_code]
                it["cenario"] = cenario
                it["lote_id"] = lote_id
                it["difficulty_estimated_original"] = ps.get("difficulty_estimated")
                if cc is None or pa is None:
                    it["difficulty_estimated_recalibrado"] = None
                    sem_scale += 1
                else:
                    novo = dificuldade_recalibrada(cc, pa)
                    it["difficulty_estimated_recalibrado"] = novo
                    dist_novo[novo] += 1
                    if ps.get("difficulty_estimated") in dist_orig:
                        dist_orig[ps["difficulty_estimated"]] += 1
                out.write(json.dumps(it, ensure_ascii=False) + "\n")
                n += 1

    print(f"itens consolidados: {n}  -> {SAIDA}")
    if sem_scale:
        print(f"  (sem phish_scale, recalibrado=None: {sem_scale})")
    print(f"difficulty_estimated ORIGINAL : {dist_orig}")
    print(f"difficulty_estimated RECALIB. (D): {dist_novo}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
