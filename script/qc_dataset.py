"""Controle de qualidade do conjunto gerado (Protocolo v3.1, secao 9).

Roda sobre os exports do driver (dataset/exports/*.json) e produz as conferencias
da secao 9, SEM gastar API: reusa os detectores reais (`item_validation`), entao
o que o QC acha e exatamente o que o pipeline usou. A unica checagem que o
protocolo pede com embedding (dedup por cosseno) e aproximada aqui por
similaridade lexical (shingles) como triagem -- a versao por embedding pode ser
rodada a parte se necessario.

Uso (Docker, sem API):
  docker run --rm -v "$PWD":/app -w /app phishforge-api-phishforge-api:latest \
    sh -c "poetry run python -m script.qc_dataset --exports dataset/exports"
"""

import argparse
import collections
import glob
import json
import re
from pathlib import Path

from app.domain.services.item_validation import (
    encontrar_disclaimer_de_simulacao,
    encontrar_dominios_reais,
    encontrar_links_invalidos,
    encontrar_marcadores,
    encontrar_nomes_de_instituicoes_reais,
    normalizar_assunto,
)
from app.domain.models.link_ref import LinkRef

PISTAS_DE_DOMINIO = {"sender_domain_mismatch", "typosquat", "homoglyph"}
_RECUSA_EXPL = re.compile(
    r"n[aã]o posso|vers[aã]o segura|cannot create|can.?t create|as an ai|not able to|desculpe,? mas n",
    re.I,
)


def _links(ex):
    return [LinkRef(text=l.get("text", ""), href=l.get("href", "")) for l in (ex.get("links") or [])]


def _e_recusa_branda(ex):
    return (
        (not (ex.get("links") or []) and not (ex.get("cues") or []))
        or bool(_RECUSA_EXPL.search(ex.get("explicacao") or ""))
        or ex.get("phish_scale") is None
    )


def _shingles(texto, n=5):
    t = re.sub(r"\s+", " ", (texto or "").lower())
    return {t[i:i + n] for i in range(max(0, len(t) - n + 1))}


