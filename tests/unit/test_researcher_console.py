"""Console do pesquisador (issue #38): auth, gestao de rodada, export, resumo."""

import logging
from uuid import uuid4

import pytest

from app.api.v1.endpoints import deps
from app.domain.services.expert_auth_service import ExpertAuthService
from tests.conftest import TEST_API_KEY

CHAVE = "chave-do-pesquisador"
H = {"X-API-Key": CHAVE}


@pytest.fixture(autouse=True)
def _chave(monkeypatch):
    monkeypatch.setattr(deps.settings, "RESEARCHER_API_KEY", CHAVE)


def _rotas(rodada_id, esp_id):
    return [
        ("post", "/api/v1/researcher/rodadas", {"nome": "n", "tcle_versao": "v1", "tcle_texto_md": "t"}),
        ("put", f"/api/v1/researcher/rodadas/{rodada_id}/itens", {"email_ids": [str(uuid4())]}),
        ("post", f"/api/v1/researcher/rodadas/{rodada_id}/abrir", None),
        ("post", f"/api/v1/researcher/rodadas/{rodada_id}/encerrar", None),
        ("post", "/api/v1/researcher/especialistas",
         {"nome": "a", "sobrenome": "b", "email": "a@b.co", "rodada_id": str(rodada_id)}),
        ("post", f"/api/v1/researcher/especialistas/{esp_id}/recodificar", None),
        ("get", "/api/v1/researcher/especialistas", None),
        ("get", "/api/v1/researcher/rodadas", None),
        ("get", f"/api/v1/researcher/rodadas/{rodada_id}", None),
        ("get", f"/api/v1/researcher/rodadas/{rodada_id}/resumo", None),
        ("get", f"/api/v1/researcher/rodadas/{rodada_id}/export?dataset=avaliacoes", None),
    ]


async def _chamar(client, metodo, url, body, headers):
    return await client.request(metodo.upper(), url, json=body, headers=headers)


# ------------------------------------------------------------------ auth

async def test_toda_rota_sem_chave_ou_com_chave_errada_da_401(expert_client):
    for metodo, url, body in _rotas(uuid4(), uuid4()):
        assert (await _chamar(expert_client, metodo, url, body, {})).status_code == 401, url
        assert (await _chamar(expert_client, metodo, url, body, {"X-API-Key": "errada"})).status_code == 401, url


async def test_chave_do_backend_go_nao_vale_no_console(expert_client):
    for metodo, url, body in _rotas(uuid4(), uuid4()):
        r = await _chamar(expert_client, metodo, url, body, {"X-API-Key": TEST_API_KEY})
        assert r.status_code == 401, url


async def test_chave_nao_configurada_da_503_em_toda_rota(expert_client, monkeypatch):
    monkeypatch.setattr(deps.settings, "RESEARCHER_API_KEY", "")
    for metodo, url, body in _rotas(uuid4(), uuid4()):
        assert (await _chamar(expert_client, metodo, url, body, H)).status_code == 503, url


# -------------------------------------------------------------- rodadas

async def test_criar_rodada_e_congelar_itens_ao_abrir(expert_client, fakes, monkeypatch):
    monkeypatch.setattr("app.api.v1.endpoints.researcher.settings.RODADA_ITENS_ESPERADOS", 2)
    r = await expert_client.post(
        "/api/v1/researcher/rodadas", headers=H,
        json={"nome": "Piloto", "tcle_versao": "v1", "tcle_texto_md": "# TCLE"},
    )
    assert r.status_code == 201 and r.json()["status"] == "rascunho"
    rid = r.json()["id"]

    itens = {"email_ids": [str(uuid4()), str(uuid4())]}
    ok = await expert_client.put(f"/api/v1/researcher/rodadas/{rid}/itens", json=itens, headers=H)
    assert ok.status_code == 200 and ok.json()["total"] == 2

    assert (await expert_client.post(f"/api/v1/researcher/rodadas/{rid}/abrir", headers=H)).json()["status"] == "aberta"

    depois = await expert_client.put(
        f"/api/v1/researcher/rodadas/{rid}/itens", json={"email_ids": [str(uuid4())]}, headers=H
    )
    assert depois.status_code == 409
    assert len(fakes["evaluation_round_repository"].itens[list(fakes["evaluation_round_repository"].itens)[0]]) == 2

    assert (await expert_client.post(f"/api/v1/researcher/rodadas/{rid}/abrir", headers=H)).status_code == 409
    assert (await expert_client.post(f"/api/v1/researcher/rodadas/{rid}/encerrar", headers=H)).json()["status"] == "encerrada"


