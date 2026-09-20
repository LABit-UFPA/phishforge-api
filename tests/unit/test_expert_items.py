"""Entrega cega dos itens e submissao da avaliacao (issue #37).

Sem `X-API-Key` (`expert_client`): as rotas do especialista se autenticam
por JWT proprio.
"""

import json

import pytest

from app.domain.models.expert_evaluation import ConteudoParaAvaliar
from app.domain.models.link_ref import LinkRef
from app.domain.services.expert_auth_service import ExpertAuthService
from app.dto.expert_responses import ExpertItemResponse
from tests.blindness import CAMPOS_PROIBIDOS, chaves_proibidas_em, propriedades_do_esquema

CONTEUDO_COM_EMOJI = "😀 Clique aqui agora para confirmar seus dados."


def _conteudo(i: int = 1, **campos) -> ConteudoParaAvaliar:
    base = dict(
        remetente=f"suporte{i}@banco.example",
        receptor="cliente@example.com",
        assunto=f"Assunto {i}",
        conteudo=f"Conteudo do item {i}.",
        links=[LinkRef(text="Acessar", href=f"http://x{i}.example/login")],
    )
    base.update(campos)
    return ConteudoParaAvaliar(**base)


async def _pronto(fakes, expert_client, itens=3, conteudos=None, consentir=True):
    """Rodada aberta com `itens` itens + especialista logado (e com consentimento)."""
    rounds, experts, evals = (
        fakes["evaluation_round_repository"], fakes["expert_repository"], fakes["expert_evaluation_repository"]
    )
    rodada = await rounds.create(nome="Piloto", tcle_versao="v1", tcle_texto_md="TCLE", status="aberta")
    conteudos = conteudos or [_conteudo(i) for i in range(1, itens + 1)]
    for ordem, c in enumerate(conteudos, start=1):
        await rounds.adicionar_item(rodada.id, object(), ordem)
        evals.registrar_item(rodada.id, c)

    codigo = ExpertAuthService.gerar_codigo()
    esp = experts.adicionar(ExpertAuthService.hash_codigo(codigo), rodada_id=rodada.id)
    token = (await expert_client.post("/api/v1/expert/session", json={"codigo_acesso": codigo})).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    if consentir:
        r = await expert_client.post("/api/v1/expert/consentimento", headers=h, json={"versao": "v1", "aceito": True})
        assert r.status_code == 200
    return rodada, esp, h


def _avaliacao(**extra):
    base = dict(
        dificuldade_percebida="medio", adequado_uso_educacional=True, qualidade_geral=4,
        justificativa="Dominio suspeito e urgencia artificial.", comentario=None, tempo_ms=42000, anotacoes=[],
    )
    base.update(extra)
    return base


def _anot(campo="conteudo", cue="urgency", ini=0, fim=5, trecho="Conte", **kw):
    return dict(campo=campo, cue_code=cue, span_start=ini, span_end=fim, trecho=trecho, **kw)


# ================================================================ cegamento

def test_o_esquema_da_resposta_nao_declara_nenhum_campo_proibido():
    """Um campo novo adicionado ao modelo de resposta falha AQUI, mesmo que
    nenhum teste de runtime o exercite.
    """
    assert propriedades_do_esquema(ExpertItemResponse) & CAMPOS_PROIBIDOS == set()


async def test_resposta_nunca_traz_chave_proibida_em_nenhum_nivel(expert_client, fakes):
    _, _, h = await _pronto(fakes, expert_client, itens=3)

    for ordem in (1, 2, 3):
        r = await expert_client.get(f"/api/v1/expert/itens/{ordem}", headers=h)
        assert r.status_code == 200
        assert chaves_proibidas_em(r.json()) == set(), r.text


async def test_formato_exato_da_resposta_do_item(expert_client, fakes):
    conteudos = [_conteudo(1, conteudo=CONTEUDO_COM_EMOJI)]
    _, _, h = await _pronto(fakes, expert_client, conteudos=conteudos)

    body = (await expert_client.get("/api/v1/expert/itens/1", headers=h)).json()

    assert set(body) == {"ordem", "total", "item", "avaliacao"}
    assert set(body["item"]) == {"remetente", "receptor", "assunto", "conteudo_texto", "links"}
    assert body["item"]["conteudo_texto"] == CONTEUDO_COM_EMOJI
    assert body["item"]["links"] == [{"text": "Acessar", "href": "http://x1.example/login"}]
    assert body["avaliacao"] is None
    assert body["total"] == 1


