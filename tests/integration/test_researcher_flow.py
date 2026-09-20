"""Console do pesquisador (issue #38) contra Postgres real, so por HTTP:
criar rodada -> vincular itens -> abrir -> cadastrar especialistas -> eles
avaliam -> export/resumo -> revogacao.
"""

import csv
import io
from uuid import uuid4

import pytest

from app.api.v1.endpoints import deps
from app.domain.models.cue import Cue, CueCode
from app.domain.models.phishing_email import PhishingEmail

CHAVE = "chave-do-pesquisador-integracao"
H = {"X-API-Key": CHAVE}
NIVEIS = ["facil", "medio", "dificil"]


@pytest.fixture(autouse=True)
def _config(monkeypatch):
    monkeypatch.setattr(deps.settings, "RESEARCHER_API_KEY", CHAVE)
    monkeypatch.setattr("app.api.v1.endpoints.researcher.settings.RODADA_ITENS_ESPERADOS", 3)


def _email(i, nivel) -> PhishingEmail:
    return PhishingEmail(
        receptor="alvo@example.com", remetente=f"s{i}@banc0.example", assunto=f"Assunto {i}",
        conteudo=f"Ação necessária: confirme seus dados agora. Item {i}.",
        explicacao="x", nivel=nivel, categoria="financeiro", links=[], is_malicious=True,
        cues=[Cue(code=CueCode.URGENCY, evidencia="agora", span_start=None, span_end=None)],
    )


async def _criar_itens(phishing_repository):
    return [await phishing_repository.create(_email(i, n)) for i, n in enumerate(NIVEIS, start=1)]


async def _rodada_aberta(c, ids):
    rid = (await c.post("/api/v1/researcher/rodadas", headers=H, json={
        "nome": "Piloto", "tcle_versao": "v1", "tcle_texto_md": "# TCLE"})).json()["id"]
    r = await c.put(f"/api/v1/researcher/rodadas/{rid}/itens", headers=H,
                    json={"email_ids": [str(i) for i in ids]})
    assert r.status_code == 200, r.text
    assert r.json() == {"total": 3, "distribuicao": {"facil": 1, "medio": 1, "dificil": 1}}
    assert (await c.post(f"/api/v1/researcher/rodadas/{rid}/abrir", headers=H)).status_code == 200
    return rid


async def _novo_especialista(c, rid, nome):
    r = await c.post("/api/v1/researcher/especialistas", headers=H, json={
        "nome": nome, "sobrenome": "Teste", "email": f"{uuid4()}@example.com", "rodada_id": rid})
    assert r.status_code == 201, r.text
    return r.json()


async def _avaliar_tudo(c, codigo, percebe):
    """`percebe(nivel_real)` -> nivel que o especialista atribui. O nivel
    real sai do 'Item N' no texto: a ordem de apresentacao e sorteada."""
    s = (await c.post("/api/v1/expert/session", json={"codigo_acesso": codigo})).json()
    h = {"Authorization": f"Bearer {s['token']}"}
    await c.post("/api/v1/expert/consentimento", headers=h, json={"versao": "v1", "aceito": True})
    await c.post("/api/v1/expert/perfil", headers=h, json={
        "anos_experiencia": 5, "area_atuacao": "Resposta a incidentes", "formacao": "CISSP"})
    for ordem in range(1, 4):
        item = (await c.get(f"/api/v1/expert/itens/{ordem}", headers=h)).json()["item"]
        texto = item["conteudo_texto"]
        ini = texto.index("agora")
        real = NIVEIS[int(texto.rstrip(".").rsplit(" ", 1)[1]) - 1]
        r = await c.put(f"/api/v1/expert/itens/{ordem}", headers=h, json={
            "dificuldade_percebida": percebe(real), "adequado_uso_educacional": True,
            "qualidade_geral": 4, "justificativa": "Urgência artificial; ação suspeita.",
            "comentario": None, "tempo_ms": 1500,
            "anotacoes": [{"campo": "conteudo", "cue_code": "urgency", "span_start": ini,
                           "span_end": ini + 5, "trecho": "agora"}]})
        assert r.status_code == 200, r.text
    return h


