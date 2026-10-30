#!/usr/bin/env python3
"""Driver de geracao do dataset (Protocolo v3.1, decisoes de 30/10/2026).

Submete os 60 lotes (15 celulas x 4 cenarios, 16 itens/lote = 960) ao endpoint
`/api/v1/generate/batch` da app em execucao, em ORDEM POR RODADA DE CENARIO
(todas as 15 celulas no cenario A, depois B, C, D; niveis intercalados), mantem
a planilha de registro da secao 8, e PARA SOZINHO quando:
  - o credito acaba (lote volta FALHOU por erro de taxa/credito), ou
  - 3 lotes seguidos falham, ou
  - atinge o --limite de lotes.
O checkpoint e por lote: re-executar pula os lotes ja concluidos no registro.

So usa a biblioteca padrao (urllib/zipfile/csv/json/re): roda no host com
`python3`, sem Docker nem Poetry, contra a app em http://localhost:8000.

Uso:
  export PHISHFORGE_API_KEY=...            # mesma API_KEY do .env da app
  python3 script/gerar_lotes.py --limite 1 # 1o lote real (piloto observado)
  python3 script/gerar_lotes.py            # segue de onde parou, ate acabar
Opcoes principais: --limite N, --itens 16, --base-url, --out, --registro, --dry-run.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
XLSX_PADRAO = RAIZ / "registro_lotes.xlsx"
_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# Ordem dos niveis dentro de uma rodada de cenario (intercalados por celula).
_ORDEM_NIVEL = {"Fácil": 0, "Facil": 0, "Médio": 1, "Medio": 1, "Difícil": 2, "Dificil": 2}
_ORDEM_EIXO = {"E1": 0, "E2": 1, "E3": 2, "E4": 3, "E5": 4}
_ORDEM_CENARIO = {"A": 0, "B": 1, "C": 2, "D": 3}

# Recusa branda (regra reproduzivel da secao 5, mesma da recontagem): e-mail
# sanitizado (sem link e sem pista), OU explicacao com recusa explicita do
# modelo, OU sem phish_scale.
_RECUSA_EXPL = re.compile(
    r"n[aã]o posso|vers[aã]o segura|cannot create|can.?t create|as an ai|not able to"
    r"|desculpe,? mas n",
    re.I,
)

REGISTRO_COLUNAS = [
    "lote_id", "eixo", "nivel_pedido", "cenario", "string_contexto",
    "modelo", "temperatura", "saida_estruturada", "versao_app", "semente",
    "data_hora", "itens_pedidos", "itens_gerados", "recusa_branda",
    "itens_utilizaveis", "descartes_duplicata", "descartes_recusa",
    "descartes_validacao", "descartes_infra", "arquivo_export", "job_id",
    "status", "observacoes",
]


def _col_index(ref: str) -> int:
    letras = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for c in letras:
        n = n * 26 + (ord(c) - 64)
    return n - 1


def ler_contextos(xlsx_path: Path) -> list[dict]:
    """Le a aba `lotes` do xlsx (stdlib, sem openpyxl): um dict por linha com
    lote_id, eixo, nivel, cenario, texto. Mesma logica de avaliar_modelos_llm.
    _ler_aba_lotes, reimplementada aqui para o driver nao importar o app."""
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
        raise SystemExit("aba 'lotes' nao encontrada no xlsx")
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
    # So os 60 lotes do dataset (E{1-5}-{F,M,D}-{A-D}-NN); exclui linhas de
    # piloto (PILOTO5-*, PILOTO6-*) e qualquer outra fora do padrao.
    padrao_lote = re.compile(r"^E[1-5]-[FMD]-[ABCD]-\d+$")
    contextos = []
    for r in linhas[1:]:
        lote_id = r.get(col("lote_id"), "").strip()
        if not lote_id or not padrao_lote.match(lote_id):
            continue
        try:
            texto = json.loads(r.get(col("corpo_json"), "")).get("context", "").strip()
        except Exception:
            texto = ""
        if not texto:
            continue
        contextos.append({
            "lote_id": lote_id,
            "eixo": r.get(col("eixo"), "").strip(),
            "nivel": r.get(col("nivel_pedido"), "").strip(),
            "cenario": r.get(col("cenario"), "").strip(),
            "texto": texto,
        })
    return contextos


def ordenar_por_rodada(contextos: list[dict]) -> list[dict]:
    """Ordem por RODADA DE CENARIO (decisao 5): cenario A em todas as celulas,
    depois B, C, D; dentro de cada rodada, por eixo e nivel (niveis
    intercalados a cada 3 lotes)."""
    return sorted(
        contextos,
        key=lambda c: (
            _ORDEM_CENARIO.get(c["cenario"], 9),
            _ORDEM_EIXO.get(c["eixo"], 9),
            _ORDEM_NIVEL.get(c["nivel"], 9),
        ),
    )


def _api_key_do_env(path: Path) -> str:
    """Le API_KEY do .env como fallback, para nao exigir exportar
    PHISHFORGE_API_KEY a mao (a API_KEY do .env e a que o endpoint exige)."""
    if not path.exists():
        return ""
    for linha in path.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if linha.startswith("API_KEY="):
            return linha.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def semente_do_lote(base: int, lote_id: str) -> int:
    """Semente deterministica por lote (reproducao exata ao re-rodar um lote)."""
    h = hashlib.sha256(f"{base}:{lote_id}".encode()).hexdigest()
    return int(h[:8], 16)


def _e_recusa_branda(exemplo: dict) -> bool:
    sanitizado = not (exemplo.get("links") or []) and not (exemplo.get("cues") or [])
    recusa = bool(_RECUSA_EXPL.search(exemplo.get("explicacao") or ""))
    sem_scale = exemplo.get("phish_scale") is None
    return sanitizado or recusa or sem_scale


def _classificar_falha(err: str) -> str:
    e = (err or "").lower()
    if any(t in e for t in ("429", "529", "rate", "overload", "timeout", "connection", "credito", "credit", "insufficient", "quota")):
        return "infra"
    if any(t in e for t in ("recusa", "index out of range", "refus", "vazio", "empty")):
        return "recusa"
    return "validacao"  # ItemInvalidoError (marcador/remetente/link/pista) e afins


def _e_erro_de_credito(job: dict) -> bool:
    txt = json.dumps(job.get("failures", []), ensure_ascii=False).lower() + " " + (job.get("error_message") or "").lower()
    return any(t in txt for t in ("credit", "credito", "insufficient", "quota", "429", "billing"))


# --- HTTP (stdlib) ---------------------------------------------------------


def _req(method, url, api_key, body=None, timeout=60):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method)
    r.add_header("X-API-Key", api_key)
    if data:
        r.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def submeter_lote(base_url, api_key, ctx, itens, semente) -> str:
    body = {
        "context": ctx["texto"],
        "difficulties": [ctx["nivel"]],
        "total": itens,
        "malicious_ratio": 1.0,
        "channel": "email",
        "seed": semente,
    }
    resp = _req("POST", f"{base_url}/api/v1/generate/batch", api_key, body)
    return resp["job_id"]


def aguardar_lote(base_url, api_key, job_id, intervalo=10, timeout_s=3600) -> dict:
    fim = time.time() + timeout_s
    while time.time() < fim:
        job = _req("GET", f"{base_url}/api/v1/generate/batch/{job_id}", api_key)
        if job["status"] in ("concluido", "concluido_com_falhas", "falhou"):
            return job
        time.sleep(intervalo)
    raise TimeoutError(f"lote {job_id} nao concluiu em {timeout_s}s")


# --- registro --------------------------------------------------------------


def carregar_feitos(registro: Path) -> set:
    if not registro.exists():
        return set()
    with registro.open(encoding="utf-8") as f:
        return {
            lin["lote_id"]
            for lin in csv.DictReader(f)
            if lin.get("status") in ("concluido", "concluido_com_falhas")
        }


def anexar_registro(registro: Path, linha: dict) -> None:
    novo = not registro.exists()
    with registro.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTRO_COLUNAS)
        if novo:
            w.writeheader()
        w.writerow(linha)


def main() -> int:
    ap = argparse.ArgumentParser(description="Driver de geracao de lotes (Protocolo v3.1).")
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--xlsx", type=Path, default=XLSX_PADRAO)
    ap.add_argument("--itens", type=int, default=16, help="itens por lote (decisao 3: 16)")
    ap.add_argument("--limite", type=int, default=0, help="maximo de lotes nesta execucao (0 = todos)")
    ap.add_argument("--seed-base", type=int, default=42)
    ap.add_argument("--out", type=Path, default=RAIZ / "dataset" / "exports")
    ap.add_argument("--registro", type=Path, default=RAIZ / "dataset" / "registro_lotes_v31.csv")
    ap.add_argument("--intervalo", type=int, default=10, help="segundos entre polls")
    ap.add_argument("--dry-run", action="store_true", help="mostra o plano e sai, sem chamar a API")
    args = ap.parse_args()

    contextos = ordenar_por_rodada(ler_contextos(args.xlsx))
    print(f"{len(contextos)} lotes no plano ({args.itens} itens/lote = {len(contextos) * args.itens} itens).")

    if args.dry_run:
        for i, c in enumerate(contextos, 1):
            print(f"{i:2d}. {c['lote_id']:12s} {c['eixo']}-{c['nivel'][:1]}-{c['cenario']} "
                  f"seed={semente_do_lote(args.seed_base, c['lote_id'])}")
        return 0

    api_key = os.environ.get("PHISHFORGE_API_KEY", "") or _api_key_do_env(RAIZ / ".env")
    if not api_key:
        raise SystemExit(
            "API key nao encontrada: defina PHISHFORGE_API_KEY, ou tenha API_KEY=... no .env."
        )

    args.out.mkdir(parents=True, exist_ok=True)
    args.registro.parent.mkdir(parents=True, exist_ok=True)
    feitos = carregar_feitos(args.registro)
    if feitos:
        print(f"Retomando: {len(feitos)} lotes ja concluidos serao pulados.")

    falhas_seguidas = 0
    rodados = 0
    for c in contextos:
        if c["lote_id"] in feitos:
            continue
        if args.limite and rodados >= args.limite:
            print(f"Atingiu o --limite de {args.limite} lotes. Parando.")
            break

        semente = semente_do_lote(args.seed_base, c["lote_id"])
        print(f"\n>>> {c['lote_id']} ({c['eixo']}-{c['nivel'][:1]}-{c['cenario']}) seed={semente}")
        try:
            job_id = submeter_lote(args.base_url, api_key, c, args.itens, semente)
            job = aguardar_lote(args.base_url, api_key, job_id, args.intervalo)
        except (urllib.error.URLError, TimeoutError) as e:
            falhas_seguidas += 1
            print(f"    ERRO de rede/timeout: {e} (falhas seguidas={falhas_seguidas})")
            anexar_registro(args.registro, {
                **{k: "" for k in REGISTRO_COLUNAS},
                "lote_id": c["lote_id"], "eixo": c["eixo"], "nivel_pedido": c["nivel"],
                "cenario": c["cenario"], "status": "erro_driver", "observacoes": str(e),
            })
            if falhas_seguidas >= 3:
                print("3 falhas seguidas. Parando (decisao 6).")
                break
            continue

        exemplos = job.get("examples", [])
        branda = sum(1 for ex in exemplos if _e_recusa_branda(ex))
        falhas = job.get("failures", [])
        por_cat = {"recusa": 0, "validacao": 0, "infra": 0}
        for fl in falhas:
            por_cat[_classificar_falha(fl.get("error", ""))] += 1
        meta = job.get("run_metadata") or {}

        arquivo = args.out / f"{c['lote_id']}_{datetime.now():%Y%m%d_%H%M%S}.json"
        arquivo.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")

        anexar_registro(args.registro, {
            "lote_id": c["lote_id"], "eixo": c["eixo"], "nivel_pedido": c["nivel"],
            "cenario": c["cenario"], "string_contexto": c["texto"],
            "modelo": meta.get("modelo", ""), "temperatura": meta.get("temperatura", ""),
            "saida_estruturada": meta.get("saida_estruturada", ""),
            "versao_app": meta.get("git_commit", ""), "semente": meta.get("seed", semente),
            "data_hora": f"{datetime.now():%Y-%m-%d %H:%M}", "itens_pedidos": args.itens,
            "itens_gerados": job.get("total_generated", 0), "recusa_branda": branda,
            "itens_utilizaveis": job.get("total_generated", 0) - branda,
            "descartes_duplicata": job.get("total_discarded", 0),
            "descartes_recusa": por_cat["recusa"], "descartes_validacao": por_cat["validacao"],
            "descartes_infra": por_cat["infra"], "arquivo_export": arquivo.name,
            "job_id": job_id, "status": job["status"], "observacoes": "",
        })

        rodados += 1
        util = job.get("total_generated", 0) - branda
        print(f"    status={job['status']} gerados={job.get('total_generated')} "
              f"recusa_branda={branda} utilizaveis={util} "
              f"descartados={job.get('total_discarded')} falhas={len(falhas)} -> {arquivo.name}")

        if job["status"] == "falhou":
            falhas_seguidas += 1
            if _e_erro_de_credito(job):
                print("    Lote FALHOU por credito/taxa. Parando (decisao 6). Recarregue e re-rode.")
                break
            if falhas_seguidas >= 3:
                print("3 lotes FALHOU seguidos. Parando (decisao 6).")
                break
        else:
            falhas_seguidas = 0

    print(f"\nFim. Lotes rodados nesta execucao: {rodados}. Registro: {args.registro}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