# ============================================================ autenticacao/gate

async def test_sem_token_da_401_e_sem_consentimento_da_403(expert_client, fakes):
    _, _, h = await _pronto(fakes, expert_client, consentir=False)

    assert (await expert_client.get("/api/v1/expert/itens/1")).status_code == 401
    assert (await expert_client.get("/api/v1/expert/itens/1", headers=h)).status_code == 403
    assert (await expert_client.put("/api/v1/expert/itens/1", headers=h, json=_avaliacao())).status_code == 403


async def test_novo_tcle_no_meio_da_coleta_bloqueia_ate_reconsentir(expert_client, fakes):
    rodada, _, h = await _pronto(fakes, expert_client)
    assert (await expert_client.get("/api/v1/expert/itens/1", headers=h)).status_code == 200

    rodada.tcle_versao = "v2"

    assert (await expert_client.get("/api/v1/expert/itens/1", headers=h)).status_code == 403


@pytest.mark.parametrize("ordem,esperado", [(0, 422), (-1, 422), (4, 404), (999, 404)])
async def test_ordem_fora_do_intervalo(expert_client, fakes, ordem, esperado):
    _, _, h = await _pronto(fakes, expert_client, itens=3)

    assert (await expert_client.get(f"/api/v1/expert/itens/{ordem}", headers=h)).status_code == esperado


async def test_item_que_nao_e_email_da_409(expert_client, fakes):
    _, _, h = await _pronto(fakes, expert_client, conteudos=[_conteudo(1, channel="sms")])

    assert (await expert_client.get("/api/v1/expert/itens/1", headers=h)).status_code == 409


async def test_lista_de_pistas_exige_token_e_traz_as_10(expert_client, fakes):
    _, _, h = await _pronto(fakes, expert_client)

    assert (await expert_client.get("/api/v1/expert/cues")).status_code == 401
    cues = (await expert_client.get("/api/v1/expert/cues", headers=h)).json()
    assert len(cues) == 10
    assert all(c["descricao_pt"] for c in cues)


# ============================================================ ordem por especialista

async def test_dois_especialistas_recebem_ordens_diferentes_cobrindo_1_a_n(expert_client, fakes):
    n = 30
    rounds, experts, evals = (
        fakes["evaluation_round_repository"], fakes["expert_repository"], fakes["expert_evaluation_repository"]
    )
    rodada = await rounds.create(nome="P", tcle_versao="v1", tcle_texto_md="T", status="aberta")
    for i in range(1, n + 1):
        await rounds.adicionar_item(rodada.id, object(), i)
        evals.registrar_item(rodada.id, _conteudo(i))

    async def sequencia():
        codigo = ExpertAuthService.gerar_codigo()
        experts.adicionar(ExpertAuthService.hash_codigo(codigo), rodada_id=rodada.id)
        token = (await expert_client.post("/api/v1/expert/session", json={"codigo_acesso": codigo})).json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        await expert_client.post("/api/v1/expert/consentimento", headers=h, json={"versao": "v1", "aceito": True})
        return [
            (await expert_client.get(f"/api/v1/expert/itens/{o}", headers=h)).json()["item"]["assunto"]
            for o in range(1, n + 1)
        ]

    a, b = await sequencia(), await sequencia()

    assert sorted(a) == sorted(b) == sorted(f"Assunto {i}" for i in range(1, n + 1))  # todos os itens, sem buraco
    assert a != b  # ordens diferentes (chance de coincidir: 1/30!)


async def test_avaliacoes_sao_criadas_uma_vez_e_a_ordem_e_estavel(expert_client, fakes):
    _, _, h = await _pronto(fakes, expert_client, itens=5)

    primeira = [(await expert_client.get(f"/api/v1/expert/itens/{o}", headers=h)).json()["item"]["assunto"] for o in range(1, 6)]
    segunda = [(await expert_client.get(f"/api/v1/expert/itens/{o}", headers=h)).json()["item"]["assunto"] for o in range(1, 6)]

    assert primeira == segunda