def _linhas(resp):
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


async def test_fluxo_completo_do_pesquisador(expert_client_real, phishing_repository):
    c = expert_client_real
    ids = await _criar_itens(phishing_repository)
    rid = await _rodada_aberta(c, ids)

    det = (await c.get(f"/api/v1/researcher/rodadas/{rid}", headers=H)).json()
    assert det["email_ids"] == [str(i) for i in ids] and det["status"] == "aberta"
    assert next(r for r in (await c.get("/api/v1/researcher/rodadas", headers=H)).json() if r["id"] == rid)["total_itens"] == 3

    # composicao congelada depois de aberta
    r = await c.put(f"/api/v1/researcher/rodadas/{rid}/itens", headers=H, json={"email_ids": [str(ids[0])]})
    assert r.status_code == 409
    assert (await c.get(f"/api/v1/researcher/rodadas/{rid}/export?dataset=itens&format=json", headers=H)).json().__len__() == 3

    ana = await _novo_especialista(c, rid, "Ana")
    bia = await _novo_especialista(c, rid, "Bia")
    assert ana["link"].endswith(f"/avaliacao/entrar?codigo={ana['codigo_acesso']}")

    # cada um avalia os 3 itens; ordem de apresentacao e sorteada, entao
    # o que se confere e a soma, nao qual item veio em qual posicao
    await _avaliar_tudo(c, ana["codigo_acesso"], lambda real: real)
    await _avaliar_tudo(c, bia["codigo_acesso"], lambda real: "medio")

    lista = (await c.get(f"/api/v1/researcher/especialistas?rodada_id={rid}", headers=H)).json()
    assert {e["concluidas"] for e in lista} == {3} and {e["total"] for e in lista} == {3}
    assert all(e["consentimento_versao"] == "v1" and e["ultimo_acesso_em"] for e in lista)
    assert ana["codigo_acesso"] not in str(lista)

    # avaliacoes: 2 especialistas x 3 itens = 6 linhas, com acentos intactos
    resp = await c.get(f"/api/v1/researcher/rodadas/{rid}/export?dataset=avaliacoes", headers=H)
    assert resp.content.startswith(b"\xef\xbb\xbf")
    av = _linhas(resp)
    assert len(av) == 6
    assert all(l["justificativa"] == "Urgência artificial; ação suspeita." for l in av)
    assert {l["nivel_sistema"] for l in av} == set(NIVEIS)

    an = _linhas(await c.get(f"/api/v1/researcher/rodadas/{rid}/export?dataset=anotacoes", headers=H))
    assert len(an) == 6
    assert {l["cue_tambem_no_llm"] for l in an} == {"true"}
    assert {l["trecho"] for l in an} == {"agora"}

    it = _linhas(await c.get(f"/api/v1/researcher/rodadas/{rid}/export?dataset=itens", headers=H))
    assert [l["ordem_canonica"] for l in it] == ["1", "2", "3"]
    assert {l["avaliacoes_concluidas"] for l in it} == {"2"}
    assert {l["cues_llm"] for l in it} == {"urgency"}

    # resumo: matriz soma 6; Ana acertou os 3, Bia acertou so o 'medio' (1)
    resumo = (await c.get(f"/api/v1/researcher/rodadas/{rid}/resumo", headers=H)).json()
    assert sum(sum(l.values()) for l in resumo["matriz_confusao"].values()) == 6
    assert resumo["concordancia_bruta"] == pytest.approx(4 / 6)
    assert resumo["frequencia_pistas"]["urgency"] == {"anotacoes": 6, "tambem_no_llm": 6}

    # especialistas: pseudonimizado por padrao
    sem_pii = await c.get(f"/api/v1/researcher/rodadas/{rid}/export?dataset=especialistas", headers=H)
    assert "Ana" not in sem_pii.text and "@example.com" not in sem_pii.text
    com_pii = _linhas(await c.get(
        f"/api/v1/researcher/rodadas/{rid}/export?dataset=especialistas&incluir_pii=true", headers=H))
    assert {l["nome"] for l in com_pii} == {"Ana", "Bia"}
    assert {l["anos_experiencia"] for l in com_pii} == {"5"}

    # revogacao: Bia some dos 4 datasets e do resumo
    tok = (await c.post("/api/v1/expert/session", json={"codigo_acesso": bia["codigo_acesso"]})).json()["token"]
    assert (await c.post("/api/v1/expert/revogacao", headers={"Authorization": f"Bearer {tok}"})).status_code == 200
    for ds, esperado in (("avaliacoes", 3), ("anotacoes", 3), ("itens", 3), ("especialistas", 1)):
        linhas = _linhas(await c.get(f"/api/v1/researcher/rodadas/{rid}/export?dataset={ds}", headers=H))
        assert len(linhas) == esperado, ds
    itens_pos = _linhas(await c.get(f"/api/v1/researcher/rodadas/{rid}/export?dataset=itens", headers=H))
    assert {l["avaliacoes_concluidas"] for l in itens_pos} == {"1"}
    assert (await c.get(f"/api/v1/researcher/rodadas/{rid}/resumo", headers=H)).json()["total_avaliacoes"] == 3


