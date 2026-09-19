"""Persistencia das pistas anotadas (issue #5) contra Postgres de
verdade: `cues` semeada pela migration V20260919090000 com os UUIDs
FIXOS espelhados do backend Go, e `email_cues` ligando cada
phishing_email as pistas que o LLM anotou nele.
"""

import asyncpg
import pytest

from app.domain.models.cue import Cue, CueCode
from app.domain.models.phishing_email import PhishingEmail

# Copiado literalmente de phishing-quest-api/migrate/changelogs/
# V20260917110000__add_cues_tables.sql -- se este teste falhar, alguem
# mudou um UUID ou um code de um lado sem espelhar no outro, o que
# destroi a comparabilidade entre os dois bancos que a issue #5 pede
# explicitamente ("Compartilhar a taxonomia de pistas entre os
# projetos").
_TAXONOMIA_CANONICA_DO_GO = {
    "00000000-0000-0000-0000-000000000001": "sender_domain_mismatch",
    "00000000-0000-0000-0000-000000000002": "typosquat",
    "00000000-0000-0000-0000-000000000003": "homoglyph",
    "00000000-0000-0000-0000-000000000004": "urgency",
    "00000000-0000-0000-0000-000000000005": "authority",
    "00000000-0000-0000-0000-000000000006": "generic_greeting",
    "00000000-0000-0000-0000-000000000007": "credential_request",
    "00000000-0000-0000-0000-000000000008": "link_text_mismatch",
    "00000000-0000-0000-0000-000000000009": "unexpected_attachment",
    "00000000-0000-0000-0000-000000000010": "scarcity",
}


def _email_de_teste(**overrides) -> PhishingEmail:
    base = dict(
        receptor="alvo@example.com",
        remetente="remetente@example.com",
        assunto="Assunto de teste de integracao",
        conteudo="Sua conta sera bloqueada em ate 2 horas. Acesse empres4.net para regularizar.",
        explicacao="Explicacao de teste.",
        nivel="dificil",
        categoria="teste_integracao",
        links=[],
        is_malicious=True,
    )
    base.update(overrides)
    return PhishingEmail(**base)


async def test_taxonomia_seeded_bate_com_a_do_go(db_connection):
    async with db_connection.get_connection() as conn:
        rows = await conn.fetch("SELECT id, code FROM cues")

    taxonomia_local = {str(row["id"]): row["code"] for row in rows}
    assert taxonomia_local == _TAXONOMIA_CANONICA_DO_GO


async def test_create_persiste_e_get_by_id_recupera_as_pistas(phishing_repository):
    email = _email_de_teste(
        cues=[
            Cue(
                code=CueCode.URGENCY,
                evidencia="em ate 2 horas",
                span_start=17,
                span_end=31,
            ),
            Cue(
                code=CueCode.TYPOSQUAT,
                evidencia="empres4.net",
                span_start=None,
                span_end=None,
            ),
        ]
    )

    email_id = await phishing_repository.create(email)
    lido = await phishing_repository.get_by_id(email_id)

    assert lido is not None
    assert len(lido.cues) == 2
    codigos = {cue.code for cue in lido.cues}
    assert codigos == {CueCode.URGENCY, CueCode.TYPOSQUAT}

    pista_urgencia = next(c for c in lido.cues if c.code == CueCode.URGENCY)
    assert pista_urgencia.span_start == 17
    assert pista_urgencia.span_end == 31
    assert pista_urgencia.evidencia == "em ate 2 horas"

    pista_typosquat = next(c for c in lido.cues if c.code == CueCode.TYPOSQUAT)
    assert pista_typosquat.span_start is None
    assert pista_typosquat.span_end is None


async def test_email_sem_cues_nao_cria_linha_em_email_cues(phishing_repository, db_connection):
    email = _email_de_teste(cues=[])
    email_id = await phishing_repository.create(email)

    async with db_connection.get_connection() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM email_cues WHERE email_id = $1", email_id
        )
    assert count == 0

    lido = await phishing_repository.get_by_id(email_id)
    assert lido.cues == []


async def test_get_by_ids_traz_as_pistas_de_varios_emails_numa_query(phishing_repository):
    """A mesma bulk-query usada pelo endpoint de status do lote
    (issue #11b) -- confirma que a issue #5 nao reintroduz N+1.
    """
    email_a = _email_de_teste(
        cues=[Cue(code=CueCode.URGENCY, evidencia="em ate 2 horas")]
    )
    email_b = _email_de_teste(cues=[Cue(code=CueCode.SCARCITY, evidencia="vagas limitadas")])

    id_a = await phishing_repository.create(email_a)
    id_b = await phishing_repository.create(email_b)

    resultado = await phishing_repository.get_by_ids([id_a, id_b])

    por_id = {e.id: e for e in resultado}
    assert por_id[id_a].cues[0].code == CueCode.URGENCY
    assert por_id[id_b].cues[0].code == CueCode.SCARCITY


async def test_apagar_email_apaga_suas_pistas_em_cascata(phishing_repository, db_connection):
    email = _email_de_teste(cues=[Cue(code=CueCode.AUTHORITY, evidencia="Diretoria Financeira")])
    email_id = await phishing_repository.create(email)

    await phishing_repository.delete(email_id)

    async with db_connection.get_connection() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM email_cues WHERE email_id = $1", email_id
        )
    assert count == 0


async def test_cue_id_inexistente_e_rejeitado_pela_fk(phishing_repository, db_connection):
    """A FK de email_cues.cue_id -> cues(id) e a ultima linha de
    defesa contra uma taxonomia local desalinhada: um cue_id que nao
    existe na tabela `cues` e rejeitado pelo banco, nao silenciosamente
    ignorado.
    """
    email_id = await phishing_repository.create(_email_de_teste(cues=[]))

    async with db_connection.get_connection() as conn:
        with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError):
            await conn.execute(
                """
                INSERT INTO email_cues (email_id, cue_id, evidencia)
                VALUES ($1, gen_random_uuid(), 'evidencia qualquer')
                """,
                email_id,
            )