async def test_abrir_sem_a_quantidade_esperada_de_itens_da_409(expert_client, monkeypatch):
    monkeypatch.setattr("app.api.v1.endpoints.researcher.settings.RODADA_ITENS_ESPERADOS", 30)
    rid = (await expert_client.post(
        "/api/v1/researcher/rodadas", headers=H,
        json={"nome": "P", "tcle_versao": "v1", "tcle_texto_md": "t"},
    )).json()["id"]
    await expert_client.put(f"/api/v1/researcher/rodadas/{rid}/itens", json={"email_ids": [str(uuid4())]}, headers=H)
    assert (await expert_client.post(f"/api/v1/researcher/rodadas/{rid}/abrir", headers=H)).status_code == 409


async def test_itens_repetidos_sao_422(expert_client):
    i = str(uuid4())
    r = await expert_client.put(f"/api/v1/researcher/rodadas/{uuid4()}/itens", json={"email_ids": [i, i]}, headers=H)
    assert r.status_code == 422


# ---------------------------------------------------------- especialistas

async def test_criar_especialista_devolve_codigo_e_link_so_uma_vez(expert_client, fakes, monkeypatch):
    monkeypatch.setattr("app.api.v1.endpoints.researcher.settings.EXPERT_FRONTEND_URL", "https://front.exemplo/")
    rodada = await fakes["evaluation_round_repository"].create("R", "v1", "t")

    r = await expert_client.post(
        "/api/v1/researcher/especialistas", headers=H,
        json={"nome": "Ana", "sobrenome": "Souza", "email": "ana@exemplo.com", "rodada_id": str(rodada.id)},
    )

    assert r.status_code == 201
    body = r.json()
    assert body["link"] == f"https://front.exemplo/avaliacao/entrar?codigo={body['codigo_acesso']}"
    # o codigo gravado e o hash; a listagem nunca o traz
    fakes["researcher_repository"].especialistas_listados = [
        {"id": uuid4(), "nome": "Ana", "sobrenome": "Souza", "email": "ana@exemplo.com",
         "rodada_id": rodada.id, "concluidas": 1, "total": 3, "consentimento_versao": "v1",
         "consentimento_em": None, "revogado_em": None, "ultimo_acesso_em": None}
    ]
    lista = await expert_client.get("/api/v1/researcher/especialistas", headers=H)
    assert body["codigo_acesso"] not in lista.text
    assert lista.json()[0]["concluidas"] == 1 and lista.json()[0]["total"] == 3


async def test_especialista_em_rodada_encerrada_ou_inexistente(expert_client, fakes):
    rodada = await fakes["evaluation_round_repository"].create("R", "v1", "t", status="encerrada")
    corpo = {"nome": "A", "sobrenome": "B", "email": "a@b.co", "rodada_id": str(rodada.id)}
    assert (await expert_client.post("/api/v1/researcher/especialistas", json=corpo, headers=H)).status_code == 409
    corpo["rodada_id"] = str(uuid4())
    assert (await expert_client.post("/api/v1/researcher/especialistas", json=corpo, headers=H)).status_code == 404


async def test_recodificar_emite_novo_codigo(expert_client, fakes):
    esp = fakes["expert_repository"].adicionar(ExpertAuthService.hash_codigo("AAAA-AAAA-AAAA-AAAA"))
    r = await expert_client.post(f"/api/v1/researcher/especialistas/{esp.id}/recodificar", headers=H)
    assert r.status_code == 200
    (_, hash_novo, _), = fakes["researcher_repository"].recodificados
    assert hash_novo == ExpertAuthService.hash_codigo(r.json()["codigo_acesso"])
    assert (await expert_client.post(f"/api/v1/researcher/especialistas/{uuid4()}/recodificar", headers=H)).status_code == 404


async def test_recodificar_revogado_da_409(expert_client, fakes):
    from datetime import datetime, timezone
    esp = fakes["expert_repository"].adicionar("h", revogado_em=datetime.now(timezone.utc))
    assert (await expert_client.post(f"/api/v1/researcher/especialistas/{esp.id}/recodificar", headers=H)).status_code == 409


# ------------------------------------------------------------ export/resumo

