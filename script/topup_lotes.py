#!/usr/bin/env python3
"""Top-up de celulas curtas (Protocolo v3.1.1, secao 8/9): completa ate 16 itens
uteis os lotes do registro que ficaram abaixo (ex.: os 3 perdidos por limite de
tokens no run completo). Gera 1 item por vez no MESMO contexto/nivel, com dedup
contra os itens ja aceitos da celula (dedup_job_ids), e salva cada novo item
como export + linha no registro, com sufixo -TUn no lote_id.

Reusa o driver (gerar_lotes.py). Stdlib-only; roda no host contra a app no ar.
Uso: python3 script/topup_lotes.py            # top-up de tudo < 16
     python3 script/topup_lotes.py --alvo 16 --max-tentativas 5
"""

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gerar_lotes as gl  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--alvo", type=int, default=16, help="itens uteis por lote")
    ap.add_argument("--registro", type=Path, default=gl.RAIZ / "dataset" / "registro_lotes_v31.csv")
    ap.add_argument("--out", type=Path, default=gl.RAIZ / "dataset" / "exports")
    ap.add_argument("--max-tentativas", type=int, default=6, help="tentativas extras por item (truncamento/dup)")
    ap.add_argument("--intervalo", type=int, default=10)
    args = ap.parse_args()

    api_key = __import__("os").environ.get("PHISHFORGE_API_KEY", "") or gl._api_key_do_env(gl.RAIZ / ".env")
    if not api_key:
        raise SystemExit("API key nao encontrada (PHISHFORGE_API_KEY ou API_KEY no .env).")

    rows = list(csv.DictReader(args.registro.open(encoding="utf-8")))
    curtos = [
        r for r in rows
        if r.get("status") in ("concluido", "concluido_com_falhas")
        and int(r.get("itens_utilizaveis") or 0) < args.alvo
        and "-TU" not in r["lote_id"]  # nao topar um top-up
    ]
    if not curtos:
        print("Nenhuma celula abaixo do alvo. Nada a fazer.")
        return 0
    print(f"{len(curtos)} celula(s) a completar: " + ", ".join(f"{r['lote_id']}({r['itens_utilizaveis']})" for r in curtos))

    for r in curtos:
        lote_id, nivel, contexto = r["lote_id"], r["nivel_pedido"], r["string_contexto"]
        deficit = args.alvo - int(r["itens_utilizaveis"])
        dedup = [r["job_id"]] if r.get("job_id") else []
        print(f"\n>>> {lote_id}: faltam {deficit} item(ns)")
        feitos = 0
        for tentativa in range(1, deficit + args.max_tentativas + 1):
            if feitos >= deficit:
                break
            semente = gl.semente_do_lote(99, f"{lote_id}:tu:{tentativa}")
            body = {
                "context": contexto, "difficulties": [nivel], "total": 1,
                "malicious_ratio": 1.0, "channel": "email", "seed": semente,
                "dedup_job_ids": dedup,
            }
            try:
                job_id = gl._req("POST", f"{args.base_url}/api/v1/generate/batch", api_key, body)["job_id"]
                job = gl.aguardar_lote(args.base_url, api_key, job_id, args.intervalo)
            except Exception as e:  # noqa: BLE001
                print(f"    tentativa {tentativa}: erro {type(e).__name__}: {e}")
                continue
            uteis = [e for e in job.get("examples", []) if not gl._e_recusa_branda(e)]
            if not uteis:
                print(f"    tentativa {tentativa}: 0 util (gerados={job.get('total_generated')}, "
                      f"falhas={len(job.get('failures',[]))}) -- tentando de novo")
                continue
            feitos += len(uteis)
            dedup.append(job_id)  # dedup os proximos tambem contra este
            novo_id = f"{lote_id}-TU{feitos}"
            arquivo = args.out / f"{novo_id}_{datetime.now():%Y%m%d_%H%M%S}.json"
            arquivo.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
            meta = job.get("run_metadata") or {}
            gl.anexar_registro(args.registro, {
                **{k: "" for k in gl.REGISTRO_COLUNAS},
                "lote_id": novo_id, "eixo": r["eixo"], "nivel_pedido": nivel,
                "cenario": r["cenario"], "string_contexto": contexto,
                "modelo": meta.get("modelo", ""), "temperatura": meta.get("temperatura", ""),
                "saida_estruturada": meta.get("saida_estruturada", ""),
                "versao_app": meta.get("git_commit", ""), "semente": meta.get("seed", semente),
                "data_hora": f"{datetime.now():%Y-%m-%d %H:%M}", "itens_pedidos": 1,
                "itens_gerados": job.get("total_generated", 0), "recusa_branda": 0,
                "itens_utilizaveis": len(uteis), "descartes_duplicata": job.get("total_discarded", 0),
                "descartes_validacao": len(job.get("failures", [])),
                "arquivo_export": arquivo.name, "job_id": job_id, "status": job["status"],
                "observacoes": f"top-up de {lote_id} (commit {meta.get('git_commit','')})",
            })
            print(f"    tentativa {tentativa}: +1 util -> {arquivo.name}")
        if feitos < deficit:
            print(f"    AVISO: {lote_id} ainda faltam {deficit - feitos} (esgotou as tentativas).")

    print("\nFim do top-up.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
