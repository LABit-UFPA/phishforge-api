"""GET /api/v1/cues (issue #35): a taxonomia de pistas com a definicao
operacional, servida a partir do repositorio (aqui, um fake em memoria).
"""

CODIGOS = {
    "sender_domain_mismatch", "typosquat", "homoglyph", "urgency", "authority",
    "generic_greeting", "credential_request", "link_text_mismatch",
    "unexpected_attachment", "scarcity",
}


async def test_lista_as_10_pistas_com_descricao(client):
    response = await client.get("/api/v1/cues")

    assert response.status_code == 200
    cues = response.json()["cues"]
    assert {c["code"] for c in cues} == CODIGOS
    for cue in cues:
        assert cue["descricao_pt"]
        assert cue["category"] in ("technical", "psychological")
        assert cue["ativo"] is True


async def test_pista_desativada_some_da_listagem(client, fakes):
    fakes["cue_repository"].entries[0].ativo = False

    response = await client.get("/api/v1/cues")

    codigos = {c["code"] for c in response.json()["cues"]}
    assert len(codigos) == 9
    assert fakes["cue_repository"].entries[0].code.value not in codigos


async def test_exige_api_key(app_and_fakes):
    import httpx

    app, _ = app_and_fakes
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as anon:
        response = await anon.get("/api/v1/cues")

    assert response.status_code == 401