def carregar(exports: Path):
    itens = []
    for arq in sorted(glob.glob(str(exports / "*.json"))):
        job = json.loads(Path(arq).read_text(encoding="utf-8"))
        itens.extend(job.get("examples", []))
    return itens


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exports", type=Path, default=Path("dataset/exports"))
    ap.add_argument("--jaccard", type=float, default=0.9, help="limiar de triagem lexical de quase-duplicata")
    args = ap.parse_args()

    itens = carregar(args.exports)
    print(f"=== QC do conjunto: {len(itens)} itens em {args.exports} ===\n")
    if not itens:
        print("Nenhum item. Rode o driver (gerar_lotes.py) antes.")
        return 1

    # 1. Contagem por celula (eixo x nivel x cenario) e utilizaveis.
    por_celula = collections.Counter()
    brandas = 0
    for ex in itens:
        chave = f"{ex.get('eixo','?')}-{(ex.get('nivel') or '?')[:1]}-{ex.get('cenario','?')}"
        por_celula[chave] += 1
        if _e_recusa_branda(ex):
            brandas += 1
    print(f"1. Itens por celula ({len(por_celula)} celulas). Recusa branda detectada: {brandas}")
    curtas = {k: v for k, v in por_celula.items() if v < 64}
    if curtas:
        print(f"   Celulas abaixo de 64: {dict(sorted(curtas.items()))}")

    # 2. Assunto repetido (igualdade normalizada, global).
    assuntos = collections.Counter(normalizar_assunto(ex.get("assunto", "")) for ex in itens)
    repetidos = {a: c for a, c in assuntos.items() if c > 1 and a}
    print(f"\n2. Assuntos repetidos (global): {sum(repetidos.values()) - len(repetidos)} itens em "
          f"{len(repetidos)} assuntos duplicados.")

    # 3. Quase-duplicata lexical (triagem; a versao por embedding e a oficial).
    shs = [(_shingles(ex.get("conteudo", "")), ex) for ex in itens]
    pares = 0
    for i in range(len(shs)):
        a = shs[i][0]
        if not a:
            continue
        for j in range(i + 1, len(shs)):
            b = shs[j][0]
            if not b:
                continue
            inter = len(a & b)
            if inter and inter / len(a | b) >= args.jaccard:
                pares += 1
    print(f"\n3. Quase-duplicatas lexicais (Jaccard>={args.jaccard}, triagem): {pares} pares.")

    # 4. Cobertura de pistas (corpo x dominio) + completadas por construcao.
    corpo = collections.Counter()
    dominio = collections.Counter()
    completadas = 0
    sem_pista_dificil = 0
    for ex in itens:
        for c in ex.get("cues") or []:
            code = c.get("code") if isinstance(c, dict) else c
            (dominio if code in PISTAS_DE_DOMINIO else corpo)[code] += 1
        val = ex.get("validacao") or {}
        completadas += len(val.get("cues_completadas_por_construcao") or [])
        ps = ex.get("phish_scale") or {}
        if (ps.get("cue_count") == 0) and (ps.get("difficulty_estimated") in ("dificil", "Difícil", "difícil")):
            sem_pista_dificil += 1
    print("\n4. Cobertura de pistas:")
    print(f"   corpo:   {dict(corpo)}")
    print(f"   dominio: {dict(dominio)} (completadas por construcao: {completadas})")

    # 5. Artefatos visiveis (detectores reais).
    com_artefato = []
    for ex in itens:
        links = _links(ex)
        achados = (
            encontrar_marcadores(ex.get("remetente"), ex.get("assunto"), ex.get("conteudo"),
                                 textos_de_link=[l.text for l in links])
            + encontrar_disclaimer_de_simulacao(ex.get("remetente"), ex.get("assunto"),
                                                ex.get("conteudo"), *[l.text for l in links])
            + [h for h, _ in encontrar_links_invalidos(links)]
        )
        if "\\n" in (ex.get("conteudo") or ""):
            achados.append("\\n literal")
        if achados:
            com_artefato.append((ex.get("id", "?"), achados))
    print(f"\n5. Itens com artefato visivel: {len(com_artefato)} (alvo: 0)")
    for id_, a in com_artefato[:10]:
        print(f"   {id_}: {a}")

    # 6. Marcas reais (personificacao: remetente/links; dominio real em qualquer campo).
    com_marca = []
    for ex in itens:
        links = _links(ex)
        nomes = encontrar_nomes_de_instituicoes_reais(ex.get("remetente"),
                                                      *[l.text for l in links], *[l.href for l in links])
        doms = encontrar_dominios_reais(ex.get("remetente"), ex.get("assunto"), ex.get("conteudo"),
                                        *[l.href for l in links])
        if nomes or doms:
            com_marca.append((ex.get("id", "?"), nomes + doms))
    print(f"\n6. Itens com marca/dominio real: {len(com_marca)}")
    for id_, m in com_marca[:10]:
        print(f"   {id_}: {m}")

    # 7. Posicoes zeradas (evidencia nao literal) -- confiabilidade do anotador.
    total_cues = sum(len(ex.get("cues") or []) for ex in itens)
    zeradas = 0
    for ex in itens:
        for c in ex.get("cues") or []:
            if isinstance(c, dict) and c.get("span_start") is None:
                zeradas += 1
    taxa = (zeradas / total_cues * 100) if total_cues else 0
    print(f"\n7. Posicoes zeradas: {zeradas}/{total_cues} pistas ({taxa:.1f}%).")

    # 8. Fidelidade a ficha (remetente/link usam o dominio da ficha?).
    fora = 0
    checados = 0
    for ex in itens:
        vs = ex.get("variation_spec") or {}
        dom = (vs.get("instituicao") or {}).get("dominio_oficial") or vs.get("dominio_da_pista")
        if not dom:
            continue
        checados += 1
        campos = (ex.get("remetente") or "") + " " + " ".join(l.href for l in _links(ex))
        if dom not in campos and (vs.get("dominio_da_pista") or "") not in campos:
            fora += 1
    print(f"\n8. Fidelidade a ficha: {fora}/{checados} itens sem o dominio da ficha no remetente/link.")

    # 9. Itens sem pista no dificil (recusa branda que passou).
    print(f"\n9. Itens com cue_count=0 e dificuldade 'dificil': {sem_pista_dificil} (devem sair).")

    print("\n=== fim do QC ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