def _avaliacao(esp, sistema, percebido, **extra):
    base = dict(
        especialista_id=esp, item_id=uuid4(), ordem_canonica=1, ordem_apresentacao=1,
        nivel_sistema=sistema, dificuldade_percebida=percebido,
        nivel_concordou=sistema == percebido, adequado_uso_educacional=True,
        qualidade_geral=4, justificativa="Nível bem calibrado; ação imediata.",
        comentario=None, tempo_ms=1000, concluida_em=None, n_anotacoes=0,
    )
    base.update(extra)
    return base


async def _rodada(fakes):
    return await fakes["evaluation_round_repository"].create("R", "v1", "t")


async def test_export_csv_tem_bom_utf8_e_acentos_corretos(expert_client, fakes):
    rodada = await _rodada(fakes)
    fakes["researcher_repository"].datasets["avaliacoes"] = [_avaliacao(uuid4(), "facil", "medio")]

    r = await expert_client.get(f"/api/v1/researcher/rodadas/{rodada.id}/export?dataset=avaliacoes", headers=H)

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert r.content.startswith(b"\xef\xbb\xbf")
    texto = r.content.decode("utf-8-sig")
    assert "Nível bem calibrado; ação imediata." in texto
    assert texto.splitlines()[0].startswith("especialista_id,item_id,")


async def test_export_sem_avaliacoes_e_dataset_vazio_nao_erro(expert_client, fakes):
    rodada = await _rodada(fakes)
    for ds in ("avaliacoes", "anotacoes", "itens", "especialistas"):
        r = await expert_client.get(f"/api/v1/researcher/rodadas/{rodada.id}/export?dataset={ds}", headers=H)
        assert r.status_code == 200
        assert len(r.content.decode("utf-8-sig").strip().splitlines()) == 1  # so o cabecalho
        j = await expert_client.get(f"/api/v1/researcher/rodadas/{rodada.id}/export?dataset={ds}&format=json", headers=H)
        assert j.json() == []


async def test_export_neutraliza_formulas_no_csv_mas_nao_no_json(expert_client, fakes):
    rodada = await _rodada(fakes)
    fakes["researcher_repository"].datasets["avaliacoes"] = [
        _avaliacao(uuid4(), "facil", "facil", justificativa='=HYPERLINK("http://x","clique")')
    ]
    csv_ = await expert_client.get(f"/api/v1/researcher/rodadas/{rodada.id}/export?dataset=avaliacoes", headers=H)
    assert "'=HYPERLINK" in csv_.content.decode("utf-8-sig")
    js = await expert_client.get(f"/api/v1/researcher/rodadas/{rodada.id}/export?dataset=avaliacoes&format=json", headers=H)
    assert js.json()[0]["justificativa"].startswith("=HYPERLINK")


async def test_export_especialistas_sem_pii_por_padrao(expert_client, fakes):
    rodada = await _rodada(fakes)
    fakes["researcher_repository"].datasets["especialistas"] = [
        {"especialista_id": uuid4(), "anos_experiencia": 6, "area_atuacao": "IR", "formacao": "CISSP",
         "consentimento_versao": "v1", "consentimento_em": None, "ultimo_acesso_em": None,
         "avaliacoes_concluidas": 3, "avaliacoes_total": 3,
         "nome": "Ana", "sobrenome": "Souza", "email": "ana@exemplo.com"}
    ]
    for sufixo in ("", "&incluir_pii=false"):
        r = await expert_client.get(
            f"/api/v1/researcher/rodadas/{rodada.id}/export?dataset=especialistas{sufixo}", headers=H
        )
        assert "Ana" not in r.text and "ana@exemplo.com" not in r.text and "nome" not in r.text.splitlines()[0]
        assert fakes["researcher_repository"].pii_pedida[-1] is False


async def test_incluir_pii_traz_os_campos_e_fica_registrado_em_log(expert_client, fakes, caplog):
    rodada = await _rodada(fakes)
    fakes["researcher_repository"].datasets["especialistas"] = [
        {"especialista_id": uuid4(), "anos_experiencia": 6, "area_atuacao": "IR", "formacao": "CISSP",
         "consentimento_versao": "v1", "consentimento_em": None, "ultimo_acesso_em": None,
         "avaliacoes_concluidas": 3, "avaliacoes_total": 3,
         "nome": "Ana", "sobrenome": "Souza", "email": "ana@exemplo.com"}
    ]
    with caplog.at_level(logging.WARNING, logger="app.audit"):
        r = await expert_client.get(
            f"/api/v1/researcher/rodadas/{rodada.id}/export?dataset=especialistas&incluir_pii=true", headers=H
        )
    assert "ana@exemplo.com" in r.text
    assert any("EXPORT_PII" in m and str(rodada.id) in m for m in caplog.messages)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.audit"):
        await expert_client.get(f"/api/v1/researcher/rodadas/{rodada.id}/export?dataset=especialistas", headers=H)
    assert not caplog.messages


