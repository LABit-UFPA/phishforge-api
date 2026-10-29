"""Resume por checkpoint JSONL da comparacao de modelos.

A rodada cheia grava cada item num JSONL assim que termina; re-rodar com
os mesmos parametros retoma de onde parou (um timeout/crash nao perde o
custo ja pago). Aqui testamos o round-trip ResultadoItem <-> JSONL e que
`_carregar_checkpoint` reconstroi os itens e as chaves (label, lote_id,
repeticao) ja feitas, tolerando uma linha truncada.

Usa `Avaliador.__new__` para nao disparar o __init__ (que abre Qdrant e
exige chaves de API) -- `_carregar_checkpoint` so mexe em self.resultados.
"""

import json

from script.avaliar_modelos_llm import Avaliador, ResultadoItem


def _item(label, lote_id, rep, erro=None):
    return ResultadoItem(
        label=label, tier="facil", provider="openai", model="m",
        lote_id=lote_id, eixo="E1", nivel="facil", cenario="A", repeticao=rep,
        context_relevance=0.5, qualidade_openai=4.0, qualidade_anthropic=4.0,
        qualidade_justificativa_openai="ok", qualidade_justificativa_anthropic="ok",
        tempo_s=1.0, item={"conteudo": "x"}, erro=erro,
    )


def _av_vazio():
    av = Avaliador.__new__(Avaliador)
    av.resultados = []
    return av


def test_sem_arquivo_retorna_vazio(tmp_path):
    av = _av_vazio()
    feitos = av._carregar_checkpoint(tmp_path / "nao_existe.jsonl")
    assert feitos == set()
    assert av.resultados == []


def test_none_nao_quebra():
    av = _av_vazio()
    assert av._carregar_checkpoint(None) == set()


def test_so_itens_ok_contam_como_feitos(tmp_path):
    ckpt = tmp_path / "ck.jsonl"
    itens = [_item("GPT", "L1", 1), _item("GPT", "L2", 1), _item("Claude", "L1", 1, erro="http")]
    ckpt.write_text(
        "\n".join(json.dumps(vars(i), ensure_ascii=False) for i in itens) + "\n",
        encoding="utf-8",
    )
    av = _av_vazio()
    feitos = av._carregar_checkpoint(ckpt)
    # O item com erro (ex.: 429 por creditos zerados) NAO e feito: re-tenta.
    assert feitos == {("GPT", "L1", 1), ("GPT", "L2", 1)}
    assert len(av.resultados) == 2
    assert all(r.erro is None for r in av.resultados)


def test_erro_depois_sucesso_na_mesma_chave_conta_como_feito(tmp_path):
    """Item re-tentado: a 1a tentativa falhou (gravada), a 2a deu OK
    (gravada de novo). A ultima vence -> conta como feito."""
    ckpt = tmp_path / "ck.jsonl"
    linhas = [
        json.dumps(vars(_item("GPT", "L1", 1, erro="http")), ensure_ascii=False),
        json.dumps(vars(_item("GPT", "L1", 1)), ensure_ascii=False),  # re-tentativa OK
    ]
    ckpt.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    av = _av_vazio()
    feitos = av._carregar_checkpoint(ckpt)
    assert feitos == {("GPT", "L1", 1)}
    assert len(av.resultados) == 1
    assert av.resultados[0].erro is None


def test_so_erros_nao_viram_feitos(tmp_path):
    ckpt = tmp_path / "ck.jsonl"
    ckpt.write_text(
        json.dumps(vars(_item("Claude", "L1", 1, erro="recusa")), ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    av = _av_vazio()
    assert av._carregar_checkpoint(ckpt) == set()
    assert av.resultados == []


def test_linha_truncada_e_ignorada(tmp_path):
    ckpt = tmp_path / "ck.jsonl"
    linha_boa = json.dumps(vars(_item("GPT", "L1", 1)), ensure_ascii=False)
    ckpt.write_text(linha_boa + "\n" + '{"label": "GPT", "lote_id":', encoding="utf-8")
    av = _av_vazio()
    feitos = av._carregar_checkpoint(ckpt)
    assert feitos == {("GPT", "L1", 1)}
    assert len(av.resultados) == 1


def test_duplicata_no_arquivo_nao_duplica(tmp_path):
    ckpt = tmp_path / "ck.jsonl"
    linha = json.dumps(vars(_item("GPT", "L1", 1)), ensure_ascii=False)
    ckpt.write_text(linha + "\n" + linha + "\n", encoding="utf-8")
    av = _av_vazio()
    feitos = av._carregar_checkpoint(ckpt)
    assert feitos == {("GPT", "L1", 1)}
    assert len(av.resultados) == 1
