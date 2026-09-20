"""Entrega cega e submissao (issue #37) contra Postgres real.

O ponto central: o especialista NUNCA ve o rotulo verdadeiro nem o que o
LLM ja anotou. Aqui os itens tem TODOS esses dados populados no banco, e
a checagem e feita sobre o JSON real devolvido pelas rotas.
"""

import asyncio
from uuid import uuid4

import asyncpg
import pytest

from app.domain.models.cue import Cue, CueCode
from app.domain.models.link_ref import LinkRef
from app.domain.models.phish_scale import PhishScale
from app.domain.models.phishing_email import PhishingEmail
from app.domain.services.expert_auth_service import ExpertAuthService
from tests.blindness import chaves_proibidas_em

SEGREDO_EXPLICACAO = "EXPLICACAO-SECRETA-que-nomeia-typosquat-e-urgencia"
SEGREDO_CATEGORIA = "CATEGORIA-SECRETA-financeiro"
EMOJI = "😀 Clique aqui agora para confirmar seus dados."


def _email(i: int, conteudo=None) -> PhishingEmail:
    return PhishingEmail(
        receptor="alvo@example.com",
        remetente=f"suporte{i}@banc0.example",
        assunto=f"Assunto {i}",
        conteudo=conteudo or f"Prezado cliente, confirme seus dados agora. Item {i}.",
        explicacao=SEGREDO_EXPLICACAO,
        nivel="dificil",
        categoria=SEGREDO_CATEGORIA,
        links=[LinkRef(text="Acessar sua conta", href=f"http://banc0-{i}.example/login")],
        is_malicious=True,
        cues=[Cue(code=CueCode.URGENCY, evidencia="agora", span_start=None, span_end=None)],
        phish_scale=PhishScale(cue_count=1, premise_alignment="alto", difficulty_estimated="dificil"),
    )


async def _rodada(rounds, phishing_repository, n, conteudos=None):
    rodada = await rounds.create(nome="Rodada", tcle_versao="v1", tcle_texto_md="TCLE", status="aberta")
    ids = []
    for i in range(1, n + 1):
        email_id = await phishing_repository.create(_email(i, (conteudos or {}).get(i)))
        await rounds.adicionar_item(rodada.id, email_id, i)
        ids.append(email_id)
    return rodada, ids


async def _especialista(client, experts, rodada, consentir=True):
    codigo = ExpertAuthService.gerar_codigo()
    esp = await experts.create(
        nome="Ana", sobrenome="Souza", email=f"{uuid4()}@example.com",
        codigo_hash=ExpertAuthService.hash_codigo(codigo), codigo_prefixo=codigo[:4], rodada_id=rodada.id,
    )
    token = (await client.post("/api/v1/expert/session", json={"codigo_acesso": codigo})).json()["token"]
    h = {"Authorization": f"Bearer {token}"}
    if consentir:
        assert (await client.post("/api/v1/expert/consentimento", headers=h, json={"versao": "v1", "aceito": True})).status_code == 200
    return esp, h


def _avaliacao(**extra):
    base = dict(
        dificuldade_percebida="dificil", adequado_uso_educacional=True, qualidade_geral=5,
        justificativa="Dominio com zero no lugar do o.", comentario="ok", tempo_ms=1000, anotacoes=[],
    )
    base.update(extra)
    return base


async def test_cegamento_com_dados_sensiveis_reais_no_banco(
    expert_client_real, evaluation_round_repository, expert_repository, phishing_repository
):
    rodada, _ = await _rodada(evaluation_round_repository, phishing_repository, 5)
    _, h = await _especialista(expert_client_real, expert_repository, rodada)

    for ordem in range(1, 6):
        r = await expert_client_real.get(f"/api/v1/expert/itens/{ordem}", headers=h)
        assert r.status_code == 200, r.text
        # chave proibida em qualquer profundidade
        assert chaves_proibidas_em(r.json()) == set()
        # e nenhum VALOR sensivel: o texto do LLM, a categoria, o nivel e a evidencia da pista
        for segredo in (SEGREDO_EXPLICACAO, SEGREDO_CATEGORIA, "dificil", "typosquat", "phish"):
            assert segredo not in r.text, segredo
        # o que o especialista PODE ver, ve
        item = r.json()["item"]
        assert item["conteudo_texto"].startswith("Prezado cliente")
        assert item["links"][0]["text"] == "Acessar sua conta"

    submetido = await expert_client_real.put("/api/v1/expert/itens/1", headers=h, json=_avaliacao())
    assert submetido.status_code == 200
    assert chaves_proibidas_em(submetido.json()) == set()
    assert SEGREDO_EXPLICACAO not in submetido.text