async def test_incluir_pii_em_outro_dataset_e_422(expert_client, fakes):
    rodada = await _rodada(fakes)
    r = await expert_client.get(
        f"/api/v1/researcher/rodadas/{rodada.id}/export?dataset=avaliacoes&incluir_pii=true", headers=H
    )
    assert r.status_code == 422


async def test_export_rodada_inexistente_e_dataset_invalido(expert_client, fakes):
    assert (await expert_client.get(f"/api/v1/researcher/rodadas/{uuid4()}/export?dataset=avaliacoes", headers=H)).status_code == 404
    rodada = await _rodada(fakes)
    assert (await expert_client.get(f"/api/v1/researcher/rodadas/{rodada.id}/export?dataset=xyz", headers=H)).status_code == 422


async def test_resumo_matriz_soma_o_total_e_concordancia(expert_client, fakes):
    rodada = await _rodada(fakes)
    a, b = uuid4(), uuid4()
    fakes["researcher_repository"].datasets["avaliacoes"] = [
        _avaliacao(a, "facil", "facil", qualidade_geral=5),
        _avaliacao(a, "medio", "facil", qualidade_geral=3),
        _avaliacao(a, "dificil", "dificil", qualidade_geral=4),
        _avaliacao(b, "facil", "medio", qualidade_geral=2, adequado_uso_educacional=False),
        _avaliacao(b, "medio", "medio", qualidade_geral=4),
        _avaliacao(b, "dificil", "medio", qualidade_geral=4),
    ]
    fakes["researcher_repository"].datasets["anotacoes"] = [
        {"cue_code": "urgency", "cue_tambem_no_llm": True},
        {"cue_code": "urgency", "cue_tambem_no_llm": False},
        {"cue_code": "typosquat", "cue_tambem_no_llm": False},
    ]

    r = await expert_client.get(f"/api/v1/researcher/rodadas/{rodada.id}/resumo", headers=H)

    j = r.json()
    assert j["total_avaliacoes"] == 6 and j["especialistas"] == 2
    assert sum(sum(l.values()) for l in j["matriz_confusao"].values()) == 6
    assert j["matriz_confusao"]["medio"] == {"facil": 1, "medio": 1, "dificil": 0}
    assert j["concordancia_bruta"] == pytest.approx(3 / 6)
    assert j["qualidade_media"] == pytest.approx(22 / 6)
    assert j["adequado_uso_educacional_pct"] == pytest.approx(5 / 6)
    assert j["frequencia_pistas"]["urgency"] == {"anotacoes": 2, "tambem_no_llm": 1}


async def test_resumo_vazio_nao_quebra(expert_client, fakes):
    rodada = await _rodada(fakes)
    j = (await expert_client.get(f"/api/v1/researcher/rodadas/{rodada.id}/resumo", headers=H)).json()
    assert j["total_avaliacoes"] == 0 and j["concordancia_bruta"] is None and j["qualidade_media"] is None


async def test_listar_e_obter_rodada_mostram_status_e_itens(expert_client, fakes, monkeypatch):
    monkeypatch.setattr("app.api.v1.endpoints.researcher.settings.RODADA_ITENS_ESPERADOS", 2)
    rid = (await expert_client.post(
        "/api/v1/researcher/rodadas", headers=H,
        json={"nome": "Piloto", "tcle_versao": "v1", "tcle_texto_md": "TCLE SECRETO LONGO"},
    )).json()["id"]
    a, b = str(uuid4()), str(uuid4())
    await expert_client.put(f"/api/v1/researcher/rodadas/{rid}/itens", json={"email_ids": [b, a]}, headers=H)
    await expert_client.post(f"/api/v1/researcher/rodadas/{rid}/abrir", headers=H)

    lista = (await expert_client.get("/api/v1/researcher/rodadas", headers=H)).json()
    assert lista[0]["status"] == "aberta" and lista[0]["total_itens"] == 2
    assert "TCLE SECRETO" not in str(lista)

    det = (await expert_client.get(f"/api/v1/researcher/rodadas/{rid}", headers=H)).json()
    assert det["email_ids"] == [b, a] and det["total_itens"] == 2 and det["status"] == "aberta"
    assert (await expert_client.get(f"/api/v1/researcher/rodadas/{uuid4()}", headers=H)).status_code == 404