async def test_recodificar_invalida_o_codigo_anterior(expert_client_real, phishing_repository):
    c = expert_client_real
    rid = await _rodada_aberta(c, await _criar_itens(phishing_repository))
    esp = await _novo_especialista(c, rid, "Cris")
    assert (await c.post("/api/v1/expert/session", json={"codigo_acesso": esp["codigo_acesso"]})).status_code == 200

    novo = (await c.post(f"/api/v1/researcher/especialistas/{esp['id']}/recodificar", headers=H)).json()

    assert novo["codigo_acesso"] != esp["codigo_acesso"]
    assert (await c.post("/api/v1/expert/session", json={"codigo_acesso": esp["codigo_acesso"]})).status_code == 401
    assert (await c.post("/api/v1/expert/session", json={"codigo_acesso": novo["codigo_acesso"]})).status_code == 200


async def test_itens_invalidos_e_email_duplicado(expert_client_real, phishing_repository):
    c = expert_client_real
    ids = await _criar_itens(phishing_repository)
    rid = (await c.post("/api/v1/researcher/rodadas", headers=H, json={
        "nome": "R", "tcle_versao": "v1", "tcle_texto_md": "t"})).json()["id"]

    inexistente = await c.put(f"/api/v1/researcher/rodadas/{rid}/itens", headers=H,
                              json={"email_ids": [str(ids[0]), str(uuid4())]})
    assert inexistente.status_code == 422

    site = PhishingEmail(
        receptor=None, remetente=None, assunto=None, conteudo=None, explicacao="x", nivel="facil",
        categoria="financeiro", links=[], is_malicious=True, channel="website",
        content_json={"url": "http://x.test", "title": "t", "visible_content": "c"},
    )
    id_site = await phishing_repository.create(site)
    nao_email = await c.put(f"/api/v1/researcher/rodadas/{rid}/itens", headers=H,
                            json={"email_ids": [str(ids[0]), str(id_site)]})
    assert nao_email.status_code == 422 and "email" in nao_email.text

    # falhou => nada foi gravado
    assert (await c.post(f"/api/v1/researcher/rodadas/{rid}/abrir", headers=H)).status_code == 409

    email = f"{uuid4()}@example.com"
    corpo = {"nome": "A", "sobrenome": "B", "email": email, "rodada_id": rid}
    assert (await c.post("/api/v1/researcher/especialistas", headers=H, json=corpo)).status_code == 201
    assert (await c.post("/api/v1/researcher/especialistas", headers=H, json=corpo)).status_code == 409


async def test_export_de_rodada_sem_avaliacoes_e_vazio(expert_client_real, phishing_repository):
    c = expert_client_real
    rid = await _rodada_aberta(c, await _criar_itens(phishing_repository))
    r = await c.get(f"/api/v1/researcher/rodadas/{rid}/export?dataset=avaliacoes", headers=H)
    assert len(_linhas(r)) == 0 and r.content.startswith(b"\xef\xbb\xbf")
    assert (await c.get(f"/api/v1/researcher/rodadas/{rid}/resumo", headers=H)).json()["total_avaliacoes"] == 0