# ================================================================== submissao

async def test_submissao_ok_persiste_e_o_get_devolve_a_avaliacao(expert_client, fakes):
    _, _, h = await _pronto(fakes, expert_client, conteudos=[_conteudo(1, conteudo=CONTEUDO_COM_EMOJI)])
    # offsets em CODE POINTS: o emoji conta 1 (em UTF-16 contaria 2)
    inicio = CONTEUDO_COM_EMOJI.index("Clique")
    assert inicio == 2
    corpo = _avaliacao(anotacoes=[_anot(ini=inicio, fim=inicio + len("Clique aqui agora"), trecho="Clique aqui agora")])

    r = await expert_client.put("/api/v1/expert/itens/1", headers=h, json=corpo)

    assert r.status_code == 200, r.text
    av = r.json()["avaliacao"]
    assert av["status"] == "concluida"
    assert av["dificuldade_percebida"] == "medio" and av["qualidade_geral"] == 4
    assert av["anotacoes"] == [
        {"campo": "conteudo", "cue_code": "urgency", "span_start": 2, "span_end": 19, "trecho": "Clique aqui agora"}
    ]
    assert chaves_proibidas_em(r.json()) == set()
    depois = (await expert_client.get("/api/v1/expert/itens/1", headers=h)).json()
    assert depois["avaliacao"] == av


async def test_offsets_em_utf16_sao_recusados_com_422(expert_client, fakes):
    """O erro classico do frontend: contar o emoji como 2. Nao pode ser gravado."""
    _, esp, h = await _pronto(fakes, expert_client, conteudos=[_conteudo(1, conteudo=CONTEUDO_COM_EMOJI)])
    inicio_utf16 = 3  # "Clique" comeca em 2 (code points) == 3 (UTF-16)

    r = await expert_client.put(
        "/api/v1/expert/itens/1", headers=h,
        json=_avaliacao(anotacoes=[_anot(ini=inicio_utf16, fim=inicio_utf16 + 6, trecho="Clique")]),
    )

    assert r.status_code == 422
    assert "code points" in r.json()["detail"]
    linha = fakes["expert_evaluation_repository"].avaliacoes[esp.id][0]
    assert linha["status"] == "pendente" and linha["anotacoes"] == []


@pytest.mark.parametrize(
    "anotacao,trecho_do_erro",
    [
        (_anot(ini=0, fim=5, trecho="OUTRO"), "nao corresponde"),
        (_anot(ini=0, fim=9999, trecho="Conte"), "passa do tamanho"),
        (_anot(campo="assunto", ini=0, fim=3, trecho="abc"), "nao corresponde"),
    ],
)
async def test_anotacao_incoerente_da_422_e_nao_grava_nada(expert_client, fakes, anotacao, trecho_do_erro):
    _, esp, h = await _pronto(fakes, expert_client, itens=1)

    r = await expert_client.put("/api/v1/expert/itens/1", headers=h, json=_avaliacao(anotacoes=[anotacao]))

    assert r.status_code == 422
    assert trecho_do_erro in r.json()["detail"]
    assert fakes["expert_evaluation_repository"].avaliacoes[esp.id][0]["status"] == "pendente"


async def test_campo_que_o_item_nao_tem_da_422(expert_client, fakes):
    _, _, h = await _pronto(fakes, expert_client, conteudos=[_conteudo(1, assunto=None)])

    r = await expert_client.put(
        "/api/v1/expert/itens/1", headers=h, json=_avaliacao(anotacoes=[_anot(campo="assunto", ini=0, fim=1, trecho="A")])
    )

    assert r.status_code == 422


async def test_pista_desativada_ou_inexistente_da_422(expert_client, fakes):
    _, _, h = await _pronto(fakes, expert_client, itens=1)
    fakes["cue_repository"].entries[3].ativo = False  # urgency
    desativada = fakes["cue_repository"].entries[3].code.value

    inativa = await expert_client.put(
        "/api/v1/expert/itens/1", headers=h, json=_avaliacao(anotacoes=[_anot(cue=desativada)])
    )
    inexistente = await expert_client.put(
        "/api/v1/expert/itens/1", headers=h, json=_avaliacao(anotacoes=[_anot(cue="inventada")])
    )

    assert inativa.status_code == 422 and "nao esta ativa" in inativa.json()["detail"]
    assert inexistente.status_code == 422