async def test_ordens_diferentes_por_especialista_cobrindo_1_a_n_sem_buraco(
    expert_client_real, evaluation_round_repository, expert_repository, phishing_repository, db_connection
):
    n = 30
    rodada, _ = await _rodada(evaluation_round_repository, phishing_repository, n)
    a, ha = await _especialista(expert_client_real, expert_repository, rodada)
    b, hb = await _especialista(expert_client_real, expert_repository, rodada)

    async def sequencia(h):
        return [
            (await expert_client_real.get(f"/api/v1/expert/itens/{o}", headers=h)).json()["item"]["assunto"]
            for o in range(1, n + 1)
        ]

    seq_a, seq_b = await sequencia(ha), await sequencia(hb)

    assert sorted(seq_a) == sorted(seq_b) == sorted(f"Assunto {i}" for i in range(1, n + 1))
    assert seq_a != seq_b
    async with db_connection.get_connection() as conn:
        for esp in (a, b):
            ordens = [r["o"] for r in await conn.fetch(
                "SELECT ordem_apresentacao AS o FROM avaliacoes WHERE especialista_id = $1 ORDER BY 1", esp.id)]
            assert ordens == list(range(1, n + 1))


async def test_primeiros_acessos_simultaneos_criam_exatamente_n_avaliacoes(
    expert_client_real, evaluation_round_repository, expert_repository, phishing_repository, db_connection
):
    """Sem o lock da linha do especialista, dois sorteios concorrentes
    violariam `uq_avaliacao_ordem` e um dos dois falharia com 500.
    """
    rodada, _ = await _rodada(evaluation_round_repository, phishing_repository, 10)
    esp, h = await _especialista(expert_client_real, expert_repository, rodada)

    respostas = await asyncio.gather(*[expert_client_real.get("/api/v1/expert/itens/1", headers=h) for _ in range(8)])

    assert [r.status_code for r in respostas] == [200] * 8
    assert len({r.json()["item"]["assunto"] for r in respostas}) == 1  # todos veem o MESMO item 1
    async with db_connection.get_connection() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM avaliacoes WHERE especialista_id = $1", esp.id) == 10


async def test_offsets_com_emoji_conferidos_pelo_proprio_postgres(
    expert_client_real, evaluation_round_repository, expert_repository, phishing_repository, db_connection
):
    """Postgres conta CARACTERES (code points), como o `len()` do Python:
    `substring(conteudo from span_start+1 for span_end-span_start)` tem que
    bater com o `trecho` gravado, mesmo com um emoji antes do trecho.
    """
    rodada, _ = await _rodada(evaluation_round_repository, phishing_repository, 1, conteudos={1: EMOJI})
    esp, h = await _especialista(expert_client_real, expert_repository, rodada)
    inicio = EMOJI.index("Clique aqui agora")
    fim = inicio + len("Clique aqui agora")

    ok = await expert_client_real.put(
        "/api/v1/expert/itens/1", headers=h,
        json=_avaliacao(anotacoes=[dict(campo="conteudo", cue_code="urgency", span_start=inicio, span_end=fim, trecho="Clique aqui agora")]),
    )
    utf16 = await expert_client_real.put(
        "/api/v1/expert/itens/1", headers=h,
        json=_avaliacao(anotacoes=[dict(campo="conteudo", cue_code="urgency", span_start=inicio + 1, span_end=fim + 1, trecho="Clique aqui agora")]),
    )

    assert ok.status_code == 200, ok.text
    assert utf16.status_code == 422  # o erro classico do frontend: emoji contado como 2
    async with db_connection.get_connection() as conn:
        linha = await conn.fetchrow(
            """
            SELECT an.trecho, substring(e.conteudo from an.span_start + 1 for an.span_end - an.span_start) AS do_banco
            FROM avaliacao_anotacoes an
            JOIN avaliacoes a ON a.id = an.avaliacao_id
            JOIN avaliacao_rodada_itens ri ON ri.id = a.rodada_item_id
            JOIN phishing_emails e ON e.id = ri.email_id
            WHERE a.especialista_id = $1
            """,
            esp.id,
        )
    assert linha["trecho"] == linha["do_banco"] == "Clique aqui agora"


