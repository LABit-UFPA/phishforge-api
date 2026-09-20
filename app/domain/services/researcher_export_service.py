import csv
import io
import json
from datetime import date, datetime
from typing import Any, Dict, List, Sequence
from uuid import UUID

# Excel em pt-BR so le UTF-8 sem BOM como ANSI: sem o BOM, os acentos da
# justificativa (o corpus qualitativo) chegam corrompidos.
BOM = "﻿"

# Colunas na ordem do arquivo. Fixas (e nao inferidas da primeira linha)
# para que um dataset vazio ainda tenha cabecalho.
COLUNAS: Dict[str, List[str]] = {
    "avaliacoes": [
        "especialista_id", "item_id", "ordem_canonica", "ordem_apresentacao",
        "nivel_sistema", "dificuldade_percebida", "nivel_concordou",
        "adequado_uso_educacional", "qualidade_geral", "justificativa",
        "comentario", "tempo_ms", "concluida_em", "n_anotacoes",
    ],
    "anotacoes": [
        "especialista_id", "item_id", "campo", "cue_code", "span_start",
        "span_end", "trecho", "cue_tambem_no_llm",
    ],
    "itens": [
        "ordem_canonica", "item_id", "nivel_sistema", "categoria", "is_malicious",
        "channel", "difficulty_estimated", "phish_scale_cue_count", "cues_llm",
        "avaliacoes_concluidas",
    ],
    "especialistas": [
        "especialista_id", "anos_experiencia", "area_atuacao", "formacao",
        "consentimento_versao", "consentimento_em", "ultimo_acesso_em",
        "avaliacoes_concluidas", "avaliacoes_total",
    ],
}
COLUNAS_PII = ["nome", "sobrenome", "email"]

DATASETS = tuple(COLUNAS)


def colunas_do_dataset(dataset: str, incluir_pii: bool) -> List[str]:
    colunas = list(COLUNAS[dataset])
    if dataset == "especialistas" and incluir_pii:
        colunas = colunas[:1] + COLUNAS_PII + colunas[1:]
    return colunas


def _neutralizar_formula(texto: str) -> str:
    """Planilhas executam celulas que comecam com = + - @ (CSV injection).
    Justificativas e trechos sao texto de terceiros; prefixar aspas
    simples faz o Excel trata-los como texto. So no CSV -- o JSON e
    entregue intacto.
    """
    if texto and texto[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + texto
    return texto


def _valor_json(valor: Any) -> Any:
    if isinstance(valor, (UUID,)):
        return str(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    return valor


def _valor_csv(valor: Any) -> str:
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "true" if valor else "false"
    if isinstance(valor, (UUID,)):
        return str(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    return _neutralizar_formula(str(valor))


def para_csv(dataset: str, linhas: Sequence[Dict[str, Any]], incluir_pii: bool = False) -> bytes:
    colunas = colunas_do_dataset(dataset, incluir_pii)
    buffer = io.StringIO()
    escritor = csv.writer(buffer, lineterminator="\r\n")
    escritor.writerow(colunas)
    for linha in linhas:
        escritor.writerow([_valor_csv(linha.get(c)) for c in colunas])
    return (BOM + buffer.getvalue()).encode("utf-8")


def para_json(dataset: str, linhas: Sequence[Dict[str, Any]], incluir_pii: bool = False) -> bytes:
    colunas = colunas_do_dataset(dataset, incluir_pii)
    dados = [{c: _valor_json(linha.get(c)) for c in colunas} for linha in linhas]
    return json.dumps(dados, ensure_ascii=False).encode("utf-8")