@pytest.mark.parametrize(
    "mudanca",
    [
        {"qualidade_geral": 0}, {"qualidade_geral": 6}, {"dificuldade_percebida": "impossivel"},
        {"justificativa": ""}, {"justificativa": "   "}, {"tempo_ms": -1},
    ],
)
async def test_campos_invalidos_da_422(expert_client, fakes, mudanca):
    _, _, h = await _pronto(fakes, expert_client, itens=1)

    assert (await expert_client.put("/api/v1/expert/itens/1", headers=h, json=_avaliacao(**mudanca))).status_code == 422


async def test_campo_obrigatorio_ausente_da_422(expert_client, fakes):
    _, _, h = await _pronto(fakes, expert_client, itens=1)
    corpo = _avaliacao()
    del corpo["adequado_uso_educacional"]

    assert (await expert_client.put("/api/v1/expert/itens/1", headers=h, json=corpo)).status_code == 422


async def test_reenviar_o_mesmo_put_nao_duplica_e_substitui_por_inteiro(expert_client, fakes):
    _, esp, h = await _pronto(fakes, expert_client, itens=1)
    duas = _avaliacao(anotacoes=[_anot(ini=0, fim=5, trecho="Conte"), _anot(cue="scarcity", ini=6, fim=8, trecho="do")])

    await expert_client.put("/api/v1/expert/itens/1", headers=h, json=duas)
    await expert_client.put("/api/v1/expert/itens/1", headers=h, json=duas)
    linha = fakes["expert_evaluation_repository"].avaliacoes[esp.id][0]
    assert len(linha["anotacoes"]) == 2  # nao 4

    uma = _avaliacao(anotacoes=[_anot(ini=0, fim=5, trecho="Conte")])
    r = await expert_client.put("/api/v1/expert/itens/1", headers=h, json=uma)
    assert len(r.json()["avaliacao"]["anotacoes"]) == 1  # substituicao TOTAL

    vazia = await expert_client.put("/api/v1/expert/itens/1", headers=h, json=_avaliacao(anotacoes=[]))
    assert vazia.json()["avaliacao"]["anotacoes"] == []


async def test_mesma_pista_em_varios_trechos_e_permitida(expert_client, fakes):
    _, _, h = await _pronto(fakes, expert_client, conteudos=[_conteudo(1, conteudo="urgente urgente urgente")])
    anot = [_anot(ini=i, fim=i + 7, trecho="urgente") for i in (0, 8, 16)]

    r = await expert_client.put("/api/v1/expert/itens/1", headers=h, json=_avaliacao(anotacoes=anot))

    assert r.status_code == 200
    assert len(r.json()["avaliacao"]["anotacoes"]) == 3


async def test_progresso_reflete_as_avaliacoes_concluidas(expert_client, fakes):
    _, _, h = await _pronto(fakes, expert_client, itens=3)
    me = lambda: expert_client.get("/api/v1/expert/me", headers=h)  # noqa: E731
    assert (await me()).json()["progresso"] == {"total": 3, "concluidas": 0, "proxima_ordem": 1}

    await expert_client.put("/api/v1/expert/itens/1", headers=h, json=_avaliacao())
    p = (await me()).json()["progresso"]
    assert p["concluidas"] == 1 and p["total"] == 3 and p["proxima_ordem"] == 2

    for o in (2, 3):
        await expert_client.put(f"/api/v1/expert/itens/{o}", headers=h, json=_avaliacao())
    assert (await me()).json()["progresso"] == {"total": 3, "concluidas": 3, "proxima_ordem": 3}


async def test_hash_e_ids_nao_vazam_na_submissao(expert_client, fakes):
    _, esp, h = await _pronto(fakes, expert_client, itens=1)

    r = await expert_client.put("/api/v1/expert/itens/1", headers=h, json=_avaliacao())

    assert str(esp.id) not in r.text
    assert "codigo_hash" not in json.dumps(r.json())