async def test_put_e_idempotente_substitui_por_inteiro_e_422_nao_grava(
    expert_client_real, evaluation_round_repository, expert_repository, phishing_repository, db_connection
):
    rodada, _ = await _rodada(evaluation_round_repository, phishing_repository, 1, conteudos={1: "urgente urgente"})
    esp, h = await _especialista(expert_client_real, expert_repository, rodada)
    duas = _avaliacao(anotacoes=[
        dict(campo="conteudo", cue_code="urgency", span_start=0, span_end=7, trecho="urgente"),
        dict(campo="conteudo", cue_code="urgency", span_start=8, span_end=15, trecho="urgente"),  # mesma pista, outro trecho
    ])

    async def contar(conn):
        return await conn.fetchval(
            "SELECT COUNT(*) FROM avaliacao_anotacoes an JOIN avaliacoes a ON a.id = an.avaliacao_id WHERE a.especialista_id = $1",
            esp.id,
        )

    await expert_client_real.put("/api/v1/expert/itens/1", headers=h, json=duas)
    await expert_client_real.put("/api/v1/expert/itens/1", headers=h, json=duas)
    async with db_connection.get_connection() as conn:
        assert await contar(conn) == 2  # nao 4

    ruim = _avaliacao(anotacoes=[dict(campo="conteudo", cue_code="urgency", span_start=0, span_end=7, trecho="XXXXXXX")])
    assert (await expert_client_real.put("/api/v1/expert/itens/1", headers=h, json=ruim)).status_code == 422
    async with db_connection.get_connection() as conn:
        assert await contar(conn) == 2  # o 422 nao apagou nem trocou nada

    uma = _avaliacao(anotacoes=[dict(campo="conteudo", cue_code="scarcity", span_start=0, span_end=7, trecho="urgente")])
    r = await expert_client_real.put("/api/v1/expert/itens/1", headers=h, json=uma)
    assert [a["cue_code"] for a in r.json()["avaliacao"]["anotacoes"]] == ["scarcity"]
    async with db_connection.get_connection() as conn:
        assert await contar(conn) == 1


async def test_progresso_ate_concluir_todos(
    expert_client_real, evaluation_round_repository, expert_repository, phishing_repository
):
    rodada, _ = await _rodada(evaluation_round_repository, phishing_repository, 3)
    _, h = await _especialista(expert_client_real, expert_repository, rodada)
    me = lambda: expert_client_real.get("/api/v1/expert/me", headers=h)  # noqa: E731
    assert (await me()).json()["progresso"] == {"total": 3, "concluidas": 0, "proxima_ordem": 1}

    await expert_client_real.put("/api/v1/expert/itens/2", headers=h, json=_avaliacao())
    assert (await me()).json()["progresso"] == {"total": 3, "concluidas": 1, "proxima_ordem": 1}

    for o in (1, 3):
        await expert_client_real.put(f"/api/v1/expert/itens/{o}", headers=h, json=_avaliacao())
    assert (await me()).json()["progresso"] == {"total": 3, "concluidas": 3, "proxima_ordem": 3}


async def test_sem_consentimento_nenhum_item_sai_do_servidor(
    expert_client_real, evaluation_round_repository, expert_repository, phishing_repository
):
    rodada, _ = await _rodada(evaluation_round_repository, phishing_repository, 2)
    _, h = await _especialista(expert_client_real, expert_repository, rodada, consentir=False)

    r = await expert_client_real.get("/api/v1/expert/itens/1", headers=h)

    assert r.status_code == 403
    assert "Assunto" not in r.text


async def test_banco_recusa_avaliacao_concluida_sem_campos_obrigatorios(
    evaluation_round_repository, expert_repository, expert_evaluation_repository, phishing_repository, db_connection
):
    rodada, _ = await _rodada(evaluation_round_repository, phishing_repository, 1)
    esp = await expert_repository.create("A", "B", f"{uuid4()}@x.com", uuid4().hex * 2, "AAAA", rodada.id)
    await expert_evaluation_repository.inicializar_avaliacoes(esp.id, rodada.id, lambda o: None)

    async with db_connection.get_connection() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            await conn.execute("UPDATE avaliacoes SET status = 'concluida' WHERE especialista_id = $1", esp.id)


async def test_inicializar_e_idempotente(
    evaluation_round_repository, expert_repository, expert_evaluation_repository, phishing_repository, db_connection
):
    rodada, _ = await _rodada(evaluation_round_repository, phishing_repository, 4)
    esp = await expert_repository.create("A", "B", f"{uuid4()}@x.com", uuid4().hex * 2, "AAAA", rodada.id)

    for _ in range(3):
        await expert_evaluation_repository.inicializar_avaliacoes(esp.id, rodada.id, lambda o: o.reverse())

    async with db_connection.get_connection() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM avaliacoes WHERE especialista_id = $1", esp.id) == 4


# ------------------------------------------------------------ delete_email

async def test_apagar_item_que_esta_numa_rodada_da_409(
    client_com_postgres_real, evaluation_round_repository, phishing_repository
):
    _, ids = await _rodada(evaluation_round_repository, phishing_repository, 1)

    r = await client_com_postgres_real.delete(f"/api/v1/emails/{ids[0]}")

    assert r.status_code == 409
    assert "rodada" in r.json()["detail"]
    assert await phishing_repository.get_by_id(ids[0]) is not None  # nada foi apagado


async def test_apagar_item_inexistente_da_404_e_livre_da_200(client_com_postgres_real, phishing_repository):
    inexistente = await client_com_postgres_real.delete(f"/api/v1/emails/{uuid4()}")
    livre_id = await phishing_repository.create(_email(1))
    livre = await client_com_postgres_real.delete(f"/api/v1/emails/{livre_id}")

    assert inexistente.status_code == 404  # antes virava 500: o 404 era engolido pelo except Exception
    assert livre.status_code == 200
